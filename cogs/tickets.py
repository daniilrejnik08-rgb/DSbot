"""Tickets — порт iHorizon: панель, создание, закрытие, transcript, claim."""
from __future__ import annotations

import asyncio

import io
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND, SUCCESS, DANGER, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    DANGER = discord.Color.red()
    GOLD = discord.Color.gold()


class TicketOpenView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Открыть тикет",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:open",
    )
    async def open_ticket(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._create_ticket(interaction)


class TicketControlView(discord.ui.View):
    def __init__(self, cog: "Tickets"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Закрыть",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close",
    )
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._close_ticket(interaction)

    @discord.ui.button(
        label="Claim",
        emoji="🙋",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:claim",
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button):
        data = self.cog._guild(interaction.guild_id)
        t = (data.get("tickets") or {}).get(str(interaction.channel_id))
        if not t:
            await interaction.response.send_message("❌ Это не тикет", ephemeral=True)
            return
        if not interaction.user.guild_permissions.manage_channels and not self.cog._is_staff(
            interaction.user, data
        ):
            await interaction.response.send_message("❌ Только staff", ephemeral=True)
            return
        t["claimed_by"] = interaction.user.id
        data.setdefault("tickets", {})[str(interaction.channel_id)] = t
        self.cog._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"🙋 Тикет принят: {interaction.user.mention}"
        )
        try:
            await interaction.channel.edit(
                topic=f"Claimed by {interaction.user} · opener {t.get('opener_id')}"
            )
        except Exception:
            pass

    @discord.ui.button(
        label="Transcript",
        emoji="📜",
        style=discord.ButtonStyle.secondary,
        custom_id="ticket:transcript",
    )
    async def transcript(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        text = await self.cog._build_transcript(interaction.channel)
        buf = io.BytesIO(text.encode("utf-8"))
        f = discord.File(buf, filename=f"transcript-{interaction.channel_id}.txt")
        await interaction.followup.send(file=f, ephemeral=True)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/tickets.json")
        self.bot.add_view(TicketOpenView(self))
        self.bot.add_view(TicketControlView(self))

    def _guild(self, guild_id: int) -> dict:
        key = str(guild_id)
        data = self.db.get(key, {}) or {}
        data.setdefault("tickets", {})
        data.setdefault("counter", 0)
        data.setdefault("staff_role_id", None)
        data.setdefault("category_id", None)
        data.setdefault("log_channel_id", None)
        return data

    def _save(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def _is_staff(self, member: discord.Member, data: dict) -> bool:
        rid = data.get("staff_role_id")
        if not rid:
            return member.guild_permissions.manage_channels
        return any(r.id == int(rid) for r in member.roles) or member.guild_permissions.administrator

    async def _create_ticket(self, interaction: discord.Interaction):
        data = self._guild(interaction.guild_id)
        # one open ticket per user
        for cid, t in (data.get("tickets") or {}).items():
            if t.get("opener_id") == interaction.user.id and not t.get("closed"):
                ch = interaction.guild.get_channel(int(cid))
                if ch:
                    await interaction.response.send_message(
                        f"❌ У вас уже есть тикет: {ch.mention}", ephemeral=True
                    )
                    return
        cat = None
        if data.get("category_id"):
            cat = interaction.guild.get_channel(int(data["category_id"]))
        data["counter"] = int(data.get("counter", 0)) + 1
        num = data["counter"]
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, attach_files=True, read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        staff_role = None
        if data.get("staff_role_id"):
            staff_role = interaction.guild.get_role(int(data["staff_role_id"]))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True, send_messages=True, read_message_history=True
                )
        name = f"ticket-{num}-{interaction.user.name}"[:90]
        try:
            channel = await interaction.guild.create_text_channel(
                name=name,
                category=cat if isinstance(cat, discord.CategoryChannel) else None,
                overwrites=overwrites,
                topic=f"Ticket #{num} · {interaction.user.id}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Нет прав на создание каналов", ephemeral=True
            )
            return
        data.setdefault("tickets", {})[str(channel.id)] = {
            "opener_id": interaction.user.id,
            "number": num,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "closed": False,
            "claimed_by": None,
        }
        self._save(interaction.guild_id, data)

        emb = discord.Embed(
            title=f"🎫 Тикет #{num}",
            description=(
                f"Привет, {interaction.user.mention}!\n"
                f"Опишите проблему — support скоро ответит.\n\n"
                f"🔒 Закрыть · 🙋 Claim · 📜 Transcript"
            ),
            color=BRAND,
        )
        await channel.send(
            content=f"{interaction.user.mention}"
            + (f" {staff_role.mention}" if staff_role else ""),
            embed=emb,
            view=TicketControlView(self),
        )
        await interaction.response.send_message(
            f"✅ Тикет создан: {channel.mention}", ephemeral=True
        )

    async def _close_ticket(self, interaction: discord.Interaction):
        data = self._guild(interaction.guild_id)
        t = (data.get("tickets") or {}).get(str(interaction.channel_id))
        if not t:
            await interaction.response.send_message("❌ Это не тикет", ephemeral=True)
            return
        opener = t.get("opener_id")
        if (
            interaction.user.id != opener
            and not self._is_staff(interaction.user, data)
        ):
            await interaction.response.send_message("❌ Нет прав", ephemeral=True)
            return
        await interaction.response.send_message("🔒 Закрываю через 3 сек…")
        # transcript to log
        log_id = data.get("log_channel_id")
        if log_id:
            log_ch = interaction.guild.get_channel(int(log_id))
            if isinstance(log_ch, discord.TextChannel):
                try:
                    text = await self._build_transcript(interaction.channel)
                    buf = io.BytesIO(text.encode("utf-8"))
                    await log_ch.send(
                        content=f"Тикет #{t.get('number')} закрыт {interaction.user.mention}",
                        file=discord.File(buf, filename=f"ticket-{t.get('number')}.txt"),
                    )
                except Exception:
                    pass
        t["closed"] = True
        data["tickets"][str(interaction.channel_id)] = t
        self._save(interaction.guild_id, data)
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception:
            pass

    async def _build_transcript(self, channel: discord.TextChannel) -> str:
        lines = [
            f"Transcript #{channel.name}",
            f"Channel ID: {channel.id}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "-" * 40,
        ]
        async for msg in channel.history(limit=500, oldest_first=True):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M")
            content = msg.content or ""
            if msg.attachments:
                content += " " + " ".join(a.url for a in msg.attachments)
            lines.append(f"[{ts}] {msg.author}: {content}")
        return "\n".join(lines)

    @app_commands.command(name="ticket_setup", description="Настроить систему тикетов")
    @app_commands.default_permissions(manage_guild=True)
    async def ticket_setup(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        staff_role: discord.Role | None = None,
        log_channel: discord.TextChannel | None = None,
        panel_channel: discord.TextChannel | None = None,
    ):
        data = self._guild(interaction.guild_id)
        data["category_id"] = category.id
        data["staff_role_id"] = staff_role.id if staff_role else None
        data["log_channel_id"] = log_channel.id if log_channel else None
        self._save(interaction.guild_id, data)

        target = panel_channel or interaction.channel
        emb = discord.Embed(
            title="🎫 Поддержка",
            description=(
                "Нажмите кнопку ниже, чтобы открыть **тикет**.\n"
                "Один открытый тикет на участника."
            ),
            color=BRAND,
        )
        await target.send(embed=emb, view=TicketOpenView(self))
        await interaction.response.send_message(
            f"✅ Тикеты настроены. Панель → {target.mention}", ephemeral=True
        )

    @app_commands.command(name="ticket_add", description="Добавить участника в тикет")
    async def ticket_add(self, interaction: discord.Interaction, member: discord.Member):
        data = self._guild(interaction.guild_id)
        if str(interaction.channel_id) not in (data.get("tickets") or {}):
            await interaction.response.send_message("❌ Не тикет", ephemeral=True)
            return
        if not self._is_staff(interaction.user, data):
            await interaction.response.send_message("❌ Staff only", ephemeral=True)
            return
        await interaction.channel.set_permissions(
            member, view_channel=True, send_messages=True, read_message_history=True
        )
        await interaction.response.send_message(f"✅ {member.mention} добавлен")

    @app_commands.command(name="ticket_close", description="Закрыть текущий тикет")
    async def ticket_close(self, interaction: discord.Interaction):
        await self._close_ticket(interaction)




async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(Tickets(bot))
    else:
        await bot.add_cog(Tickets(bot), guilds=guilds)
