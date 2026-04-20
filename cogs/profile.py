from __future__ import annotations

import asyncio
import io
import random
import re
import time
from datetime import datetime, timedelta
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


ANIME_BG_APIS: list[str] = [
    "https://api.waifu.pics/sfw/waifu",
    "https://api.waifu.pics/sfw/neko",
]


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
            {"id": "lvl_10", "name": "Level 10", "coins": 1200},
            {"id": "lvl_25", "name": "Level 25", "coins": 3500},
            {"id": "msg_500", "name": "500 messages", "coins": 1800},
            {"id": "streak_7", "name": "7-day login streak", "coins": 1400},
            {"id": "rich_100k", "name": "100k total coins", "coins": 2600},
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
        paths = (
            "arial.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        )
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

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
        del style  # единый glass-стиль
        W, H = 1100, 468
        accent = (72, 196, 255)
        accent_soft = (72, 196, 255, 55)
        bg_dark = (10, 11, 16)
        glass = (22, 24, 32, 210)
        glass_edge = (120, 200, 255, 90)

        base = Image.new("RGB", (W, H), bg_dark)
        px = base.load()
        for y in range(H):
            t = y / max(H - 1, 1)
            r = int(10 + t * 8)
            g = int(11 + t * 10)
            b = int(18 + t * 14)
            for x in range(W):
                px[x, y] = (r, g, b)

        if bg_bytes:
            try:
                bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
                bg = bg.resize((W, H), Image.Resampling.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=8))
                bg = bg.point(lambda x: int(x * 0.35))
                base.paste(bg, (0, 0))
            except Exception:
                pass

        img = base.convert("RGBA")
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 115))
        img.alpha_composite(overlay)
        draw = ImageDraw.Draw(img)

        font_xl = self._load_font(26)
        font_md = self._load_font(17)
        font_sm = self._load_font(15)
        font_xs = self._load_font(13)

        cx0, cy0 = 24, 24
        cw, ch = W - 48, H - 48
        draw.rounded_rectangle((cx0, cy0, cx0 + cw, cy0 + ch), radius=22, fill=glass, outline=glass_edge, width=2)

        pad = 36
        col_left = cx0 + pad
        col_mid = col_left + 228
        col_right = col_mid + 448

        av_size = 132
        av_x, av_y = col_left, cy0 + pad
        av_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        av_img = av_img.resize((av_size, av_size), Image.Resampling.LANCZOS)
        rad = 20
        mask = Image.new("L", (av_size, av_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, av_size - 1, av_size - 1), radius=rad, fill=255)
        avatar_layer = Image.new("RGBA", (av_size, av_size))
        avatar_layer.paste(av_img, (0, 0), mask=mask)
        glow = Image.new("RGBA", (av_size + 10, av_size + 10), (0, 0, 0, 0))
        ImageDraw.Draw(glow).rounded_rectangle(
            (2, 2, av_size + 7, av_size + 7),
            radius=rad + 2,
            outline=(*accent, 140),
            width=3,
        )
        img.alpha_composite(glow, (av_x - 5, av_y - 5))
        img.alpha_composite(avatar_layer, (av_x, av_y))

        name_y = av_y + av_size + 14
        draw.text((col_left, name_y), _shorten(member_name, 18), fill=(250, 252, 255, 255), font=font_xl)
        sub = f"Lvl {level} · {_rank_title(level)}"
        if title_text:
            sub += f" · {_shorten(title_text.strip(), 16)}"
        draw.text((col_left, name_y + 34), sub, fill=(180, 190, 210, 255), font=font_sm)
        line_y = name_y + 62
        draw.line((col_left, line_y, col_left + 190, line_y), fill=(*accent, 200), width=2)

        candy_y = line_y + 18
        draw.text((col_left, candy_y), "Баланс", fill=(160, 175, 200, 255), font=font_xs)
        draw.text((col_left + 72, candy_y), f"{balance:,} 🪙", fill=(240, 245, 255, 255), font=font_md)
        medal_y = candy_y + 36
        draw.text((col_left, medal_y), "Значки", fill=(160, 175, 200, 255), font=font_xs)
        draw.text(
            (col_left + 72, medal_y),
            f"{len(badges)} шт.",
            fill=(240, 245, 255, 255),
            font=font_md,
        )
        draw.text((col_left, medal_y + 34), f"Сообщений: {messages:,}", fill=(160, 175, 200, 255), font=font_xs)

        pill_w, pill_h = 200, 34
        pill_x = col_mid + 120
        pill_y = cy0 + pad + 6
        draw.rounded_rectangle(
            (pill_x, pill_y, pill_x + pill_w, pill_y + pill_h),
            radius=17,
            fill=(18, 20, 28, 230),
            outline=accent_soft,
            width=1,
        )
        pill_text = "Статистика"
        bbox = draw.textbbox((0, 0), pill_text, font=font_sm)
        tw = bbox[2] - bbox[0]
        draw.text((pill_x + (pill_w - tw) / 2, pill_y + 8), pill_text, fill=(220, 235, 255, 255), font=font_sm)

        def stat_box(x: int, y: int, w: int, h: int, title: str, value: str) -> None:
            draw.rounded_rectangle((x, y, x + w, y + h), radius=14, fill=(18, 20, 28, 200), outline=accent_soft, width=1)
            draw.text((x + 12, y + 10), title, fill=(140, 155, 185, 255), font=font_xs)
            draw.text((x + 12, y + 30), _shorten(value, 22), fill=(235, 242, 255, 255), font=font_md)

        grid_top = pill_y + 48
        gw, gh = 196, 72
        gap = 14
        stat_box(col_mid, grid_top, gw, gh, "Находится в", voice_label)
        stat_box(col_mid + gw + gap, grid_top, gw, gh, "Голосовой онлайн", _format_voice_duration(voice_seconds))
        rank_txt = f"{msg_rank} место" if msg_rank is not None else "—"
        stat_box(col_mid, grid_top + gh + gap, gw, gh, "Топ по сообщениям", rank_txt)
        stat_box(col_mid + gw + gap, grid_top + gh + gap, gw, gh, "Любимая комната", "Нет")

        ratio = 0.0 if need <= 0 else _clamp(xp / need, 0.0, 1.0)
        xp_bar_y = grid_top + (gh + gap) * 2 + 18
        xp_bar_x = col_mid
        xp_bw = gw * 2 + gap
        xp_bh = 12
        draw.rounded_rectangle((xp_bar_x, xp_bar_y, xp_bar_x + xp_bw, xp_bar_y + xp_bh), radius=8, fill=(40, 44, 58, 255))
        fill_w = int(xp_bw * ratio)
        if fill_w > 0:
            draw.rounded_rectangle(
                (xp_bar_x, xp_bar_y, xp_bar_x + fill_w, xp_bar_y + xp_bh),
                radius=8,
                fill=(*accent, 240),
            )
        xp_txt = f"XP {xp}/{need} ({int(ratio * 100)}%) · Серия {streak}д · Репутация {rep}"
        draw.text((xp_bar_x, xp_bar_y + 18), xp_txt, fill=(170, 185, 210, 255), font=font_xs)

        logo_x = col_right + 10
        logo_y = cy0 + pad + 8
        logo_s = 116
        logo_layer = Image.new("RGBA", (logo_s, logo_s), (0, 0, 0, 0))
        ld = ImageDraw.Draw(logo_layer)
        cx = logo_s // 2
        pts = [
            (cx, 18),
            (logo_s - 22, logo_s - 28),
            (cx + 8, logo_s - 14),
            (22, logo_s - 28),
        ]
        ld.polygon(pts, fill=(50, 160, 245, 230))
        ld.ellipse((cx - 28, 24, cx + 28, 72), outline=(120, 220, 255, 200), width=3)
        img.alpha_composite(logo_layer, (logo_x, logo_y))

        card_inner = (26, 28, 36, 215)
        partner_y = logo_y + logo_s + 14
        ph, ph_h = logo_x - 16, 64
        draw.rounded_rectangle(
            (ph, partner_y, ph + 260, partner_y + ph_h),
            radius=14,
            fill=card_inner,
            outline=accent_soft,
            width=1,
        )
        draw.ellipse((ph + 14, partner_y + 14, ph + 48, partner_y + 48), outline=(90, 100, 120, 255), width=2)
        draw.text((ph + 62, partner_y + 14), "Пары нет", fill=(230, 236, 250, 255), font=font_md)
        draw.text((ph + 62, partner_y + 38), "Пусто", fill=(130, 145, 170, 255), font=font_sm)

        clan_y = partner_y + ph_h + 12
        draw.rounded_rectangle(
            (ph, clan_y, ph + 260, clan_y + ph_h),
            radius=14,
            fill=card_inner,
            outline=accent_soft,
            width=1,
        )
        draw.text((ph + 14, clan_y + 10), "Клан", fill=(160, 175, 200, 255), font=font_xs)
        if clan_name:
            draw.text((ph + 14, clan_y + 28), _shorten(clan_name, 24), fill=(230, 236, 250, 255), font=font_md)
        else:
            draw.text((ph + 14, clan_y + 28), "Клана нет", fill=(230, 236, 250, 255), font=font_md)
            draw.text((ph + 14, clan_y + 46), "Пусто", fill=(130, 145, 170, 255), font=font_sm)

        badge_y = cy0 + ch - 52
        slot_n = 7
        slot_r = 15
        total_w = slot_n * (slot_r * 2 + 10)
        bx0 = cx0 + (cw - total_w) // 2
        pinned = badges[:slot_n]
        for i in range(slot_n):
            sx = bx0 + i * (slot_r * 2 + 10)
            sy = badge_y
            draw.ellipse((sx, sy, sx + slot_r * 2, sy + slot_r * 2), fill=(30, 32, 42, 255), outline=accent_soft, width=1)
            if i < len(pinned):
                badge_line = pinned[i].strip()
                glyph = badge_line[0] if badge_line else "·"
                draw.text((sx + slot_r - 5, sy + slot_r - 10), glyph, fill=(210, 230, 255, 255), font=font_md)

        draw.text(
            (col_mid, cy0 + ch - 78),
            f"Всего монет {coins_total:,} · банк {bank:,}",
            fill=(140, 155, 180, 255),
            font=font_xs,
        )

        out = io.BytesIO()
        img.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

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
        bg_bytes = await self._anime_bg_bytes()

        if member.voice and member.voice.channel:
            voice_label = _shorten(member.voice.channel.name, 20)
        else:
            voice_label = "Не в войсе"

        png = await asyncio.to_thread(
            self._render_card_sync,
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

        file = discord.File(io.BytesIO(png), filename="profile.png")
        embed = discord.Embed(color=BRAND)
        embed.set_image(url="attachment://profile.png")
        embed.set_footer(text="/daily_login • /balance • /leaderboard")
        await interaction.followup.send(embed=embed, file=file)

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
        eco["balance"] = int(eco.get("balance", 0)) + reward
        Wallet.save(interaction.guild.id, interaction.user.id, eco)
        p["achievements_claimed"].append(aid)
        self.save_profile(interaction.guild.id, interaction.user.id, p)
        await interaction.response.send_message(f"🎉 Claimed **{defs[aid]['name']}**: +{reward} coins")

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
        try:
            font = ImageFont.truetype("arial.ttf", 18)
            font_small = ImageFont.truetype("arial.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

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


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
