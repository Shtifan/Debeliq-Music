import discord
from discord.ext import commands
import json
import asyncio

# Load config
with open("config.json") as f:
    config = json.load(f)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()  # Global sync
        print(f"Synced {len(synced)} global commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

async def main():
    async with bot:
        await bot.load_extension("cogs.music")
        await bot.start(config["token"])

asyncio.run(main())
