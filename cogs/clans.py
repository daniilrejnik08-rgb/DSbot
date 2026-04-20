from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet

try:
    from utils.theme import BRAND, GOLD, SUCCESS
except Exception:
    BRAND = discord.Color.from_rgb(88, 101, 242)
    GOLD = discord.Color.gold()
    SUCCESS = discord.Color.green()


def _clan_power(clan: dict[str, Any]) -> int:
    return int(clan.get("points", 0)) + int(clan.get("war_wins", 0)) * 500 + int(clan.get("bank", 0)) // 20


def _clan_embed(
    guild: discord.Guild,
    clan_id: str,
    clan: dict[str, Any],
    *,
    subtitle: str | None = None,
) -> discord.Embed:
    members = clan.get("members", [])
    lines: list[str] = []
    for uid in members[:18]:
        m = guild.get_member(int(uid))
        lines.append(m.mention if m else f"<@{uid}>")
    rest = len(members) - 18
    body = "\n".join(lines) if lines else "—"
    if rest > 0:
        body += f"\n*и ещё {rest}…*"

    emb = discord.Embed(
        title=f"🛡️ {clan.get('name', 'Клан')}",
        description=subtitle or f"**ID клана:** `{clan_id}`",
        color=BRAND,
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        emb.set_thumbnail(url=guild.icon.url)
    emb.add_field(name="⚔️ Сила клана", value=f"**{_clan_power(clan):,}** очков", inline=True)
    emb.add_field(name="👥 Участники", value=f"**{len(members)}**", inline=True)
    emb.add_field(name="🏆 Побед в войнах", value=f"**{clan.get('war_wins', 0)}**", inline=True)
    emb.add_field(
        name="🏦 Банк клана",
        value=f"**{int(clan.get('bank', 0)):,}** 🪙",
        inline=True,
    )
    emb.add_field(name="✨ Очки", value=f"**{int(clan.get('points', 0)):,}**", inline=True)
    tgt = int(clan.get("quest_target", 1))
    prg = int(clan.get("quest_progress", 0))
    bar_w = 14
    filled = int(bar_w * prg / max(tgt, 1))
    bar = "█" * filled + "░" * (bar_w - filled)
    emb.add_field(
        name="🎯 Клановый квест",
        value=f"`{bar}` **{prg}/{tgt}**",
        inline=False,
    )
    emb.add_field(name="Состав", value=body[:1020] or "—", inline=False)
    created = clan.get("created_at")
    if created:
        emb.set_footer(text=f"Создан · {str(created)[:10]}")
    return emb


class ClanRefreshView(discord.ui.View):
    """Кнопка обновления сообщения с карточкой клана."""

    def __init__(self, cog: "Clans", clan_id: str):
        super().__init__(timeout=600)
        self.cog = cog
        self.clan_id = clan_id

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.primary, emoji="🔃", row=0)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button):
        clans = self.cog.get_clans(interaction.guild.id)
        clan = clans.get(self.clan_id)
        if not clan:
            await interaction.response.send_message("❌ Клан удалён или не найден.", ephemeral=True)
            return
        emb = _clan_embed(interaction.guild, self.clan_id, clan)
        await interaction.response.edit_message(embed=emb, view=self)


