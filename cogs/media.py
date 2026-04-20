from __future__ import annotations

import asyncio
import logging
import re
import shutil
from collections import defaultdict
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

try:
    from utils.theme import BRAND, SUCCESS
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()

log = logging.getLogger(__name__)

try:
    import yt_dlp

    _HAS_YTDL = True
except ImportError:
    _HAS_YTDL = False

try:
    import davey as _davey  # noqa: F401

    _HAS_DAVEY = True
except Exception:
    _HAS_DAVEY = False

try:
    import imageio_ffmpeg

    _HAS_IMAGEIO_FFMPEG = True
except Exception:
    _HAS_IMAGEIO_FFMPEG = False

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin",
    "options": "-vn",
}

YDL_COMMON = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "nocheckcertificate": True,
}


def _flatten_info(info: dict[str, Any]) -> dict[str, Any]:
    if "entries" in info and info["entries"]:
        return info["entries"][0]
    return info


def _audio_url_from_info(info: dict[str, Any]) -> str | None:
    if info.get("url"):
        return str(info["url"])
    for fmt in info.get("formats") or []:
        if fmt.get("acodec") and fmt["acodec"] != "none" and fmt.get("url"):
            return str(fmt["url"])
    return None


def extract_audio_sync(query: str) -> tuple[str | None, str]:
    if not _HAS_YTDL:
        raise RuntimeError("yt-dlp не установлен")
    opts = dict(YDL_COMMON)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(query, download=False)
    info = _flatten_info(info)
    title = info.get("title") or info.get("id") or "Трек"
    url = _audio_url_from_info(info)
    return url, str(title)[:200]


class GuildMusicState:
    __slots__ = ("queue", "volume", "text_channel_id", "loop_mode")

    def __init__(self) -> None:
        self.queue: list[dict[str, Any]] = []
        self.volume: float = 0.35
        self.text_channel_id: int | None = None
        self.loop_mode: str = "off"


