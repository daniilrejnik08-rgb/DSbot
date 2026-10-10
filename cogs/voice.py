from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.from_rgb(88, 101, 242)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Права владельца временной комнаты
_OWNER_OVERWRITES = dict(
    connect=True,
    speak=True,
    view_channel=True,
    stream=True,
    manage_channels=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)


def _voice_banner_file() -> tuple[discord.File, str] | None:
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
            "Зайдите в **➕ Create Channel** — появится ваша комната.\n"
            "Управление: кнопки ниже **или** команда `/voice_panel` (в комнате).\n\n"
            "・ 🔒 Замок · 👁️ Видимость · ✏️ Имя · 👥 Лимит\n"
            "・ 👑 Владелец · 🔑 Доступ · 🎙️ Речь · 👢 Кик · 🚫 Бан\n"
            "・ 📋 Статус · 🔗 Инвайт · 🗑️ Удалить комнату\n\n"
            "*Ответы на кнопки видите только вы.*"
        ),
        color=BRAND,
        timestamp=discord.utils.utcnow(),
    ).set_footer(text="Панель временных войсов")


def _room_status_embed(
    channel: discord.VoiceChannel,
    owner_id: int | None,
    *,
    extra: str = "",
) -> discord.Embed:
    overw = channel.overwrites_for(channel.guild.default_role)
    locked = overw.connect is False
    hidden = overw.view_channel is False
    limit = channel.user_limit or 0
    members = list(channel.members)
    names = ", ".join(m.display_name for m in members[:12]) or "—"
    if len(members) > 12:
        names += f" (+{len(members) - 12})"

    owner_line = f"<@{owner_id}>" if owner_id else "—"
    flags = []
    flags.append("🔒 закрыта" if locked else "🔓 открыта")
    flags.append("🙈 скрыта" if hidden else "👀 в списке")
    flags.append(f"👥 {len(members)}" + (f"/{limit}" if limit else ""))

    emb = discord.Embed(
        title=f"🎙 {channel.name}",
        description=extra or None,
        color=BRAND,
        timestamp=discord.utils.utcnow(),
    )
    emb.add_field(name="Владелец", value=owner_line, inline=True)
    emb.add_field(name="Состояние", value=" · ".join(flags), inline=True)
    emb.add_field(name="Битрейт", value=f"{channel.bitrate // 1000} kbps", inline=True)
    emb.add_field(name="Участники", value=names, inline=False)
    emb.set_footer(text=f"ID {channel.id}")
    return emb


class VoiceRenameModal(discord.ui.Modal, title="Название комнаты"):
    new_name = discord.ui.TextInput(
        label="Новое название",
        min_length=1,
        max_length=50,
        placeholder="Например: Team Alpha",
    )

    def __init__(self, cog: "Voice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        name = str(self.new_name).strip()[:100]
        try:
            await channel.edit(name=name)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ Не удалось переименовать: `{e}`", ephemeral=True)
            return
        self.cog.save_profile_name(data, interaction.user.id, name)
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"✏️ Название: **{name}**", ephemeral=True)


