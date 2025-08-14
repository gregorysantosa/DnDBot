import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from dateutil import parser
import asyncio
from datetime import datetime, timezone
import json
from discord import File
from io import StringIO
import pytz
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import time
import traceback

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GUILD_ID = 856322099239845919
# 856322099239845919 <- DnD
# 1402852211083448380 <- Dev

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True  # Needed for member info

bot = commands.Bot(command_prefix="!", intents=intents)

# Store signups keyed by message ID
# accepted: dict user_id -> character description (str)
# waitlist: set of user_ids
# Also store event_time as datetime
event_signups = {}

vault = {}

def format_accepted(accepted_dict):
    if not accepted_dict:
        return "No one yet."
    lines = []
    for user_id, char_desc in accepted_dict.items():
        member = bot.get_user(user_id)
        name = member.display_name if member else f"<User {user_id}>"
        lines.append(f"**{name}**: {char_desc}")
    return "\n".join(lines)

def format_waitlist(waitlist_set):
    if not waitlist_set:
        return "No one yet."
    lines = []
    for user_id in waitlist_set:
        member = bot.get_user(user_id)
        name = member.display_name if member else f"<User {user_id}>"
        lines.append(name)
    return "\n".join(lines)

class JoinModal(discord.ui.Modal):
    def __init__(self, message_id, user_id, max_participants, event_title):
        super().__init__(title=f"{event_title}")

        self.message_id = message_id
        self.user_id = user_id
        self.max_participants = max_participants

    character_desc = discord.ui.TextInput(
        label="Character Description",
        style=discord.TextStyle.paragraph,
        placeholder="Ex: {Name} - {Lvl} {Class}",
        required=True,
        max_length=200,
    )

    async def on_submit(self, interaction: discord.Interaction):
        signups = event_signups.get(self.message_id)
        if not signups:
            await interaction.response.send_message("Event expired or not found.", ephemeral=True)
            return

        accepted = signups["accepted"]
        waitlist = signups["waitlist"]

        if self.user_id in accepted:
            await interaction.response.send_message("You already joined!", ephemeral=True)
            return
        if self.user_id in waitlist:
            await interaction.response.send_message("You are on the waitlist. Use Leave to remove yourself first.", ephemeral=True)
            return

        if len(accepted) < self.max_participants:
            accepted[self.user_id] = self.character_desc.value
            channel = bot.get_channel(interaction.channel_id)
            message = await channel.fetch_message(self.message_id)
            embed = message.embeds[0]
            embed.set_field_at(
                1,
                name=f"✅ Accepted ({len(accepted)}/{self.max_participants})",
                value=format_accepted(accepted),
                inline=True
            )
            embed.set_field_at(
                2,
                name="🕒 Waitlist",
                value=format_waitlist(waitlist),
                inline=True
            )
            await message.edit(embed=embed)
            await interaction.response.send_message("You have joined the event!", ephemeral=True)
        else:
            await interaction.response.send_message("Sorry, event is full. Use Waitlist button to join waitlist.", ephemeral=True)


