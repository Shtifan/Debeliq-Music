import discord
import random
import json
from discord.ext import commands, tasks
from discord import app_commands
from utils.ytdl import YTDLSource
from utils.spotify import SpotifyHelper

with open("config.json") as f:
    cfg = json.load(f)


class Music(commands.Cog):
    def __init__(self, bot, spotify_helper):
        self.bot = bot
        self.spotify_helper = spotify_helper
        self.queues = {}
        self.current = {}
        self.history = {}
        self.loop_states = {}
        self.volumes = {}
        self.speeds = {}
        self.start_times = {}
        self.check_empty_channels.start()

    def get_speed(self, gid):
        return self.speeds.get(gid, 1.0)

    def set_speed(self, gid, speed):
        self.speeds[gid] = speed

    def get_queue(self, gid):
        return self.queues.setdefault(gid, [])

    def get_history(self, gid):
        return self.history.setdefault(gid, [])

    def get_loop(self, gid):
        return self.loop_states.get(gid)

    def set_loop(self, gid, state):
        self.loop_states[gid] = state

    def get_vol(self, gid):
        return self.volumes.get(gid, 0.5)

    def set_vol(self, gid, vol):
        self.volumes[gid] = vol
        vc = discord.utils.get(self.bot.voice_clients, guild__id=gid)
        if vc and vc.source:
            vc.source.volume = vol

    def is_voice_channel_empty(self, gid):
        vc = discord.utils.get(self.bot.voice_clients, guild__id=gid)
        if not vc or not vc.channel:
            return True
        users = [m for m in vc.channel.members if not m.bot]
        return len(users) == 0

    async def join_vc(self, inter):
        if inter.user.voice:
            ch = inter.user.voice.channel
            vc = inter.guild.voice_client
            if not vc or not vc.is_connected():
                vc = await ch.connect()
            elif vc.channel != ch:
                await vc.move_to(ch)
            return vc
        await inter.followup.send("Join a voice channel first.", ephemeral=True)
        return None

    async def play_next(self, gid, text_channel=None, from_back=False):
        vc = discord.utils.get(self.bot.voice_clients, guild__id=gid)
        queue = self.get_queue(gid)
        loop_mode = self.get_loop(gid)

        if loop_mode == "song" and self.current.get(gid) and not from_back:
            queue.insert(0, self.current[gid].query)
        elif loop_mode == "queue" and self.current.get(gid) and not from_back:
            queue.append(self.current[gid].query)

        if self.current.get(gid) and not from_back:
            self.get_history(gid).append(self.current[gid].query)

        if not queue:
            self.current.pop(gid, None)
            if text_channel:
                await text_channel.send("Queue finished.")
            if vc:
                await vc.disconnect()
            return

        if vc:
            query = queue.pop(0)
            try:
                speed = self.get_speed(gid)
                player = await YTDLSource.from_query(
                    query, loop=self.bot.loop, speed=speed
                )
                if player is None:
                    if text_channel:
                        await text_channel.send(f"Could not play `{query}`. Skipping.")
                    await self.play_next(gid, text_channel)
                    return
                player.volume = self.get_vol(gid)
                vc.play(
                    player,
                    after=lambda e: self.bot.loop.call_soon_threadsafe(
                        self.bot.loop.create_task,
                        self.play_next(gid, text_channel),
                    ),
                )
                self.current[gid] = player
                player.query = query
                self.start_times[gid] = discord.utils.utcnow().timestamp()
                if text_channel:
                    await text_channel.send(f"Now playing: **{player.title}**")
            except Exception as e:
                print(f"Error playing {query}: {e}")
                if text_channel:
                    await text_channel.send(f"Failed to play `{query}`. Skipping.")
                await self.play_next(gid, text_channel)
        else:
            self.current.pop(gid, None)
            if text_channel:
                await text_channel.send("Queue finished.")

    @tasks.loop(seconds=30)
    async def check_empty_channels(self):
        for vc in self.bot.voice_clients:
            if not vc.is_connected():
                continue
            if self.is_voice_channel_empty(vc.guild.id):
                await vc.disconnect()

    @app_commands.command(name="play", description="Play music from search or link")
    @app_commands.describe(query="YouTube URL, Spotify URL or name search")
    async def play(self, inter, query: str):
        await inter.response.defer(thinking=True)

        tracks = []
        is_spotify = "open.spotify.com" in query
        if is_spotify:
            try:
                tracks = self.spotify_helper.extract_tracks(query)
                if not tracks:
                    await inter.followup.send(
                        "Could not extract tracks from Spotify link."
                    )
                    return
            except Exception as e:
                await inter.followup.send("Error extracting Spotify tracks.")
                print(f"Spotify extraction error: {e}")
                return
        else:
            tracks = [query]

        q = self.get_queue(inter.guild.id)
        q.extend(tracks)

        vc = inter.guild.voice_client
        if not vc:
            vc = await self.join_vc(inter)
            if not vc:
                return

        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(inter.guild.id, inter.channel)

        if is_spotify:
            await inter.followup.send(
                f"Added {len(tracks)} tracks from Spotify to the queue."
            )
        else:
            await inter.followup.send(f"Added to queue: `{query}`.")

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, inter):
        vc = inter.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await inter.response.send_message("Skipped.")
        else:
            await inter.response.send_message("Nothing is playing.")
        if vc and self.is_voice_channel_empty(inter.guild.id):
            await vc.disconnect()

    @app_commands.command(name="queue", description="Show the queue")
    async def queue_cmd(self, inter):
        q = self.get_queue(inter.guild.id)
        cur = self.current.get(inter.guild.id)
        if not q and not cur:
            await inter.response.send_message("Nothing is playing.")
            return
        em = discord.Embed(title="Queue")
        if cur:
            dur = int(cur.data.get("duration", 0))
            start = self.start_times.get(inter.guild.id)
            if start:
                pos = int(discord.utils.utcnow().timestamp() - start)
            else:
                pos = 0
            pos_str = self.format_time(pos)
            dur_str = self.format_time(dur)
            em.add_field(
                name="Now", value=f"{cur.title} [{pos_str}/{dur_str}]", inline=False
            )
        if q:
            em.add_field(
                name="Up Next",
                value="\n".join(f"{i+1}. {t}" for i, t in enumerate(q[:10])),
                inline=False,
            )
            if len(q) > 10:
                em.set_footer(text=f"...and {len(q)-10} more")
        await inter.response.send_message(embed=em)

    @app_commands.command(name="nowplaying", description="What's playing")
    async def nowplaying(self, inter):
        cur = self.current.get(inter.guild.id)
        if cur:
            dur = int(cur.data.get("duration", 0))
            start = self.start_times.get(inter.guild.id)
            if start:
                pos = int(discord.utils.utcnow().timestamp() - start)
            else:
                pos = 0
            pos_str = self.format_time(pos)
            dur_str = self.format_time(dur)
            await inter.response.send_message(
                f"Now: **{cur.title}** [{pos_str}/{dur_str}]"
            )
        else:
            await inter.response.send_message("Nothing is playing.")

    def format_time(self, seconds):
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02}:{s:02}"
        else:
            return f"{m}:{s:02}"

    @app_commands.command(name="stop", description="Stop and disconnect")
    async def stop(self, inter):
        vc = inter.guild.voice_client
        if vc:
            vc.stop()
            await vc.disconnect()
        gid = inter.guild.id
        for d in [
            self.queues,
            self.current,
            self.history,
            self.loop_states,
            self.volumes,
        ]:
            d.pop(gid, None)
        await inter.response.send_message("Stopped and cleaned up.")

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, inter):
        vc = inter.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await inter.response.send_message("Paused.")
        else:
            await inter.response.send_message("Nothing to pause.")

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, inter):
        vc = inter.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await inter.response.send_message("Resumed.")
        else:
            await inter.response.send_message("Nothing paused.")

    @app_commands.command(name="clear", description="Clear the queue")
    async def clear(self, inter):
        self.get_queue(inter.guild.id).clear()
        await inter.response.send_message("Queue cleared.")

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle(self, inter):
        random.shuffle(self.get_queue(inter.guild.id))
        await inter.response.send_message("Queue shuffled.")

    @app_commands.command(name="remove", description="Remove song from queue")
    @app_commands.describe(idx="Song position")
    async def remove(self, inter, idx: int):
        q = self.get_queue(inter.guild.id)
        if 1 <= idx <= len(q):
            removed = q.pop(idx - 1)
            await inter.response.send_message(f"Removed **{removed}**.")
        else:
            await inter.response.send_message("Invalid position.")

    @app_commands.command(name="move", description="Move song in queue")
    @app_commands.describe(frm="From position", to="To position")
    async def move(self, inter, frm: int, to: int):
        q = self.get_queue(inter.guild.id)
        if not all(1 <= x <= len(q) for x in (frm, to)):
            return await inter.response.send_message("Invalid positions.")
        s = q.pop(frm - 1)
        q.insert(to - 1, s)
        await inter.response.send_message(f"Moved to position {to}.")

    @app_commands.command(name="swap", description="Swap songs in queue")
    @app_commands.describe(a="First song", b="Second song")
    async def swap(self, inter, a: int, b: int):
        q = self.get_queue(inter.guild.id)
        if not all(1 <= x <= len(q) for x in (a, b)):
            return await inter.response.send_message("Invalid positions.")
        q[a - 1], q[b - 1] = q[b - 1], q[a - 1]
        await inter.response.send_message(f"Swapped positions {a} and {b}.")

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def loop(self, inter):
        gid = inter.guild.id
        cur = self.get_loop(gid)
        nxt = "song" if cur is None else "queue" if cur == "song" else None
        self.set_loop(gid, nxt)
        await inter.response.send_message(f"Loop mode: **{nxt or 'off'}**")

    @app_commands.command(name="volume", description="Set playback volume (max 200%)")
    @app_commands.describe(level="Volume level (0-200)")
    async def volume(self, inter, level: int):
        capped = max(0, min(level, 200))
        self.set_vol(inter.guild.id, capped / 100)
        await inter.response.send_message(f"Volume set to **{capped}%**")

    @app_commands.command(name="seek", description="Seek in current song")
    @app_commands.describe(position="Time in seconds")
    async def seek(self, inter, position: int):
        vc = inter.guild.voice_client
        cur = self.current.get(inter.guild.id)
        if not vc or not cur:
            return await inter.response.send_message("Nothing playing.")
        self.get_queue(inter.guild.id).insert(0, cur.query)
        await vc.stop()
        await self.play_next(inter.guild.id, inter.channel)
        await inter.response.send_message(f"Seeking to {position}s (reloaded).")

    @app_commands.command(name="speed", description="Set playback speed")
    @app_commands.describe(rate="Speed from 0.5x to 2.0x")
    async def speed(self, inter, rate: app_commands.Range[float, 0.5, 2.0]):
        cur = self.current.get(inter.guild.id)
        vc = inter.guild.voice_client
        if not vc or not cur:
            await inter.response.send_message("Nothing playing.")
            return
        await inter.response.defer(thinking=True)
        self.set_speed(inter.guild.id, rate)
        self.get_queue(inter.guild.id).insert(0, cur.query)
        await vc.stop()
        await inter.followup.send(f"Playback speed set to {rate}x (reloading...)")
        await self.play_next(inter.guild.id, inter.channel)

    async def cog_unload(self):
        self.check_empty_channels.cancel()


async def setup(bot):
    with open("config.json") as f:
        cfg = json.load(f)
    spotify_helper = SpotifyHelper(
        client_id=cfg["spotify_client_id"], client_secret=cfg["spotify_client_secret"]
    )
    await bot.add_cog(Music(bot, spotify_helper))
