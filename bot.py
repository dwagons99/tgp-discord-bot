# bot.py
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from datetime import datetime, timezone
import asyncio

# ---------- Utility ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def log(msg):
    line = f"[{now_iso()}] {msg}"
    print(line)
    try:
        with open("debug.log", "a", encoding="utf8") as f:
            f.write(line + "\n")
    except Exception:
        # non-fatal if file can't be written
        pass

# ---------- Ensure Files ----------
if not os.path.exists("config.json"):
    with open("config.json", "w", encoding="utf8") as f:
        json.dump({
            "token": "YOUR_BOT_TOKEN_HERE",
            "guild_id": 0,
            "channel_id": 0,
            "authorized_roles": [],
            "ticket_category_id": 0,
            "alert_user_id": 0,
            "debug": True
        }, f, indent=2)
    log("🆕 Created config.json; fill in details then restart.")
    raise SystemExit

if not os.path.exists("stock.json"):
    with open("stock.json", "w", encoding="utf8") as f:
        json.dump({
            "Hex Lifetime": 0,
            "Hex Monthly": 0,
            "SRC Lifetime": 0,
            "SRC Monthly": 0
        }, f, indent=2)
    log("🆕 Created stock.json with defaults.")

# load config and stock
with open("config.json", "r", encoding="utf8") as f:
    raw_conf = json.load(f)

with open("stock.json", "r", encoding="utf8") as f:
    stock = json.load(f)

# ---------- Normalize config (accept camelCase or snake_case) ----------
def parse_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default

config = {
    "token": raw_conf.get("token") or raw_conf.get("token"),
    "guild_id": parse_int(raw_conf.get("guild_id") or raw_conf.get("guildId")),
    "channel_id": parse_int(raw_conf.get("channel_id") or raw_conf.get("stockChannelId") or raw_conf.get("channelId")),
    "authorized_roles": [parse_int(r) for r in (raw_conf.get("authorized_roles") or raw_conf.get("authorizedRoles") or [])],
    "ticket_category_id": parse_int(raw_conf.get("ticket_category_id") or raw_conf.get("ticketCategoryId")),
    "alert_user_id": parse_int(raw_conf.get("alert_user_id") or raw_conf.get("alertUserId")),
    "debug": bool(raw_conf.get("debug", False))
}

if not config["token"] or config["token"].startswith("YOUR_BOT_TOKEN"):
    log("ERROR: config.json token is missing or placeholder. Edit config.json and restart.")
    raise SystemExit

# ---------- Bot ----------
intents = discord.Intents.default()
intents.message_content = False   # not needed for slash commands; turn on only if you use message content
intents.guilds = True
intents.members = True  # we may need members to check roles
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Helpers ----------
def save_stock():
    try:
        with open("stock.json", "w", encoding="utf8") as f:
            json.dump(stock, f, indent=2)
    except Exception as e:
        log(f"Failed to write stock.json: {e}")

def has_authorized_role(interaction: discord.Interaction) -> bool:
    """
    Returns True if the invoking user has any role listed in config['authorized_roles'].
    Works even if interaction.user is a plain User (will try to fetch Member).
    """
    try:
        target_roles = set(config["authorized_roles"])
        if not target_roles:
            return False
        # prefer member on interaction (should be Member in guild)
        member = None
        if isinstance(interaction.user, discord.Member):
            member = interaction.user
        elif interaction.guild:
            # try to fetch member
            member = interaction.guild.get_member(interaction.user.id) or asyncio.run_coroutine_threadsafe(
                interaction.guild.fetch_member(interaction.user.id), bot.loop
            ).result()
        if not member:
            return False
        return any(r.id in target_roles for r in member.roles)
    except Exception:
        return False

