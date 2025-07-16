import asyncio
import discord
from yt_dlp import YoutubeDL

# YTDL format options
ytdl_format_options = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "source_address": "0.0.0.0",
    "add_header": [
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    ],
}

# FFmpeg options
ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# Initialize YoutubeDL
ytdl = YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    """A class for streaming audio from YouTube."""

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.url = data.get("url")

    @classmethod
    async def from_query(cls, query, *, loop=None, speed=1.0):
        """Create a YTDLSource from a search query or URL."""
        loop = loop or asyncio.get_event_loop()

        if not query.startswith("http"):
            query = f"ytsearch:{query}"

        try:
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=False)
            )

            if data is None:
                print(f"No results found for query: {query}")
                return None

            if "entries" in data:
                data = data["entries"][0]

            if not data or "url" not in data:
                print(f"Invalid data for query: {query}")
                return None

            ffmpeg_opts = ffmpeg_options.copy()
            if speed != 1.0:
                atempo = f"atempo={speed}"
                if "options" in ffmpeg_opts and ffmpeg_opts["options"]:
                    ffmpeg_opts["options"] += f" -af {atempo}"
                else:
                    ffmpeg_opts["options"] = f"-af {atempo}"

            return cls(discord.FFmpegPCMAudio(data["url"], **ffmpeg_opts), data=data)

        except Exception as e:
            print(f"Error in from_query({query}): {e}")
            return None
