"""Giveaways — порт идей iHorizon: создание, участие, розыгрыш, reroll."""
from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import JSONHandler

try:
    from utils.theme import BRAND, SUCCESS, DANGER, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    DANGER = discord.Color.red()
    GOLD = discord.Color.gold()


class GiveawayJoinView(discord.ui.View):
    def __init__(self, cog: "Giveaways", gw_id: str):
        super().__init__(timeout=None)
        self.cog = cog
        self.gw_id = gw_id

    @discord.ui.button(
        label="Участвовать",
        emoji="🎉",
        style=discord.ButtonStyle.success,
        custom_id="gw:join",
    )
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button):
        # custom_id is static; resolve gw from message id
        msg_id = str(interaction.message.id) if interaction.message else ""
        data = self.cog.db.get(str(interaction.guild_id), {})
        gws: dict = data.get("active", {})
        gw = gws.get(msg_id)
        if not gw or gw.get("ended"):
            await interaction.response.send_message("❌ Розыгрыш неактивен.", ephemeral=True)
            return
        if time.time() >= float(gw.get("ends_at", 0)):
            await interaction.response.send_message("❌ Розыгрыш уже завершён.", ephemeral=True)
            return
        uid = str(interaction.user.id)
        entries: list = gw.setdefault("entries", [])
        if uid in entries:
            entries.remove(uid)
            self.cog._save_guild(interaction.guild_id, data)
            await interaction.response.send_message(
                "🚪 Вы **вышли** из розыгрыша.", ephemeral=True
            )
        else:
            # required role
            req = gw.get("required_role_id")
            if req:
                role = interaction.guild.get_role(int(req))
                if role and role not in interaction.user.roles:
                    await interaction.response.send_message(
                        f"❌ Нужна роль {role.mention}", ephemeral=True
                    )
                    return
            entries.append(uid)
            self.cog._save_guild(interaction.guild_id, data)
            await interaction.response.send_message(
                f"✅ Вы в розыгрыше! Участников: **{len(entries)}**", ephemeral=True
            )
        # update embed count
        try:
            emb = interaction.message.embeds[0] if interaction.message.embeds else None
            if emb:
                emb.set_field_at(
                    0 if emb.fields and emb.fields[0].name == "Участники" else -1,
                    name="Участники",
                    value=str(len(entries)),
                    inline=True,
                ) if emb.fields else emb.add_field(
                    name="Участники", value=str(len(entries)), inline=True
                )
                # safer: rebuild
                new_emb = self.cog._build_embed(gw, len(entries))
                await interaction.message.edit(embed=new_emb, view=self)
        except Exception:
            pass


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/giveaways.json")
        self.bot.add_view(GiveawayJoinView(self, "persistent"))
        self._ticker.start()

    def cog_unload(self):
        self._ticker.cancel()

    def _save_guild(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def _build_embed(self, gw: dict, count: int | None = None) -> discord.Embed:
        ends = int(gw.get("ends_at", 0))
        n = count if count is not None else len(gw.get("entries") or [])
        emb = discord.Embed(
            title=f"🎉 {gw.get('prize', 'Розыгрыш')}",
            description=(
                f"**Приз:** {gw.get('prize')}\n"
                f"**Победителей:** {gw.get('winners', 1)}\n"
                f"**Окончание:** <t:{ends}:R> (<t:{ends}:f>)\n"
                f"Нажмите **Участвовать**, чтобы войти / выйти."
            ),
            color=GOLD,
            timestamp=discord.utils.utcnow(),
        )
        emb.add_field(name="Участники", value=str(n), inline=True)
        host = gw.get("host_id")
        if host:
            emb.add_field(name="Организатор", value=f"<@{host}>", inline=True)
        req = gw.get("required_role_id")
        if req:
            emb.add_field(name="Роль", value=f"<@&{req}>", inline=True)
        emb.set_footer(text=f"ID · {gw.get('message_id', '—')}")
        return emb

    async def _end_giveaway(self, guild: discord.Guild, msg_id: str, gw: dict, *, reroll: bool = False):
        data = self.db.get(str(guild.id), {})
        entries = list(gw.get("entries") or [])
        winners_n = max(1, int(gw.get("winners", 1)))
        channel = guild.get_channel(int(gw.get("channel_id", 0)))
        if not isinstance(channel, discord.TextChannel):
            gw["ended"] = True
            data.setdefault("active", {})[msg_id] = gw
            self._save_guild(guild.id, data)
            return

        if not entries:
            text = "😢 Никто не участвовал."
            winners: list[str] = []
        else:
            k = min(winners_n, len(entries))
            winners = random.sample(entries, k)
            mentions = ", ".join(f"<@{w}>" for w in winners)
            text = f"🎊 Победител{'и' if k > 1 else 'ь'}: {mentions}\n**Приз:** {gw.get('prize')}"

        gw["ended"] = True
        gw["winner_ids"] = winners
        data.setdefault("active", {})[msg_id] = gw
        # archive
        data.setdefault("ended", {})[msg_id] = gw
        self._save_guild(guild.id, data)

        emb = discord.Embed(
            title="🎉 Розыгрыш завершён" + (" (reroll)" if reroll else ""),
            description=text,
            color=SUCCESS,
        )
        try:
            msg = await channel.fetch_message(int(msg_id))
            await msg.edit(embed=emb, view=None)
        except Exception:
            await channel.send(embed=emb)
        else:
            await channel.send(content=text, embed=emb)

    @tasks.loop(seconds=20)
    async def _ticker(self):
        now = time.time()
        for key, data in list(self.db.items()):
            if not isinstance(data, dict):
                continue
            try:
                gid = int(key)
            except ValueError:
                continue
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            active = data.get("active") or {}
            changed = False
            for msg_id, gw in list(active.items()):
                if gw.get("ended"):
                    continue
                if now >= float(gw.get("ends_at", 0)):
                    await self._end_giveaway(guild, msg_id, gw)
                    changed = True
            if changed:
                self._save_guild(gid, data)

    @_ticker.before_loop
    async def _before_ticker(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="gstart", description="Запустить розыгрыш")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        duration="Длительность: 10m, 1h, 1d…",
        winners="Число победителей",
        prize="Приз",
        required_role="Опционально: роль для участия",
    )
    async def gstart(
        self,
        interaction: discord.Interaction,
        duration: str,
        prize: app_commands.Range[str, 1, 200],
        winners: app_commands.Range[int, 1, 20] = 1,
        required_role: discord.Role | None = None,
    ):
        seconds = self._parse_duration(duration)
        if seconds is None or seconds < 30:
            await interaction.response.send_message(
                "❌ Длительность: например `10m`, `1h`, `2d` (мин. 30с)", ephemeral=True
            )
            return
        ends = int(time.time() + seconds)
        gw = {
            "prize": prize,
            "winners": winners,
            "ends_at": ends,
            "host_id": interaction.user.id,
            "channel_id": interaction.channel_id,
            "entries": [],
            "ended": False,
            "required_role_id": required_role.id if required_role else None,
        }
        emb = self._build_embed(gw, 0)
        view = GiveawayJoinView(self, "new")
        await interaction.response.send_message(embed=emb, view=view)
        msg = await interaction.original_response()
        gw["message_id"] = str(msg.id)
        data = self.db.get(str(interaction.guild_id), {}) or {}
        data.setdefault("active", {})[str(msg.id)] = gw
        self._save_guild(interaction.guild_id, data)
        # re-edit footer with id
        emb.set_footer(text=f"ID · {msg.id}")
        try:
            await msg.edit(embed=emb, view=view)
        except Exception:
            pass

    @app_commands.command(name="gend", description="Досрочно завершить розыгрыш")
    @app_commands.default_permissions(manage_guild=True)
    async def gend(self, interaction: discord.Interaction, message_id: str):
        data = self.db.get(str(interaction.guild_id), {}) or {}
        gw = (data.get("active") or {}).get(message_id)
        if not gw:
            await interaction.response.send_message("❌ Розыгрыш не найден", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self._end_giveaway(interaction.guild, message_id, gw)
        await interaction.followup.send("✅ Завершён", ephemeral=True)

    @app_commands.command(name="greroll", description="Переиграть победителей")
    @app_commands.default_permissions(manage_guild=True)
    async def greroll(self, interaction: discord.Interaction, message_id: str):
        data = self.db.get(str(interaction.guild_id), {}) or {}
        gw = (data.get("ended") or {}).get(message_id) or (data.get("active") or {}).get(message_id)
        if not gw:
            await interaction.response.send_message("❌ Розыгрыш не найден", ephemeral=True)
            return
        gw["ended"] = False
        await interaction.response.defer(ephemeral=True)
        await self._end_giveaway(interaction.guild, message_id, gw, reroll=True)
        await interaction.followup.send("✅ Reroll", ephemeral=True)

    @staticmethod
    def _parse_duration(raw: str) -> int | None:
        raw = raw.strip().lower()
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        total = 0
        num = ""
        for ch in raw:
            if ch.isdigit():
                num += ch
            elif ch in units and num:
                total += int(num) * units[ch]
                num = ""
            else:
                return None
        if num:
            total += int(num) * 60  # bare number = minutes
        return total or None


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
