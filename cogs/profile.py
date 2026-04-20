from __future__ import annotations

import asyncio
import io
import os
import random
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet

try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.blurple()

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False
    ImageFont = None  # type: ignore[misc, assignment]


# Noto Sans (SIL OFL) в репозитории — кириллица в Docker/Linux, где нет Arial
_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def load_cyrillic_font(size: int) -> Any:
    """Шрифт с кириллицей для PIL: сначала локальный Noto, потом системные."""
    if not _HAS_PIL or ImageFont is None:
        raise RuntimeError("Pillow is not installed")
    candidates: tuple[str | Path, ...] = (
        _FONT_DIR / "NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "arial.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


ANIME_BG_APIS: list[str] = [
    "https://api.waifu.pics/sfw/waifu",
    "https://api.waifu.pics/sfw/neko",
]

# Анимированный профиль: ~60 FPS (мин. шаг кадра в мс), макс. кадров — баланс CPU / размер / Discord
PROFILE_GIF_TARGET_FPS = 60
PROFILE_GIF_MAX_FRAMES = 55


def _gif_even_frame_indices(n: int, m: int) -> list[int]:
    """Равномерные индексы по всему циклу GIF (не только начало), без дубликатов подряд."""
    if n <= 0:
        return [0]
    m = max(1, min(m, n))
    if m <= 1:
        return [0]
    raw = [min(n - 1, int(round(k * (n - 1) / (m - 1)))) for k in range(m)]
    out: list[int] = []
    for x in raw:
        if not out or out[-1] != x:
            out.append(x)
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _format_voice_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0м."
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}ч {m}м." if m else f"{h}ч."
    return f"{m}м."


