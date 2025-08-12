import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from dateutil import parser
import asyncio
from datetime import datetime, timezone

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

class JoinModal(discord.ui.Modal, title="Format: {Name} - {Lvl} {Class}"):
    def __init__(self, message_id, user_id, max_participants):
        super().__init__()
        self.message_id = message_id
        self.user_id = user_id
        self.max_participants = max_participants

    character_desc = discord.ui.TextInput(
        label="Character Description",
        style=discord.TextStyle.paragraph,
        placeholder="Enter your character name, class, or details here",
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
    def __init__(self, message_id, max_participants):
        super().__init__(timeout=None)
        self.message_id = message_id
        self.max_participants = max_participants

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
            modal = JoinModal(self.message_id, user_id, self.max_participants)
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

allowed_user_ids = {284137393483939841, 261651766213345282}  # Replace with actual Discord user IDs

async def schedule_event_reminder(message_id: int):
    signups = event_signups.get(message_id)
    if not signups:
        return  # event expired or deleted

    event_time = signups.get("event_time")
    if not event_time:
        return

    reminder_time = event_time.timestamp() - 15*60  # 15 minutes before event start (in seconds)
    now = datetime.now(timezone.utc).timestamp()
    wait_seconds = reminder_time - now

    if wait_seconds <= 0:
        # Event is soon or passed, skip or send immediately
        wait_seconds = 0

    await asyncio.sleep(wait_seconds)

    # After waiting, send reminder message
    channel = None
    message = None

    # Try to find the message's channel and message
    for guild in bot.guilds:
        for channel_candidate in guild.text_channels:
            try:
                message = await channel_candidate.fetch_message(message_id)
                channel = channel_candidate
                break
            except discord.NotFound:
                continue
            except discord.Forbidden:
                continue
        if message:
            break

    if not message or not channel:
        return  # message not found or inaccessible

    accepted = signups.get("accepted", {})
    if not accepted:
        return  # no participants to notify

    mentions = []
    for user_id in accepted.keys():
        member = channel.guild.get_member(user_id)
        if member:
            mentions.append(member.mention)

    if not mentions:
        return  # no members to mention

    mention_text = " ".join(mentions)
    await channel.send(f"⏰ Reminder: The event **{message.embeds[0].title}** starts in 15 minutes! {mention_text}")

@bot.tree.command(name="event", description="Create a custom event embed")
@app_commands.describe(
    title="Title of your event",
    description="Description for the event",
    time="Date and time for the event in ISO 8601 format, YYYY-MM-DDTHH:MM:SS-7:00",
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
        # Ensure datetime is timezone aware UTC
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        else:
            parsed_time = parsed_time.astimezone(timezone.utc)
    except Exception:
        await interaction.response.send_message("Invalid time format. Use ISO8601 (YYYY-MM-DDTHH:MM:SS).", ephemeral=True)
        return

    embed_time_str = f"<t:{int(parsed_time.timestamp())}:F>"

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

    # Send the embed + role mentions
    await interaction.response.send_message(
        content=roles_to_ping,
        embed=embed,
        allowed_mentions=discord.AllowedMentions(roles=True)
    )

    message = await interaction.original_response()

    # Initialize signup lists and store event time
    event_signups[message.id] = {
        "accepted": {},
        "waitlist": set(),
        "max_participants": max_participants,
        "event_time": parsed_time
    }

    # Add buttons
    view = EventView(message.id, max_participants)
    await message.edit(view=view)

    # Schedule the reminder task
    bot.loop.create_task(schedule_event_reminder(message.id))

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    print(f"✅ Logged in as {bot.user} and synced commands to guild {GUILD_ID}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    await interaction.response.send_message(f"Error: {error}", ephemeral=True)

bot.run(TOKEN)