# ---------- Stock Embed ----------
def generate_stock_embed():
    embed = discord.Embed(
        title="The Golden Prism Store",
        description="This message is updated automatically.",
        color=0x00AAFF,
        timestamp=datetime.now(timezone.utc)
    )

    embed.add_field(
        name="《Hex:》",
        value=(
            f"Lifetime — {'🟢 In Stock — **$80**' if stock.get('Hex Lifetime', 0) > 0 else '🔴 Out of Stock — **$80**'}\n"
            f"Monthly — {'🟢 In Stock — **$13**' if stock.get('Hex Monthly', 0) > 0 else '🔴 Out of Stock — **$13**'}"
        ),
        inline=False
    )
    embed.add_field(
        name="《SRC:》",
        value=(
            f"Lifetime — {'🟢 In Stock — **$65**' if stock.get('SRC Lifetime', 0) > 0 else '🔴 Out of Stock — **$65**'}\n"
            f"Monthly — {'🟢 In Stock — **$12**' if stock.get('SRC Monthly', 0) > 0 else '🔴 Out of Stock — **$12**'}"
        ),
        inline=False
    )
    return embed

async def find_own_stock_message(channel: discord.TextChannel):
    """Return the first recent message authored by the bot in the channel, or None."""
    try:
        async for msg in channel.history(limit=100):
            if msg.author and msg.author.id == bot.user.id:
                return msg
    except Exception as e:
        log(f"Error while searching messages in channel {channel.id}: {e}")
    return None

async def update_stock_message():
    try:
        # Prefer using bot.get_channel for reliability
        ch = bot.get_channel(config["channel_id"])
        if ch is None and config["guild_id"]:
            guild = bot.get_guild(config["guild_id"])
            if guild:
                ch = guild.get_channel(config["channel_id"])
        if ch is None:
            log(f"⚠️ Stock channel ID {config['channel_id']} not found or bot has no access.")
            return

        # check permissions
        me_member = ch.guild.me if ch.guild else None
        if me_member:
            perms = ch.permissions_for(me_member)
            if not perms.send_messages or not perms.embed_links:
                log("⚠️ Bot lacks SendMessages or EmbedLinks permission for the stock channel.")
                return

        own_msg = await find_own_stock_message(ch)
        if own_msg:
            await own_msg.edit(embed=generate_stock_embed())
            log("♻️ Updated stock message.")
        else:
            await ch.send(embed=generate_stock_embed())
            log("🆕 Posted new stock message.")
    except Exception as e:
        log(f"⚠️ update_stock_message error: {e}")

# ---------- Slash Commands ----------
@bot.tree.command(name="addstock", description="Add to a product's stock count.")
@app_commands.describe(product="Product name (case-insensitive)", amount="Amount to add")
async def addstock(interaction: discord.Interaction, product: str, amount: int):
    # Check authorization
    if not any(r.id in config["authorized_roles"] for r in interaction.user.roles):
        await interaction.response.send_message("⛔ You are not authorized to use this command.", ephemeral=True)
        return

    # Normalize input
    product_clean = product.strip().lower()
    match = next((key for key in stock.keys() if key.lower() == product_clean), None)

    if not match:
        valid = ", ".join(stock.keys())
        await interaction.response.send_message(
            f"⚠️ Invalid product name.\nAvailable products: `{valid}`",
            ephemeral=True
        )
        return

    # Apply change
    stock[match] += amount
    with open("stock.json", "w", encoding="utf8") as f:
        json.dump(stock, f, indent=2)

    await update_stock_message()
    await interaction.response.send_message(
        f"✅ Added **{amount}** units to **{match}**.",
        ephemeral=True
    )


@bot.tree.command(name="removestock", description="Remove from a product's stock count.")
@app_commands.describe(product="Product name (case-insensitive)", amount="Amount to remove")
async def removestock(interaction: discord.Interaction, product: str, amount: int):
    # Check authorization
    if not any(r.id in config["authorized_roles"] for r in interaction.user.roles):
        await interaction.response.send_message("⛔ You are not authorized to use this command.", ephemeral=True)
        return

    # Normalize input
    product_clean = product.strip().lower()
    match = next((key for key in stock.keys() if key.lower() == product_clean), None)

    if not match:
        valid = ", ".join(stock.keys())
        await interaction.response.send_message(
            f"⚠️ Invalid product name.\nAvailable products: `{valid}`",
            ephemeral=True
        )
        return

    # Apply change safely
    stock[match] = max(0, stock[match] - amount)
    with open("stock.json", "w", encoding="utf8") as f:
        json.dump(stock, f, indent=2)

    await update_stock_message()
    await interaction.response.send_message(
        f"✅ Removed **{amount}** units from **{match}**.",
        ephemeral=True
    )

