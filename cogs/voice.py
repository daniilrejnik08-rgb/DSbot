from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND as _THEME_BRAND
except Exception:
    _THEME_BRAND = discord.Color.from_rgb(88, 101, 242)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"

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

# ─── palette ─────────────────────────────────────────────────────────
_C_OPEN = discord.Color.from_rgb(87, 242, 135)      # green
_C_LOCKED = discord.Color.from_rgb(237, 66, 69)     # red
_C_HIDDEN = discord.Color.from_rgb(154, 170, 180)   # gray
_C_BRAND = _THEME_BRAND
_C_GOLD = discord.Color.from_rgb(254, 231, 92)
_C_BLURPLE = discord.Color.from_rgb(88, 101, 242)


def _parse_color(raw: str | None, fallback: discord.Color = _C_BRAND) -> discord.Color:
    if not raw:
        return fallback
    s = str(raw).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return discord.Color(int(s, 16))
    return fallback


def _slots_bar(current: int, limit: int, width: int = 10) -> str:
    if limit <= 0:
        filled = min(current, width)
        return "▓" * filled + "░" * (width - filled) + f"  {current}/∞"
    filled = int(round(min(current, limit) / limit * width))
    return "▓" * filled + "░" * (width - filled) + f"  {current}/{limit}"


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


def _default_guild() -> dict[str, Any]:
    return {
        "enabled": True,
        "cooldown_seconds": 20,
        "creator_channel_id": None,
        "category_id": None,
        "control_channel_id": None,
        "blacklist_role_id": None,
        "temp_channels": {},
        "user_profiles": {},
        # ── customization ──
        "panel_title": "Приватная голосовая комната",
        "panel_footer": "Orbis · временные войсы",
        "panel_color": None,  # hex без #, None → бренд
        "creator_name": "➕ Create Channel",
        "name_template": "🎧 {name}",
        "default_limit": 5,
        "auto_lock": False,
        "notify_on_create": True,
        "status_style": "rich",  # rich | minimal
    }


