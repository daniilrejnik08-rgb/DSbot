from __future__ import annotations

import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.from_rgb(88, 101, 242)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _voice_banner_file() -> tuple[discord.File, str] | None:
    """Картинка для embed: сначала ищется настоящая GIF (анимация), иначе статика.

    Положите **оригинальную** гифку с диска как `assets/voice_panel_banner.gif`
    ( так не восстановить).
    """
    for name in (
        "voice_panel_banner.gif",
        "voice_panel_banner.webp",
        "voice_panel_banner.png",
        "voice_panel_banner.jpg",
        "voice_panel_static.jpg",
    ):
        path = _ASSETS / name
        if path.is_file():
            return discord.File(path, filename=name), name
    return None


def build_voice_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="Приватная голосовая комната",
        description=(
            "Создайте канал через **➕ Create Channel**, зайдите в него — откроется управление.\n\n"
            "・ **Комната** — замок, видимость в списке, имя и лимит слотов\n"
            "・ **Участники** — новый владелец, кто может зайти и говорить, кик\n\n"
            "*Ответы на нажатия видите только вы.*"
        ),
        color=BRAND,
        timestamp=discord.utils.utcnow(),
    ).set_footer(text="Панель для владельца временного войса")


class VoiceRenameModal(discord.ui.Modal, title="Изменить название комнаты"):
    new_name = discord.ui.TextInput(label="Новое название", min_length=1, max_length=50, placeholder="Например: Team Alpha")

    def __init__(self, cog: "Voice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        await channel.edit(name=str(self.new_name))
        self.cog.save_profile_name(data, interaction.user.id, str(self.new_name))
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"✏️ Название изменено: **{self.new_name}**", ephemeral=True)


class VoiceLimitModal(discord.ui.Modal, title="Изменить лимит"):
    limit = discord.ui.TextInput(label="Лимит от 0 до 99", min_length=1, max_length=2, placeholder="5")

    def __init__(self, cog: "Voice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(str(self.limit))
        except ValueError:
            await interaction.response.send_message("❌ Введите число", ephemeral=True)
            return
        if limit < 0 or limit > 99:
            await interaction.response.send_message("❌ Лимит должен быть от 0 до 99", ephemeral=True)
            return
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        await channel.edit(user_limit=limit)
        self.cog.save_profile_limit(data, interaction.user.id, limit)
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"👥 Лимит изменен: **{limit}**", ephemeral=True)


class VoiceMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "Voice", action: str, placeholder: str):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.cog = cog
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("❌ Участник не найден", ephemeral=True)
            return
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return

        if self.action == "transfer":
            if member not in channel.members:
                await interaction.response.send_message("❌ Пользователь должен быть в вашей комнате", ephemeral=True)
                return
            data["temp_channels"][str(channel.id)]["owner"] = member.id
            self.cog.save_guild_data(interaction.guild.id, data)
            await interaction.response.send_message(f"👑 Владелец комнаты: {member.mention}", ephemeral=True)
            return

        if self.action == "access":
            overw = channel.overwrites_for(member)
            current = overw.connect
            overw.connect = True if current is not True else None
            await channel.set_permissions(member, overwrite=overw)
            state = "выдан" if current is not True else "сброшен"
            await interaction.response.send_message(f"🔑 Доступ {state}: {member.mention}", ephemeral=True)
            return

        if self.action == "speak":
            overw = channel.overwrites_for(member)
            current = overw.speak
            overw.speak = True if current is not True else None
            await channel.set_permissions(member, overwrite=overw)
            state = "разрешен" if current is not True else "сброшен"
            await interaction.response.send_message(f"🎙️ Право говорить {state}: {member.mention}", ephemeral=True)
            return

        if self.action == "kick":
            if member not in channel.members:
                await interaction.response.send_message("❌ Пользователь не в вашей комнате", ephemeral=True)
                return
            await member.move_to(None)
            await interaction.response.send_message(f"👢 Участник выгнан: {member.mention}", ephemeral=True)
            return


class VoiceMemberSelectView(discord.ui.View):
    def __init__(self, cog: "Voice", action: str, placeholder: str):
        super().__init__(timeout=60)
        self.add_item(VoiceMemberSelect(cog, action, placeholder))


