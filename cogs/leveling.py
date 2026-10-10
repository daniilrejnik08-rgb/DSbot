"""Leveling / XP — порт iHorizon: XP за сообщения, уровни, роли, лидерборд."""
from __future__ import annotations

import math
import random
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND, SUCCESS, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    GOLD = discord.Color.gold()


def xp_for_level(level: int) -> int:
    """Кумулятивный XP до level (level 0 = 0)."""
    # soft curve: 5L^2 + 50L
    return 5 * level * level + 50 * level


def level_from_xp(xp: int) -> int:
    # solve 5L^2 + 50L - xp = 0
    if xp <= 0:
        return 0
    return int((-50 + math.sqrt(2500 + 20 * xp)) / 10)


class Leveling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/leveling.json")
        self._cd: dict[str, float] = {}  # guild.user -> last xp time

    def _g(self, guild_id: int) -> dict:
        data = self.db.get(str(guild_id), {}) or {}
        data.setdefault("users", {})
        data.setdefault("enabled", True)
        data.setdefault("xp_min", 15)
        data.setdefault("xp_max", 25)
        data.setdefault("cooldown", 60)
        data.setdefault("level_up_channel_id", None)
        data.setdefault("ignored_channels", [])
        data.setdefault("role_rewards", {})  # level_str -> role_id
        return data

    def _save(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def _user(self, data: dict, uid: str) -> dict:
        u = data.setdefault("users", {}).setdefault(uid, {"xp": 0, "level": 0})
        u.setdefault("xp", 0)
        u.setdefault("level", 0)
        return u

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        data = self._g(message.guild.id)
        if not data.get("enabled", True):
            return
        if message.channel.id in (data.get("ignored_channels") or []):
            return
        key = f"{message.guild.id}.{message.author.id}"
        now = time.time()
        cd = float(data.get("cooldown", 60))
        if now - self._cd.get(key, 0) < cd:
            return
        self._cd[key] = now

        gain = random.randint(int(data.get("xp_min", 15)), int(data.get("xp_max", 25)))
        u = self._user(data, str(message.author.id))
        u["xp"] = int(u.get("xp", 0)) + gain
        new_level = level_from_xp(u["xp"])
        old_level = int(u.get("level", 0))
        u["level"] = new_level
        self._save(message.guild.id, data)

        if new_level > old_level:
            await self._on_level_up(message, data, new_level)

    async def _on_level_up(self, message: discord.Message, data: dict, level: int):
        text = f"🎉 {message.author.mention} достиг **уровня {level}**!"
        # role rewards
        rewards = data.get("role_rewards") or {}
        role_id = rewards.get(str(level))
        if role_id:
            role = message.guild.get_role(int(role_id))
            if role:
                try:
                    await message.author.add_roles(role, reason=f"Level {level}")
                    text += f"\nРоль: {role.mention}"
                except Exception:
                    pass
        ch_id = data.get("level_up_channel_id")
        target = message.channel
        if ch_id:
            ch = message.guild.get_channel(int(ch_id))
            if isinstance(ch, discord.TextChannel):
                target = ch
        try:
            emb = discord.Embed(description=text, color=GOLD)
            await target.send(embed=emb)
        except Exception:
            pass

    @app_commands.command(name="rank", description="Ваш уровень и XP")
    async def rank(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        member = member or interaction.user
        data = self._g(interaction.guild_id)
        u = self._user(data, str(member.id))
        xp = int(u.get("xp", 0))
        lvl = int(u.get("level", 0))
        cur_floor = xp_for_level(lvl)
        next_need = xp_for_level(lvl + 1)
        into = xp - cur_floor
        span = max(1, next_need - cur_floor)
        pct = min(1.0, into / span)
        bar_w = 12
        filled = int(pct * bar_w)
        bar = "▓" * filled + "░" * (bar_w - filled)

        emb = discord.Embed(
            title=f"📊 Rank — {member.display_name}",
            color=BRAND,
        )
        emb.add_field(name="Уровень", value=f"**{lvl}**", inline=True)
        emb.add_field(name="XP", value=f"**{xp}**", inline=True)
        emb.add_field(
            name="Прогресс",
            value=f"`{bar}` {into}/{span}",
            inline=False,
        )
        emb.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="levels_top", description="Топ по уровню / XP")
    async def leaderboard(self, interaction: discord.Interaction):
        # note: economy also has /leaderboard — this is levels
        data = self._g(interaction.guild_id)
        rows = []
        for uid, u in (data.get("users") or {}).items():
            rows.append((uid, int(u.get("level", 0)), int(u.get("xp", 0))))
        rows.sort(key=lambda x: (x[1], x[2]), reverse=True)
        lines = []
        for i, (uid, lvl, xp) in enumerate(rows[:15], 1):
            lines.append(f"**{i}.** <@{uid}> — lvl **{lvl}** (`{xp}` XP)")
        emb = discord.Embed(
            title="🏆 Топ уровней",
            description="\n".join(lines) or "Пока пусто — пишите в чат!",
            color=GOLD,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="level_setup", description="Настройки XP-системы")
    @app_commands.default_permissions(manage_guild=True)
    async def level_setup(
        self,
        interaction: discord.Interaction,
        enabled: bool | None = None,
        level_up_channel: discord.TextChannel | None = None,
        xp_min: app_commands.Range[int, 1, 100] | None = None,
        xp_max: app_commands.Range[int, 1, 200] | None = None,
        cooldown: app_commands.Range[int, 10, 600] | None = None,
    ):
        data = self._g(interaction.guild_id)
        if enabled is not None:
            data["enabled"] = enabled
        if level_up_channel is not None:
            data["level_up_channel_id"] = level_up_channel.id
        if xp_min is not None:
            data["xp_min"] = xp_min
        if xp_max is not None:
            data["xp_max"] = max(xp_max, int(data.get("xp_min", 15)))
        if cooldown is not None:
            data["cooldown"] = cooldown
        self._save(interaction.guild_id, data)
        emb = discord.Embed(
            title="⚙️ Leveling",
            description=(
                f"Включено: **{data.get('enabled')}**\n"
                f"XP: **{data.get('xp_min')}–{data.get('xp_max')}** / "
                f"кулдаун **{data.get('cooldown')}**с\n"
                f"Канал level-up: {('<#' + str(data['level_up_channel_id']) + '>') if data.get('level_up_channel_id') else 'текущий'}"
            ),
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @app_commands.command(name="level_role", description="Роль за уровень")
    @app_commands.default_permissions(manage_guild=True)
    async def level_role(
        self,
        interaction: discord.Interaction,
        level: app_commands.Range[int, 1, 500],
        role: discord.Role,
    ):
        data = self._g(interaction.guild_id)
        data.setdefault("role_rewards", {})[str(level)] = role.id
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"✅ На уровне **{level}** → {role.mention}", ephemeral=True
        )

    @app_commands.command(name="level_ignore", description="Игнор XP в канале (toggle)")
    @app_commands.default_permissions(manage_guild=True)
    async def level_ignore(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ):
        data = self._g(interaction.guild_id)
        ignored: list = list(data.get("ignored_channels") or [])
        if channel.id in ignored:
            ignored.remove(channel.id)
            msg = f"✅ XP снова считается в {channel.mention}"
        else:
            ignored.append(channel.id)
            msg = f"🔇 XP отключён в {channel.mention}"
        data["ignored_channels"] = ignored
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="level_set", description="Выставить XP/уровень участнику")
    @app_commands.default_permissions(manage_guild=True)
    async def level_set(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        xp: app_commands.Range[int, 0, 10_000_000],
    ):
        data = self._g(interaction.guild_id)
        u = self._user(data, str(member.id))
        u["xp"] = xp
        u["level"] = level_from_xp(xp)
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"✅ {member.mention}: XP={xp}, lvl={u['level']}", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))
