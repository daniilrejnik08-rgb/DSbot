from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.warnings_db = JSONHandler("data/warnings.json")

    @app_commands.command(name="warn", description="Выдать предупреждение")
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Нельзя предупредить этого пользователя", ephemeral=True)
            return
        guild_id, user_id = str(interaction.guild.id), str(member.id)
        warnings = self.warnings_db.get_nested(guild_id, user_id, default=[])
        warnings.append(
            {
                "moderator": interaction.user.id,
                "reason": reason,
                "timestamp": datetime.now().isoformat(),
                "id": len(warnings) + 1,
            }
        )
        self.warnings_db.set_nested(warnings, guild_id, user_id)
        await interaction.response.send_message(f"⚠️ {member.mention} получил предупреждение: **{reason}**")
        if len(warnings) >= 3:
            try:
                await member.timeout(timedelta(hours=1), reason="3 предупреждения")
                await interaction.channel.send(f"🔨 {member.mention} получил тайм-аут на 1 час за 3 предупреждения")
            except discord.Forbidden:
                pass

    @app_commands.command(name="warnings", description="Посмотреть предупреждения пользователя")
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        guild_id, user_id = str(interaction.guild.id), str(member.id)
        warnings = self.warnings_db.get_nested(guild_id, user_id, default=[])
        if not warnings:
            await interaction.response.send_message(f"✅ У {member.mention} нет предупреждений", ephemeral=True)
            return
        embed = discord.Embed(title=f"⚠️ Предупреждения {member.display_name}", color=discord.Color.orange())
        for warn in warnings[-10:]:
            mod = interaction.guild.get_member(warn["moderator"])
            mod_name = mod.mention if mod else "Неизвестный"
            dt = datetime.fromisoformat(warn["timestamp"]).strftime("%d.%m.%Y %H:%M")
            embed.add_field(
                name=f'Предупреждение #{warn["id"]}',
                value=f"**Модератор:** {mod_name}\n**Причина:** {warn['reason']}\n**Дата:** {dt}",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clearwarn", description="Снять все предупреждения")
    @app_commands.default_permissions(administrator=True)
    async def clearwarn(self, interaction: discord.Interaction, member: discord.Member):
        self.warnings_db.set_nested([], str(interaction.guild.id), str(member.id))
        await interaction.response.send_message(f"✅ Предупреждения {member.mention} сняты")

    @app_commands.command(name="kick", description="Кикнуть пользователя")
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Нарушение правил"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Нельзя кикнуть этого пользователя", ephemeral=True)
            return
        await member.kick(reason=reason)
        await interaction.response.send_message(f"👢 {member.mention} кикнут. Причина: **{reason}**")

    @app_commands.command(name="ban", description="Забанить пользователя")
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "Нарушение правил", days: int = 0):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Нельзя забанить этого пользователя", ephemeral=True)
            return
        await member.ban(reason=reason, delete_message_days=days)
        await interaction.response.send_message(f"🔨 {member.mention} забанен. Причина: **{reason}**")

    @app_commands.command(name="mute", description="Замутить пользователя")
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "Нарушение правил"):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ Нельзя замутить этого пользователя", ephemeral=True)
            return
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(f"🔇 {member.mention} замьючен на {minutes} мин")

    @app_commands.command(name="unmute", description="Размутить пользователя")
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"✅ {member.mention} размьючен")

    @app_commands.command(name="purge", description="Очистить сообщения")
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"✅ Удалено {len(deleted)} сообщений", ephemeral=True)

    @app_commands.command(name="botsay", description="Отправить сообщение от имени бота")
    @app_commands.describe(
        text="Текст сообщения бота",
        channel="Куда отправить (пусто — этот канал)",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def botsay(
        self,
        interaction: discord.Interaction,
        text: str,
        channel: discord.TextChannel | None = None,
    ):
        t = text.strip()
        if not t or len(t) > 2000:
            await interaction.response.send_message("❌ Текст: 1…2000 символов.", ephemeral=True)
            return
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("❌ Нужен текстовый канал.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await target.send(t)
        except discord.Forbidden:
            await interaction.followup.send("❌ У бота нет прав писать в этот канал.", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Отправлено в {target.mention}", ephemeral=True)

    @commands.command(name="say")
    @commands.has_permissions(manage_messages=True)
    async def say_prefix(self, ctx: commands.Context, *, text: str):
        """Префикс `!say`: отправить текст от имени бота (удаляет ваше сообщение)."""
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(text)


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Moderation(bot))
    else:
        await bot.add_cog(Moderation(bot), guild=g)
