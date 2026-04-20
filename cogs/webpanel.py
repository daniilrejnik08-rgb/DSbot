import secrets

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler


class WebPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/webpanel.json")

    @app_commands.command(name="webpanel_token", description="Сгенерировать токен для веб-панели")
    @app_commands.default_permissions(administrator=True)
    async def webpanel_token(self, interaction: discord.Interaction):
        token = secrets.token_urlsafe(24)
        cfg = self.db.get(str(interaction.guild.id), {})
        cfg["admin_token"] = token
        self.db.set(str(interaction.guild.id), cfg)
        await interaction.response.send_message(
            f"🔐 Токен веб-панели: `{token}`\n(сохраняй в секрете)",
            ephemeral=True,
        )

    @app_commands.command(name="webpanel_config_export", description="Экспорт базовой конфигурации для веб-панели")
    @app_commands.default_permissions(administrator=True)
    async def webpanel_config_export(self, interaction: discord.Interaction):
        cfg = self.db.get(str(interaction.guild.id), {})
        if not cfg:
            cfg = {"admin_token": None}
        await interaction.response.send_message(
            f"```json\n{cfg}\n```",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(WebPanel(bot))
    else:
        await bot.add_cog(WebPanel(bot), guild=g)