@bot.tree.command(name="restockmessage", description="Create or reset the persistent stock message.")
async def restockmessage(interaction: discord.Interaction):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    await update_stock_message()
    await interaction.response.send_message("✅ Stock message refreshed.", ephemeral=True)

@bot.tree.command(name="liststock", description="List all stock statuses (admin only).")
async def liststock(interaction: discord.Interaction):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    lines = [f"{k}: {'🟢 In Stock' if v>0 else '🔴 Out of Stock'}" for k, v in stock.items()]
    await interaction.response.send_message("\n".join(lines) or "No products defined.", ephemeral=True)

@bot.tree.command(name="getstatus", description="Get a single product's status.")
@app_commands.describe(product="Product name")
async def getstatus(interaction: discord.Interaction, product: str):
    if product not in stock:
        await interaction.response.send_message("⚠️ Product not found.", ephemeral=True)
        return
    await interaction.response.send_message(f"{product} — {'🟢 In Stock' if stock[product] > 0 else '🔴 Out of Stock'}", ephemeral=True)

@bot.tree.command(name="resetstock", description="Reset all stock to 0 (admin only).")
async def resetstock(interaction: discord.Interaction):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    for k in list(stock.keys()):
        stock[k] = 0
    save_stock()
    await update_stock_message()
    await interaction.response.send_message("🧹 All stock reset to 0.", ephemeral=True)

# ---------- Ticket Category Watch ----------
@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    try:
        cat_id = getattr(channel, "category_id", None)
        if cat_id != config["ticket_category_id"]:
            return
        if not config["alert_user_id"]:
            log("alert_user_id not configured; skipping ticket DM.")
            return

        alert_user = await bot.fetch_user(config["alert_user_id"])
        if not alert_user:
            log("Could not fetch alert user; they may have DMs closed or ID incorrect.")
            return

        embed = discord.Embed(
            title="🎟️ New Ticket Opened",
            description=f"A new ticket was created: {channel.mention}",
            color=0x00AAFF,
            timestamp=datetime.now(timezone.utc)
        )

        maybe = (channel.name or "").strip()
        # attempt to find numeric ID in channel name (Ticket Tool sometimes uses user id)
        import re
        m = re.search(r"\d{17,19}", maybe)
        if m:
            try:
                u = await bot.fetch_user(int(m.group(0)))
                embed.add_field(name="Opened By", value=f"{u} ({u.id})", inline=True)
            except Exception:
                embed.add_field(name="Opened By", value=f"User ID {m.group(0)}", inline=True)

        await alert_user.send(embed=embed)
        log(f"📩 DM sent about new ticket {channel.name}")
    except Exception as e:
        log(f"⚠️ Ticket watcher error: {e}")

# ---------- Ready ----------
@bot.event
async def on_ready():
    log(f"✅ Logged in as {bot.user} ({bot.user.id})")

    # Attempt to ensure guild is available; retry a few times because cache may take a moment
    tries = 0
    guild = None
    while tries < 5:
        guild = bot.get_guild(config["guild_id"])
        if guild:
            break
        tries += 1
        log(f"Guild {config['guild_id']} not found yet; retrying in 2s ({tries}/5)...")
        await asyncio.sleep(2)

    try:
        if guild:
            await bot.tree.sync(guild=guild)
            log("🌐 Slash commands synced (guild-scoped).")
            # update stock message now that guild/channel should be visible
            await update_stock_message()
        else:
            # fallback: try syncing globally (may take up to an hour to propagate)
            try:
                await bot.tree.sync()
                log("🌐 Slash commands synced globally (fallback).")
            except Exception as e:
                log(f"Failed to sync slash commands globally: {e}")
            log(f"⚠️ Could not find guild {config['guild_id']} after retries.")
    except Exception as e:
        log(f"⚠️ Slash sync or update error: {e}")

# ---------- Start ----------
if __name__ == "__main__":
    bot.run(config["token"])