class VoiceLimitModal(discord.ui.Modal, title="Лимит слотов"):
    limit = discord.ui.TextInput(
        label="Лимит 0–99 (0 = без лимита)",
        min_length=1,
        max_length=2,
        placeholder="5",
    )

    def __init__(self, cog: "Voice"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit = int(str(self.limit).strip())
        except ValueError:
            await interaction.response.send_message("❌ Введите число", ephemeral=True)
            return
        if limit < 0 or limit > 99:
            await interaction.response.send_message("❌ Лимит 0–99", ephemeral=True)
            return
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        try:
            await channel.edit(user_limit=limit)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ Ошибка: `{e}`", ephemeral=True)
            return
        self.cog.save_profile_limit(data, interaction.user.id, limit)
        self.cog.save_guild_data(interaction.guild.id, data)
        label = "без лимита" if limit == 0 else str(limit)
        await interaction.response.send_message(f"👥 Лимит: **{label}**", ephemeral=True)


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

        # claim не требует быть владельцем
        if self.action == "claim":
            await self.cog._handle_claim(interaction, member)
            return

        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return

        if self.action == "transfer":
            if member.id == interaction.user.id:
                await interaction.response.send_message("❌ Нельзя передать себе", ephemeral=True)
                return
            if member not in channel.members:
                await interaction.response.send_message(
                    "❌ Новый владелец должен быть **в вашей комнате**", ephemeral=True
                )
                return
            data["temp_channels"][str(channel.id)]["owner"] = member.id
            self.cog.save_guild_data(interaction.guild.id, data)
            try:
                await channel.set_permissions(member, **_OWNER_OVERWRITES)
                await channel.set_permissions(
                    interaction.user,
                    connect=True,
                    speak=True,
                    view_channel=True,
                    stream=True,
                    manage_channels=None,
                    move_members=None,
                    mute_members=None,
                    deafen_members=None,
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            await interaction.response.send_message(
                f"👑 Владелец: {member.mention}", ephemeral=True
            )
            return

        if self.action == "access":
            overw = channel.overwrites_for(member)
            current = overw.connect
            # toggle: нет явного True → выдать True; иначе сбросить
            grant = current is not True
            overw.connect = True if grant else None
            if grant:
                overw.view_channel = True
            try:
                await channel.set_permissions(member, overwrite=overw)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            state = "выдан" if grant else "сброшен"
            await interaction.response.send_message(
                f"🔑 Доступ {state}: {member.mention}", ephemeral=True
            )
            return

        if self.action == "speak":
            overw = channel.overwrites_for(member)
            current = overw.speak
            grant = current is not True
            overw.speak = True if grant else False
            try:
                await channel.set_permissions(member, overwrite=overw)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            state = "разрешена" if grant else "запрещена"
            await interaction.response.send_message(
                f"🎙️ Речь {state}: {member.mention}", ephemeral=True
            )
            return

        if self.action == "kick":
            if member.id == interaction.user.id:
                await interaction.response.send_message("❌ Нельзя кикнуть себя", ephemeral=True)
                return
            if member not in channel.members:
                await interaction.response.send_message("❌ Нет в комнате", ephemeral=True)
                return
            try:
                await member.move_to(None)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            await interaction.response.send_message(
                f"👢 Выгнан: {member.mention}", ephemeral=True
            )
            return

        if self.action == "ban":
            if member.id == interaction.user.id:
                await interaction.response.send_message("❌ Нельзя забанить себя", ephemeral=True)
                return
            if member.guild_permissions.administrator:
                await interaction.response.send_message(
                    "❌ Нельзя банить администратора", ephemeral=True
                )
                return
            try:
                await channel.set_permissions(
                    member, connect=False, view_channel=False, speak=False
                )
                if member in channel.members:
                    await member.move_to(None)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            await interaction.response.send_message(
                f"🚫 Забанен в комнате: {member.mention}\n"
                f"(снять: **🔑 Доступ** → выбрать снова)",
                ephemeral=True,
            )
            return


class VoiceMemberSelectView(discord.ui.View):
    def __init__(self, cog: "Voice", action: str, placeholder: str):
        super().__init__(timeout=90)
        self.add_item(VoiceMemberSelect(cog, action, placeholder))


class VoiceControlView(discord.ui.View):
    """Постоянная панель (timeout=None) — кнопки для владельца комнаты."""

    def __init__(self, cog: "Voice"):
        super().__init__(timeout=None)
        self.cog = cog

    # —— ряд 0: комната ——
    @discord.ui.button(
        label="Статус",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="voice:status",
        row=0,
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        owner_id = (data.get("temp_channels") or {}).get(str(channel.id), {}).get("owner")
        emb = _room_status_embed(channel, owner_id)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(
        label="Замок",
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
        try:
            await channel.set_permissions(interaction.guild.default_role, overwrite=overw)
            # владелец всегда может зайти
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message(
            "🔒 Комната **закрыта**" if is_open else "🔓 Комната **открыта**",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Видимость",
        emoji="👁️",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:hide_toggle",
        row=0,
    )
    async def hide_toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, _ = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        overw = channel.overwrites_for(interaction.guild.default_role)
        visible = overw.view_channel is not False
        overw.view_channel = False if visible else None
        try:
            await channel.set_permissions(interaction.guild.default_role, overwrite=overw)
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message(
            "🙈 Скрыта из списка" if visible else "👀 Снова в списке",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Имя",
        emoji="✏️",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:rename",
        row=0,
    )
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceRenameModal(self.cog))

    # —— ряд 1: слоты / люди ——
    @discord.ui.button(
        label="Лимит",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:limit",
        row=1,
    )
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceLimitModal(self.cog))

    @discord.ui.button(
        label="Владелец",
        emoji="👑",
        style=discord.ButtonStyle.primary,
        custom_id="voice:transfer",
        row=1,
    )
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(
            self.cog, "transfer", "Новый владелец (должен быть в комнате)"
        )
        await interaction.response.send_message(
            "Выберите нового владельца:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Доступ",
        emoji="🔑",
        style=discord.ButtonStyle.success,
        custom_id="voice:access",
        row=1,
    )
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "access", "Выдать / снять вход")
        await interaction.response.send_message(
            "Кому выдать или снять доступ:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Речь",
        emoji="🎙️",
        style=discord.ButtonStyle.success,
        custom_id="voice:speak",
        row=1,
    )
    async def speak(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "speak", "Разрешить / запретить речь")
        await interaction.response.send_message(
            "Кому менять право говорить:", view=view, ephemeral=True
        )

    # —— ряд 2: модерация / утилиты ——
    @discord.ui.button(
        label="Кик",
        emoji="👢",
        style=discord.ButtonStyle.danger,
        custom_id="voice:kick",
        row=2,
    )
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "kick", "Кого выгнать")
        await interaction.response.send_message("Кого выгнать:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Бан",
        emoji="🚫",
        style=discord.ButtonStyle.danger,
        custom_id="voice:ban",
        row=2,
    )
    async def ban(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "ban", "Забанить в этой комнате")
        await interaction.response.send_message(
            "Кого забанить в комнате (кик + запрет входа):", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Инвайт",
        emoji="🔗",
        style=discord.ButtonStyle.secondary,
        custom_id="voice:invite",
        row=2,
    )
    async def invite(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, _ = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        try:
            inv = await channel.create_invite(
                max_age=3600,
                max_uses=5,
                unique=True,
                reason=f"Voice room invite by {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(
                f"❌ Не удалось создать инвайт (нужны права Create Invite): `{e}`",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"🔗 Инвайт на **1 час**, до **5** входов:\n{inv.url}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Удалить",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="voice:delete",
        row=2,
    )
    async def delete_room(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        cid = str(channel.id)
        data.get("temp_channels", {}).pop(cid, None)
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message("🗑️ Комната удаляется…", ephemeral=True)
        try:
            await channel.delete(reason=f"Удалена владельцем {interaction.user}")
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            pass


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
        data.setdefault("temp_channels", {})
        data.setdefault("user_profiles", {})
        return data

    def save_guild_data(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def save_profile_name(self, guild_data: dict, user_id: int, name: str):
        profiles = guild_data.setdefault("user_profiles", {})
        profile = profiles.setdefault(str(user_id), {})
        profile["name"] = name

    def save_profile_limit(self, guild_data: dict, user_id: int, limit: int):
        profiles = guild_data.setdefault("user_profiles", {})
        profile = profiles.setdefault(str(user_id), {})
        profile["limit"] = limit

    def _find_owned_channel(
        self, guild: discord.Guild, user_id: int, temp_channels: dict
    ) -> discord.VoiceChannel | None:
        for cid, meta in list(temp_channels.items()):
            if meta.get("owner") != user_id:
                continue
            ch = guild.get_channel(int(cid))
            if isinstance(ch, discord.VoiceChannel):
                return ch
            temp_channels.pop(cid, None)
        return None

    async def _ensure_owner(self, interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ Вы не в голосовом канале", ephemeral=True
            )
            return None, None
        channel = interaction.user.voice.channel
        data = self.get_guild_data(interaction.guild.id)
        channel_data = data.get("temp_channels", {}).get(str(channel.id))
        if not channel_data:
            await interaction.response.send_message(
                "❌ Это не временный канал бота", ephemeral=True
            )
            return None, None
        if channel_data.get("owner") != interaction.user.id:
            await interaction.response.send_message(
                "❌ Управлять может только владелец. "
                "Если владелец ушёл — `/voice_claim`",
                ephemeral=True,
            )
            return None, None
        return channel, data

    async def ensure_owner_ephemeral(self, interaction: discord.Interaction):
        return await self._ensure_owner(interaction)

    async def _handle_claim(self, interaction: discord.Interaction, _member: discord.Member | None = None):
        """Перехват владения, если владелец не в канале."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ Зайдите в комнату, которой хотите завладеть", ephemeral=True
            )
            return
        channel = interaction.user.voice.channel
        data = self.get_guild_data(interaction.guild.id)
        meta = data.get("temp_channels", {}).get(str(channel.id))
        if not meta:
            await interaction.response.send_message(
                "❌ Это не временный канал бота", ephemeral=True
            )
            return
        owner_id = meta.get("owner")
        if owner_id == interaction.user.id:
            await interaction.response.send_message(
                "✅ Вы уже владелец", ephemeral=True
            )
            return
        owner_in_channel = any(m.id == owner_id for m in channel.members)
        if owner_in_channel:
            await interaction.response.send_message(
                "❌ Владелец сейчас в комнате — нельзя забрать права", ephemeral=True
            )
            return
        meta["owner"] = interaction.user.id
        data["temp_channels"][str(channel.id)] = meta
        self.save_guild_data(interaction.guild.id, data)
        try:
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException):
            pass
        await interaction.response.send_message(
            f"👑 Вы теперь владелец **{channel.name}**", ephemeral=True
        )

    # ── setup / toggle ──────────────────────────────────────────────

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
        category = category or (interaction.channel.category if interaction.channel else None)
        if category is None:
            await interaction.response.send_message("❌ Укажите категорию", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        data = self.get_guild_data(interaction.guild.id)

        # удалить старый Create Channel, если ещё существует
        old_creator = data.get("creator_channel_id")
        if old_creator:
            old_ch = interaction.guild.get_channel(old_creator)
            if isinstance(old_ch, discord.VoiceChannel):
                try:
                    await old_ch.delete(reason="voice_setup: замена Create Channel")
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass

        channel = await interaction.guild.create_voice_channel(
            "➕ Create Channel", category=category
        )
        data["enabled"] = True
        data["category_id"] = category.id
        data["creator_channel_id"] = channel.id
        data["control_channel_id"] = (
            control_channel.id if control_channel else interaction.channel.id
        )
        data["blacklist_role_id"] = blacklist_role.id if blacklist_role else None
        data["cooldown_seconds"] = cooldown_seconds
        self.save_guild_data(interaction.guild.id, data)

        panel_channel = interaction.guild.get_channel(data["control_channel_id"])
        panel_line = "Панель не отправлена — укажите текстовый канал."
        if isinstance(panel_channel, discord.TextChannel):
            embed = build_voice_panel_embed()
            banner = _voice_banner_file()
            send_kw: dict[str, Any] = {"embed": embed, "view": VoiceControlView(self)}
            if banner:
                file_obj, fname = banner
                embed.set_image(url=f"attachment://{fname}")
                send_kw["file"] = file_obj
            await panel_channel.send(**send_kw)
            panel_line = f"Панель: {panel_channel.mention}"

        done = discord.Embed(
            title="Голосовые комнаты готовы",
            description=(
                f"{channel.mention} — зайдите, чтобы создать **свой** войс.\n"
                f"Кулдаун: **{cooldown_seconds}** с\n"
                f"{panel_line}\n\n"
                f"В комнате: `/voice_panel` · `/voice_claim`"
            ),
            color=BRAND,
        )
        await interaction.followup.send(embed=done, ephemeral=True)

    @app_commands.command(
        name="voice_toggle", description="Включить или выключить систему временных войсов"
    )
    @app_commands.default_permissions(manage_channels=True)
    async def voice_toggle(self, interaction: discord.Interaction, enabled: bool):
        data = self.get_guild_data(interaction.guild.id)
        data["enabled"] = enabled
        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(
            "✅ Система включена" if enabled else "⛔ Система выключена"
        )

    @app_commands.command(
        name="voice_panel",
        description="Открыть панель управления вашей временной комнатой",
    )
    async def voice_panel(self, interaction: discord.Interaction):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        owner_id = (data.get("temp_channels") or {}).get(str(channel.id), {}).get("owner")
        emb = _room_status_embed(
            channel,
            owner_id,
            extra="Кнопки ниже — только для владельца.",
        )
        await interaction.response.send_message(
            embed=emb, view=VoiceControlView(self), ephemeral=True
        )

    @app_commands.command(
        name="voice_claim",
        description="Забрать владение комнатой, если владелец вышел",
    )
    async def voice_claim(self, interaction: discord.Interaction):
        await self._handle_claim(interaction)

    # ── listener ────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return
        guild_data = self.get_guild_data(member.guild.id)
        if not guild_data.get("enabled", True):
            return

        creator_id = guild_data.get("creator_channel_id")
        temp_channels: dict = guild_data.get("temp_channels", {})
        user_profiles: dict = guild_data.get("user_profiles", {})

        # Создание комнаты
        if after.channel and creator_id and after.channel.id == creator_id:
            blacklist_role_id = guild_data.get("blacklist_role_id")
            if blacklist_role_id and any(r.id == blacklist_role_id for r in member.roles):
                try:
                    await member.move_to(None)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                return

            existing = self._find_owned_channel(member.guild, member.id, temp_channels)
            if existing is not None:
                try:
                    await member.move_to(existing)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                guild_data["temp_channels"] = temp_channels
                self.save_guild_data(member.guild.id, guild_data)
                return

            cooldown = int(guild_data.get("cooldown_seconds", 20))
            now = time.time()
            last = self.cooldowns.get(member.id, 0.0)
            if cooldown > 0 and (now - last) < cooldown:
                try:
                    await member.move_to(None)
                except (discord.Forbidden, discord.HTTPException):
                    pass
                return
            self.cooldowns[member.id] = now

            profile = user_profiles.get(str(member.id), {})
            category = after.channel.category
            if guild_data.get("category_id"):
                saved = member.guild.get_channel(guild_data["category_id"])
                if isinstance(saved, discord.CategoryChannel):
                    category = saved

            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(
                    connect=True, view_channel=True
                ),
                member: discord.PermissionOverwrite(**_OWNER_OVERWRITES),
            }
            try:
                new_channel = await member.guild.create_voice_channel(
                    name=str(profile.get("name") or f"🎧 {member.display_name}")[:100],
                    category=category,
                    user_limit=int(profile.get("limit", 5) or 0),
                    overwrites=overwrites,
                )
                await member.move_to(new_channel)
            except (discord.Forbidden, discord.HTTPException):
                return

            temp_channels[str(new_channel.id)] = {
                "owner": member.id,
                "created_at": int(now),
            }
            guild_data["temp_channels"] = temp_channels
            self.save_guild_data(member.guild.id, guild_data)

            # личная подсказка владельцу в control-канал (если есть)
            ctrl_id = guild_data.get("control_channel_id")
            if ctrl_id:
                ctrl = member.guild.get_channel(ctrl_id)
                if isinstance(ctrl, discord.TextChannel):
                    try:
                        emb = _room_status_embed(
                            new_channel,
                            member.id,
                            extra=(
                                f"{member.mention}, ваша комната создана.\n"
                                f"Управление: кнопки на панели или `/voice_panel`"
                            ),
                        )
                        await ctrl.send(
                            content=member.mention,
                            embed=emb,
                            view=VoiceControlView(self),
                            delete_after=120,
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass

        # Автоудаление пустой комнаты
        if before.channel and str(before.channel.id) in temp_channels:
            remaining = [m for m in before.channel.members if m.id != member.id]
            if len(remaining) == 0:
                temp_channels.pop(str(before.channel.id), None)
                guild_data["temp_channels"] = temp_channels
                self.save_guild_data(member.guild.id, guild_data)
                try:
                    await before.channel.delete(
                        reason="Автоудаление пустого временного канала"
                    )
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass

    # ── slash shortcuts ─────────────────────────────────────────────

    @app_commands.command(name="voice_lock", description="Закрыть свой временный войс")
    async def voice_lock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.set_permissions(
                interaction.guild.default_role, connect=False
            )
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Канал закрыт", ephemeral=True)

    @app_commands.command(name="voice_unlock", description="Открыть свой временный войс")
    async def voice_unlock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.set_permissions(
                interaction.guild.default_role, connect=None
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message("🔓 Канал открыт", ephemeral=True)

    @app_commands.command(name="voice_limit", description="Лимит участников вашей комнаты")
    async def voice_limit(
        self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]
    ):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.edit(user_limit=limit)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        self.save_profile_limit(data, interaction.user.id, limit)
        self.save_guild_data(interaction.guild.id, data)
        label = "без лимита" if limit == 0 else str(limit)
        await interaction.response.send_message(f"👥 Лимит: **{label}**", ephemeral=True)

    @app_commands.command(name="voice_kick", description="Кикнуть из вашей комнаты")
    async def voice_kick(self, interaction: discord.Interaction, member: discord.Member):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        if member not in channel.members:
            await interaction.response.send_message(
                "❌ Пользователь не в канале", ephemeral=True
            )
            return
        try:
            await member.move_to(None)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message(
            f"👢 {member.mention} отключён", ephemeral=True
        )

    @app_commands.command(name="voice_rename", description="Переименовать вашу комнату")
    async def voice_rename(
        self, interaction: discord.Interaction, name: app_commands.Range[str, 1, 50]
    ):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.edit(name=name)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        self.save_profile_name(data, interaction.user.id, name)
        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(f"✏️ **{name}**", ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(Voice(bot))
    else:
        await bot.add_cog(Voice(bot), guilds=guilds)
