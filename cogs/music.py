import discord
import random
import json
from discord.ext import commands
from discord import app_commands
from utils.ytdl import YTDLSource, ytdl
from utils.spotify import SpotifyHelper

# Load configuration from config.json
with open("config.json") as f:
    cfg = json.load(f)

# A dictionary of available audio filters and their ffmpeg options
AUDIO_FILTERS = {
    "none": None,
    "bassboost": "bass=g=10",
    "nightcore": "atempo=1.06,asetrate=44100*1.25",
    "vaporwave": "asetrate=44100*0.8,aresample=44100,atempo=0.8",
    "8d": "apulsator=hz=0.08",
    "vibrato": "vibrato=f=6.5",
    "tremolo": "tremolo",
    "earrape": "acrusher=1:1:64:0:log",
}


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
        self.filters = {}  # To store active filters
        self.start_times = {}
        self.autoplay_states = {}  # To store autoplay states
        self.text_channels = {}  # To store the text channel for each guild

    # --- Helper Methods ---

    def get_queue(self, gid):
        return self.queues.setdefault(gid, [])

    def get_history(self, gid):
        return self.history.setdefault(gid, [])

    def get_loop(self, gid):
        return self.loop_states.get(gid)

    def set_loop(self, gid, state):
        self.loop_states[gid] = state

    def get_vol(self, gid):
        return self.volumes.get(gid, 1.0)

    def set_vol(self, gid, vol):
        self.volumes[gid] = vol
        vc = discord.utils.get(self.bot.voice_clients, guild__id=gid)
        if vc and vc.source:
            vc.source.volume = vol

    def get_speed(self, gid):
        return self.speeds.get(gid, 1.0)

    def set_speed(self, gid, speed):
        self.speeds[gid] = speed

    def get_filter(self, gid):
        """Get the audio filter for a guild."""
        return self.filters.get(gid)

    def set_filter(self, gid, filter_name):
        """Set the audio filter for a guild."""
        self.filters[gid] = AUDIO_FILTERS.get(filter_name.lower())

    def get_autoplay(self, gid):
        """Get the autoplay state for a guild."""
        return self.autoplay_states.get(gid, True)

    def set_autoplay(self, gid, state):
        """Set the autoplay state for a guild."""
        self.autoplay_states[gid] = state

    def format_time(self, seconds):
        seconds = int(seconds)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02}:{s:02}"
        else:
            return f"{m}:{s:02}"

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

    # --- Core Music Logic ---

    async def _find_related_song(self, title: str, history: list):
        """
        Searches for a related song that is not in the recent history.
        It first tries a targeted search for the same artist, then falls back to a broader search.
        """
        try:
            # --- Stage 1: Targeted Search ---
            artist = ""
            # A simple heuristic to find the artist from the title.
            # You can add more separators like '|' or 'by' if needed.
            separators = ["-", "—", "by", "ft.", "feat."]
            lower_title = title.lower()

            for sep in separators:
                if f" {sep} " in lower_title:
                    # Take the part before the separator as the artist
                    artist = title.split(sep)[0].strip()
                    break

            # Use the artist if found, otherwise use the original title for the search
            search_term = (
                f"{artist} official audio" if artist else f"{title} official audio"
            )
            query = f"ytsearch5:{search_term}"

            data = await self.bot.loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=False, process=False)
            )

            if data and "entries" in data and data["entries"]:
                recent_history = [h.lower() for h in history[-10:]]
                for entry in data["entries"]:
                    entry_title = entry.get("title")
                    if not entry_title:
                        continue

                    # Check if the found song is already in recent history
                    is_duplicate = False
                    for past_title in recent_history:
                        if (
                            entry_title.lower() in past_title
                            or past_title in entry_title.lower()
                        ):
                            is_duplicate = True
                            break

                    # If it's not a duplicate, we have found a good candidate
                    if not is_duplicate:
                        return entry_title

            # --- Stage 2: Fallback to Broader Search ---
            # If the targeted search found no unique song, fall back to the original method.
            fallback_query = f"ytsearch5:related to {title}"
            data = await self.bot.loop.run_in_executor(
                None,
                lambda: ytdl.extract_info(
                    fallback_query, download=False, process=False
                ),
            )

            if not data or "entries" not in data or not data["entries"]:
                return None

            recent_history = [h.lower() for h in history[-10:]]
            for entry in data["entries"]:
                entry_title = entry.get("title")
                if not entry_title:
                    continue

                is_duplicate = False
                for past_title in recent_history:
                    if (
                        entry_title.lower() in past_title
                        or past_title in entry_title.lower()
                    ):
                        is_duplicate = True
                        break

                if not is_duplicate:
                    # Return the first non-duplicate song from the broader search
                    return entry_title

            return None  # No suitable song found in either search

        except Exception as e:
            print(f"Error finding related song: {e}")
            return None

    async def play_next(self, gid, text_channel=None, from_back=False):
        vc = discord.utils.get(self.bot.voice_clients, guild__id=gid)
        queue = self.get_queue(gid)
        loop_mode = self.get_loop(gid)
        autoplay_mode = self.get_autoplay(gid)

        if text_channel:
            self.text_channels[gid] = text_channel

        if loop_mode == "song" and self.current.get(gid) and not from_back:
            queue.insert(0, self.current[gid].query)
        elif loop_mode == "queue" and self.current.get(gid) and not from_back:
            queue.append(self.current[gid].query)

        if not queue:
            if autoplay_mode and self.current.get(gid):
                last_song_title = self.current.get(gid).title
                history = self.get_history(gid)
                next_song_query = await self._find_related_song(
                    last_song_title, history
                )

                if next_song_query:
                    queue.append(next_song_query)
                    if text_channel:
                        await text_channel.send(f"Autoplaying: **{next_song_query}**.")
                else:
                    self.current.pop(gid, None)
                    if text_channel:
                        await text_channel.send(
                            "Autoplay could not find a unique related song. Queue finished."
                        )
                    if vc:
                        await vc.disconnect()
                    return
            else:
                self.current.pop(gid, None)
                if text_channel and not autoplay_mode:
                    await text_channel.send(
                        "Looks like my job here is done, leaving now."
                    )
                if vc:
                    await vc.disconnect()
                return

        if vc:
            query = queue.pop(0)
            try:
                speed = self.get_speed(gid)
                audio_filter = self.get_filter(gid)
                player = await YTDLSource.from_query(
                    query, loop=self.bot.loop, speed=speed, filter_options=audio_filter
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
                        self.play_next(gid, self.text_channels.get(gid)),
                    ),
                )
                self.current[gid] = player
                player.query = query
                self.get_history(gid).append(player.title)
                self.start_times[gid] = discord.utils.utcnow().timestamp()

                if text_channel:
                    # Check if the last message was the autoplay announcement
                    last_message = [m async for m in text_channel.history(limit=1)][0]
                    if "Autoplaying" not in last_message.content:
                        await text_channel.send(f"Started playing: **{player.title}**.")

            except Exception as e:
                print(f"Error playing {query}: {e}")
                if text_channel:
                    await text_channel.send(f"Failed to play `{query}`. Skipping.")
                await self.play_next(gid, text_channel)
        else:
            self.current.pop(gid, None)

    # --- Command Checks ---
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if the user is in the same voice channel as the bot."""
        vc = interaction.guild.voice_client
        if not vc or not vc.is_connected():
            return True  # Allow commands if bot is not in a channel

        # Allow /play even if not in the same channel, as it can be used to summon the bot
        if interaction.command.name in ("play", "playnext"):
            return True

        if interaction.user.voice and interaction.user.voice.channel == vc.channel:
            return True

        await interaction.response.send_message(
            "You must be in the same voice channel as the bot to use this command.",
            ephemeral=True,
        )
        return False

    # --- Events ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """Handle the bot leaving an empty voice channel."""
        # Ignore the bot's own voice state updates or if the user is just muting/deafening
        if member.id == self.bot.user.id or before.channel == after.channel:
            return

        vc = discord.utils.get(self.bot.voice_clients, guild=member.guild)

        # If the bot is not in a voice channel, or the event is not for the bot's channel, ignore it
        if not vc or not vc.channel or before.channel != vc.channel:
            return

        # Check if the bot is now the only member in the channel
        if len(vc.channel.members) == 1 and vc.channel.members[0] == self.bot.user:
            gid = member.guild.id
            text_channel = self.text_channels.get(gid)

            if text_channel:
                await text_channel.send(
                    "Leaving because there is no one in the voice channel."
                )

            self.get_queue(gid).clear()

            if vc.is_playing() or vc.is_paused():
                vc.stop()

            await vc.disconnect()

            # Clean up all associated data for the guild
            for d in [
                self.queues,
                self.current,
                self.history,
                self.loop_states,
                self.volumes,
                self.filters,
                self.autoplay_states,
                self.start_times,
                self.text_channels,
            ]:
                d.pop(gid, None)

    # --- Playback Commands ---
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

        # Store the channel where the command was initiated
        self.text_channels[inter.guild.id] = inter.channel

        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(inter.guild.id, inter.channel)

        if is_spotify:
            await inter.followup.send(
                f"Added {len(tracks)} tracks from Spotify to the queue. Autoplay is {'on' if self.get_autoplay(inter.guild.id) else 'off'}."
            )
        else:
            await inter.followup.send(
                f"Added to queue: `{query}`. Autoplay is {'on' if self.get_autoplay(inter.guild.id) else 'off'}."
            )

    @app_commands.command(
        name="playnext", description="Add a song to the front of the queue"
    )
    @app_commands.describe(query="YouTube URL, Spotify URL or name search")
    async def playnext(self, inter, query: str):
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
        q[:0] = tracks

        vc = inter.guild.voice_client
        if not vc:
            vc = await self.join_vc(inter)
            if not vc:
                return

        # Store the channel where the command was initiated
        self.text_channels[inter.guild.id] = inter.channel

        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(inter.guild.id, inter.channel)

        if is_spotify:
            await inter.followup.send(
                f"Added {len(tracks)} tracks from Spotify to the front of the queue. Autoplay is {'on' if self.get_autoplay(inter.guild.id) else 'off'}."
            )
        else:
            await inter.followup.send(
                f"Added to front of queue: `{query}`. Autoplay is {'on' if self.get_autoplay(inter.guild.id) else 'off'}."
            )

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, inter):
        vc = inter.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await inter.response.send_message("Skipped.")
        else:
            await inter.response.send_message("Nothing is playing.")

    @app_commands.command(name="stop", description="Stop music and leave voice channel")
    async def stop(self, inter):
        gid = inter.guild.id
        self.set_autoplay(gid, False)
        vc = inter.guild.voice_client
        if vc:
            self.get_queue(gid).clear()
            vc.stop()
            await vc.disconnect()
        for d in [
            self.queues,
            self.current,
            self.history,
            self.loop_states,
            self.volumes,
            self.filters,
            self.autoplay_states,
            self.start_times,
            self.text_channels,
        ]:
            d.pop(gid, None)
        await inter.response.send_message(
            "Music stopped in the server, see you next time."
        )

    @app_commands.command(name="pause", description="Pause or resume playback (toggle)")
    async def pause(self, inter):
        vc = inter.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await inter.response.send_message("Nothing is playing.")
            return
        if vc.is_playing():
            vc.pause()
            await inter.response.send_message("Paused.")
        elif vc.is_paused():
            vc.resume()
            await inter.response.send_message("Resumed.")

    @app_commands.command(
        name="back", description="Play the previous song from history"
    )
    async def back(self, inter):
        gid = inter.guild.id
        history = self.get_history(gid)
        cur = self.current.get(gid)
        vc = inter.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            return await inter.response.send_message("Nothing is playing.")
        # Need at least 2 songs in history: current and previous
        if len(history) < 2:
            return await inter.response.send_message("No previous song in history.")
        # Remove current song from history if present at the end
        if cur and history and history[-1] == cur.title:
            history.pop()
        if not history:
            return await inter.response.send_message("No previous song in history.")
        prev_title = history.pop()  # Get previous song
        self.get_queue(gid).insert(0, prev_title)
        vc.stop()
        await inter.response.send_message(f"Playing previous song: **{prev_title}**")

    # --- Queue Management Commands ---
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
                speed = self.get_speed(inter.guild.id)
                elapsed = discord.utils.utcnow().timestamp() - start
                pos = int(elapsed * speed)
            else:
                pos = 0
            pos_str = self.format_time(pos)
            dur_str = self.format_time(dur)
            em.add_field(
                name="Now",
                value=f"[{cur.title}]({cur.data.get('webpage_url', '')}) [{pos_str}/{dur_str}]",
                inline=False,
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
                speed = self.get_speed(inter.guild.id)
                elapsed = discord.utils.utcnow().timestamp() - start
                pos = int(elapsed * speed)
            else:
                pos = 0
            pos_str = self.format_time(pos)
            dur_str = self.format_time(dur)
            await inter.response.send_message(
                f"Now: **{cur.title}** [{pos_str}/{dur_str}]"
            )
        else:
            await inter.response.send_message("Nothing is playing.")

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

    # --- Audio Settings and Effects ---
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

        # This is a simple reload-based seek. True seeking is more complex.
        vc.stop()
        await inter.response.send_message(f"Seeking to {position}s (reloading...).")

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
        vc.stop()
        await inter.followup.send(f"Playback speed set to {rate}x (reloading...)")

    @app_commands.command(name="filter", description="Apply an audio filter")
    @app_commands.describe(
        filter_name="The audio filter to apply. Choose 'none' to disable."
    )
    @app_commands.choices(
        filter_name=[
            app_commands.Choice(name=key, value=key) for key in AUDIO_FILTERS.keys()
        ]
    )
    async def filter(self, inter, filter_name: str):
        gid = inter.guild.id
        vc = inter.guild.voice_client
        cur = self.current.get(gid)

        self.set_filter(gid, filter_name)

        if vc and cur:
            await inter.response.defer(thinking=True)
            self.get_queue(gid).insert(0, cur.query)
            vc.stop()
            await inter.followup.send(
                f"Filter set to **{filter_name}**. Reloading current song..."
            )
        else:
            await inter.response.send_message(f"Filter set to **{filter_name}**.")

    @app_commands.command(name="autoplay", description="Toggle autoplay mode")
    async def autoplay(self, inter):
        gid = inter.guild.id
        current_state = self.get_autoplay(gid)
        new_state = not current_state
        self.set_autoplay(gid, new_state)
        await inter.response.send_message(
            f"Autoplay is now **{'on' if new_state else 'off'}**."
        )


async def setup(bot):
    with open("config.json") as f:
        cfg = json.load(f)
    spotify_helper = SpotifyHelper(
        client_id=cfg["spotify_client_id"], client_secret=cfg["spotify_client_secret"]
    )
    await bot.add_cog(Music(bot, spotify_helper))