class VoiceControlView(discord.ui.View):
    def __init__(self, cog: "Voice"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Передать владельца",
        emoji="👑",
        style=discord.ButtonStyle.primary,
        custom_id="voice:transfer",
        row=0,
    )
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "transfer", "Новый владелец — из вашей комнаты")
        await interaction.response.send_message("Выберите участника:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Закрыть / открыть",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:lock_toggle",
        row=0,
    )
    async def lock_toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, _ = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        overw = channel.overwrites_for(interaction.guild.default_role)
        is_open = overw.connect is not False
        overw.connect = False if is_open else None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overw)
        await interaction.response.send_message("🔒 Комната закрыта" if is_open else "🔓 Комната открыта", ephemeral=True)

    @discord.ui.button(
        label="Название",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:rename",
        row=0,
    )
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceRenameModal(self.cog))

    @discord.ui.button(
        label="Лимит слотов",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:limit",
        row=0,
    )
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceLimitModal(self.cog))

    @discord.ui.button(
        label="Скрыть / показать",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:hide_toggle",
        row=1,
    )
    async def hide_toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, _ = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        overw = channel.overwrites_for(interaction.guild.default_role)
        visible = overw.view_channel is not False
        overw.view_channel = False if visible else None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overw)
        await interaction.response.send_message("🙈 Комната скрыта" if visible else "👀 Комната видима", ephemeral=True)

    @discord.ui.button(
        label="Доступ в комнату",
        emoji="🔑",
        style=discord.ButtonStyle.success,
        custom_id="voice:access",
        row=1,
    )
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "access", "Кому выдать или снять вход")
        await interaction.response.send_message("Выберите участника:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Право говорить",
        emoji="🎙️",
        style=discord.ButtonStyle.success,
        custom_id="voice:speak",
        row=1,
    )
    async def speak(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "speak", "Кому разрешить или запретить речь")
        await interaction.response.send_message("Выберите участника:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Выгнать",
        emoji="👢",
        style=discord.ButtonStyle.danger,
        custom_id="voice:kick",
        row=1,
    )
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "kick", "Кого отключить от канала")
        await interaction.response.send_message("Выберите участника:", view=view, ephemeral=True)


