import asyncio
import discord
from yt_dlp import YoutubeDL

# YTDL format options
ytdl_format_options = {
    "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",  # Prefer non-DASH
    "quiet": True,
    "no_warnings": True,
    "skip_unavailable_fragments": True,
    "source_address": "0.0.0.0",  # Force IPv4
    "nocheckcertificate": True,
    "extract_flat": False,  # Get real URLs
    "noplaylist": True,  # Single track only
    "concurrent_fragment_downloads": 1,  # Avoid too many parallel requests
    "force_ipv4": True,
    "extractor_args": {"youtube": {"player_client": ["web"]}},  # Avoid tv/ios clients
    "http_headers": {  # Mimic Chrome
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    },
}

# FFmpeg options
ffmpeg_options = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

ytdl = YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    """A class for streaming audio from YouTube or other sources."""

    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.webpage_url = data.get("webpage_url")  # Always keep the original page link

    @classmethod
    async def from_query(cls, query, *, loop=None, speed=1.0, filter_options=None):
        loop = loop or asyncio.get_event_loop()

        if not query.startswith("http"):
            query = f"ytsearch:{query}"

        try:
            # Step 1: Extract info (just metadata, no download)
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=False)
            )

            if data is None:
                print(f"No results found for query: {query}")
                return None

            if "entries" in data:
                data = data["entries"][0]

            if not data or "url" not in data:
                print(f"Invalid data for query: {query} - URL not found.")
                return None

            # Step 2: Re-extract URL right before playback to avoid 403
            fresh_info = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(data["webpage_url"], download=False)
            )

            if "entries" in fresh_info:
                fresh_info = fresh_info["entries"][0]

            if not fresh_info or "url" not in fresh_info:
                print(f"Could not refresh stream URL for: {data['title']}")
                return None

            # Step 3: Build FFmpeg options
            ffmpeg_opts = ffmpeg_options.copy()
            options = ffmpeg_opts.get("options", "")

            if speed != 1.0:
                options += f" -af atempo={speed}"

            if filter_options:
                if "-af" in options:
                    options += f",{filter_options}"
                else:
                    options += f" -af {filter_options}"

            ffmpeg_opts["options"] = options

            return cls(
                discord.FFmpegPCMAudio(fresh_info["url"], **ffmpeg_opts),
                data=fresh_info,
            )

        except Exception as e:
            print(f"Error in from_query({query}): {e}")
            return None