def _shorten(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= n:
        return text
    return text[: max(0, n - 1)].rstrip() + "…"


def _rank_title(level: int) -> str:
    if level >= 40:
        return "Legend"
    if level >= 25:
        return "Master"
    if level >= 15:
        return "Pro"
    if level >= 8:
        return "Skilled"
    return "Rookie"


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/profiles.json")
        self._clans_db = JSONHandler("data/clans.json")
        self.last_xp: dict[int, datetime] = {}
        self._bg_cache: list[bytes] = []
        self._http: aiohttp.ClientSession | None = None
        self._profile_render_cd: dict[int, float] = {}
        self._voice_session_start: dict[tuple[int, int], float] = {}
        # Папка кастомных фонов. На хостингах каталог может быть read-only — не падаем при ошибке.
        base_dir = Path(os.getenv("DATA_DIR", "data"))
        self._bg_dir = base_dir / "profile_backgrounds"
        try:
            self._bg_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # fallback в локальную data/ (на случай если DATA_DIR недоступен)
            self._bg_dir = Path("data") / "profile_backgrounds"
            try:
                self._bg_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                # последний fallback — текущая директория; команды будут работать, но загрузка может быть недоступна
                self._bg_dir = Path(".") / "profile_backgrounds"

    async def cog_load(self) -> None:
        if self._http is None:
            self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

    async def cog_unload(self) -> None:
        if self._http is not None:
            await self._http.close()
            self._http = None

    def get_profile(self, guild_id: int, user_id: int) -> dict[str, Any]:
        key = f"{guild_id}.{user_id}"
        profile = self.db.get(key, {})
        if not profile:
            profile = {
                "xp": 0,
                "level": 1,
                "badges": [],
                "messages": 0,
                "daily_streak": 0,
                "last_login": None,
            }
            self.db.set(key, profile)
        return profile

    def save_profile(self, guild_id: int, user_id: int, profile: dict[str, Any]) -> None:
        self.db.set(f"{guild_id}.{user_id}", profile)

    def _ensure_meta(self, profile: dict[str, Any]) -> None:
        profile.setdefault("achievements_claimed", [])
        profile.setdefault("wins", 0)
        profile.setdefault("losses", 0)
        profile.setdefault("style", "dark")
        profile.setdefault("rep", 0)
        profile.setdefault("rep_last_given", None)
        profile.setdefault("pinned_badges", [])
        profile.setdefault("title", "")
        profile.setdefault("history", [])
        profile.setdefault("voice_seconds", 0)
        profile.setdefault("bg_name", None)

    def _sanitize_bg_name(self, name: str) -> str:
        name = re.sub(r"\s+", "_", name.strip())
        name = re.sub(r"[^a-zA-Z0-9_\-\.]+", "", name)
        return name[:48].strip("._-") or "bg"

    def _list_backgrounds(self) -> list[Path]:
        if not self._bg_dir.exists():
            return []
        items = []
        for p in self._bg_dir.glob("*"):
            if p.is_file() and p.suffix.lower() in {".gif", ".png", ".jpg", ".jpeg", ".webp"}:
                items.append(p)
        return sorted(items, key=lambda x: x.name.lower())

    def _get_bg_path(self, bg_name: str) -> Path | None:
        n = self._sanitize_bg_name(bg_name)
        for p in self._list_backgrounds():
            if p.stem.lower() == n.lower() or p.name.lower() == n.lower():
                return p
        # allow exact filename with extension
        candidate = self._bg_dir / n
        if candidate.exists() and candidate.is_file():
            return candidate
        return None

    def _render_profile_gif_sync(self, *args: Any, gif_bg_bytes: bytes) -> bytes:
        """
        Собирает анимированный профиль (GIF) поверх GIF-фона.
        args совпадают с _render_card_sync, но вместо bg_bytes берём кадры GIF.
        """
        if not _HAS_PIL:
            raise RuntimeError("Pillow required")
        try:
            im = Image.open(io.BytesIO(gif_bg_bytes))
        except Exception:
            # fallback: один кадр как PNG
            call_args = list(args)
            if len(call_args) >= 3:
                call_args[2] = None
            return self._render_card_sync(*call_args)  # type: ignore[arg-type]

        frames: list[Image.Image] = []
        durations: list[int] = []
        try:
            n = int(getattr(im, "n_frames", 1))
        except Exception:
            n = 1
        n = max(1, n)

        durs: list[int] = []
        for i in range(n):
            try:
                im.seek(i)
                durs.append(int(im.info.get("duration", 100) or 100))
            except Exception:
                durs.append(100)

        target_ms = max(10, round(1000.0 / float(PROFILE_GIF_TARGET_FPS)))
        m_out = min(PROFILE_GIF_MAX_FRAMES, n)
        indices = _gif_even_frame_indices(n, m_out)

        for j, fi in enumerate(indices):
            try:
                im.seek(fi)
                fr = im.convert("RGB")
            except Exception:
                continue
            b = io.BytesIO()
            fr.save(b, format="PNG")
            call_args = list(args)
            if len(call_args) >= 3:
                call_args[2] = b.getvalue()
            png_bytes = self._render_card_sync(*call_args)  # type: ignore[arg-type]
            card_rgb = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            # Сжимаем GIF, чтобы надёжнее проходить лимит вложений Discord.
            card_rgb = card_rgb.resize((900, 383), Image.Resampling.LANCZOS)
            card = card_rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=128)
            frames.append(card)
            fi_next = indices[j + 1] if j + 1 < len(indices) else n
            chunk_ms = sum(durs[fi:fi_next])
            if chunk_ms <= 0:
                chunk_ms = target_ms
            # Стандартная скорость цикла: время между выбранными кадрами; нижняя граница ~60 FPS
            ms_out = max(target_ms, min(10000, chunk_ms))
            durations.append(ms_out)

        if not frames:
            call_args = list(args)
            if len(call_args) >= 3:
                call_args[2] = None
            return self._render_card_sync(*call_args)  # type: ignore[arg-type]

        out = io.BytesIO()
        frames[0].save(
            out,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
            optimize=True,
        )
        return out.getvalue()

    def required_xp(self, level: int) -> int:
        return 80 + level * 45

    def evaluate_badges(self, profile: dict[str, Any]) -> None:
        if profile["level"] >= 10 and "⭐ Ученик" not in profile["badges"]:
            profile["badges"].append("⭐ Ученик")
        if profile["level"] >= 25 and "💫 Мастер" not in profile["badges"]:
            profile["badges"].append("💫 Мастер")
        if profile["messages"] >= 500 and "💬 Активист" not in profile["badges"]:
            profile["badges"].append("💬 Активист")
        if profile["daily_streak"] >= 7 and "🔥 Серия 7+" not in profile["badges"]:
            profile["badges"].append("🔥 Серия 7+")

    def _achievement_defs(self) -> list[dict[str, Any]]:
        return [
            {"id": "lvl_10", "name": "Уровень 10", "coins": 1200},
            {"id": "lvl_25", "name": "Уровень 25", "coins": 3500},
            {"id": "msg_500", "name": "500 сообщений", "coins": 1800},
            {"id": "streak_7", "name": "Серия входов 7 дней", "coins": 1400},
            {"id": "rich_100k", "name": "100 000 монет всего", "coins": 2600},
        ]

    def _is_achievement_done(self, ach_id: str, profile: dict[str, Any], eco: dict[str, Any]) -> bool:
        if ach_id == "lvl_10":
            return int(profile.get("level", 1)) >= 10
        if ach_id == "lvl_25":
            return int(profile.get("level", 1)) >= 25
        if ach_id == "msg_500":
            return int(profile.get("messages", 0)) >= 500
        if ach_id == "streak_7":
            return int(profile.get("daily_streak", 0)) >= 7
        if ach_id == "rich_100k":
            return int(eco.get("balance", 0)) + int(eco.get("bank", 0)) >= 100000
        return False

    def _push_history_point(self, profile: dict[str, Any], coins_total: int) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        history = profile.setdefault("history", [])
        if history and history[-1].get("d") == today:
            history[-1]["lvl"] = int(profile.get("level", 1))
            history[-1]["coins"] = int(coins_total)
            history[-1]["msg"] = int(profile.get("messages", 0))
        else:
            history.append(
                {
                    "d": today,
                    "lvl": int(profile.get("level", 1)),
                    "coins": int(coins_total),
                    "msg": int(profile.get("messages", 0)),
                }
            )
            profile["history"] = history[-30:]

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        now = datetime.now()
        last = self.last_xp.get(message.author.id)
        if last and (now - last) < timedelta(seconds=35):
            return
        self.last_xp[message.author.id] = now

        profile = self.get_profile(message.guild.id, message.author.id)
        self._ensure_meta(profile)
        profile["messages"] += 1
        profile["xp"] += random.randint(7, 15)
        leveled = False
        while profile["xp"] >= self.required_xp(profile["level"]):
            profile["xp"] -= self.required_xp(profile["level"])
            profile["level"] += 1
            leveled = True
        self.evaluate_badges(profile)
        self.save_profile(message.guild.id, message.author.id, profile)
        if leveled:
            try:
                await message.channel.send(f"🎉 {message.author.mention} достиг уровня **{profile['level']}**!")
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        if before.channel == after.channel:
            return
        gid = member.guild.id
        uid = member.id
        key = (gid, uid)
        now = time.time()
        if before.channel:
            start = self._voice_session_start.pop(key, None)
            if start is not None:
                dt = int(now - start)
                if 0 < dt < 86400 * 14:
                    p = self.get_profile(gid, uid)
                    self._ensure_meta(p)
                    p["voice_seconds"] = int(p.get("voice_seconds", 0)) + dt
                    self.save_profile(gid, uid, p)
        if after.channel:
            self._voice_session_start[key] = now

    def _messages_rank(self, guild_id: int, user_id: int) -> int | None:
        prefix = f"{guild_id}."
        rows: list[tuple[int, int]] = []
        for k, v in self.db.data.items():
            if not isinstance(k, str) or not k.startswith(prefix):
                continue
            try:
                uid = int(k.split(".", 1)[1])
            except (IndexError, ValueError):
                continue
            rows.append((int(v.get("messages", 0)), uid))
        rows.sort(key=lambda x: (-x[0], x[1]))
        for i, (_, uid) in enumerate(rows, start=1):
            if uid == user_id:
                return i
        return None

    def _clan_name(self, guild_id: int, user_id: int) -> str | None:
        clans = self._clans_db.get(str(guild_id), {})
        if not isinstance(clans, dict):
            return None
        for clan in clans.values():
            if not isinstance(clan, dict):
                continue
            if user_id in clan.get("members", []):
                return str(clan.get("name", "")) or None
        return None

    def _load_font(self, size: int) -> Any:
        return load_cyrillic_font(size)

    async def _fetch_bytes(self, url: str) -> bytes | None:
        if self._http is None:
            await self.cog_load()
        assert self._http is not None
        try:
            async with self._http.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
        except Exception:
            return None

    async def _anime_bg_bytes(self) -> bytes | None:
        if self._bg_cache and random.random() < 0.7:
            return random.choice(self._bg_cache)

        api = random.choice(ANIME_BG_APIS)
        if self._http is None:
            await self.cog_load()
        assert self._http is not None
        try:
            async with self._http.get(api) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception:
            return None

        img_url = data.get("url")
        if not isinstance(img_url, str):
            return None
        b = await self._fetch_bytes(img_url)
        if b:
            self._bg_cache.append(b)
            self._bg_cache = self._bg_cache[-12:]
        return b

    def _render_card_sync(
        self,
        member_name: str,
        avatar_bytes: bytes,
        bg_bytes: bytes | None,
        level: int,
        xp: int,
        need: int,
        messages: int,
        streak: int,
        coins_total: int,
        balance: int,
        bank: int,
        badges: list[str],
        last_login_text: str,
        style: str,
        title_text: str,
        rep: int,
        voice_label: str,
        voice_seconds: int,
        msg_rank: int | None,
        clan_name: str | None,
    ) -> bytes:
        del style, last_login_text
        W, H = 1100, 468
        accent = (72, 196, 255)
        accent_line = (80, 200, 255, 175)
        text_main = (246, 249, 255, 255)
        text_dim = (180, 194, 220, 255)
        text_soft = (145, 160, 188, 255)

        base = Image.new("RGB", (W, H), (8, 10, 16))
        px = base.load()
        for y in range(H):
            t = y / max(H - 1, 1)
            for x in range(W):
                u = x / max(W - 1, 1)
                r = int(9 + 8 * t + 7 * u)
                g = int(11 + 8 * t + 10 * u)
                b = int(18 + 12 * t + 14 * u)
                px[x, y] = (r, g, b)

        cx0, cy0 = 24, 24
        cw, ch = W - 48, H - 48
        if bg_bytes:
            try:
                bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
                bg = bg.resize((cw, ch), Image.Resampling.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=0.6))
                card_mask = Image.new("L", (cw, ch), 0)
                ImageDraw.Draw(card_mask).rounded_rectangle((0, 0, cw - 1, ch - 1), radius=22, fill=255)
                base.paste(bg, (cx0, cy0), mask=card_mask)
            except Exception:
                pass

        img = base.convert("RGBA")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((cx0, cy0, cx0 + cw, cy0 + ch), radius=22, outline=accent_line, width=2)

        font_xl = self._load_font(38)
        font_lg = self._load_font(21)
        font_md = self._load_font(17)
        font_sm = self._load_font(15)
        font_xs = self._load_font(13)

        def txt(x: int, y: int, s: str, fill: tuple[int, int, int, int], f: Any) -> None:
            # лёгкая подложка под текст для читаемости на GIF
            draw.text((x + 1, y + 1), s, fill=(0, 0, 0, 180), font=f)
            draw.text((x, y), s, fill=fill, font=f)

        def box(x: int, y: int, w: int, h: int, title: str, value: str) -> None:
            draw.rounded_rectangle((x, y, x + w, y + h), radius=13, outline=(85, 190, 245, 170), width=1)
            txt(x + 12, y + 8, title, text_soft, font_xs)
            txt(x + 12, y + 31, _shorten(value, 24), text_main, font_md)

        pad = 34
        left_x = cx0 + pad
        mid_x = left_x + 228
        right_x = mid_x + 446
        top_y = cy0 + pad

        av_size = 132
        av_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size), Image.Resampling.LANCZOS)
        mask = Image.new("L", (av_size, av_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, av_size - 1, av_size - 1), radius=20, fill=255)
        av_layer = Image.new("RGBA", (av_size, av_size))
        av_layer.paste(av_img, (0, 0), mask=mask)
        img.alpha_composite(av_layer, (left_x, top_y))
        draw.rounded_rectangle((left_x, top_y, left_x + av_size, top_y + av_size), radius=20, outline=(110, 210, 255, 220), width=2)

        name_y = top_y + av_size + 14
        txt(left_x, name_y, _shorten(member_name, 18), text_main, font_xl)
        sub = f"Lvl {level} · {_rank_title(level)}"
        if title_text:
            sub += f" · {_shorten(title_text.strip(), 16)}"
        txt(left_x, name_y + 42, sub, text_dim, font_sm)
        draw.line((left_x, name_y + 75, left_x + 190, name_y + 75), fill=(95, 205, 255, 235), width=2)
        txt(left_x, name_y + 95, f"Баланс      {balance:,} 🪙", text_dim, font_md)
        txt(left_x, name_y + 128, f"Значки      {len(badges)} шт.", text_dim, font_md)
        txt(left_x, name_y + 161, f"Сообщений   {messages:,}", text_dim, font_md)

        pill_w, pill_h = 200, 34
        pill_x, pill_y = mid_x + 120, top_y + 5
        draw.rounded_rectangle((pill_x, pill_y, pill_x + pill_w, pill_y + pill_h), radius=17, outline=(90, 195, 250, 185), width=1)
        pb = draw.textbbox((0, 0), "Статистика", font=font_sm)
        txt(int(pill_x + (pill_w - (pb[2] - pb[0])) / 2), pill_y + 8, "Статистика", text_dim, font_sm)

        gw, gh, gap = 196, 72, 14
        grid_top = pill_y + 48
        rank_txt = f"{msg_rank} место" if msg_rank is not None else "—"
        box(mid_x, grid_top, gw, gh, "Находится в", voice_label)
        box(mid_x + gw + gap, grid_top, gw, gh, "Голосовой онлайн", _format_voice_duration(voice_seconds))
        box(mid_x, grid_top + gh + gap, gw, gh, "Топ по сообщениям", rank_txt)
        box(mid_x + gw + gap, grid_top + gh + gap, gw, gh, "Любимая комната", "Нет")

        ratio = 0.0 if need <= 0 else _clamp(xp / need, 0.0, 1.0)
        xp_bar_y = grid_top + (gh + gap) * 2 + 18
        xp_bar_x = mid_x
        xp_bw = gw * 2 + gap
        xp_bh = 12
        draw.rounded_rectangle((xp_bar_x, xp_bar_y, xp_bar_x + xp_bw, xp_bar_y + xp_bh), radius=8, outline=(100, 205, 255, 180), width=1)
        fill_w = int(xp_bw * ratio)
        if fill_w > 2:
            draw.rounded_rectangle((xp_bar_x + 1, xp_bar_y + 1, xp_bar_x + fill_w, xp_bar_y + xp_bh - 1), radius=7, fill=(72, 196, 255, 230))
        txt(xp_bar_x, xp_bar_y + 18, f"XP {xp}/{need} ({int(ratio * 100)}%) · Серия {streak}д · Репутация {rep}", text_dim, font_xs)
        txt(xp_bar_x, cy0 + ch - 78, f"Всего монет {coins_total:,} · банк {bank:,}", text_soft, font_xs)

        # Правая колонка (блоки «Пара» / «Клан»; декоративный логотип убран)
        card_x = right_x - 6
        partner_y = top_y + 8
        box(card_x, partner_y, 260, 64, "Пара", "Пары нет")
        clan_y = partner_y + 76
        box(card_x, clan_y, 260, 64, "Клан", clan_name if clan_name else "Клана нет")

        # Нижняя линия значков
        badge_y = cy0 + ch - 52
        slot_n = 7
        slot_r = 15
        total_w = slot_n * (slot_r * 2 + 10)
        bx0 = cx0 + (cw - total_w) // 2
        pinned = badges[:slot_n]
        for i in range(slot_n):
            sx = bx0 + i * (slot_r * 2 + 10)
            sy = badge_y
            draw.ellipse((sx, sy, sx + slot_r * 2, sy + slot_r * 2), outline=(95, 200, 255, 175), width=1)
            if i < len(pinned):
                badge_line = pinned[i].strip()
                glyph = badge_line[0] if badge_line else "·"
                txt(sx + slot_r - 5, sy + slot_r - 10, glyph, (210, 230, 255, 255), font_md)

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    def build_ledger_embed(self, guild_id: int, member: discord.Member) -> discord.Embed:
        eco = Wallet.get(guild_id, member.id)
        raw = list(reversed(eco.get("ledger", [])[:20]))
        if not raw:
            text = (
                "Записей пока нет. Здесь появятся **ежедневка**, **работа**, **игры**, "
                "**магазин**, **переводы**, **банк**."
            )
        else:
            lines: list[str] = []
            for e in raw:
                dt = str(e.get("ts", ""))[:19].replace("T", " ")
                kind = str(e.get("k", ""))
                d = int(e.get("d", 0))
                note = str(e.get("n", ""))
                sgn = "+" if d > 0 else ""
                line = f"`{dt}` **{kind}** {sgn}{d} 🪙"
                if note:
                    line += f"\n　_{note}_"
                lines.append(line)
            text = "\n".join(lines)
        emb = discord.Embed(
            title=f"📉 Движение монет · {member.display_name}",
            description=text[:4090],
            color=BRAND,
        )
        emb.set_footer(text="Журнал наличных · /economy_hub — игры и баланс")
        return emb

    def build_achievements_embed(self, guild_id: int, member: discord.Member) -> discord.Embed:
        p = self.get_profile(guild_id, member.id)
        self._ensure_meta(p)
        eco = Wallet.get(guild_id, member.id)
        claimed = set(p.get("achievements_claimed", []))
        lines: list[str] = []
        for ach in self._achievement_defs():
            done = self._is_achievement_done(ach["id"], p, eco)
            icon = "✅" if ach["id"] in claimed else ("🟨" if done else "⬜")
            lines.append(f"{icon} **{ach['name']}** — `{ach['id']}` — **{ach['coins']}** 🪙")
        emb = discord.Embed(
            title=f"🏆 Достижения · {member.display_name}",
            description="\n".join(lines),
            color=BRAND,
        )
        emb.set_footer(text="✅ забрано · 🟨 готово к /achievement_claim · ⬜ в процессе")
        return emb

    @app_commands.command(name="profile", description="Профиль (картинка) + случайный аниме-фон")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        p = self.get_profile(interaction.guild.id, member.id)
        self._ensure_meta(p)
        need = self.required_xp(int(p["level"]))
        eco = Wallet.get(interaction.guild.id, member.id)
        coins_total = int(eco.get("balance", 0)) + int(eco.get("bank", 0))
        self._push_history_point(p, coins_total)
        self.save_profile(interaction.guild.id, member.id, p)
        last_login_text = "never"
        if p.get("last_login"):
            try:
                dt = datetime.fromisoformat(str(p["last_login"]))
                last_login_text = dt.strftime("%Y-%m-%d")
            except Exception:
                last_login_text = "unknown"

        if not _HAS_PIL:
            await interaction.response.send_message(
                "❌ Для рисования профиля установите Pillow: `pip install Pillow`",
                ephemeral=True,
            )
            return

        now_ts = datetime.now().timestamp()
        if member.id == interaction.user.id:
            last_ts = self._profile_render_cd.get(interaction.user.id, 0.0)
            if now_ts - last_ts < 5:
                await interaction.response.send_message("⏳ Подождите пару секунд перед следующим рендером.", ephemeral=True)
                return
            self._profile_render_cd[interaction.user.id] = now_ts

        await interaction.response.defer()
        avatar_bytes = await self._fetch_bytes(member.display_avatar.url)
        if not avatar_bytes:
            await interaction.followup.send("❌ Не удалось загрузить аватар.", ephemeral=True)
            return
        bg_bytes: bytes | None = None
        bg_gif_bytes: bytes | None = None
        bg_name = p.get("bg_name")
        if isinstance(bg_name, str) and bg_name.strip():
            path = self._get_bg_path(bg_name)
            if path and path.exists():
                try:
                    raw = path.read_bytes()
                    if path.suffix.lower() == ".gif":
                        bg_gif_bytes = raw
                    else:
                        bg_bytes = raw
                except Exception:
                    bg_bytes = None
        if bg_bytes is None and bg_gif_bytes is None:
            bg_bytes = await self._anime_bg_bytes()

        if member.voice and member.voice.channel:
            voice_label = _shorten(member.voice.channel.name, 20)
        else:
            voice_label = "Не в войсе"

        args = (
            member.display_name,
            avatar_bytes,
            bg_bytes,
            int(p["level"]),
            int(p["xp"]),
            int(need),
            int(p["messages"]),
            int(p["daily_streak"]),
            coins_total,
            int(eco.get("balance", 0)),
            int(eco.get("bank", 0)),
            list(p.get("badges", [])),
            last_login_text,
            str(p.get("style", "dark")),
            str(p.get("title", "")),
            int(p.get("rep", 0)),
            voice_label,
            int(p.get("voice_seconds", 0)),
            self._messages_rank(interaction.guild.id, member.id),
            self._clan_name(interaction.guild.id, member.id),
        )

        if bg_gif_bytes:
            gif = await asyncio.to_thread(self._render_profile_gif_sync, *args, gif_bg_bytes=bg_gif_bytes)
            file = discord.File(io.BytesIO(gif), filename="profile.gif")
            image_url = None
        else:
            png = await asyncio.to_thread(self._render_card_sync, *args)
            file = discord.File(io.BytesIO(png), filename="profile.png")
            image_url = "attachment://profile.png"
        embed = discord.Embed(
            title=f"Профиль · {member.display_name}",
            color=BRAND,
        )
        if image_url:
            embed.set_image(url=image_url)
        embed.set_footer(text="Кнопки ниже · /daily_login · /economy_hub")
        view = ProfileMenuView(self, member, interaction.user)
        if bg_gif_bytes:
            # Для GIF надёжнее разделить на 2 сообщения:
            # 1) чистый файл (анимация), 2) панель/кнопки.
            await interaction.followup.send(content=f"Профиль · {member.display_name}", file=file)
            await interaction.followup.send(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, file=file, view=view)

    @app_commands.command(name="daily_login", description="Ежедневная серия входа")
    async def daily_login(self, interaction: discord.Interaction):
        profile = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(profile)
        now = datetime.now()
        if profile["last_login"]:
            last = datetime.fromisoformat(profile["last_login"])
            delta = now - last
            if delta < timedelta(hours=20):
                await interaction.response.send_message("⏰ Бонус входа уже получен сегодня", ephemeral=True)
                return
            if delta <= timedelta(hours=48):
                profile["daily_streak"] += 1
            else:
                profile["daily_streak"] = 1
        else:
            profile["daily_streak"] = 1
        profile["last_login"] = now.isoformat()
        profile["xp"] += 25 + min(150, profile["daily_streak"] * 5)
        self.evaluate_badges(profile)
        self.save_profile(interaction.guild.id, interaction.user.id, profile)
        await interaction.response.send_message(f"✅ Серия входов: **{profile['daily_streak']}** дней. Получено XP!")

    @app_commands.command(name="profile_stats", description="Профиль 2.0: подробная статистика")
    async def profile_stats(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        p = self.get_profile(interaction.guild.id, member.id)
        self._ensure_meta(p)
        eco = Wallet.get(interaction.guild.id, member.id)
        total = int(eco.get("balance", 0)) + int(eco.get("bank", 0))
        need = self.required_xp(int(p.get("level", 1)))
        xp = int(p.get("xp", 0))
        ratio = 0 if need <= 0 else int((xp / need) * 100)
        wins = int(p.get("wins", 0))
        losses = int(p.get("losses", 0))
        wr = 0.0 if (wins + losses) == 0 else (wins / (wins + losses)) * 100

        embed = discord.Embed(title=f"Profile 2.0 • {member.display_name}", color=BRAND)
        embed.add_field(name="Level", value=str(p.get("level", 1)), inline=True)
        embed.add_field(name="XP progress", value=f"{xp}/{need} ({ratio}%)", inline=True)
        embed.add_field(name="Rank", value=_rank_title(int(p.get("level", 1))), inline=True)
        embed.add_field(name="Messages", value=f"{int(p.get('messages', 0)):,}", inline=True)
        embed.add_field(name="Coins total", value=f"{total:,}", inline=True)
        embed.add_field(name="Login streak", value=f"{int(p.get('daily_streak', 0))} days", inline=True)
        embed.add_field(name="Wins/Losses", value=f"{wins}/{losses} (WR {wr:.1f}%)", inline=False)
        embed.add_field(name="Reputation", value=str(int(p.get("rep", 0))), inline=True)
        embed.add_field(name="Style", value=str(p.get("style", "dark")), inline=True)
        embed.add_field(name="Title", value=_shorten(str(p.get("title", "") or "-"), 28), inline=True)
        embed.add_field(name="Badges", value=", ".join(p.get("badges", [])[:8]) or "No badges yet", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="achievements", description="Список достижений и прогресса")
    async def achievements(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        p = self.get_profile(interaction.guild.id, member.id)
        self._ensure_meta(p)
        eco = Wallet.get(interaction.guild.id, member.id)
        claimed = set(p.get("achievements_claimed", []))
        lines = []
        for ach in self._achievement_defs():
            done = self._is_achievement_done(ach["id"], p, eco)
            icon = "✅" if ach["id"] in claimed else ("🟨" if done else "⬜")
            lines.append(f"{icon} **{ach['name']}** — {ach['coins']} coins")
        embed = discord.Embed(title=f"Achievements • {member.display_name}", description="\n".join(lines), color=BRAND)
        embed.set_footer(text="✅ claimed • 🟨 ready to claim • ⬜ locked")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="achievement_claim", description="Забрать награду за достижение")
    async def achievement_claim(self, interaction: discord.Interaction, achievement_id: str):
        p = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(p)
        eco = Wallet.get(interaction.guild.id, interaction.user.id)
        defs = {a["id"]: a for a in self._achievement_defs()}
        aid = achievement_id.strip().lower()
        if aid not in defs:
            await interaction.response.send_message("❌ Unknown achievement id.", ephemeral=True)
            return
        if aid in p["achievements_claimed"]:
            await interaction.response.send_message("⏰ Already claimed.", ephemeral=True)
            return
        if not self._is_achievement_done(aid, p, eco):
            await interaction.response.send_message("🔒 Achievement is not completed yet.", ephemeral=True)
            return
        reward = int(defs[aid]["coins"])
        Wallet.add_balance(
            interaction.guild.id,
            interaction.user.id,
            reward,
            ledger=("Достижение", defs[aid]["name"]),
        )
        p["achievements_claimed"].append(aid)
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(f"🎉 **{defs[aid]['name']}** — получено **{reward}** 🪙")

    @app_commands.command(name="profile_style", description="Стиль карточки профиля")
    @app_commands.choices(
        style=[
            app_commands.Choice(name="Dark", value="dark"),
            app_commands.Choice(name="Neon", value="neon"),
            app_commands.Choice(name="Minimal", value="minimal"),
        ]
    )
    async def profile_style(self, interaction: discord.Interaction, style: str):
        p = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(p)
        p["style"] = style
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(f"✅ Profile style set to **{style}**", ephemeral=True)

    @app_commands.command(name="profile_title", description="Установить короткий титул в профиле")
    async def profile_title(self, interaction: discord.Interaction, title: app_commands.Range[str, 0, 28]):
        p = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(p)
        p["title"] = title.strip()
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message("✅ Title updated.", ephemeral=True)

    @app_commands.command(name="profile_bg_list", description="Список доступных фонов профиля (GIF/PNG/JPG)")
    async def profile_bg_list(self, interaction: discord.Interaction):
        items = self._list_backgrounds()
        if not items:
            await interaction.response.send_message(
                "Фоны не найдены. Загрузите: `/profile_bg_upload` (GIF/PNG/JPG/WebP).",
                ephemeral=True,
            )
            return
        lines = [f"- **{p.stem}** ({p.suffix.lower()})" for p in items[:40]]
        if len(items) > 40:
            lines.append(f"…и ещё {len(items) - 40}")
        await interaction.response.send_message("Доступные фоны:\n" + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="profile_bg_set", description="Выбрать фон профиля по имени (из списка)")
    @app_commands.describe(name="Имя фона (как в /profile_bg_list)")
    async def profile_bg_set(self, interaction: discord.Interaction, name: str):
        p = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(p)
        path = self._get_bg_path(name)
        if not path:
            await interaction.response.send_message("❌ Фон не найден. Посмотрите список: `/profile_bg_list`", ephemeral=True)
            return
        p["bg_name"] = path.stem
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(f"✅ Фон профиля выбран: **{path.stem}**", ephemeral=True)

    @app_commands.command(name="profile_bg_clear", description="Сбросить фон профиля (снова случайный аниме-фон)")
    async def profile_bg_clear(self, interaction: discord.Interaction):
        p = self.get_profile(interaction.guild.id, interaction.user.id)
        self._ensure_meta(p)
        p["bg_name"] = None
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message("✅ Фон сброшен. Вызовите `/profile` для обновления.", ephemeral=True)

    @app_commands.command(name="profile_bg_upload", description="Загрузить фон профиля (GIF/PNG/JPG/WebP) в папку бота")
    @app_commands.describe(name="Имя (опционально), под которым сохранить", file="Файл фона")
    async def profile_bg_upload(self, interaction: discord.Interaction, file: discord.Attachment, name: str | None = None):
        if file.size and file.size > 6_500_000:
            await interaction.response.send_message("❌ Слишком большой файл. Максимум ~6.5MB.", ephemeral=True)
            return
        fname = name or Path(file.filename).stem
        safe = self._sanitize_bg_name(fname)
        ext = Path(file.filename).suffix.lower()
        if ext not in {".gif", ".png", ".jpg", ".jpeg", ".webp"}:
            await interaction.response.send_message("❌ Формат не поддерживается. Нужно GIF/PNG/JPG/WebP.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            data = await file.read()
        except Exception:
            await interaction.followup.send("❌ Не удалось прочитать файл.", ephemeral=True)
            return
        out_path = self._bg_dir / f"{safe}{ext}"
        try:
            out_path.write_bytes(data)
        except Exception:
            await interaction.followup.send("❌ Не удалось сохранить файл на диске.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Загружено: **{out_path.stem}**\nВыбрать: `/profile_bg_set name:{out_path.stem}`", ephemeral=True)

    @app_commands.command(name="rep", description="Выдать +1 репутации пользователю (1 раз в сутки)")
    async def rep(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id or member.bot:
            await interaction.response.send_message("❌ Нельзя выдать репутацию этому пользователю.", ephemeral=True)
            return
        giver = self.get_profile(interaction.guild.id, interaction.user.id)
        receiver = self.get_profile(interaction.guild.id, member.id)
        self._ensure_meta(giver)
        self._ensure_meta(receiver)
        now = datetime.now()
        last = giver.get("rep_last_given")
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last))
                if now - last_dt < timedelta(hours=20):
                    await interaction.response.send_message("⏰ Репутацию можно выдавать раз в сутки.", ephemeral=True)
                    return
            except Exception:
                pass
        giver["rep_last_given"] = now.isoformat()
        receiver["rep"] = int(receiver.get("rep", 0)) + 1
        self.save_profile(interaction.guild.id, interaction.user.id, giver)
        self.save_profile(interaction.guild.id, member.id, receiver)
        await interaction.response.send_message(f"👍 {member.mention} получил +1 репутации")

    @app_commands.command(name="profile_history", description="История прогресса профиля (график)")
    async def profile_history(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        p = self.get_profile(interaction.guild.id, member.id)
        self._ensure_meta(p)
        history = list(p.get("history", []))[-14:]
        if len(history) < 2:
            await interaction.response.send_message("📉 Недостаточно данных для графика. Нужна история за несколько дней.")
            return
        if not _HAS_PIL:
            await interaction.response.send_message("❌ Для графика нужен Pillow: `pip install Pillow`", ephemeral=True)
            return

        await interaction.response.defer()
        W, H = 900, 320
        img = Image.new("RGB", (W, H), (24, 24, 28))
        draw = ImageDraw.Draw(img)
        font = load_cyrillic_font(18)
        font_small = load_cyrillic_font(14)

        pad = 50
        draw.rectangle((pad, pad, W - pad, H - pad), outline=(130, 130, 150), width=2)
        lvls = [int(x.get("lvl", 1)) for x in history]
        min_v, max_v = min(lvls), max(lvls)
        if max_v == min_v:
            max_v = min_v + 1
        span_x = (W - pad * 2) / (len(history) - 1)
        points = []
        for i, v in enumerate(lvls):
            x = pad + i * span_x
            y = H - pad - ((v - min_v) / (max_v - min_v)) * (H - pad * 2)
            points.append((x, y))
        for i in range(len(points) - 1):
            draw.line((points[i][0], points[i][1], points[i + 1][0], points[i + 1][1]), fill=(120, 140, 255), width=3)
        for x, y in points:
            draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(220, 220, 255))
        draw.text((pad, 18), f"Level history • {member.display_name}", fill=(240, 240, 250), font=font)
        draw.text((pad, H - 30), f"{history[0].get('d')}  ->  {history[-1].get('d')}", fill=(180, 180, 190), font=font_small)
        draw.text((W - 190, 18), f"min={min_v} max={max_v}", fill=(180, 180, 190), font=font_small)

        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        out.seek(0)
        file = discord.File(out, filename="profile_history.png")
        embed = discord.Embed(title=f"Profile history • {member.display_name}", color=BRAND)
        embed.set_image(url="attachment://profile_history.png")
        await interaction.followup.send(embed=embed, file=file)


class ProfileTitleModal(discord.ui.Modal, title="Титул в карточке"):
    inp = discord.ui.TextInput(
        label="До 28 символов (пусто — сброс)",
        max_length=28,
        required=False,
        style=discord.TextStyle.short,
    )

    def __init__(self, cog: Profile):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        p = self.cog.get_profile(interaction.guild.id, interaction.user.id)
        self.cog._ensure_meta(p)
        p["title"] = str(self.inp.value).strip()
        self.cog.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(
            "✅ Титул сохранён. Вызовите `/profile` ещё раз, чтобы обновить картинку.",
            ephemeral=True,
        )


class ProfileStyleSelect(discord.ui.Select):
    def __init__(self, cog: Profile):
        opts = [
            discord.SelectOption(label="Тёмный", value="dark", emoji="🌑"),
            discord.SelectOption(label="Неон", value="neon", emoji="💜"),
            discord.SelectOption(label="Минимализм", value="minimal", emoji="⬜"),
        ]
        super().__init__(placeholder="Стиль карточки (сохраняется в профиль)…", min_values=1, max_values=1, options=opts)
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        v = self.values[0]
        p = self.cog.get_profile(interaction.guild.id, interaction.user.id)
        self.cog._ensure_meta(p)
        p["style"] = v
        self.cog.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(
            f"✅ Стиль **{v}** сохранён. Снова `/profile` для новой картинки.",
            ephemeral=True,
        )


class ProfileCustomizeView(discord.ui.View):
    def __init__(self, cog: Profile):
        super().__init__(timeout=180)
        self.cog = cog
        self.add_item(ProfileStyleSelect(cog))

    @discord.ui.button(label="Титул в карточке…", style=discord.ButtonStyle.secondary, row=1)
    async def title_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(ProfileTitleModal(self.cog))


class ProfileMenuView(discord.ui.View):
    def __init__(self, cog: Profile, target: discord.Member, viewer: discord.Member):
        super().__init__(timeout=600)
        self.cog = cog
        self.target = target
        self.viewer = viewer

    def _ok(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.viewer.id

    @discord.ui.button(label="Кастомизация", style=discord.ButtonStyle.primary, emoji="🎨", row=0)
    async def cust(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message("Это меню чужого профиля.", ephemeral=True)
            return
        if self.target.id != self.viewer.id:
            await interaction.response.send_message("Кастомизация только **своего** профиля.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Стиль и титул:",
            view=ProfileCustomizeView(self.cog),
            ephemeral=True,
        )

    @discord.ui.button(label="Достижения", style=discord.ButtonStyle.secondary, emoji="🏆", row=0)
    async def ach(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message("Это меню чужого профиля.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self.cog.build_achievements_embed(interaction.guild.id, self.target),
            ephemeral=True,
        )

    @discord.ui.button(label="Движение монет", style=discord.ButtonStyle.secondary, emoji="📉", row=0)
    async def led(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message("Это меню чужого профиля.", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=self.cog.build_ledger_embed(interaction.guild.id, self.target),
            ephemeral=True,
        )

    @discord.ui.button(label="Игры и экономика", style=discord.ButtonStyle.success, emoji="🎮", row=1)
    async def eco(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not self._ok(interaction):
            await interaction.response.send_message("Это меню чужого профиля.", ephemeral=True)
            return
        emb = discord.Embed(
            title="🎮 Игры и экономика",
            color=BRAND,
            description=(
                "Ставки в играх списываются с **наличных** 🪙 и попадают в журнал «Движение монет».\n\n"
                "**Игры:** `/coinflip` `/dice` `/slots` `/blackjack` `/roulette` `/guess` `/rps` "
                "`/wheel` `/crash` `/highlow` `/trivia` `/plinko` `/mines` …\n"
                "**Экономика:** `/balance` `/daily` `/work` `/pay` `/deposit` `/withdraw` `/shop` `/buy`"
            ),
        )
        emb.add_field(name="Панель", value="`/economy_hub` — кнопки экономики", inline=False)
        await interaction.response.send_message(embed=emb, ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Profile(bot))
    else:
        await bot.add_cog(Profile(bot), guild=g)