class Clans(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/clans.json")

    def get_clans(self, guild_id: int) -> dict:
        key = str(guild_id)
        clans = self.db.get(key, {})
        if not clans:
            self.db.set(key, {})
        return self.db.get(key, {})

    def save_clans(self, guild_id: int, clans: dict):
        self.db.set(str(guild_id), clans)

    def user_clan(self, guild_id: int, user_id: int):
        clans = self.get_clans(guild_id)
        for clan_id, clan in clans.items():
            if user_id in clan.get("members", []):
                return clan_id, clan
        return None, None

    @app_commands.command(name="clan_create", description="Создать клан")
    @app_commands.describe(name="Название (2–30 символов)")
    async def clan_create(self, interaction: discord.Interaction, name: app_commands.Range[str, 2, 30]):
        clans = self.get_clans(interaction.guild.id)
        _, exists = self.user_clan(interaction.guild.id, interaction.user.id)
        if exists:
            await interaction.response.send_message("❌ Вы уже состоите в клане", ephemeral=True)
            return
        clan_id = str(max([int(k) for k in clans.keys()], default=0) + 1)
        clans[clan_id] = {
            "name": name,
            "owner": interaction.user.id,
            "members": [interaction.user.id],
            "bank": 0,
            "points": 0,
            "quest_progress": 0,
            "quest_target": random.randint(5, 12),
            "war_wins": 0,
            "created_at": datetime.now().isoformat(),
        }
        self.save_clans(interaction.guild.id, clans)
        emb = discord.Embed(
            title="🛡️ Клан создан",
            description=f"**{name}** · ID `{clan_id}`\nДрузья могут вступить: `/clan_join {clan_id}`",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="clan_join", description="Вступить в клан по ID")
    async def clan_join(self, interaction: discord.Interaction, clan_id: str):
        clans = self.get_clans(interaction.guild.id)
        if clan_id not in clans:
            await interaction.response.send_message("❌ Клан не найден", ephemeral=True)
            return
        if self.user_clan(interaction.guild.id, interaction.user.id)[0]:
            await interaction.response.send_message("❌ Вы уже в клане", ephemeral=True)
            return
        clans[clan_id]["members"].append(interaction.user.id)
        self.save_clans(interaction.guild.id, clans)
        emb = discord.Embed(
            title="✅ Вступление",
            description=f"Вы в клане **{clans[clan_id]['name']}**",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="clan_info", description="Большая карточка вашего клана")
    async def clan_info(self, interaction: discord.Interaction):
        clan_id, clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        emb = _clan_embed(interaction.guild, clan_id, clan, subtitle="Главная панель клана")
        view = ClanRefreshView(self, clan_id)
        await interaction.response.send_message(embed=emb, view=view)

    @app_commands.command(name="clan_show", description="Посмотреть клан по ID (рекрутинг)")
    async def clan_show(self, interaction: discord.Interaction, clan_id: str):
        clans = self.get_clans(interaction.guild.id)
        if clan_id not in clans:
            await interaction.response.send_message("❌ Клан не найден.", ephemeral=True)
            return
        clan = clans[clan_id]
        emb = _clan_embed(interaction.guild, clan_id, clan, subtitle="Публичная карточка")
        await interaction.response.send_message(embed=emb, view=ClanRefreshView(self, clan_id))

    @app_commands.command(name="clan_bank_deposit", description="Пожертвовать в банк клана")
    async def clan_bank_deposit(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            await interaction.response.send_message("❌ Сумма должна быть > 0", ephemeral=True)
            return
        clan_id, clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        eco = Wallet.get(interaction.guild.id, interaction.user.id)
        if eco["balance"] < amount:
            await interaction.response.send_message("❌ Недостаточно средств", ephemeral=True)
            return
        eco["balance"] -= amount
        clan["bank"] += amount
        clan["points"] += amount // 20
        clan["quest_progress"] += 1
        Wallet.save(interaction.guild.id, interaction.user.id, eco)
        Wallet.log_ledger(interaction.guild.id, interaction.user.id, -amount, "Клан", f"в банк {clan['name']}")
        clans = self.get_clans(interaction.guild.id)
        clans[clan_id] = clan
        self.save_clans(interaction.guild.id, clans)
        emb = discord.Embed(
            title="🏦 Взнос",
            description=f"**+{amount:,}** 🪙 в банк **{clan['name']}**\nПрогресс квеста: **{clan['quest_progress']}/{clan['quest_target']}**",
            color=GOLD,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="clan_quest_claim", description="Получить награду за клановый квест")
    async def clan_quest_claim(self, interaction: discord.Interaction):
        clan_id, clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        if clan["quest_progress"] < clan["quest_target"]:
            await interaction.response.send_message(
                f"❌ Квест ещё не выполнен (**{clan['quest_progress']}/{clan['quest_target']}**)",
                ephemeral=True,
            )
            return
        reward = random.randint(2500, 6500)
        clan["bank"] += reward
        clan["points"] += reward // 25
        clan["quest_progress"] = 0
        clan["quest_target"] = random.randint(6, 15)
        clans = self.get_clans(interaction.guild.id)
        clans[clan_id] = clan
        self.save_clans(interaction.guild.id, clans)
        emb = discord.Embed(
            title="🎁 Клановый квест",
            description=f"В банк начислено **{reward:,}** 🪙\nНовая цель квеста: **{clan['quest_target']}** действий.",
            color=SUCCESS,
        )
        await interaction.response.send_message(embed=emb)

    @app_commands.command(name="clan_war", description="Клановая война с другим кланом")
    async def clan_war(self, interaction: discord.Interaction, enemy_clan_id: str):
        my_id, my_clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not my_clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        clans = self.get_clans(interaction.guild.id)
        if enemy_clan_id not in clans or enemy_clan_id == my_id:
            await interaction.response.send_message("❌ Неверный ID клана противника", ephemeral=True)
            return
        enemy = clans[enemy_clan_id]
        my_power = _clan_power(my_clan) + random.randint(100, 900)
        enemy_power = _clan_power(enemy) + random.randint(100, 900)
        prize = random.randint(1500, 4500)
        if my_power >= enemy_power:
            my_clan["war_wins"] = int(my_clan.get("war_wins", 0)) + 1
            my_clan["bank"] = int(my_clan.get("bank", 0)) + prize
            my_clan["points"] = int(my_clan.get("points", 0)) + prize // 30
            result = discord.Embed(
                title="🏆 Победа в клановой войне",
                description=(
                    f"**{my_clan['name']}** одержал верх над **{enemy['name']}**\n"
                    f"Сила: **{my_power}** vs **{enemy_power}**\n"
                    f"Приз в банк: **{prize:,}** 🪙"
                ),
                color=SUCCESS,
            )
        else:
            enemy["war_wins"] = int(enemy.get("war_wins", 0)) + 1
            enemy["bank"] = int(enemy.get("bank", 0)) + prize
            result = discord.Embed(
                title="💥 Поражение",
                description=(
                    f"**{enemy['name']}** сильнее в этом раунде.\n"
                    f"Сила: **{my_power}** vs **{enemy_power}**\n"
                    f"Приз достался врагу: **{prize:,}** 🪙"
                ),
                color=discord.Color.dark_red(),
            )
        clans[my_id] = my_clan
        clans[enemy_clan_id] = enemy
        self.save_clans(interaction.guild.id, clans)
        await interaction.response.send_message(embed=result)

    @app_commands.command(name="clan_top", description="Топ кланов сервера (расширенный)")
    async def clan_top(self, interaction: discord.Interaction):
        clans = self.get_clans(interaction.guild.id)
        rows: list[tuple[str, str, int, int, int]] = []
        for cid, clan in clans.items():
            pwr = _clan_power(clan)
            rows.append((cid, clan.get("name", "?"), pwr, len(clan.get("members", [])), int(clan.get("bank", 0))))
        rows.sort(key=lambda x: x[2], reverse=True)
        lines = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, (cid, name, pwr, nmem, bank) in enumerate(rows[:12]):
            pre = medals[i] if i < len(medals) else f"{i + 1}."
            lines.append(f"{pre} **{name}** · `{cid}`\n　сила **{pwr:,}** · 👥 {nmem} · 🏦 {bank:,} 🪙")
        emb = discord.Embed(
            title="🏅 Рейтинг кланов сервера",
            description="\n\n".join(lines) if lines else "Кланов пока нет.",
            color=GOLD,
        )
        emb.set_footer(text="/clan_show ID — публичная карточка · /clan_join ID")
        await interaction.response.send_message(embed=emb)


async def setup(bot: commands.Bot):
    await bot.add_cog(Clans(bot))
