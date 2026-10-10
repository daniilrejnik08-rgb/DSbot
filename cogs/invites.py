"""Invite tracking — порт iHorizon: учёт инвайтов, лидерборд, join attribution."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler

try:
    from utils.theme import BRAND, SUCCESS, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    GOLD = discord.Color.gold()


class Invites(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/invites.json")
        # guild_id -> code -> uses
        self._cache: dict[int, dict[str, int]] = {}

    def _g(self, guild_id: int) -> dict:
        data = self.db.get(str(guild_id), {}) or {}
        data.setdefault("inviters", {})  # user_id -> {joins, leaves, fake, bonus}
        data.setdefault("joins", {})  # member_id -> inviter_id
        data.setdefault("log_channel_id", None)
        return data

    def _save(self, guild_id: int, data: dict):
        self.db.set(str(guild_id), data)

    def _ensure_inviter(self, data: dict, uid: str) -> dict:
        inv = data.setdefault("inviters", {}).setdefault(
            uid, {"joins": 0, "leaves": 0, "fake": 0, "bonus": 0}
        )
        for k in ("joins", "leaves", "fake", "bonus"):
            inv.setdefault(k, 0)
        return inv

    def _score(self, inv: dict) -> int:
        return int(inv.get("joins", 0)) + int(inv.get("bonus", 0)) - int(inv.get("leaves", 0)) - int(
            inv.get("fake", 0)
        )

    async def _refresh_cache(self, guild: discord.Guild):
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            self._cache[guild.id] = {}
            return
        self._cache[guild.id] = {i.code: i.uses or 0 for i in invites}

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            await self._refresh_cache(g)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            cache = self._cache.setdefault(invite.guild.id, {})
            cache[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        if invite.guild:
            self._cache.get(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        before = dict(self._cache.get(guild.id, {}))
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            return
        after = {i.code: i.uses or 0 for i in invites}
        self._cache[guild.id] = after

        used_code = None
        inviter: discord.Member | None = None
        for inv in invites:
            prev = before.get(inv.code, 0)
            if (inv.uses or 0) > prev:
                used_code = inv.code
                if inv.inviter:
                    inviter = guild.get_member(inv.inviter.id) or inv.inviter
                break

        data = self._g(guild.id)
        if inviter and not getattr(inviter, "bot", False):
            row = self._ensure_inviter(data, str(inviter.id))
            # fake if account very new (< 1 day)
            age = (discord.utils.utcnow() - member.created_at).total_seconds()
            if age < 86400:
                row["fake"] = int(row.get("fake", 0)) + 1
                kind = "fake"
            else:
                row["joins"] = int(row.get("joins", 0)) + 1
                kind = "join"
            data.setdefault("joins", {})[str(member.id)] = inviter.id
            self._save(guild.id, data)
        else:
            kind = "unknown"
            inviter = None

        log_id = data.get("log_channel_id")
        if log_id:
            ch = guild.get_channel(int(log_id))
            if isinstance(ch, discord.TextChannel):
                if inviter:
                    emb = discord.Embed(
                        title="📥 Новый участник",
                        description=(
                            f"{member.mention} (`{member.id}`)\n"
                            f"Пригласил: {inviter.mention}\n"
                            f"Код: `{used_code or '—'}` · тип: **{kind}**\n"
                            f"Счёт пригласившего: **{self._score(self._ensure_inviter(data, str(inviter.id)))}**"
                        ),
                        color=SUCCESS,
                    )
                else:
                    emb = discord.Embed(
                        title="📥 Новый участник",
                        description=f"{member.mention} — инвайт не определён (vanity/виджет)",
                        color=BRAND,
                    )
                try:
                    await ch.send(embed=emb)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        data = self._g(member.guild.id)
        inviter_id = (data.get("joins") or {}).get(str(member.id))
        if not inviter_id:
            return
        row = self._ensure_inviter(data, str(inviter_id))
        row["leaves"] = int(row.get("leaves", 0)) + 1
        self._save(member.guild.id, data)

    @app_commands.command(name="invites", description="Показать инвайты участника")
    async def invites_cmd(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        member = member or interaction.user
        data = self._g(interaction.guild_id)
        row = self._ensure_inviter(data, str(member.id))
        emb = discord.Embed(
            title=f"📨 Инвайты — {member.display_name}",
            color=BRAND,
        )
        emb.add_field(name="Joins", value=str(row.get("joins", 0)), inline=True)
        emb.add_field(name="Leaves", value=str(row.get("leaves", 0)), inline=True)
        emb.add_field(name="Fake", value=str(row.get("fake", 0)), inline=True)
        emb.add_field(name="Bonus", value=str(row.get("bonus", 0)), inline=True)
        emb.add_field(name="Итого", value=f"**{self._score(row)}**", inline=True)
        emb.set_thumbnail(url=member.display_avatar.url)
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="invite_leaderboard", description="Топ пригласивших")
    async def invite_lb(self, interaction: discord.Interaction):
        data = self._g(interaction.guild_id)
        rows = []
        for uid, inv in (data.get("inviters") or {}).items():
            rows.append((uid, self._score(inv)))
        rows.sort(key=lambda x: x[1], reverse=True)
        lines = []
        for i, (uid, score) in enumerate(rows[:15], 1):
            lines.append(f"**{i}.** <@{uid}> — `{score}`")
        emb = discord.Embed(
            title="🏆 Топ инвайтов",
            description="\n".join(lines) or "Пока пусто",
            color=GOLD,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="invite_add", description="Начислить бонусные инвайты")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1000],
    ):
        data = self._g(interaction.guild_id)
        row = self._ensure_inviter(data, str(member.id))
        row["bonus"] = int(row.get("bonus", 0)) + amount
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"✅ {member.mention}: bonus +{amount} (итого {self._score(row)})"
        )

    @app_commands.command(name="invite_remove", description="Снять бонусные инвайты")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1, 1000],
    ):
        data = self._g(interaction.guild_id)
        row = self._ensure_inviter(data, str(member.id))
        row["bonus"] = max(0, int(row.get("bonus", 0)) - amount)
        self._save(interaction.guild_id, data)
        await interaction.response.send_message(
            f"✅ {member.mention}: bonus −{amount} (итого {self._score(row)})"
        )

    @app_commands.command(name="invite_setup", description="Канал логов инвайтов")
    @app_commands.default_permissions(manage_guild=True)
    async def invite_setup(
        self, interaction: discord.Interaction, log_channel: discord.TextChannel
    ):
        data = self._g(interaction.guild_id)
        data["log_channel_id"] = log_channel.id
        self._save(interaction.guild_id, data)
        await self._refresh_cache(interaction.guild)
        await interaction.response.send_message(
            f"✅ Логи инвайтов → {log_channel.mention}", ephemeral=True
        )


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(Invites(bot))
    else:
        await bot.add_cog(Invites(bot), guilds=guilds)
