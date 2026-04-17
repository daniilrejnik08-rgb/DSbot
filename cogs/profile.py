from __future__ import annotations

import asyncio
import io
import random
import re
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
        self.last_xp: dict[int, datetime] = {}
        self._bg_cache: list[bytes] = []
        self._http: aiohttp.ClientSession | None = None
        self._profile_render_cd: dict[int, float] = {}

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
        badges: list[str],
        last_login_text: str,
        style: str,
        title_text: str,
        rep: int,
    ) -> bytes:
        W, H = 960, 360
        if style == "neon":
            base = Image.new("RGB", (W, H), (20, 12, 30))
            bar_color = (170, 80, 255, 220)
            panel_color = (24, 16, 36, 178)
        elif style == "minimal":
            base = Image.new("RGB", (W, H), (28, 28, 28))
            bar_color = (130, 130, 130, 220)
            panel_color = (20, 20, 20, 185)
        else:
            base = Image.new("RGB", (W, H), (24, 24, 28))
            bar_color = (120, 140, 255, 210)
            panel_color = (18, 18, 22, 170)

        if bg_bytes:
            try:
                bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
                bg = bg.resize((W, H), Image.Resampling.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=2))
                base.paste(bg, (0, 0))
            except Exception:
                pass

        base = base.convert("RGBA")
        base.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, 120)))
        draw = ImageDraw.Draw(base)

        try:
            font_title = ImageFont.truetype("arial.ttf", 40)
            font_big = ImageFont.truetype("arial.ttf", 28)
            font = ImageFont.truetype("arial.ttf", 22)
            font_small = ImageFont.truetype("arial.ttf", 18)
        except Exception:
            font_title = ImageFont.load_default()
            font_big = ImageFont.load_default()
            font = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Panel
        panel = Image.new("RGBA", (W - 64, H - 64), panel_color)
        panel_draw = ImageDraw.Draw(panel)
        panel_draw.rounded_rectangle(
            (0, 0, panel.size[0], panel.size[1]),
            radius=22,
            outline=(255, 255, 255, 70),
            width=2,
        )
        base.alpha_composite(panel, (32, 32))

        # Avatar
        av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
        av = av.resize((128, 128), Image.Resampling.LANCZOS)
        mask = Image.new("L", (128, 128), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 127, 127), fill=255)
        av_circle = Image.new("RGBA", (128, 128))
        av_circle.paste(av, (0, 0), mask=mask)
        base.alpha_composite(av_circle, (60, 76))
        draw.ellipse((56, 72, 60 + 128 + 4, 76 + 128 + 4), outline=(255, 255, 255, 140), width=3)

        # Header
        draw.text((210, 66), _shorten(member_name, 24), fill=(255, 255, 255, 240), font=font_title)
        draw.text((210, 112), f"Rank: {_rank_title(level)}", fill=(255, 255, 255, 160), font=font_small)
        if title_text:
            draw.text((560, 112), _shorten(title_text, 26), fill=(255, 255, 255, 175), font=font_small)

        # XP bar
        bar_x, bar_y = 210, 150
        bar_w, bar_h = 640, 22
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=12, fill=(255, 255, 255, 45))
        ratio = 0.0 if need <= 0 else _clamp(xp / need, 0.0, 1.0)
        fill_w = int(bar_w * ratio)
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=12, fill=bar_color)
        xp_percent = int(ratio * 100)
        draw.text((bar_x, bar_y + 30), f"Level {level}  |  XP {xp}/{need}  |  {xp_percent}%", fill=(255, 255, 255, 210), font=font)

        # Stats
        draw.text((210, 220), f"Messages: {messages}", fill=(255, 255, 255, 220), font=font_big)
        draw.text((210, 255), f"Login streak: {streak}d", fill=(255, 255, 255, 220), font=font_big)
        draw.text((560, 220), f"Coins total: {coins_total:,}", fill=(255, 255, 255, 220), font=font_big)
        badge_text = ", ".join(badges[:4]) if badges else "No badges yet"
        draw.text((560, 255), f"Badges: {_shorten(badge_text, 32)}", fill=(255, 255, 255, 220), font=font)
        draw.text((560, 286), f"Last login: {last_login_text}", fill=(255, 255, 255, 170), font=font_small)
        draw.text((210, 286), f"Reputation: {rep}", fill=(255, 255, 255, 170), font=font_small)

        out = io.BytesIO()
        base.convert("RGB").save(out, format="PNG", optimize=True)
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
            list(p.get("badges", [])),
            last_login_text,
            str(p.get("style", "dark")),
            str(p.get("title", "")),
            int(p.get("rep", 0)),
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
