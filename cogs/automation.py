import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

def _ticket_meta_from_topic(topic: str | None) -> dict[str, str]:
    if not topic:
        return {}
    out: dict[str, str] = {}
    for part in topic.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


class CloseTicketButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Закрыть тикет", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")

    async def callback(self, interaction: discord.Interaction):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Эту кнопку можно использовать только в текстовом тикете.", ephemeral=True)
            return
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Не удалось определить участника.", ephemeral=True)
            return

        meta = _ticket_meta_from_topic(channel.topic)
        owner_id_raw = meta.get("owner_id")
        staff_role_raw = meta.get("staff_role_id")
        is_owner = owner_id_raw is not None and owner_id_raw.isdigit() and int(owner_id_raw) == interaction.user.id
        is_staff = False
        if staff_role_raw and staff_role_raw.isdigit():
            is_staff = any(r.id == int(staff_role_raw) for r in interaction.user.roles)
        can_manage = interaction.user.guild_permissions.manage_channels

        if not (is_owner or is_staff or can_manage):
            await interaction.response.send_message("❌ Закрывать тикет может автор, staff или модератор.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Тикет будет удален через 5 секунд...")
        await asyncio.sleep(5)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CloseTicketButton())


class TicketDropdown(discord.ui.Select):
    def __init__(self, cog: "Automation"):
        self.cog = cog
        options = [
            discord.SelectOption(label="Задать вопрос", description="Исключительно вопросы, имеющие смысл.", emoji="🌺", value="question"),
            discord.SelectOption(label="Репорт-баг", description="Уведомить администрацию о найденном баге.", emoji="🛠️", value="bug"),
            discord.SelectOption(label="Апелляция блокировки", description="Подать заявку на апелляцию бана.", emoji="⚖️", value="appeal"),
            discord.SelectOption(label="Жалоба на игрока", description="Подать жалобу на нарушителя.", emoji="📝", value="report"),
        ]
        super().__init__(placeholder="Выберите категорию обращения", min_values=1, max_values=1, options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        user = interaction.user
        if guild is None or not isinstance(user, discord.Member):
            await interaction.response.send_message("❌ Команду можно использовать только на сервере.", ephemeral=True)
            return

        s = self.cog.settings(guild.id)
        category_id = s.get("ticket_category_id")
        staff_role_id = s.get("ticket_staff_role_id")
        ticket_category = guild.get_channel(category_id) if category_id else None
        if not isinstance(ticket_category, discord.CategoryChannel):
            await interaction.response.send_message("❌ Категория тикетов не настроена. Используй `/ticket_setup`.", ephemeral=True)
            return

        staff_role = guild.get_role(staff_role_id) if staff_role_id else None
        topic_key = self.values[0]
        topic_ru = {
            "question": "вопрос",
            "bug": "баг",
            "appeal": "апелляция",
            "report": "жалоба",
        }.get(topic_key, "тикет")

        existing = None
        for ch in ticket_category.text_channels:
            meta = _ticket_meta_from_topic(ch.topic)
            if meta.get("owner_id", "") == str(user.id):
                existing = ch
                break
        if existing is not None:
            await interaction.response.send_message(f"ℹ️ У вас уже есть открытый тикет: {existing.mention}", ephemeral=True)
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, embed_links=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f"ticket-{topic_key}-{user.id}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=ticket_category,
            overwrites=overwrites,
            topic=f"owner_id={user.id};ticket_topic={topic_key};staff_role_id={staff_role_id or ''}",
        )

        embed = discord.Embed(
            title=f"🎫 Тикет открыт! ({topic_ru.capitalize()})",
            description=f"Приветствуем, {user.mention}!\nОпишите вашу проблему как можно подробнее. Администрация скоро ответит.",
            color=0xFF66B2,
        )
        embed.set_footer(text="Чтобы закрыть тикет, нажмите кнопку ниже.")
        await ticket_channel.send(embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ Ваш тикет создан: {ticket_channel.mention}", ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self, cog: "Automation"):
        super().__init__(timeout=None)
        self.add_item(TicketDropdown(cog))


class Automation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/automation.json")
        self.bot.add_view(TicketView(self))
        self.bot.add_view(CloseTicketView())

    def settings(self, guild_id: int) -> dict:
        key = str(guild_id)
        s = self.db.get(key, {})
        if not s:
            s = {
                "autorole_id": None,
                "welcome_channel_id": None,
                "log_channel_id": None,
                "ticket_channel_id": None,
                "ticket_category_id": None,
                "ticket_staff_role_id": None,
                "ticket_info_channel_id": None,
                "ticket_banner_url": None,
                "ticket_separator_url": None,
            }
            self.db.set(key, s)
        else:
            changed = False
            defaults = {
                "ticket_category_id": None,
                "ticket_staff_role_id": None,
                "ticket_info_channel_id": None,
                "ticket_banner_url": None,
                "ticket_separator_url": None,
            }
            for k, v in defaults.items():
                if k not in s:
                    s[k] = v
                    changed = True
            if changed:
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

    @app_commands.command(name="ticket_setup", description="Настроить систему тикетов и отправить панель")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        category: discord.CategoryChannel,
        staff_role: discord.Role | None = None,
        info_channel: discord.TextChannel | None = None,
        banner_url: str | None = None,
        separator_url: str | None = None,
    ):
        s = self.settings(interaction.guild.id)
        s["ticket_channel_id"] = panel_channel.id
        s["ticket_category_id"] = category.id
        s["ticket_staff_role_id"] = staff_role.id if staff_role else None
        s["ticket_info_channel_id"] = info_channel.id if info_channel else None
        if banner_url is not None:
            s["ticket_banner_url"] = banner_url.strip() or None
        if separator_url is not None:
            s["ticket_separator_url"] = separator_url.strip() or None
        self.db.set(str(interaction.guild.id), s)

        panel_embed = discord.Embed(
            title="📑 - ОБРАЩЕНИЕ В ПОДДЕРЖКУ",
            description="Перед тем, как открыть тикет, пожалуйста, ознакомьтесь с информацией в закреплённом FAQ.",
            color=0xFF66B2,
        )
        icon_url = interaction.guild.icon.url if interaction.guild.icon else None
        panel_embed.set_footer(text="SUPPORT PANEL", icon_url=icon_url)
        await panel_channel.send(embed=panel_embed, view=TicketView(self))
        await interaction.response.send_message(
            f"✅ Тикет-система настроена.\nПанель: {panel_channel.mention}\nКатегория тикетов: {category.mention}",
            ephemeral=True,
        )

    @app_commands.command(name="faq_scwh", description="Развернуть FAQ и систему поддержки")
    @app_commands.default_permissions(administrator=True)
    async def faq_scwh(self, interaction: discord.Interaction):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ Команду можно использовать только в текстовом канале.", ephemeral=True)
            return

        s = self.settings(interaction.guild.id)
        if not s.get("ticket_category_id"):
            await interaction.response.send_message("❌ Сначала настройте систему через `/ticket_setup`.", ephemeral=True)
            return

        await interaction.response.send_message("✅ Система поддержки развернута.", ephemeral=True)
        channel = interaction.channel
        tickets_mention = channel.mention

        info_channel_id = s.get("ticket_info_channel_id")
        info_line = f"<#{info_channel_id}>" if info_channel_id else tickets_mention
        banner_url = s.get("ticket_banner_url")
        separator_url = s.get("ticket_separator_url")

        embeds: list[discord.Embed] = []
        if banner_url:
            embed1 = discord.Embed(color=0xFF66B2)
            embed1.set_image(url=banner_url)
            embeds.append(embed1)

        embed2 = discord.Embed(
            title="– Всё, что связано с заходом на Сервер:",
            description=(
                f"**Основная информация о сервере находится в данном канале:** {info_line}\n\n"
                "**1. Ошибки с подключением:**\n"
                "– Конкретного решения данной проблемы нет, но есть пара способов, которые могут вам помочь!\n"
                "– Отключите все программы, влияющие на подключение к Интернету.\n"
                "– Очистите ДНС кэш.\n"
                "– Если вам ничего не помогло, попробуйте использовать VPN.\n"
                f"– Вообще ничего не помогло? Обратитесь в: {tickets_mention}"
            ),
            color=0xFF66B2,
        )
        if separator_url:
            embed2.set_image(url=separator_url)
        embeds.append(embed2)

        embed3 = discord.Embed(
            title="– Всё, что связано с сайтом:",
            description=(
                "**2. Частые вопросы по сайту:**\n"
                "– Если страница не открывается, очистите кэш и проверьте сеть.\n\n"
                "**2.1. Остались проблемы:**\n"
                f"– Откройте тикет в канале: {tickets_mention}"
            ),
            color=0xFF66B2,
        )
        if separator_url:
            embed3.set_image(url=separator_url)
        embeds.append(embed3)

        embed4 = discord.Embed(
            title="– Прочее:",
            description=(
                "**4. Я нашёл баг, что мне делать?**\n"
                f"– Если вы нашли баг, обратитесь в {tickets_mention}\n\n"
                "**4.1. Я незаслуженно получил наказание на сервере.**\n"
                f"– Подайте апелляцию через тикет: {tickets_mention}"
            ),
            color=0xFF66B2,
        )
        if separator_url:
            embed4.set_image(url=separator_url)
        embeds.append(embed4)

        embed_ticket = discord.Embed(
            title="📑 - ОБРАЩЕНИЕ В ПОДДЕРЖКУ",
            description="Перед тем, как открыть тикет, пожалуйста, ознакомьтесь с вышеприведённой информацией.",
            color=0xFF66B2,
        )
        icon_url = interaction.guild.icon.url if interaction.guild.icon else None
        embed_ticket.set_footer(text="SUPPORT PANEL", icon_url=icon_url)
        embeds.append(embed_ticket)

        await channel.send(embeds=embeds, view=TicketView(self))


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(Automation(bot))
    else:
        await bot.add_cog(Automation(bot), guilds=guilds)
