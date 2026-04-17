from datetime import datetime, timedelta
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


class Seasons(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/seasons.json")

    def get_state(self, guild_id: int) -> dict:
        key = str(guild_id)
        state = self.db.get(key, {})
        if not state:
            state = {
                "name": "Обычная неделя",
                "effect": "none",
                "battle_pass": {},
                "battle_pass_season": 1,
                "until": (datetime.now() + timedelta(days=7)).isoformat(),
            }
            self.db.set(key, state)
        state.setdefault("battle_pass", {})
        state.setdefault("battle_pass_season", 1)
        return state

    def _bp_user(self, state: dict, user_id: int) -> dict:
        bp = state.setdefault("battle_pass", {})
        user = bp.setdefault(str(user_id), {"xp": 0, "claimed_levels": []})
        user.setdefault("xp", 0)
        user.setdefault("claimed_levels", [])
        return user

    def _bp_level(self, xp: int) -> int:
        return max(1, (xp // 100) + 1)

    @app_commands.command(name="season_status", description="Текущий сезон/ивент недели")
    async def season_status(self, interaction: discord.Interaction):
        s = self.get_state(interaction.guild.id)
        until = datetime.fromisoformat(s["until"]).strftime("%d.%m %H:%M")
        user = self._bp_user(s, interaction.user.id)
        xp = int(user.get("xp", 0))
        lvl = self._bp_level(xp)
        await interaction.response.send_message(
            f"🗓️ Сезон: **{s['name']}**\n"
            f"Эффект: **{s['effect']}**\n"
            f"До: **{until}**\n"
            f"Battle Pass S{s['battle_pass_season']}: **ур. {lvl}**, XP: **{xp}**"
        )

    @app_commands.command(name="season_roll", description="Сменить недельный ивент (админ)")
    @app_commands.default_permissions(administrator=True)
    async def season_roll(self, interaction: discord.Interaction):
        events = [
            ("Дождливая неделя", "water_boost"),
            ("Засуха", "water_penalty"),
            ("Золотой урожай", "fruit_boost"),
            ("Ночь ремесленника", "craft_discount"),
        ]
        name, effect = random.choice(events)
        s = self.get_state(interaction.guild.id)
        s["name"], s["effect"] = name, effect
        s["until"] = (datetime.now() + timedelta(days=7)).isoformat()
        s["battle_pass_season"] = int(s.get("battle_pass_season", 1)) + 1
        s["battle_pass"] = {}
        self.db.set(str(interaction.guild.id), s)
        await interaction.response.send_message(f"🌦️ Новый недельный ивент: **{name}** | Battle Pass сброшен")

    @app_commands.command(name="battlepass_claim", description="Получить награду battle pass (ежедневно)")
    async def battlepass_claim(self, interaction: discord.Interaction):
        s = self.get_state(interaction.guild.id)
        user = self._bp_user(s, interaction.user.id)
        # Daily XP grant for BP progression
        user["xp"] = int(user.get("xp", 0)) + random.randint(18, 35)
        lvl = self._bp_level(int(user["xp"]))
        claimed = set(user.get("claimed_levels", []))
        if lvl in claimed:
            self.db.set(str(interaction.guild.id), s)
            await interaction.response.send_message(
                f"⏰ Награда уровня {lvl} уже забрана. Текущий BP XP: {user['xp']}",
                ephemeral=True,
            )
            return

        reward = 350 + (lvl * 90)
        user.setdefault("claimed_levels", []).append(lvl)
        self.db.set(str(interaction.guild.id), s)
        d = Wallet.get(interaction.guild.id, interaction.user.id)
        d["balance"] += reward
        Wallet.save(interaction.guild.id, interaction.user.id, d)
        await interaction.response.send_message(
            f"🎟️ Battle Pass: уровень **{lvl}**, награда **{reward}** 🪙, XP: **{user['xp']}**"
        )

    @app_commands.command(name="battlepass_status", description="Статус Battle Pass")
    async def battlepass_status(self, interaction: discord.Interaction):
        s = self.get_state(interaction.guild.id)
        user = self._bp_user(s, interaction.user.id)
        xp = int(user.get("xp", 0))
        lvl = self._bp_level(xp)
        next_need = lvl * 100
        left = max(0, next_need - xp)
        claimed_count = len(user.get("claimed_levels", []))
        await interaction.response.send_message(
            f"🎫 S{s['battle_pass_season']} | Level: **{lvl}**\n"
            f"XP: **{xp}** | До следующего уровня: **{left}**\n"
            f"Забрано уровней: **{claimed_count}**"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Seasons(bot))