class EventView(discord.ui.View):
    def __init__(self, message_id, max_participants, title):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.max_participants = max_participants
        self.title = title

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        signups = event_signups.get(self.message_id)
        if not signups:
            await interaction.response.send_message("Event expired or not found.", ephemeral=True)
            return

        accepted = signups["accepted"]
        waitlist = signups["waitlist"]

        if user_id in accepted:
            await interaction.response.send_message("You already joined!", ephemeral=True)
            return
        if user_id in waitlist:
            await interaction.response.send_message("You are on the waitlist. Use Leave to remove yourself first.", ephemeral=True)
            return

        if len(accepted) < self.max_participants:
            # Get event title from the embed
            channel = bot.get_channel(interaction.channel_id)
            message = await channel.fetch_message(self.message_id)
            event_title = message.embeds[0].title if message.embeds else "Event"

            modal = JoinModal(self.message_id, user_id, self.max_participants, event_title)
            await interaction.response.send_modal(modal)
        else:
            await interaction.response.send_message("Sorry, the event is full. Use the Waitlist button to join the waitlist.", ephemeral=True)

    @discord.ui.button(label="Waitlist", style=discord.ButtonStyle.primary)
    async def waitlist(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        signups = event_signups.get(self.message_id)
        if not signups:
            await interaction.response.send_message("Event expired or not found.", ephemeral=True)
            return

        accepted = signups["accepted"]
        waitlist = signups["waitlist"]

        if user_id in waitlist:
            await interaction.response.send_message("You are already on the waitlist.", ephemeral=True)
            return
        if user_id in accepted:
            await interaction.response.send_message("You already joined the event. Use Leave to remove yourself first.", ephemeral=True)
            return

        waitlist.add(user_id)

        # Update embed message
        channel = bot.get_channel(interaction.channel_id)
        message = await channel.fetch_message(self.message_id)
        embed = message.embeds[0]
        embed.set_field_at(
            2,
            name="🕒 Waitlist",
            value=format_waitlist(waitlist),
            inline=True
        )
        await message.edit(embed=embed)

        await interaction.response.send_message("You have been added to the waitlist.", ephemeral=True)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        signups = event_signups.get(self.message_id)
        max_participants = signups.get("max_participants", 10)

        if not signups:
            await interaction.response.send_message("Event expired or not found.", ephemeral=True)
            return

        accepted = signups["accepted"]
        waitlist = signups["waitlist"]

        changed = False

        if user_id in accepted:
            del accepted[user_id]
            changed = True
            # Promote first in waitlist if any
            if waitlist:
                promoted = waitlist.pop()
                accepted[promoted] = "No description provided."
        elif user_id in waitlist:
            waitlist.remove(user_id)
            changed = True

        if changed:
            # Update embed message
            channel = bot.get_channel(interaction.channel_id)
            message = await channel.fetch_message(self.message_id)
            embed = message.embeds[0]
            embed.set_field_at(
                1,
                name=f"✅ Accepted ({len(accepted)}/{max_participants})",
                value=format_accepted(accepted),
                inline=True
            )
            embed.set_field_at(
                2,
                name="🕒 Waitlist",
                value=format_waitlist(waitlist),
                inline=True
            )
            await message.edit(embed=embed)
            await interaction.response.send_message("You have left the event.", ephemeral=True)
        else:
            await interaction.response.send_message("You are not in the event or waitlist.", ephemeral=True)

    @discord.ui.button(label="🔚", style=discord.ButtonStyle.secondary)
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Only event creator can finish
        if interaction.user.id not in allowed_user_ids:
            await interaction.response.send_message("You cannot finish this adventure.", ephemeral=True)
            return

        await interaction.response.send_modal(FinishAdventureModal(self))

    async def update_message(self, interaction: discord.Interaction):
        data = event_signups[self.message_id]
        embed = interaction.message.embeds[0]

        accepted_list = "\n".join(data["accepted"].values()) if data["accepted"] else "No one yet."
        waitlist_list = "\n".join(data["waitlist"]) if data["waitlist"] else "No one yet."

        embed.set_field_at(1, name=f"✅ Accepted ({len(data['accepted'])}/{self.max_participants})", value=accepted_list, inline=True)
        embed.set_field_at(2, name="🕒 Waitlist", value=waitlist_list, inline=True)

        await interaction.message.edit(embed=embed, view=self)


class FinishAdventureModal(discord.ui.Modal, title="Finish Adventure"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.description_input = discord.ui.TextInput(
            label="Adventure Summary",
            style=discord.TextStyle.paragraph,
            placeholder="What happened during the adventure?",
            required=False
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction):
        message_data = event_signups.get(self.view.message_id)
        if not message_data:
            await interaction.response.send_message("Event data not found.", ephemeral=True)
            return

        accepted_players = list(message_data["accepted"].values())
        if not accepted_players:
            players_list = "No players joined this adventure."
        else:
            players_list = "\n".join(f"• {player}" for player in accepted_players)

        finish_embed = discord.Embed(
            title=f"🏆 Adventure Finished: {self.view.title}",
            description=f"**Adventurers:**\n{players_list}\n\n**Summary:**\n{self.description_input.value or 'No story provided.'}",
            color=discord.Color.gold()
        )
        finish_embed.set_footer(text=f"Event ended by {interaction.user.display_name}")

        await interaction.channel.send(embed=finish_embed)

        # Save to history
        event_history[self.view.message_id] = {
            "title": self.view.title,
            "players": accepted_players,
            "summary": self.description_input.value or "No story provided.",
            "ended_by": interaction.user.display_name
        }

        # Disable all buttons
        for child in self.view.children:
            child.disabled = True
        await self.view.message.edit(view=self.view)

        # Remove from active events
        event_signups.pop(self.view.message_id, None)

        await interaction.response.send_message("Adventure finished and archived!", ephemeral=True)

# Event tracking
event_signups = {}
event_history = {}  # Stores finished events
allowed_user_ids = {284137393483939841, 261651766213345282}  # Replace with actual Discord user IDs

async def schedule_event_reminder(message_id: int):
    signups = event_signups.get(message_id)
    if not signups:
        return  # event expired or deleted

    event_time = signups.get("event_time")
    if not event_time:
        return

    reminders = [
        (48 * 60 * 60, "48 hours"),
        (12 * 60 * 60, "12 hours")
    ]

    now = datetime.now(timezone.utc).timestamp()

    for seconds_before, label in reminders:
        reminder_time = event_time.timestamp() - seconds_before
        wait_seconds = reminder_time - now

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

            # After waiting, send reminder message
            channel = None
            message = None

            for guild in bot.guilds:
                for channel_candidate in guild.text_channels:
                    try:
                        message = await channel_candidate.fetch_message(message_id)
                        channel = channel_candidate
                        break
                    except (discord.NotFound, discord.Forbidden):
                        continue
                if message:
                    break

            if not message or not channel:
                return

            accepted = signups.get("accepted", {})
            if not accepted:
                return

            mentions = []
            for user_id in accepted.keys():
                member = channel.guild.get_member(user_id)
                if member:
                    mentions.append(member.mention)

            if mentions:
                mention_text = " ".join(mentions)
                await channel.send(
                    f"⏰ Reminder: The event **{message.embeds[0].title}** starts in {label}! {mention_text}"
                )

PST = pytz.timezone("America/Los_Angeles")

@bot.tree.command(name="event", description="Create a custom event embed")
@app_commands.describe(
    title="Title of your event",
    description="Description for the event",
    time="Date and time for the event in ISO 8601 format, YYYY-MM-DDTHH:MM:SS",
    roles_to_ping="Roles to ping (mention them here)",
    max_participants="Maximum number of participants allowed",
    image_url="Optional URL of an image to display below description"
)
async def event(
    interaction: discord.Interaction,
    title: str,
    description: str,
    time: str,
    roles_to_ping: str,
    max_participants: int,
    image_url: str = None
):
    if interaction.user.id not in allowed_user_ids:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    try:
        parsed_time = parser.isoparse(time)
        if parsed_time.tzinfo is None:
            parsed_time = PST.localize(parsed_time)
        else:
            parsed_time = parsed_time.astimezone(PST)
        utc_time = parsed_time.astimezone(timezone.utc)
    except Exception:
        await interaction.response.send_message(
            "Invalid time format. Use ISO8601 (YYYY-MM-DDTHH:MM:SS).",
            ephemeral=True
        )
        return

    embed_time_str = f"<t:{int(utc_time.timestamp())}:F>"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green()
    )
    embed.add_field(name="Time", value=embed_time_str, inline=False)
    if image_url:
        embed.set_image(url=image_url)
    embed.add_field(name=f"✅ Accepted (0/{max_participants})", value="No one yet.", inline=True)
    embed.add_field(name="🕒 Waitlist", value="No one yet.", inline=True)
    embed.set_footer(text=f"Created by {interaction.user.display_name}")

    await interaction.response.send_message(
        content=roles_to_ping,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )

    message = await interaction.original_response()

    event_signups[message.id] = {
        "accepted": {},
        "waitlist": set(),
        "max_participants": max_participants,
        "event_time": utc_time,
        "title": title
    }

    view = EventView(message.id, max_participants, title)
    view.message = message  # Store reference to original message
    await message.edit(view=view)

# ---- Vault commands ----

# vault now stores list of dicts: {"description": str, "link": Optional[str]}
vault = {}

RARITY_CHOICES = [
    app_commands.Choice(name="Common", value="Common"),
    app_commands.Choice(name="Uncommon", value="Uncommon"),
    app_commands.Choice(name="Rare", value="Rare"),
    app_commands.Choice(name="Very Rare", value="Very Rare"),
    app_commands.Choice(name="Legendary", value="Legendary"),
    app_commands.Choice(name="Artifact", value="Artifact"),
    app_commands.Choice(name="Unique", value="Unique"),
    app_commands.Choice(name="???", value="???"),
    app_commands.Choice(name="Currency", value="Currency")
]

RARITY_EMOJIS = {
    "Common": "⚪",
    "Uncommon": "🟢",
    "Rare": "🔵",
    "Very Rare": "🟣",
    "Legendary": "🟡",
    "Artifact": "🟠",
    "Unique": "🟣",
    "???": "⚫",
    "Currency": "🟡"
}

TYPES_CHOICES = [
    app_commands.Choice(name="Armor", value="Armor"),
    app_commands.Choice(name="Potions", value="Potions"),
    app_commands.Choice(name="Rings", value="Rings"),
    app_commands.Choice(name="Rods", value="Rods"),
    app_commands.Choice(name="Scrolls", value="Scrolls"),
    app_commands.Choice(name="Staffs", value="Staffs"),
    app_commands.Choice(name="Wands", value="Wands"),
    app_commands.Choice(name="Weapons", value="Weapons"),
    app_commands.Choice(name="Wondrous Item", value="Wondrous Item"),
    app_commands.Choice(name="cp", value="cp"),
    app_commands.Choice(name="sp", value="sp"),
    app_commands.Choice(name="gp", value="gp"),
    app_commands.Choice(name="pp", value="pp"),
]

TYPE_EMOJIS = {
    "Armor": "🛡️",
    "Potions": "🧪",
    "Rings": "💍",
    "Rods": "✨",
    "Scrolls": "📜",
    "Staffs": "🔮",
    "Wands": "🪄",
    "Weapons": "⚔️",
    "Wondrous Item": "🎁",
    "cp": "💲",
    "sp": "💲",
    "gp": "💲",
    "pp": "💲",
}
# Vault items now include rarity, link, and description

@bot.tree.command(name="additem", description="Add an item to a user's vault")
@app_commands.describe(
    user="User to add the item for",
    description="Description of the item",
    link="Optional link related to the item",
    rarity="Rarity of the item",
    types="Type of the item"
)
@app_commands.choices(rarity=RARITY_CHOICES, types=TYPES_CHOICES)
async def additem(
    interaction: discord.Interaction,
    user: discord.User,
    description: str,
    rarity: app_commands.Choice[str],
    types: app_commands.Choice[str],
    link: str = None,
):
    if interaction.user.id not in allowed_user_ids:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    vault.setdefault(user.id, []).append({
        "description": description,
        "link": link,
        "rarity": rarity.value if rarity else "Common",
        "types": types.value if types else "Other"
    })

    embed = discord.Embed(
        title="Item Added",
        color=discord.Color.green()
    )
    embed.description = f"Added to **{user.display_name}**'s vault:\n• **{description}**"
    embed.add_field(name="Rarity", value=f"{RARITY_EMOJIS.get(rarity.value, '')} {rarity.value}" if rarity else "Common", inline=True)
    embed.add_field(name="Type", value=f"{TYPE_EMOJIS.get(types.value, '')} {types.value}" if types else "Other", inline=True)
    if link:
        embed.add_field(name="Link", value=f"[Click Here]({link})", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="removeitem", description="Remove an item from a user's vault")
@app_commands.describe(
    user="User to remove the item from",
    description="Description of the item to remove",
    link="Optional link related to the item",
    rarity="Rarity of the item",
    types="Type of the item"
)
@app_commands.choices(rarity=RARITY_CHOICES, types=TYPES_CHOICES)
async def removeitem(
    interaction: discord.Interaction,
    user: discord.User,
    description: str,
    rarity: app_commands.Choice[str],
    types: app_commands.Choice[str],
    link: str = None,
):
    if interaction.user.id not in allowed_user_ids:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    items = vault.get(user.id, [])
    embed = discord.Embed(color=discord.Color.red())
    target_rarity = rarity.value if rarity else "Common"
    target_type = types.value if types else "Other"
    found = False
    for i, item in enumerate(items):
        if (item.get("description") == description
            and (link is None or item.get("link") == link)
            and item.get("rarity", "Common") == target_rarity
            and item.get("types", "Other") == target_type):
            del items[i]
            found = True
            break

    if found:
        embed.title = "Item Removed"
        embed.description = f"Removed from **{user.display_name}**'s vault:\n• **{description}**"
        embed.add_field(name="Rarity", value=f"{RARITY_EMOJIS.get(target_rarity, '')} {target_rarity}", inline=True)
        embed.add_field(name="Type", value=f"{TYPE_EMOJIS.get(target_type, '')} {target_type}", inline=True)
        if link:
            embed.add_field(name="Link", value=f"[Click Here]({link})", inline=True)
    else:
        embed.title = "Item Not Found"
        embed.description = (
            f"Could not find **{description}** with rarity **{target_rarity}** and type **{target_type}** in **{user.display_name}**'s vault."
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="showvault", description="Show your vault or another user's vault")
@app_commands.describe(user="User whose vault to show (optional)")
async def showvault(interaction: discord.Interaction, user: discord.User = None):
    if user is None:
        user = interaction.user  # Default to the caller

    items = vault.get(user.id, [])

    embed = discord.Embed(
        title=f"{user.display_name}'s Vault",
        color=discord.Color.blue()
    )

    if not items:
        embed.description = "No items in the vault."
    else:
        lines = []
        for item in items:
            desc = item.get("description")
            link = item.get("link")
            rarity = f"{RARITY_EMOJIS.get(item.get('rarity', 'Common'), '')} {item.get('rarity', 'Common')}"
            types = f"{TYPE_EMOJIS.get(item.get('types', 'Other'), '')} {item.get('types', 'Other')}"
            line = f"• **{desc}** — *{rarity}* — _{types}_"
            if link:
                line += f" ([link]({link}))"
            lines.append(line)

        embed.description = "\n\n".join(lines)  # Extra spacing between items

    embed.set_image(url="https://cdn.discordapp.com/attachments/1404353825573441546/1404994722925121636/Party_Inventory.jpg?ex=689d36cd&is=689be54d&hm=70c56a91815ce92ac5f8345b21b2ba050852bf26c22ff76bec198bb7a9528c6a&")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="exportvault", description="Export the entire vault data as a JSON file")
