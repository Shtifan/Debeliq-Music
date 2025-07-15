import asyncio
import discord
from yt_dlp import YoutubeDL

ytdl_format_options = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'auto',
    'extract_flat': False,
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_query(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()

        if not query.startswith("http"):
            query = f"ytsearch:{query}"

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))

        if 'entries' in data:
            data = data['entries'][0]

        return cls(discord.FFmpegPCMAudio(
            data['url'],
            **ffmpeg_options
        ), data=data)
