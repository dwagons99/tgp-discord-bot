# bot.py — Render-ready version
import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import asyncio
from datetime import datetime, timezone

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
        pass

# ---------- Load Config ----------
if not os.path.exists("stock.json"):
    with open("stock.json", "w", encoding="utf8") as f:
        json.dump({
            "Hex Lifetime": 0,
            "Hex Monthly": 0,
            "SRC Lifetime": 0,
            "SRC Monthly": 0
        }, f, indent=2)
    log("🆕 Created stock.json with defaults.")

with open("stock.json", "r", encoding="utf8") as f:
    stock = json.load(f)

# Environment variables from Render
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # <-- your token in Render dashboard
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
AUTHORIZED_ROLES = [int(r) for r in os.getenv("AUTHORIZED_ROLES", "").split(",") if r.strip().isdigit()]
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID", "0"))
ALERT_USER_ID = int(os.getenv("ALERT_USER_ID", "0"))

if not DISCORD_TOKEN:
    log("❌ Missing DISCORD_TOKEN environment variable. Set it in Render → Environment Variables.")
    raise SystemExit

# ---------- Bot ----------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- Helpers ----------
def save_stock():
    with open("stock.json", "w", encoding="utf8") as f:
        json.dump(stock, f, indent=2)

def has_authorized_role(interaction: discord.Interaction) -> bool:
    if not AUTHORIZED_ROLES or not interaction.guild:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if not member:
        return False
    return any(r.id in AUTHORIZED_ROLES for r in member.roles)

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

async def update_stock_message():
    try:
        ch = bot.get_channel(CHANNEL_ID)
        if not ch:
            guild = bot.get_guild(GUILD_ID)
            if guild:
                ch = guild.get_channel(CHANNEL_ID)
        if not ch:
            log(f"⚠️ Channel {CHANNEL_ID} not found.")
            return

        async for msg in ch.history(limit=20):
            if msg.author.id == bot.user.id:
                await msg.edit(embed=generate_stock_embed())
                log("♻️ Updated stock message.")
                return
        await ch.send(embed=generate_stock_embed())
        log("🆕 Posted new stock message.")
    except Exception as e:
        log(f"⚠️ update_stock_message error: {e}")

# ---------- Slash Commands ----------
@bot.tree.command(name="addstock", description="Add to a product's stock count.")
@app_commands.describe(product="Product name", amount="Amount to add")
async def addstock(interaction: discord.Interaction, product: str, amount: int):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    product_clean = product.strip().lower()
    match = next((k for k in stock if k.lower() == product_clean), None)
    if not match:
        await interaction.response.send_message(f"⚠️ Invalid product name.", ephemeral=True)
        return
    stock[match] += amount
    save_stock()
    await update_stock_message()
    await interaction.response.send_message(f"✅ Added {amount} to {match}.", ephemeral=True)

@bot.tree.command(name="removestock", description="Remove from a product's stock count.")
@app_commands.describe(product="Product name", amount="Amount to remove")
async def removestock(interaction: discord.Interaction, product: str, amount: int):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    product_clean = product.strip().lower()
    match = next((k for k in stock if k.lower() == product_clean), None)
    if not match:
        await interaction.response.send_message(f"⚠️ Invalid product name.", ephemeral=True)
        return
    stock[match] = max(0, stock[match] - amount)
    save_stock()
    await update_stock_message()
    await interaction.response.send_message(f"✅ Removed {amount} from {match}.", ephemeral=True)

@bot.tree.command(name="restockmessage", description="Refresh or create the stock display message.")
async def restockmessage(interaction: discord.Interaction):
    if not has_authorized_role(interaction):
        await interaction.response.send_message("⛔ You are not authorized.", ephemeral=True)
        return
    await update_stock_message()
    await interaction.response.send_message("✅ Stock message refreshed.", ephemeral=True)

# ---------- Ticket Monitor ----------
@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    try:
        if getattr(channel, "category_id", None) != TICKET_CATEGORY_ID:
            return
        if not ALERT_USER_ID:
            return
        user = await bot.fetch_user(ALERT_USER_ID)
        if not user:
            return
        embed = discord.Embed(
            title="🎟️ New Ticket Opened",
            description=f"A new ticket was created: {channel.mention}",
            color=0x00AAFF,
            timestamp=datetime.now(timezone.utc)
        )
        await user.send(embed=embed)
        log(f"📩 Alerted {user} about {channel.name}")
    except Exception as e:
        log(f"⚠️ Ticket watcher error: {e}")

# ---------- Ready ----------
@bot.event
async def on_ready():
    log(f"✅ Logged in as {bot.user} ({bot.user.id})")
    try:
        guild = bot.get_guild(GUILD_ID)
        if guild:
            await bot.tree.sync(guild=guild)
            log("🌐 Slash commands synced (guild).")
        await update_stock_message()
    except Exception as e:
        log(f"⚠️ on_ready error: {e}")

# ---------- Run ----------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
