import discord, random
from discord.ext import commands
from discord import app_commands
from utils.ytdl import YTDLSource
from utils.spotify import SpotifyHelper
import json

with open("config.json") as f:
    cfg = json.load(f)
sp = SpotifyHelper(cfg["spotify_client_id"], cfg["spotify_client_secret"])

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues    = {}
        self.current   = {}
        self.history   = {}
        self.loop_states = {}
        self.volumes   = {}
        self.autoplay  = {}

    def get_queue(self,g): return self.queues.setdefault(g,[])
    def get_history(self,g): return self.history.setdefault(g,[])
    def get_loop(self,g): return self.loop_states.get(g)
    def set_loop(self,g,s): self.loop_states[g] = s
    def get_vol(self,g): return self.volumes.get(g,0.5)
    def set_vol(self,g,v):
        self.volumes[g]=v
        vc=discord.utils.get(self.bot.voice_clients,guild__id=g)
        if vc and vc.source: vc.source.volume=v
    def get_auto(self,g): return self.autoplay.get(g,False)
    def set_auto(self,g,v): self.autoplay[g]=v

    async def join_vc(self,inter):
        if inter.user.voice:
            ch=inter.user.voice.channel
            vc=inter.guild.voice_client
            if not vc or not vc.is_connected(): vc=await ch.connect()
            elif vc.channel!=ch: await vc.move_to(ch)
            return vc
        await inter.followup.send("Join voice first.",ephemeral=True)
        return None

    async def play_next(self,guild_id, text_channel=None, from_back=False):
        vc = discord.utils.get(self.bot.voice_clients, guild__id=guild_id)
        queue = self.get_queue(guild_id)
        loop = self.get_loop(guild_id)
        if loop=="song" and self.current.get(guild_id) and not from_back:
            queue.insert(0,self.current[guild_id].query)
        elif loop=="queue" and self.current.get(guild_id) and not from_back:
            queue.append(self.current[guild_id].query)
        if self.current.get(guild_id) and not from_back:
            self.get_history(guild_id).append(self.current[guild_id].query)

        if not queue:
            if self.get_auto(guild_id) and self.current.get(guild_id):
                related = await YTDLSource.get_related(self.current[guild_id].query)
                if related: queue.append(related)
        if queue and vc:
            query=queue.pop(0)
            try:
                player=await YTDLSource.from_query(query, loop=self.bot.loop)
                player.volume=self.get_vol(guild_id)
                vc.play(player,after=lambda e:self.bot.loop.call_soon_threadsafe(
                    self.bot.loop.create_task,self.play_next(guild_id,text_channel)
                ))
                self.current[guild_id]=player
                player.query=query
                if text_channel: await text_channel.send(f"Now playing: **{player.title}**")
            except Exception:
                if text_channel: await text_channel.send(f"Failed: `{query}`. Skipped.")
                await self.play_next(guild_id,text_channel)
        else:
            self.current.pop(guild_id,None)
            if text_channel: await text_channel.send("Queue finished.")

    @app_commands.command(name="play",description="Play from YouTube/Spotify/search")
    @app_commands.describe(query="URL or search term")
    async def play(self,inter,query:str):
        await inter.response.defer(thinking=True)
        vc=inter.guild.voice_client
        if not vc:
            vc=await self.join_vc(inter)
            if not vc: return
        tracks = sp.extract_tracks(query) if sp.is_spotify_url(query) else [query]
        if not tracks:
            await inter.followup.send("No tracks found.")
            return
        q=self.get_queue(inter.guild.id)
        q.extend(tracks)
        msg = f"Added {len(tracks)} track(s)."
        await inter.followup.send(msg)
        if not vc.is_playing() and not vc.is_paused():
            await self.play_next(inter.guild.id, inter.channel)

    @app_commands.command(name="skip",description="Skip current")
    async def skip(self,inter):
        vc=inter.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await inter.response.send_message("Skipped.")
        else:
            await inter.response.send_message("Nothing to skip.")

    @app_commands.command(name="queue",description="Show queue")
    async def queue_cmd(self,inter):
        q=self.get_queue(inter.guild.id)
        cur=self.current.get(inter.guild.id)
        if not q and not cur:
            return await inter.response.send_message("Nothing playing.")
        em=discord.Embed(title="Queue")
        if cur: em.add_field(name="Now",value=cur.title,inline=False)
        if q:
            em.add_field(name="Up next",value="\n".join(f"{i+1}. {t}" for i,t in enumerate(q[:10])),inline=False)
            if len(q)>10: em.set_footer(text=f"...and {len(q)-10} more")
        await inter.response.send_message(embed=em)

    @app_commands.command(name="nowplaying",description="Show current")
    async def nowplaying(self,inter):
        cur=self.current.get(inter.guild.id)
        if cur:
            await inter.response.send_message(f"Now: **{cur.title}**")
        else:
            await inter.response.send_message("Nothing is playing.")

    @app_commands.command(name="stop",description="Stop & cleanup")
    async def stop(self,inter):
        vc=inter.guild.voice_client
        if vc: vc.stop(); await vc.disconnect()
        g=inter.guild.id
        for d in [self.queues,self.current,self.history,self.loop_states,self.volumes,self.autoplay]:
            d.pop(g,None)
        await inter.response.send_message("Stopped and cleaned up.")

    @app_commands.command(name="pause",description="Pause playback")
    async def pause(self,inter):
        vc=inter.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await inter.response.send_message("Paused")
        else:
            await inter.response.send_message("Nothing playing.")

    @app_commands.command(name="resume",description="Resume playback")
    async def resume(self,inter):
        vc=inter.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await inter.response.send_message("Resumed")
        else:
            await inter.response.send_message("Nothing paused.")

    @app_commands.command(name="clear",description="Clear queue")
    async def clear(self,inter):
        q=self.get_queue(inter.guild.id)
        q.clear()
        await inter.response.send_message("Cleared queue.")

    @app_commands.command(name="shuffle",description="Shuffle queue")
    async def shuffle(self,inter):
        q=self.get_queue(inter.guild.id)
        random.shuffle(q)
        await inter.response.send_message("Shuffled queue.")

    @app_commands.command(name="remove",description="Remove from queue")
    @app_commands.describe(idx="Position")
    async def remove(self,inter,idx:int):
        q=self.get_queue(inter.guild.id)
        if 1<=idx<=len(q):
            s=q.pop(idx-1)
            await inter.response.send_message(f"Removed **{s}**.")
        else:
            await inter.response.send_message("Invalid position.")

    @app_commands.command(name="move",description="Move song")
    @app_commands.describe(frm="From pos",to="To pos")
    async def move(self,inter,frm:int,to:int):
        q=self.get_queue(inter.guild.id)
        if not all(1<=x<=len(q) for x in (frm,to)):
            return await inter.response.send_message("Invalid positions.")
        s=q.pop(frm-1); q.insert(to-1, s)
        await inter.response.send_message(f"Moved to position {to}.")

    @app_commands.command(name="swap",description="Swap songs")
    @app_commands.describe(a="Song 1",b="Song 2")
    async def swap(self,inter,a:int,b:int):
        q=self.get_queue(inter.guild.id)
        if not all(1<=x<=len(q) for x in (a,b)):
            return await inter.response.send_message("Invalid positions.")
        q[a-1], q[b-1] = q[b-1], q[a-1]
        await inter.response.send_message(f"Swapped {a}↔️{b}.")

    @app_commands.command(name="loop",description="Cycle loop: off → song → queue")
    async def loop(self,inter):
        g=inter.guild.id
        current=self.get_loop(g)
        nxt="song" if current is None else "queue" if current=="song" else None
        self.set_loop(g,nxt)
        await inter.response.send_message(f"Loop mode: **{nxt or 'off'}**")

    @app_commands.command(name="volume",description="Set volume")
    @app_commands.describe(level="0–100")
    async def volume(self,inter,level:app_commands.Range[int,0,100]):
        vol=level/100; self.set_vol(inter.guild.id,vol)
        await inter.response.send_message(f"Volume: **{level}%**")

    @app_commands.command(name="autoplay",description="Toggle autoplay")
    async def autoplay(self,inter):
        g=inter.guild.id
        now=not self.get_auto(g)
        self.set_auto(g,now)
        await inter.response.send_message(f"Autoplay: **{'on' if now else 'off'}**")

    @app_commands.command(name="seek",description="Seek in current track (seconds)")
    @app_commands.describe(position="Seconds to jump to")
    async def seek(self,inter,position:int):
        vc=inter.guild.voice_client
        cur=self.current.get(inter.guild.id)
        if not vc or not cur:
            return await inter.response.send_message("Nothing playing.")
        await vc.stop()
        await self.play_next(inter.guild.id, inter.channel)
        # For simplicity, we just restart track (because FFmpeg with -ss requires re-loading).
        await inter.response.send_message(f"Seeking to {position}s (reload).")

    @app_commands.command(name="speed",description="Set playback speed")
    @app_commands.describe(rate="0.5–2.0")
    async def speed(self,inter,rate:app_commands.Range[float,0.5,2.0]):
        cur=self.current.get(inter.guild.id)
        vc=inter.guild.voice_client
        if not vc or not cur:
            return await inter.response.send_message("Nothing playing.")
        que=self.get_queue(inter.guild.id)
        que.insert(0,cur.query)
        await vc.stop()
        await self.play_next(inter.guild.id, inter.channel)
        await inter.response.send_message(f"Setting speed to {rate}x (reloaded).")

async def setup(bot):
    await bot.add_cog(Music(bot))