def build_voice_panel_embed(cfg: dict[str, Any] | None = None) -> discord.Embed:
    cfg = cfg or {}
    title = cfg.get("panel_title") or "Приватная голосовая комната"
    footer = cfg.get("panel_footer") or "Orbis · временные войсы"
    color = _parse_color(cfg.get("panel_color"), _C_BRAND)
    creator = cfg.get("creator_name") or "➕ Create Channel"

    desc = (
        f"### Как создать\n"
        f"Зайдите в **{creator}** — мгновенно появится ваша комната.\n\n"
        f"### Управление\n"
        f"Кнопки на этой панели **или** `/voice_panel` прямо в войсе.\n\n"
        f"```\n"
        f" 🔒 Замок     👁️ Видимость    ✏️ Имя     👥 Лимит\n"
        f" 👑 Владелец  🔑 Доступ       🎙️ Речь    👢 Кик\n"
        f" 🚫 Бан       🔗 Инвайт       📋 Статус  🗑️ Удалить\n"
        f"```\n"
        f"Только **владелец** комнаты может управлять · ответы видите только вы."
    )
    emb = discord.Embed(
        title=f"「 {title} 」",
        description=desc,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    emb.set_footer(text=footer)
    return emb


def _room_status_embed(
    channel: discord.VoiceChannel,
    owner_id: int | None,
    *,
    extra: str = "",
    cfg: dict[str, Any] | None = None,
) -> discord.Embed:
    cfg = cfg or {}
    overw = channel.overwrites_for(channel.guild.default_role)
    locked = overw.connect is False
    hidden = overw.view_channel is False
    limit = channel.user_limit or 0
    members = list(channel.members)
    n = len(members)

    if locked:
        color = _C_LOCKED
        state_icon = "🔒"
        state_text = "Закрыта"
    elif hidden:
        color = _C_HIDDEN
        state_icon = "🙈"
        state_text = "Скрыта"
    else:
        color = _C_OPEN
        state_icon = "🔓"
        state_text = "Открыта"

    # override with guild accent if open
    if not locked and not hidden and cfg.get("panel_color"):
        color = _parse_color(cfg.get("panel_color"), color)

    names = []
    for m in members[:15]:
        tag = " 👑" if owner_id and m.id == owner_id else ""
        names.append(f"`{m.display_name}`{tag}")
    members_line = " · ".join(names) if names else "*пусто*"
    if n > 15:
        members_line += f"  +{n - 15}"

    owner_line = f"<@{owner_id}>" if owner_id else "—"
    bar = _slots_bar(n, limit)
    bitrate = channel.bitrate // 1000

    style = (cfg.get("status_style") or "rich").lower()
    if style == "minimal":
        emb = discord.Embed(
            title=f"{state_icon} {channel.name}",
            description=(
                f"{extra}\n" if extra else ""
            ) + f"{state_text} · {bar}\nВладелец: {owner_line}",
            color=color,
        )
        return emb

    emb = discord.Embed(
        title=f"{state_icon}  {channel.name}",
        description=extra or None,
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    emb.add_field(name="Владелец", value=owner_line, inline=True)
    emb.add_field(name="Статус", value=f"**{state_text}**", inline=True)
    emb.add_field(name="Битрейт", value=f"`{bitrate} kbps`", inline=True)
    emb.add_field(name="Слоты", value=f"`{bar}`", inline=False)
    emb.add_field(name=f"Участники · {n}", value=members_line, inline=False)

    vis = "скрыт из списка" if hidden else "в списке каналов"
    lock = "только по доступу" if locked else "зайти может каждый"
    emb.add_field(
        name="Доступ",
        value=f"👁️ {vis}\n🚪 {lock}",
        inline=True,
    )
    emb.add_field(
        name="Быстрые команды",
        value="`/voice_panel` · `/voice_claim`",
        inline=True,
    )
    footer = cfg.get("panel_footer") or "Orbis · временные войсы"
    emb.set_footer(text=f"{footer} · ID {channel.id}")
    return emb


# ─── modals ──────────────────────────────────────────────────────────

class VoiceRenameModal(discord.ui.Modal, title="Название комнаты"):
    new_name = discord.ui.TextInput(
        label="Новое название",
        min_length=1,
        max_length=50,
        placeholder="Team Alpha / 🎮 Катка / …",
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
            await interaction.response.send_message(f"❌ Не удалось: `{e}`", ephemeral=True)
            return
        self.cog.save_profile_name(data, interaction.user.id, name)
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✏️ Комната переименована в **{name}**",
                color=_C_GOLD,
            ),
            ephemeral=True,
        )


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
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        self.cog.save_profile_limit(data, interaction.user.id, limit)
        self.cog.save_guild_data(interaction.guild.id, data)
        label = "∞ без лимита" if limit == 0 else str(limit)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"👥 Лимит слотов: **{label}**",
                color=_C_OPEN,
            ),
            ephemeral=True,
        )