async def exportvault(interaction: discord.Interaction):
    if interaction.user.id not in allowed_user_ids:
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return

    # Serialize vault dictionary to JSON string
    vault_json = json.dumps(vault, indent=4)
    
    # Use StringIO to create a file-like object from the JSON string
    file_obj = StringIO(vault_json)
    file_obj.seek(0)
    
    # Send as a file attachment
    await interaction.response.send_message(
        content="Here is the exported vault data.",
        file=File(fp=file_obj, filename="vault_export.json"),
        ephemeral=True
    )

@bot.tree.command(name="importvaultfile", description="Import vault from uploaded JSON file")
async def importvaultfile(interaction: discord.Interaction, file: discord.Attachment):
    if interaction.user.id not in allowed_user_ids:
        await interaction.response.send_message("You do not have permission.", ephemeral=True)
        return
    
    try:
        content = await file.read()
        new_vault = json.loads(content.decode())
        if not isinstance(new_vault, dict):
            raise ValueError("Invalid format")

        vault.clear()
        vault.update({int(k): v for k, v in new_vault.items()})
        await interaction.response.send_message("Vault imported successfully!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Error importing: {e}", ephemeral=True)


trade_interest_messages = {}  # key: message_id (interest msg) -> dict with original_poster_id, interested_user_id, trade_post_id
trade_sessions = {}  # key: trade_interest_message_id -> original_tradepost_message_id

