import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler


class Automation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/automation.json")

    def settings(self, guild_id: int) -> dict:
        key = str(guild_id)
        s = self.db.get(key, {})
        if not s:
            s = {"autorole_id": None, "welcome_channel_id": None, "log_channel_id": None, "ticket_channel_id": None}
            self.db.set(key, s)
        return s

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        s = self.settings(member.guild.id)
        if s.get("autorole_id"):
            role = member.guild.get_role(s["autorole_id"])
            if role:
                try:
                    await member.add_roles(role, reason="Auto role")
                except discord.Forbidden:
                    pass
        if s.get("welcome_channel_id"):
            ch = member.guild.get_channel(s["welcome_channel_id"])
            if isinstance(ch, discord.TextChannel):
                view = discord.ui.View(timeout=None)
                btn = discord.ui.Button(label="Открыть правила", style=discord.ButtonStyle.link, url="https://discord.com")
                view.add_item(btn)
                await ch.send(f"👋 Добро пожаловать, {member.mention}!", view=view)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        s = self.settings(member.guild.id)
        if s.get("welcome_channel_id"):
            ch = member.guild.get_channel(s["welcome_channel_id"])
            if isinstance(ch, discord.TextChannel):
                await ch.send(f"👋 {member.display_name} покинул сервер")

    @app_commands.command(name="autorole_set", description="Установить авто-роль")
    @app_commands.default_permissions(manage_roles=True)
    async def autorole_set(self, interaction: discord.Interaction, role: discord.Role):
        s = self.settings(interaction.guild.id)
        s["autorole_id"] = role.id
        self.db.set(str(interaction.guild.id), s)
        await interaction.response.send_message(f"✅ Авто-роль установлена: {role.mention}")

    @app_commands.command(name="welcome_set", description="Канал для welcome/bye")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        s = self.settings(interaction.guild.id)
        s["welcome_channel_id"] = channel.id
        self.db.set(str(interaction.guild.id), s)
        await interaction.response.send_message(f"✅ Welcome канал: {channel.mention}")

    @app_commands.command(name="modlog_set", description="Канал логов модерации")
    @app_commands.default_permissions(manage_guild=True)
    async def modlog_set(self, interaction: discord.Interaction, channel: discord.TextChannel):
        s = self.settings(interaction.guild.id)
        s["log_channel_id"] = channel.id
        self.db.set(str(interaction.guild.id), s)
        await interaction.response.send_message(f"✅ Канал модлогов: {channel.mention}")

    @app_commands.command(name="ticket_setup", description="Создать простую кнопку тикета")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_setup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        class TicketView(discord.ui.View):
            @discord.ui.button(label="Создать тикет", style=discord.ButtonStyle.green)
            async def create_ticket(self, i: discord.Interaction, _):
                perms = {
                    i.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    i.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                    i.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
                }
                ticket = await i.guild.create_text_channel(name=f"ticket-{i.user.name}", overwrites=perms)
                await i.response.send_message(f"🎫 Тикет создан: {ticket.mention}", ephemeral=True)

        await channel.send("Поддержка сервера:", view=TicketView(timeout=None))
        await interaction.response.send_message("✅ Тикет панель отправлена", ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Automation(bot))
    else:
        await bot.add_cog(Automation(bot), guild=g)