class VoiceCustomizeModal(discord.ui.Modal, title="Кастомизация войсов"):
    panel_title = discord.ui.TextInput(
        label="Заголовок панели",
        max_length=80,
        required=False,
        placeholder="Приватная голосовая комната",
    )
    panel_footer = discord.ui.TextInput(
        label="Подпись внизу (footer)",
        max_length=80,
        required=False,
        placeholder="Orbis · временные войсы",
    )
    name_template = discord.ui.TextInput(
        label="Шаблон имени комнаты ({name} = ник)",
        max_length=80,
        required=False,
        placeholder="🎧 {name}",
    )
    panel_color = discord.ui.TextInput(
        label="Цвет панели (HEX без #)",
        max_length=6,
        required=False,
        placeholder="5865F2",
    )
    creator_name = discord.ui.TextInput(
        label="Имя канала-создателя",
        max_length=80,
        required=False,
        placeholder="➕ Create Channel",
    )

    def __init__(self, cog: "Voice", guild_id: int, cfg: dict[str, Any]):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id
        self.panel_title.default = str(cfg.get("panel_title") or "")[:80]
        self.panel_footer.default = str(cfg.get("panel_footer") or "")[:80]
        self.name_template.default = str(cfg.get("name_template") or "🎧 {name}")[:80]
        self.panel_color.default = str(cfg.get("panel_color") or "")[:6]
        self.creator_name.default = str(cfg.get("creator_name") or "➕ Create Channel")[:80]

    async def on_submit(self, interaction: discord.Interaction):
        data = self.cog.get_guild_data(self.guild_id)
        if str(self.panel_title).strip():
            data["panel_title"] = str(self.panel_title).strip()[:80]
        if str(self.panel_footer).strip():
            data["panel_footer"] = str(self.panel_footer).strip()[:80]
        tmpl = str(self.name_template).strip()
        if tmpl:
            if "{name}" not in tmpl:
                tmpl = tmpl + " {name}"
            data["name_template"] = tmpl[:80]
        color_raw = str(self.panel_color).strip().lstrip("#")
        if color_raw:
            if not re.fullmatch(r"[0-9a-fA-F]{6}", color_raw):
                await interaction.response.send_message(
                    "❌ Цвет: 6 hex-символов, например `5865F2`", ephemeral=True
                )
                return
            data["panel_color"] = color_raw.upper()
        if str(self.creator_name).strip():
            data["creator_name"] = str(self.creator_name).strip()[:80]
            # переименовать существующий create-channel
            cid = data.get("creator_channel_id")
            if cid:
                ch = interaction.guild.get_channel(cid) if interaction.guild else None
                if isinstance(ch, discord.VoiceChannel):
                    try:
                        await ch.edit(name=data["creator_name"])
                    except (discord.Forbidden, discord.HTTPException):
                        pass
        self.cog.save_guild_data(self.guild_id, data)

        preview = build_voice_panel_embed(data)
        await interaction.response.send_message(
            content="✅ Кастомизация сохранена. Превью панели:",
            embed=preview,
            ephemeral=True,
        )


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

        if self.action == "claim":
            await self.cog._handle_claim(interaction)
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
                    "❌ Новый владелец должен быть **в комнате**", ephemeral=True
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
                embed=discord.Embed(
                    description=f"👑 Новый владелец — {member.mention}",
                    color=_C_GOLD,
                ),
                ephemeral=True,
            )
            return

        if self.action == "access":
            overw = channel.overwrites_for(member)
            grant = overw.connect is not True
            overw.connect = True if grant else None
            if grant:
                overw.view_channel = True
            try:
                await channel.set_permissions(member, overwrite=overw)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            state = "выдан ✅" if grant else "сброшен"
            await interaction.response.send_message(
                f"🔑 Доступ {state}: {member.mention}", ephemeral=True
            )
            return

        if self.action == "speak":
            overw = channel.overwrites_for(member)
            grant = overw.speak is not True
            overw.speak = True if grant else False
            try:
                await channel.set_permissions(member, overwrite=overw)
            except (discord.Forbidden, discord.HTTPException) as e:
                await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
                return
            state = "разрешена ✅" if grant else "запрещена 🔇"
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
                embed=discord.Embed(
                    description=(
                        f"🚫 {member.mention} забанен в этой комнате.\n"
                        f"Снять бан: **🔑 Доступ** → выбрать снова."
                    ),
                    color=_C_LOCKED,
                ),
                ephemeral=True,
            )
            return


class VoiceMemberSelectView(discord.ui.View):
    def __init__(self, cog: "Voice", action: str, placeholder: str):
        super().__init__(timeout=90)
        self.add_item(VoiceMemberSelect(cog, action, placeholder))


