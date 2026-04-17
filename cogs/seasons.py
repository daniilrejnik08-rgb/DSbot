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
                "until": (datetime.now() + timedelta(days=7)).isoformat(),
            }
            self.db.set(key, state)
        return state

    @app_commands.command(name="season_status", description="Текущий сезон/ивент недели")
    async def season_status(self, interaction: discord.Interaction):
        s = self.get_state(interaction.guild.id)
        until = datetime.fromisoformat(s["until"]).strftime("%d.%m %H:%M")
        await interaction.response.send_message(
            f"🗓️ Сезон: **{s['name']}**\nЭффект: **{s['effect']}**\nДо: **{until}**"
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
        self.db.set(str(interaction.guild.id), s)
        await interaction.response.send_message(f"🌦️ Новый недельный ивент: **{name}**")

    @app_commands.command(name="battlepass_claim", description="Получить награду battle pass (ежедневно)")
    async def battlepass_claim(self, interaction: discord.Interaction):
        s = self.get_state(interaction.guild.id)
        bp = s.setdefault("battle_pass", {})
        user_key = str(interaction.user.id)
        now = datetime.now()
        last = bp.get(user_key)
        if last and (now - datetime.fromisoformat(last)) < timedelta(hours=20):
            await interaction.response.send_message("⏰ Награда battle pass уже получена", ephemeral=True)
            return
        bp[user_key] = now.isoformat()
        s["battle_pass"] = bp
        self.db.set(str(interaction.guild.id), s)
        d = Wallet.get(interaction.guild.id, interaction.user.id)
        d["balance"] += random.randint(400, 1100)
        Wallet.save(interaction.guild.id, interaction.user.id, d)
        await interaction.response.send_message("🎟️ Награда battle pass получена")


async def setup(bot: commands.Bot):
    await bot.add_cog(Seasons(bot))