@bot.tree.command(name="tradepost", description="Put one of your vault items up for trade")
@app_commands.describe(
    item_description="Description (or part) of the item you want to trade",
    wanted_description="What you want in exchange for this item"
)
async def tradepost(interaction: discord.Interaction, item_description: str, wanted_description: str):
    user_id = interaction.user.id
    user_items = vault.get(user_id, [])

    matched_item = None
    for item in user_items:
        if item_description.lower() in item.get("description", "").lower():
            matched_item = item
            break

    if not matched_item:
        await interaction.response.send_message(
            f"No item found in your vault matching '{item_description}'.", ephemeral=True
        )
        return

    rarity = matched_item.get("rarity", "Common")
    types = matched_item.get("types", "Other")
    desc = matched_item.get("description", "No description")
    link = matched_item.get("link")

    embed = discord.Embed(
        title="Item For Trade",
        color=discord.Color.gold()
    )
    embed.description = f"**{desc}**"
    embed.add_field(name="Rarity", value=f"{RARITY_EMOJIS.get(rarity, '')} {rarity}", inline=True)
    embed.add_field(name="Type", value=f"{TYPE_EMOJIS.get(types, '')} {types}", inline=True)
    embed.add_field(name="Wanted In Exchange", value=wanted_description, inline=False)
    if link:
        embed.add_field(name="Link", value=f"[Click Here]({link})", inline=True)

    embed.set_footer(text=f"Posted for trade by {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    message = await interaction.original_response()
    await message.add_reaction("🙋")  # Reaction to show interest

    # Save who posted this trade for reaction validation later
    trade_interest_messages[message.id] = user_id
    # Note: You do not have a response attribute on message, just store with message.id
    # You will map interest messages to this original tradepost message in on_reaction_add

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    message = reaction.message
    emoji = reaction.emoji

    # Interest reaction on trade post message
    if emoji == "🙋" and message.embeds:
        embed_title = message.embeds[0].title

        if embed_title == "Item For Trade":
            # Someone is interested in trade, create a reply message with ✅ react
            interested_embed = discord.Embed(
                title="Trade Interest",
                description=(
                    f"**{user.display_name}** is interested in this trade!\n\n"
                    "Original poster, react ✅ to this message to accept the trade."
                ),
                color=discord.Color.green()
            )
            interested_embed.set_footer(text=f"React to accept trade. Trade Post ID: {message.id}")

            interest_message = await message.reply(embed=interested_embed)
            await interest_message.add_reaction("✅")

            original_poster_id = trade_interest_messages.get(message.id)
            trade_interest_messages[interest_message.id] = {
                "original_poster_id": original_poster_id,
                "interested_user_id": user.id,
                "trade_post_id": message.id
            }
            # Map interest message id to original tradepost message id for future reference
            trade_sessions[interest_message.id] = message.id

    # Accept trade reaction on interest message
    elif emoji == "✅" and message.embeds:
        embed_title = message.embeds[0].title

        if embed_title == "Trade Interest":
            data = trade_interest_messages.get(message.id)
            if data is None:
                return

            original_poster_id = data["original_poster_id"]

            # Only original poster can accept trade here
            if user.id == original_poster_id:
                guild = message.guild
                original_member = guild.get_member(original_poster_id)
                interested_member = guild.get_member(data["interested_user_id"])

                accepted_embed = discord.Embed(
                    title="Trade Accepted ✅",
                    description=(
                        f"Trade accepted by **{original_member.display_name if original_member else 'Original Poster'}** "
                        f"and **{interested_member.display_name if interested_member else 'Interested User'}**!\n"
                        f"An admin will shortly complete the trade transaction."
                    ),
                    color=discord.Color.gold()
                )
                accepted_embed.set_footer(text=f"Trade post ID: {data['trade_post_id']}")

                await message.edit(embed=accepted_embed)
                await message.clear_reactions()
                await message.add_reaction("📦")  # Reaction for transaction complete

    # Transaction complete reaction by admin
    elif emoji == "📦" and message.embeds:
        embed_title = message.embeds[0].title

        if embed_title == "Trade Accepted ✅":
            if user.id not in allowed_user_ids:
                return  # Unauthorized user; ignore

            # Lookup original TradePost embed message ID
            original_msg_id = trade_sessions.get(message.id)
            if not original_msg_id:
                return

            # Fetch the channel and original message object
            channel = message.channel
            original_msg = await channel.fetch_message(original_msg_id)

            # Remove 📦 reaction from the original TradePost embed message to disable it
            await original_msg.clear_reaction("🙋")

            # Remove the 📦 reaction from the Trade Accepted message to disable it
            await message.clear_reaction(emoji)

            # Find the two traders from trade_interest_messages mapping
            traders = trade_interest_messages.get(message.id)

            if traders:
                guild = message.guild
                original_member = guild.get_member(traders["original_poster_id"])
                interested_member = guild.get_member(traders["interested_user_id"])

                mentions = []
                if original_member:
                    mentions.append(original_member.mention)
                if interested_member:
                    mentions.append(interested_member.mention)

                mention_text = " ".join(mentions) if mentions else ""

                await message.channel.send(
                    content=f"✅ Transaction has been completed by **{user.display_name}**! {mention_text}",
                    reference=message.to_reference(fail_if_not_exists=False)
                )

                # Optionally clean up tracking data here
                del trade_interest_messages[message.id]
                del trade_sessions[message.id]


# ---- Help command ----
@bot.tree.command(name="help", description="Show list of all commands and their descriptions")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Bot Commands Help",
        color=discord.Color.blurple()
    )

    # Get all commands in the tree for the current guild or global
    commands_list = bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))

    for cmd in commands_list:
        embed.add_field(name=f"/{cmd.name}", value=cmd.description or "No description", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---- events and error ----

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f"✅ Logged in as {bot.user} and synced commands to guild {GUILD_ID}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(f"Error: {error}", ephemeral=True)


# Minimal HTTP server
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('', port), Handler)
    server.serve_forever()

# Minimal HTTP server (your HEAD/GET fix is fine)
Thread(target=run_server).start()

retry_delay = 5  # start small
while True:
    try:
        bot.run(TOKEN)
        break  # only exits loop if bot.run finishes cleanly
    except Exception as e:
        print(f"Bot crashed: {e}. Retrying in {retry_delay} seconds...")
        traceback.print_exc()  # shows full stack trace
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, 60)  # exponential backoff up to 60s