class VoiceControlView(discord.ui.View):
    def __init__(self, cog: "Voice"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Статус", emoji="📋", style=discord.ButtonStyle.primary,
        custom_id="voice:status", row=0,
    )
    async def status(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        owner_id = (data.get("temp_channels") or {}).get(str(channel.id), {}).get("owner")
        emb = _room_status_embed(channel, owner_id, cfg=data)
        await interaction.response.send_message(embed=emb, ephemeral=True)

    @discord.ui.button(
        label="Замок", emoji="🔒", style=discord.ButtonStyle.secondary,
        custom_id="voice:lock_toggle", row=0,
    )
    async def lock_toggle(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        overw = channel.overwrites_for(interaction.guild.default_role)
        is_open = overw.connect is not False
        overw.connect = False if is_open else None
        try:
            await channel.set_permissions(interaction.guild.default_role, overwrite=overw)
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        if is_open:
            msg, col = "🔒 Комната **закрыта** — вход только по доступу", _C_LOCKED
        else:
            msg, col = "🔓 Комната **открыта**", _C_OPEN
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, color=col), ephemeral=True
        )

    @discord.ui.button(
        label="Видимость", emoji="👁️", style=discord.ButtonStyle.secondary,
        custom_id="voice:hide_toggle", row=0,
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
        if visible:
            msg, col = "🙈 Комната **скрыта** из списка каналов", _C_HIDDEN
        else:
            msg, col = "👀 Комната снова **в списке**", _C_OPEN
        await interaction.response.send_message(
            embed=discord.Embed(description=msg, color=col), ephemeral=True
        )

    @discord.ui.button(
        label="Имя", emoji="✏️", style=discord.ButtonStyle.secondary,
        custom_id="voice:rename", row=0,
    )
    async def rename(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceRenameModal(self.cog))

    @discord.ui.button(
        label="Лимит", emoji="👥", style=discord.ButtonStyle.secondary,
        custom_id="voice:limit", row=1,
    )
    async def limit(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(VoiceLimitModal(self.cog))

    @discord.ui.button(
        label="Владелец", emoji="👑", style=discord.ButtonStyle.primary,
        custom_id="voice:transfer", row=1,
    )
    async def transfer(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(
            self.cog, "transfer", "Новый владелец (должен быть в комнате)"
        )
        await interaction.response.send_message(
            "Выберите нового владельца:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Доступ", emoji="🔑", style=discord.ButtonStyle.success,
        custom_id="voice:access", row=1,
    )
    async def access(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "access", "Выдать / снять вход")
        await interaction.response.send_message(
            "Кому выдать или снять доступ:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Речь", emoji="🎙️", style=discord.ButtonStyle.success,
        custom_id="voice:speak", row=1,
    )
    async def speak(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "speak", "Разрешить / запретить речь")
        await interaction.response.send_message(
            "Кому менять право говорить:", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Кик", emoji="👢", style=discord.ButtonStyle.danger,
        custom_id="voice:kick", row=2,
    )
    async def kick(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "kick", "Кого выгнать")
        await interaction.response.send_message("Кого выгнать:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Бан", emoji="🚫", style=discord.ButtonStyle.danger,
        custom_id="voice:ban", row=2,
    )
    async def ban(self, interaction: discord.Interaction, _: discord.ui.Button):
        view = VoiceMemberSelectView(self.cog, "ban", "Забанить в этой комнате")
        await interaction.response.send_message(
            "Кого забанить (кик + запрет входа):", view=view, ephemeral=True
        )

    @discord.ui.button(
        label="Инвайт", emoji="🔗", style=discord.ButtonStyle.secondary,
        custom_id="voice:invite", row=2,
    )
    async def invite(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, _ = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        try:
            inv = await channel.create_invite(
                max_age=3600, max_uses=5, unique=True,
                reason=f"Voice invite by {interaction.user}",
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(
                f"❌ Нужны права Create Invite: `{e}`", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔗 Инвайт в комнату",
                description=(
                    f"**Срок:** 1 час · **Входов:** до 5\n\n"
                    f"[Присоединиться]({inv.url})\n`{inv.url}`"
                ),
                color=_C_BLURPLE,
            ),
            ephemeral=True,
        )

    @discord.ui.button(
        label="Удалить", emoji="🗑️", style=discord.ButtonStyle.danger,
        custom_id="voice:delete", row=2,
    )
    async def delete_room(self, interaction: discord.Interaction, _: discord.ui.Button):
        channel, data = await self.cog.ensure_owner_ephemeral(interaction)
        if not channel:
            return
        name = channel.name
        data.get("temp_channels", {}).pop(str(channel.id), None)
        self.cog.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"🗑️ **{name}** удаляется…",
                color=_C_LOCKED,
            ),
            ephemeral=True,
        )
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
        base = _default_guild()
        if not data:
            self.db.set(key, base)
            return dict(base)
        # merge defaults for new keys
        for k, v in base.items():
            data.setdefault(k, v)
        data.setdefault("temp_channels", {})
        data.setdefault("user_profiles", {})
        return data

    def save_guild_data(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def save_profile_name(self, guild_data: dict, user_id: int, name: str):
        profiles = guild_data.setdefault("user_profiles", {})
        profiles.setdefault(str(user_id), {})["name"] = name

    def save_profile_limit(self, guild_data: dict, user_id: int, limit: int):
        profiles = guild_data.setdefault("user_profiles", {})
        profiles.setdefault(str(user_id), {})["limit"] = limit

    def _format_room_name(self, guild_data: dict, member: discord.Member) -> str:
        profile = guild_data.get("user_profiles", {}).get(str(member.id), {})
        if profile.get("name"):
            return str(profile["name"])[:100]
        tmpl = guild_data.get("name_template") or "🎧 {name}"
        try:
            name = tmpl.replace("{name}", member.display_name)
        except Exception:
            name = f"🎧 {member.display_name}"
        return name[:100]

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
                "❌ Управлять может только владелец. Если он ушёл — `/voice_claim`",
                ephemeral=True,
            )
            return None, None
        return channel, data

    async def ensure_owner_ephemeral(self, interaction: discord.Interaction):
        return await self._ensure_owner(interaction)

    async def _handle_claim(self, interaction: discord.Interaction):
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
            await interaction.response.send_message("✅ Вы уже владелец", ephemeral=True)
            return
        if any(m.id == owner_id for m in channel.members):
            await interaction.response.send_message(
                "❌ Владелец сейчас в комнате", ephemeral=True
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
            embed=discord.Embed(
                description=f"👑 Вы владелец **{channel.name}**",
                color=_C_GOLD,
            ),
            ephemeral=True,
        )

    # ── admin ────────────────────────────────────────────────────────

    @app_commands.command(name="voice_setup", description="Настроить систему временных войсов")
    @app_commands.default_permissions(manage_channels=True)
    async def voice_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel | None = None,
        control_channel: discord.TextChannel | None = None,
        blacklist_role: discord.Role | None = None,
        cooldown_seconds: app_commands.Range[int, 0, 120] = 20,
        default_limit: app_commands.Range[int, 0, 99] = 5,
        auto_lock: bool = False,
    ):
        category = category or (interaction.channel.category if interaction.channel else None)
        if category is None:
            await interaction.response.send_message("❌ Укажите категорию", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        data = self.get_guild_data(interaction.guild.id)

        old_creator = data.get("creator_channel_id")
        if old_creator:
            old_ch = interaction.guild.get_channel(old_creator)
            if isinstance(old_ch, discord.VoiceChannel):
                try:
                    await old_ch.delete(reason="voice_setup: замена Create Channel")
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    pass

        creator_name = data.get("creator_name") or "➕ Create Channel"
        channel = await interaction.guild.create_voice_channel(
            creator_name, category=category
        )
        data["enabled"] = True
        data["category_id"] = category.id
        data["creator_channel_id"] = channel.id
        data["control_channel_id"] = (
            control_channel.id if control_channel else interaction.channel.id
        )
        data["blacklist_role_id"] = blacklist_role.id if blacklist_role else None
        data["cooldown_seconds"] = cooldown_seconds
        data["default_limit"] = int(default_limit)
        data["auto_lock"] = bool(auto_lock)
        self.save_guild_data(interaction.guild.id, data)

        panel_channel = interaction.guild.get_channel(data["control_channel_id"])
        panel_line = "Панель не отправлена — укажите текстовый канал."
        if isinstance(panel_channel, discord.TextChannel):
            embed = build_voice_panel_embed(data)
            banner = _voice_banner_file()
            send_kw: dict[str, Any] = {"embed": embed, "view": VoiceControlView(self)}
            if banner:
                file_obj, fname = banner
                embed.set_image(url=f"attachment://{fname}")
                send_kw["file"] = file_obj
            await panel_channel.send(**send_kw)
            panel_line = f"Панель: {panel_channel.mention}"

        done = discord.Embed(
            title="✨ Голосовые комнаты готовы",
            description=(
                f"{channel.mention} — зайдите, чтобы создать **свой** войс.\n\n"
                f"⏱ Кулдаун: **{cooldown_seconds}** с\n"
                f"👥 Лимит по умолчанию: **{default_limit or '∞'}**\n"
                f"🔒 Авто-замок: **{'да' if auto_lock else 'нет'}**\n"
                f"{panel_line}\n\n"
                f"Кастомизация: `/voice_customize` · `/voice_prefs`\n"
                f"В комнате: `/voice_panel` · `/voice_claim`"
            ),
            color=_parse_color(data.get("panel_color"), _C_BRAND),
        )
        done.set_footer(text=data.get("panel_footer") or "Orbis · временные войсы")
        await interaction.followup.send(embed=done, ephemeral=True)

    @app_commands.command(
        name="voice_customize",
        description="Кастомизация панели и шаблонов войсов (название, цвет, шаблон)",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def voice_customize(self, interaction: discord.Interaction):
        data = self.get_guild_data(interaction.guild.id)
        await interaction.response.send_modal(
            VoiceCustomizeModal(self, interaction.guild.id, data)
        )

    @app_commands.command(
        name="voice_prefs",
        description="Ваши личные настройки комнаты (имя по умолчанию, лимит, авто-замок)",
    )
    @app_commands.describe(
        default_name="Имя комнаты по умолчанию (пусто = шаблон сервера)",
        default_limit="Лимит слотов 0–99",
        auto_lock="Сразу закрывать комнату при создании",
    )
    async def voice_prefs(
        self,
        interaction: discord.Interaction,
        default_name: app_commands.Range[str, 1, 50] | None = None,
        default_limit: app_commands.Range[int, 0, 99] | None = None,
        auto_lock: bool | None = None,
    ):
        data = self.get_guild_data(interaction.guild.id)
        profile = data.setdefault("user_profiles", {}).setdefault(
            str(interaction.user.id), {}
        )
        changed = []
        if default_name is not None:
            profile["name"] = str(default_name).strip()[:100]
            changed.append(f"имя → **{profile['name']}**")
        if default_limit is not None:
            profile["limit"] = int(default_limit)
            changed.append(f"лимит → **{profile['limit'] or '∞'}**")
        if auto_lock is not None:
            profile["auto_lock"] = bool(auto_lock)
            changed.append(f"авто-замок → **{'да' if auto_lock else 'нет'}**")

        if not changed:
            # show current
            emb = discord.Embed(
                title="🎛 Ваши настройки войса",
                color=_parse_color(data.get("panel_color"), _C_BRAND),
            )
            emb.add_field(
                name="Имя по умолчанию",
                value=f"`{profile.get('name') or '— шаблон сервера —'}`",
                inline=False,
            )
            lim = profile.get("limit")
            if lim is None:
                lim = data.get("default_limit", 5)
            emb.add_field(name="Лимит", value=str(lim if lim else "∞"), inline=True)
            al = profile.get("auto_lock")
            if al is None:
                al = data.get("auto_lock", False)
            emb.add_field(name="Авто-замок", value="да" if al else "нет", inline=True)
            emb.add_field(
                name="Шаблон сервера",
                value=f"`{data.get('name_template') or '🎧 {name}'}`",
                inline=False,
            )
            emb.set_footer(text="Укажите параметры команды, чтобы изменить")
            await interaction.response.send_message(embed=emb, ephemeral=True)
            return

        self.save_guild_data(interaction.guild.id, data)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Сохранено",
                description="\n".join(f"· {c}" for c in changed),
                color=_C_OPEN,
            ),
            ephemeral=True,
        )

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
        description="Панель управления вашей временной комнатой",
    )
    async def voice_panel(self, interaction: discord.Interaction):
        channel, data = await self._ensure_owner(interaction)
        if not channel:
            return
        owner_id = (data.get("temp_channels") or {}).get(str(channel.id), {}).get("owner")
        emb = _room_status_embed(
            channel,
            owner_id,
            extra="**Ваша панель управления** — кнопки ниже.",
            cfg=data,
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

    @app_commands.command(
        name="voice_repost_panel",
        description="Заново отправить панель управления в control-канал",
    )
    @app_commands.default_permissions(manage_channels=True)
    async def voice_repost_panel(self, interaction: discord.Interaction):
        data = self.get_guild_data(interaction.guild.id)
        ctrl_id = data.get("control_channel_id")
        if not ctrl_id:
            await interaction.response.send_message(
                "❌ Сначала `/voice_setup`", ephemeral=True
            )
            return
        ch = interaction.guild.get_channel(ctrl_id)
        if not isinstance(ch, discord.TextChannel):
            await interaction.response.send_message(
                "❌ Control-канал не найден", ephemeral=True
            )
            return
        embed = build_voice_panel_embed(data)
        banner = _voice_banner_file()
        send_kw: dict[str, Any] = {"embed": embed, "view": VoiceControlView(self)}
        if banner:
            file_obj, fname = banner
            embed.set_image(url=f"attachment://{fname}")
            send_kw["file"] = file_obj
        await ch.send(**send_kw)
        await interaction.response.send_message(
            f"✅ Панель отправлена в {ch.mention}", ephemeral=True
        )

    # ── listener ─────────────────────────────────────────────────────

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

            limit = profile.get("limit")
            if limit is None:
                limit = int(guild_data.get("default_limit", 5) or 0)

            overwrites = {
                member.guild.default_role: discord.PermissionOverwrite(
                    connect=True, view_channel=True
                ),
                member: discord.PermissionOverwrite(**_OWNER_OVERWRITES),
            }

            # auto-lock: profile > guild
            auto_lock = profile.get("auto_lock")
            if auto_lock is None:
                auto_lock = bool(guild_data.get("auto_lock", False))
            if auto_lock:
                overwrites[member.guild.default_role] = discord.PermissionOverwrite(
                    connect=False, view_channel=True
                )

            try:
                new_channel = await member.guild.create_voice_channel(
                    name=self._format_room_name(guild_data, member),
                    category=category,
                    user_limit=int(limit or 0),
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

            if guild_data.get("notify_on_create", True):
                ctrl_id = guild_data.get("control_channel_id")
                if ctrl_id:
                    ctrl = member.guild.get_channel(ctrl_id)
                    if isinstance(ctrl, discord.TextChannel):
                        try:
                            emb = _room_status_embed(
                                new_channel,
                                member.id,
                                extra=(
                                    f"{member.mention}, комната создана.\n"
                                    f"Управление: кнопки или `/voice_panel`"
                                ),
                                cfg=guild_data,
                            )
                            await ctrl.send(
                                content=member.mention,
                                embed=emb,
                                view=VoiceControlView(self),
                                delete_after=120,
                            )
                        except (discord.Forbidden, discord.HTTPException):
                            pass

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

    # ── slash shortcuts ──────────────────────────────────────────────

    @app_commands.command(name="voice_lock", description="Закрыть свой временный войс")
    async def voice_lock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.set_permissions(interaction.guild.default_role, connect=False)
            await channel.set_permissions(interaction.user, **_OWNER_OVERWRITES)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(description="🔒 Канал закрыт", color=_C_LOCKED),
            ephemeral=True,
        )

    @app_commands.command(name="voice_unlock", description="Открыть свой временный войс")
    async def voice_unlock(self, interaction: discord.Interaction):
        channel, _ = await self._ensure_owner(interaction)
        if not channel:
            return
        try:
            await channel.set_permissions(interaction.guild.default_role, connect=None)
        except (discord.Forbidden, discord.HTTPException) as e:
            await interaction.response.send_message(f"❌ `{e}`", ephemeral=True)
            return
        await interaction.response.send_message(
            embed=discord.Embed(description="🔓 Канал открыт", color=_C_OPEN),
            ephemeral=True,
        )

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
        label = "∞" if limit == 0 else str(limit)
        await interaction.response.send_message(
            embed=discord.Embed(description=f"👥 Лимит: **{label}**", color=_C_OPEN),
            ephemeral=True,
        )

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
        await interaction.response.send_message(
            embed=discord.Embed(description=f"✏️ **{name}**", color=_C_GOLD),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
