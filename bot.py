import discord
from discord.ext import commands
import json
import asyncio

# Load configuration from config.json
with open("config.json") as f:
    config = json.load(f)

# Set up intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # Enable voice state intents

# Initialize the bot
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Event handler for when the bot is ready."""
    print(f"Logged in as {bot.user.name}.")
    try:
        # Sync commands for each guild
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
        
        synced = await bot.tree.sync() # Sync global commands as a fallback
        print(f"Synced {len(synced)} global commands.")

    except Exception as e:
        print(f"Error syncing commands: {e}")


async def main():
    """Main function to load cogs and start the bot."""
    async with bot:
        await bot.load_extension("cogs.music")
        await bot.start(config["token"])


# Run the main function
if __name__ == "__main__":
    asyncio.run(main())