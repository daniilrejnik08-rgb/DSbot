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


class Profile(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/profiles.json")
        self.last_xp: dict[int, datetime] = {}
        self._bg_cache: list[bytes] = []
        self._http: aiohttp.ClientSession | None = None

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
    ) -> bytes:
        W, H = 960, 360
        base = Image.new("RGB", (W, H), (24, 24, 28))

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
        panel = Image.new("RGBA", (W - 64, H - 64), (18, 18, 22, 170))
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
        draw.text((210, 112), "Anime Profile Card", fill=(255, 255, 255, 160), font=font_small)

        # XP bar
        bar_x, bar_y = 210, 150
        bar_w, bar_h = 640, 22
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=12, fill=(255, 255, 255, 45))
        ratio = 0.0 if need <= 0 else _clamp(xp / need, 0.0, 1.0)
        fill_w = int(bar_w * ratio)
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=12, fill=(120, 140, 255, 210))
        draw.text((bar_x, bar_y + 30), f"Уровень {level} • XP {xp}/{need}", fill=(255, 255, 255, 210), font=font)

        # Stats
        draw.text((210, 220), f"💬 Сообщения: {messages}", fill=(255, 255, 255, 220), font=font_big)
        draw.text((210, 255), f"🔥 Серия входов: {streak}", fill=(255, 255, 255, 220), font=font_big)
        draw.text((560, 220), f"🪙 Монеты (всего): {coins_total:,}", fill=(255, 255, 255, 220), font=font_big)
        badge_text = ", ".join(badges[:6]) if badges else "Нет"
        draw.text((560, 255), f"🏅 Бейджи: {_shorten(badge_text, 28)}", fill=(255, 255, 255, 220), font=font)

        out = io.BytesIO()
        base.convert("RGB").save(out, format="PNG", optimize=True)
        return out.getvalue()

    @app_commands.command(name="profile", description="Профиль (картинка) + случайный аниме-фон")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        p = self.get_profile(interaction.guild.id, member.id)
        need = self.required_xp(int(p["level"]))
        eco = Wallet.get(interaction.guild.id, member.id)
        coins_total = int(eco.get("balance", 0)) + int(eco.get("bank", 0))

        if not _HAS_PIL:
            await interaction.response.send_message(
                "❌ Для рисования профиля установите Pillow: `pip install Pillow`",
                ephemeral=True,
            )
            return

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
        )

        file = discord.File(io.BytesIO(png), filename="profile.png")
        embed = discord.Embed(color=BRAND)
        embed.set_image(url="attachment://profile.png")
        embed.set_footer(text="Фон — рандом аниме • /daily_login")
        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="daily_login", description="Ежедневная серия входа")
    async def daily_login(self, interaction: discord.Interaction):
        profile = self.get_profile(interaction.guild.id, interaction.user.id)
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