class Voice(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/voice.json")
        self.cooldowns: dict[int, float] = {}
        self.bot.add_view(VoiceControlView(self))

    def get_guild_data(self, guild_id: int) -> dict:
        key = str(guild_id)
        data = self.db.get(key, {})
        if not data:
            data = {
                "enabled": True,
                "cooldown_seconds": 20,
                "creator_channel_id": None,
                "category_id": None,
                "control_channel_id": None,
                "blacklist_role_id": None,
                "temp_channels": {},
                "user_profiles": {},
            }
            self.db.set(key, data)
        return data

    def save_guild_data(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    @app_commands.command(name="voice_setup", description="Настроить систему временных войсов")
    @app_commands.default_permissions(manage_channels=True)
    async def voice_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
        control_channel: discord.TextChannel | None = None,
        blacklist_role: discord.Role | None = None,
        cooldown_seconds: app_commands.Range[int, 0, 120] = 20,
    ):
        category = category or interaction.channel.category
        if category is None:
            await interaction.response.send_message("❌ Укажите категорию", ephemeral=True)
            return

        channel = await interaction.guild.create_voice_channel("➕ Create Channel", category=category)
        data = self.get_guild_data(interaction.guild.id)
        data["enabled"] = True
        data["category_id"] = category.id
        data["creator_channel_id"] = channel.id
        data["control_channel_id"] = control_channel.id if control_channel else interaction.channel.id
        data["blacklist_role_id"] = blacklist_role.id if blacklist_role else None
        data["cooldown_seconds"] = cooldown_seconds
        self.save_guild_data(interaction.guild.id, data)

        panel_channel = interaction.guild.get_channel(data["control_channel_id"])
        panel_line = "Панель не отправлена — выберите текстовый канал для панели."
        if isinstance(panel_channel, discord.TextChannel):
            embed = build_voice_panel_embed()
            banner = _voice_banner_file()
            send_kw: dict = {"embed": embed, "view": VoiceControlView(self)}
            if banner:
                file_obj, fname = banner
                embed.set_image(url=f"attachment://{fname}")
                send_kw["file"] = file_obj
            await panel_channel.send(**send_kw)
            panel_line = f"Панель управления: {panel_channel.mention}"

        done = discord.Embed(
            title="Голосовые комнаты готовы",
            description=(
                f"{channel.mention} — зайдите сюда, чтобы создать **свой** временный войс.\n"
                f"Кулдаун: **{cooldown_seconds}** с\n"
                f"{panel_line}"
            ),
            color=BRAND,
        )
        await interaction.response.send_message(embed=done)

    @app_commands.command(name="voice_toggle", description="Включить или выключить систему временных войсов")
    @app_commands.default_permissions(manage_channels=True)
    async def voice_toggle(self, interaction: discord.Interaction, enabled: bool):
        data = self.get_guild_data(interaction.guild.id)
        data["enabled"] = enabled
        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message("✅ Система включена" if enabled else "⛔ Система выключена")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild_data = self.get_guild_data(member.guild.id)
        if not guild_data.get("enabled", True):
            return

        creator_id = guild_data.get("creator_channel_id")
        temp_channels: dict = guild_data.get("temp_channels", {})
        user_profiles: dict = guild_data.get("user_profiles", {})

        if after.channel and creator_id and after.channel.id == creator_id:
            blacklist_role_id = guild_data.get("blacklist_role_id")
            if blacklist_role_id and any(role.id == blacklist_role_id for role in member.roles):
                try:
                    await member.move_to(None)
                except discord.Forbidden:
                    pass
                return

            cooldown = int(guild_data.get("cooldown_seconds", 20))
            now = time.time()
            last = self.cooldowns.get(member.id, 0.0)
            if cooldown > 0 and (now - last) < cooldown:
                try:
                    await member.move_to(None)
                except discord.Forbidden:
                    pass
                return
            self.cooldowns[member.id] = now

            profile = user_profiles.get(str(member.id), {})
            category = after.channel.category
            if guild_data.get("category_id"):
                saved_category = member.guild.get_channel(guild_data["category_id"])
                if isinstance(saved_category, discord.CategoryChannel):
                    category = saved_category

            new_channel = await member.guild.create_voice_channel(
                name=profile.get("name") or f"🎧 {member.display_name}",
                category=category,
                user_limit=int(profile.get("limit", 5)),
            )
            await member.move_to(new_channel)
            temp_channels[str(new_channel.id)] = {"owner": member.id, "created_at": int(now)}
            guild_data["temp_channels"] = temp_channels
            self.save_guild_data(member.guild.id, guild_data)

        if before.channel and str(before.channel.id) in temp_channels:
            if len(before.channel.members) == 0:
                temp_channels.pop(str(before.channel.id), None)
                guild_data["temp_channels"] = temp_channels
                self.save_guild_data(member.guild.id, guild_data)
                try:
                    await before.channel.delete(reason="Автоудаление пустого временного канала")
                except discord.Forbidden:
                    pass

    async def _ensure_owner(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Вы не в голосовом канале", ephemeral=True)
            return None, None
        channel = interaction.user.voice.channel
        data = self.get_guild_data(interaction.guild.id)
        channel_data = data.get("temp_channels", {}).get(str(channel.id))
        if not channel_data:
            await interaction.response.send_message("❌ Это не временный канал бота", ephemeral=True)
            return None, None
        if channel_data.get("owner") != interaction.user.id:
            await interaction.response.send_message("❌ Управлять каналом может только владелец", ephemeral=True)
            return None, None
        return channel, data

    async def ensure_owner_ephemeral(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ Вы не в голосовом канале", ephemeral=True)
            return None, None
        channel = interaction.user.voice.channel
        data = self.get_guild_data(interaction.guild.id)
        channel_data = data.get("temp_channels", {}).get(str(channel.id))
        if not channel_data:
            await interaction.response.send_message("❌ Это не временный канал бота", ephemeral=True)
            return None, None
        if channel_data.get("owner") != interaction.user.id:
            await interaction.response.send_message("❌ Управлять каналом может только владелец", ephemeral=True)
            return None, None
        return channel, data

    def save_profile_name(self, guild_data: dict, user_id: int, name: str):
        profiles = guild_data.setdefault("user_profiles", {})
        profile = profiles.setdefault(str(user_id), {})
        profile["name"] = name

    def save_profile_limit(self, guild_data: dict, user_id: int, limit: int):
        profiles = guild_data.setdefault("user_profiles", {})
        profile = profiles.setdefault(str(user_id), {})
        profile["limit"] = limit

    @app_commands.command(name="voice_lock", description="Закрыть свой временный войс")
    async def voice_lock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        await interaction.response.send_message("🔒 Канал закрыт")

    @app_commands.command(name="voice_unlock", description="Открыть свой временный войс")
    async def voice_unlock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message("🔓 Канал открыт")

    @app_commands.command(name="voice_limit", description="Изменить лимит участников войса")
    async def voice_limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        await channel.edit(user_limit=limit)
        self.save_profile_limit(data, interaction.user.id, limit)
        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"👥 Новый лимит: {limit}")

    @app_commands.command(name="voice_kick", description="Кикнуть участника из вашего войса")
    async def voice_kick(self, interaction: discord.Interaction, member: discord.Member):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        if member not in channel.members:
            await interaction.response.send_message("❌ Пользователь не в вашем канале", ephemeral=True)
            return
        await member.move_to(None)
        await interaction.response.send_message(f"👢 {member.mention} отключен от канала")

    @app_commands.command(name="voice_rename", description="Переименовать ваш временный войс")
    async def voice_rename(self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 50]):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        await channel.edit(name=name)
        self.save_profile_name(data, interaction.user.id, name)
        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"✏️ Новое имя канала: **{name}**")


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Voice(bot))
    else:
        await bot.add_cog(Voice(bot), guild=g)