class Media(commands.Cog):
    """Музыка: YouTube, поиск, прямые ссылки, вложения. Нужны FFmpeg и yt-dlp (pip)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._states: dict[int, GuildMusicState] = defaultdict(GuildMusicState)
        self._now_playing: dict[int, dict[str, Any]] = {}
        self._ffmpeg_executable = self._detect_ffmpeg()

    def _detect_ffmpeg(self) -> str | None:
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        if _HAS_IMAGEIO_FFMPEG:
            try:
                return imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                return None
        return None

    def _state(self, guild_id: int) -> GuildMusicState:
        return self._states[guild_id]

    def _voice_client(self, guild: discord.Guild) -> discord.VoiceClient | None:
        return guild.voice_client

    async def _connect_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        if not _HAS_DAVEY:
            await interaction.followup.send(
                "❌ На хостинге не установлена voice-библиотека `davey`. "
                "Установите зависимости из `requirements.txt` и перезапустите бота.",
                ephemeral=True,
            )
            return None
        if not interaction.user or not getattr(interaction.user, "voice", None):
            await interaction.followup.send("❌ Зайдите в голосовой канал.", ephemeral=True)
            return None
        ch = interaction.user.voice.channel
        if not isinstance(ch, discord.VoiceChannel):
            await interaction.followup.send("❌ Нужен обычный голосовой канал.", ephemeral=True)
            return None
        vc = self._voice_client(interaction.guild)
        try:
            if vc and vc.channel and vc.channel.id != ch.id:
                await vc.move_to(ch)
                return vc
            if not vc:
                return await ch.connect(self_deaf=True)
            return vc
        except RuntimeError as e:
            msg = str(e).lower()
            if "davey" in msg or "pynacl" in msg or "voice" in msg:
                await interaction.followup.send(
                    "❌ Голосовые библиотеки не установлены на хостинге. "
                    "Установите зависимости из `requirements.txt` и перезапустите бота.",
                    ephemeral=True,
                )
                return None
            await interaction.followup.send(f"❌ Ошибка подключения к голосу: {e}", ephemeral=True)
            return None
        except discord.ClientException as e:
            await interaction.followup.send(f"❌ Не удалось подключиться: {e}", ephemeral=True)
            return None

    def _after_play(self, guild_id: int, error: BaseException | None) -> None:
        if error:
            log.warning("Music playback error: %s", error)
        fut = asyncio.run_coroutine_threadsafe(self._play_next(guild_id), self.bot.loop)
        try:
            fut.result(timeout=60)
        except Exception as e:
            log.exception("after play: %s", e)

    async def _play_next(self, guild_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        vc = self._voice_client(guild)
        if not vc:
            return
        st = self._state(guild_id)
        if not st.queue:
            await asyncio.sleep(0.5)
            if not st.queue and vc.is_connected() and not vc.is_playing() and not vc.is_paused():
                await vc.disconnect()
            return

        if st.loop_mode == "one" and guild_id in self._now_playing and not vc.is_playing() and not vc.is_paused():
            item = self._now_playing[guild_id]
            item_from_queue = False
        else:
            item = st.queue.pop(0)
            item_from_queue = True
        url = item["url"]
        title = item["title"]
        try:
            ffmpeg_kwargs = dict(FFMPEG_OPTS)
            if self._ffmpeg_executable:
                ffmpeg_kwargs["executable"] = self._ffmpeg_executable
            source = discord.FFmpegPCMAudio(url, **ffmpeg_kwargs)
            vol_source = discord.PCMVolumeTransformer(source, volume=st.volume)
        except Exception as e:
            log.exception("FFmpeg: %s", e)
            ch_id = st.text_channel_id
            if ch_id:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    await ch.send(
                        f"❌ Ошибка FFmpeg: `{e}`\n"
                        "Установите **FFmpeg** в систему или добавьте `imageio-ffmpeg` в зависимости."
                    )
            await self._play_next(guild_id)
            return

        def after(err: BaseException | None) -> None:
            self._after_play(guild_id, err)

        if not discord.opus.is_loaded():
            log.error("libopus не загружена — установите пакет libopus (например libopus0 в Docker).")
            if item_from_queue:
                st.queue.insert(0, item)
            try:
                vol_source.cleanup()
            except Exception:
                pass
            ch_id = st.text_channel_id
            if ch_id:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    await ch.send(
                        "❌ На сервере не установлена библиотека **Opus** (нужна для голоса). "
                        "В Docker добавьте пакет `libopus0` и пересоберите образ."
                    )
            return

        vc.play(vol_source, after=after)
        self._now_playing[guild_id] = item
        if st.loop_mode == "all":
            st.queue.append(item)
        ch_id = st.text_channel_id
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                embed = discord.Embed(
                    title="▶️ Сейчас играет",
                    description=f"**{title}**",
                    color=SUCCESS,
                )
                embed.set_footer(text="/queue • /skip • /stop")
                await ch.send(embed=embed)

    async def _enqueue(
        self,
        interaction: discord.Interaction,
        url: str,
        title: str,
    ) -> None:
        try:
            gid = interaction.guild.id
            st = self._state(gid)
            st.text_channel_id = interaction.channel_id
            st.queue.append({"url": url, "title": title, "requester": interaction.user.id})
            pos = len(st.queue)
            vc = await self._connect_voice(interaction)
            if not vc:
                st.queue.pop()
                return
            embed = discord.Embed(
                description=f"🎵 **{title}** — в очереди (#{pos})",
                color=BRAND,
            )
            await interaction.followup.send(embed=embed)
            if not vc.is_playing() and not vc.is_paused():
                await self._play_next(gid)
        except RuntimeError as e:
            msg = str(e).lower()
            if "davey" in msg or "voice" in msg or "pynacl" in msg:
                await interaction.followup.send(
                    "❌ Голосовой стек не готов на сервере (davey/PyNaCl). "
                    "Переустановите зависимости и перезапустите контейнер.",
                    ephemeral=True,
                )
                return
            raise

    async def _play_from_query(self, interaction: discord.Interaction, query: str) -> None:
        q = query.strip()
        if q.startswith("http://") or q.startswith("https://"):
            if re.search(r"\.(mp3|ogg|wav|m4a|flac)(\?|$)", q, re.I):
                await self._enqueue(interaction, q, "Прямой поток")
                return
            if not _HAS_YTDL:
                await interaction.followup.send(
                    "❌ Для ссылок установите: `pip install yt-dlp` и **FFmpeg**.", ephemeral=True
                )
                return
            try:
                loop = asyncio.get_event_loop()
                url, title = await loop.run_in_executor(None, extract_audio_sync, q)
            except Exception as e:
                err = str(e).lower()
                if "unsupported url" in err:
                    await interaction.followup.send(
                        "❌ Этот сайт не поддерживается (yt-dlp). "
                        "Используйте **YouTube**, **SoundCloud** (если доступно) или **прямую ссылку** на аудиофайл (.mp3, .ogg…).",
                        ephemeral=True,
                    )
                    return
                await interaction.followup.send(f"❌ Не удалось получить аудио: `{e}`", ephemeral=True)
                return
            if not url:
                await interaction.followup.send("❌ Нет аудиопотока.", ephemeral=True)
                return
            await self._enqueue(interaction, url, title)
            return

        if not _HAS_YTDL:
            await interaction.followup.send(
                "❌ Для поиска: `pip install yt-dlp` и **FFmpeg** в PATH.", ephemeral=True
            )
            return
        try:
            loop = asyncio.get_event_loop()
            url, title = await loop.run_in_executor(None, extract_audio_sync, q)
        except Exception as e:
            err = str(e).lower()
            if "unsupported url" in err:
                await interaction.followup.send(
                    "❌ Этот сайт не поддерживается (yt-dlp). "
                    "Используйте **YouTube** или **прямую ссылку** на аудиофайл.",
                    ephemeral=True,
                )
                return
            await interaction.followup.send(f"❌ Поиск: `{e}`", ephemeral=True)
            return
        if not url:
            await interaction.followup.send("❌ Ничего не найдено.", ephemeral=True)
            return
        await self._enqueue(interaction, url, title)

    @app_commands.command(name="play", description="Музыка: поиск YouTube, ссылка или ваш файл")
    @app_commands.describe(
        query="Название трека, YouTube/ссылка",
        attachment="Ваш mp3/ogg/wav — прикрепите к сообщению",
    )
    async def play(
        self,
        interaction: discord.Interaction,
        query: str | None = None,
        attachment: discord.Attachment | None = None,
    ):
        if not query and not attachment:
            await interaction.response.send_message(
                "❌ Укажите запрос **или** прикрепите аудиофайл.", ephemeral=True
            )
            return

        await interaction.response.defer()

        if attachment:
            if attachment.size > 25 * 1024 * 1024:
                await interaction.followup.send("❌ Файл больше 25 МБ.", ephemeral=True)
                return
            ct = (attachment.content_type or "").lower()
            ok_ext = attachment.filename.lower().endswith((".mp3", ".ogg", ".wav", ".m4a", ".flac", ".opus"))
            if not ok_ext and not any(x in ct for x in ("audio", "ogg", "mpeg", "wav", "mp4", "webm")):
                await interaction.followup.send("❌ Нужен аудиофайл (mp3, ogg, wav…).", ephemeral=True)
                return
            title = attachment.filename or "Файл"
            await self._enqueue(interaction, attachment.url, title)
            return

        assert query is not None
        await self._play_from_query(interaction, query)

    @app_commands.command(name="mix", description="Фоновый микс из интернета (YouTube)")
    @app_commands.choices(
        style=[
            app_commands.Choice(name="🌙 Lo-Fi / Chill", value="lofi"),
            app_commands.Choice(name="🔊 Phonk", value="phonk"),
            app_commands.Choice(name="🎸 Rock", value="rock"),
            app_commands.Choice(name="✨ Pop", value="pop"),
            app_commands.Choice(name="🎮 Gaming / Epic", value="gaming"),
            app_commands.Choice(name="🎲 Случайный", value="random"),
        ]
    )
    async def mix(self, interaction: discord.Interaction, style: str):
        queries = {
            "lofi": "lofi hip hop radio beats to relax study",
            "phonk": "phonk drift mix",
            "rock": "best rock music mix",
            "pop": "pop hits mix 2024",
            "gaming": "epic gaming music mix",
            "random": "chill music mix",
        }
        q = queries.get(style, queries["random"])
        if not _HAS_YTDL:
            await interaction.response.send_message(
                "❌ `pip install yt-dlp` и **FFmpeg**.", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            loop = asyncio.get_event_loop()
            url, title = await loop.run_in_executor(None, extract_audio_sync, q)
        except Exception as e:
            await interaction.followup.send(f"❌ `{e}`", ephemeral=True)
            return
        if not url:
            await interaction.followup.send("❌ Не найдено.", ephemeral=True)
            return
        await self._enqueue(interaction, url, f"Микс • {title}")

    @app_commands.command(name="music_queue", description="Добавить в очередь (то же, что /play)")
    async def music_queue(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer()
        await self._play_from_query(interaction, query)

    @app_commands.command(name="queue", description="Очередь треков")
    async def queue_cmd(self, interaction: discord.Interaction):
        st = self._state(interaction.guild.id)
        if not st.queue:
            await interaction.response.send_message("📭 Очередь пуста.", ephemeral=True)
            return
        lines = [f"`{i}.` **{item['title']}**" for i, item in enumerate(st.queue[:15], 1)]
        embed = discord.Embed(title="🎧 Очередь", description="\n".join(lines), color=BRAND)
        embed.set_footer(text=f"Loop mode: {st.loop_mode}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="music_list", description="Показать очередь (как /queue)")
    async def music_list(self, interaction: discord.Interaction):
        st = self._state(interaction.guild.id)
        if not st.queue:
            await interaction.response.send_message("📭 Очередь пуста.", ephemeral=True)
            return
        lines = [f"`{i}.` **{item['title']}**" for i, item in enumerate(st.queue[:15], 1)]
        embed = discord.Embed(title="🎧 Очередь", description="\n".join(lines), color=BRAND)
        embed.set_footer(text=f"Loop mode: {st.loop_mode}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skip", description="Пропустить трек")
    async def skip(self, interaction: discord.Interaction):
        vc = self._voice_client(interaction.guild)
        if not vc or not vc.is_connected():
            await interaction.response.send_message("❌ Бот не в голосе.", ephemeral=True)
            return
        if not vc.is_playing() and not vc.is_paused():
            await interaction.response.send_message("❌ Ничего не играет.", ephemeral=True)
            return
        vc.stop()
        await interaction.response.send_message("⏭️ Пропущено.", ephemeral=True)

    @app_commands.command(name="stopmusic", description="Остановить и очистить очередь")
    async def stopmusic(self, interaction: discord.Interaction):
        st = self._state(interaction.guild.id)
        st.queue.clear()
        self._now_playing.pop(interaction.guild.id, None)
        vc = self._voice_client(interaction.guild)
        if vc and vc.is_connected():
            vc.stop()
            await vc.disconnect()
        await interaction.response.send_message("⏹️ Остановлено.", ephemeral=True)

    @app_commands.command(name="pause", description="Пауза")
    async def pause(self, interaction: discord.Interaction):
        vc = self._voice_client(interaction.guild)
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Пауза.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ничего не играет.", ephemeral=True)

    @app_commands.command(name="resume", description="Продолжить")
    async def resume(self, interaction: discord.Interaction):
        vc = self._voice_client(interaction.guild)
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Дальше.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Нет паузы.", ephemeral=True)

    @app_commands.command(name="leave", description="Выйти из голоса")
    async def leave(self, interaction: discord.Interaction):
        vc = self._voice_client(interaction.guild)
        if vc and vc.is_connected():
            self._state(interaction.guild.id).queue.clear()
            self._now_playing.pop(interaction.guild.id, None)
            await vc.disconnect()
            await interaction.response.send_message("👋 Вышла из голоса.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Бот не в голосе.", ephemeral=True)

    @app_commands.command(name="volume", description="Громкость 0–100 %")
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 100]):
        st = self._state(interaction.guild.id)
        st.volume = percent / 100.0
        vc = self._voice_client(interaction.guild)
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = st.volume
        await interaction.response.send_message(f"🔊 Громкость: **{percent}%**", ephemeral=True)

    @app_commands.command(name="music_mode", description="Режим проигрывания: off/one/all")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Loop current track", value="one"),
            app_commands.Choice(name="Loop full queue", value="all"),
        ]
    )
    async def music_mode(self, interaction: discord.Interaction, mode: str):
        st = self._state(interaction.guild.id)
        st.loop_mode = mode
        await interaction.response.send_message(f"🎛️ Music mode: **{mode}**", ephemeral=True)

    @app_commands.command(name="queue_shuffle", description="Перемешать очередь музыки")
    async def queue_shuffle(self, interaction: discord.Interaction):
        st = self._state(interaction.guild.id)
        if len(st.queue) < 2:
            await interaction.response.send_message("❌ Недостаточно треков в очереди.", ephemeral=True)
            return
        import random

        random.shuffle(st.queue)
        await interaction.response.send_message("🔀 Очередь перемешана.", ephemeral=True)

    @app_commands.command(name="queue_remove", description="Удалить трек из очереди по номеру")
    async def queue_remove(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, 50]):
        st = self._state(interaction.guild.id)
        if not st.queue or index > len(st.queue):
            await interaction.response.send_message("❌ Неверный номер.", ephemeral=True)
            return
        removed = st.queue.pop(index - 1)
        await interaction.response.send_message(f"🗑️ Удалено: **{removed['title']}**", ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Media(bot))
    else:
        await bot.add_cog(Media(bot), guild=g)
