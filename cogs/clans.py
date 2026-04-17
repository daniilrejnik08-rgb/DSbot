from datetime import datetime
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


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
        await interaction.response.send_message(f"🛡️ Клан **{name}** создан")

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
        await interaction.response.send_message(f"✅ Вы вступили в клан **{clans[clan_id]['name']}**")

    @app_commands.command(name="clan_info", description="Информация о вашем клане")
    async def clan_info(self, interaction: discord.Interaction):
        clan_id, clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        embed = discord.Embed(title=f"🛡️ {clan['name']}", color=discord.Color.dark_blue())
        embed.add_field(name="ID", value=clan_id, inline=True)
        embed.add_field(name="Участники", value=str(len(clan["members"])), inline=True)
        embed.add_field(name="Банк", value=f"{clan['bank']} 🪙", inline=True)
        embed.add_field(name="Очки", value=str(clan["points"]), inline=True)
        embed.add_field(name="Победы в войнах", value=str(clan["war_wins"]), inline=True)
        embed.add_field(name="Квест", value=f"{clan['quest_progress']}/{clan['quest_target']}", inline=True)
        await interaction.response.send_message(embed=embed)

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
        clans = self.get_clans(interaction.guild.id)
        clans[clan_id] = clan
        self.save_clans(interaction.guild.id, clans)
        await interaction.response.send_message(f"🏦 В банк клана внесено **{amount}** 🪙")

    @app_commands.command(name="clan_quest_claim", description="Получить награду за клановый квест")
    async def clan_quest_claim(self, interaction: discord.Interaction):
        clan_id, clan = self.user_clan(interaction.guild.id, interaction.user.id)
        if not clan:
            await interaction.response.send_message("❌ Вы не в клане", ephemeral=True)
            return
        if clan["quest_progress"] < clan["quest_target"]:
            await interaction.response.send_message("❌ Квест еще не выполнен", ephemeral=True)
            return
        reward = random.randint(2500, 6500)
        clan["bank"] += reward
        clan["points"] += reward // 25
        clan["quest_progress"] = 0
        clan["quest_target"] = random.randint(6, 15)
        clans = self.get_clans(interaction.guild.id)
        clans[clan_id] = clan
        self.save_clans(interaction.guild.id, clans)
        await interaction.response.send_message(f"🎁 Клан получил награду: **{reward}** 🪙 в банк")

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
        my_power = my_clan["points"] + random.randint(100, 600)
        enemy_power = enemy["points"] + random.randint(100, 600)
        prize = random.randint(1000, 3500)
        if my_power >= enemy_power:
            my_clan["war_wins"] += 1
            my_clan["bank"] += prize
            result = f"🏆 Победа клана **{my_clan['name']}**! +{prize} 🪙 в банк"
        else:
            enemy["war_wins"] += 1
            enemy["bank"] += prize
            result = f"💥 Поражение. Победил клан **{enemy['name']}**"
        clans[my_id] = my_clan
        clans[enemy_clan_id] = enemy
        self.save_clans(interaction.guild.id, clans)
        await interaction.response.send_message(result)

    @app_commands.command(name="clan_top", description="Топ кланов сервера")
    async def clan_top(self, interaction: discord.Interaction):
        clans = self.get_clans(interaction.guild.id)
        rows = []
        for cid, clan in clans.items():
            score = clan.get("points", 0) + clan.get("war_wins", 0) * 500 + clan.get("bank", 0) // 20
            rows.append((cid, clan["name"], score))
        rows.sort(key=lambda x: x[2], reverse=True)
        lines = [f"{i}. **{name}** — {score} очков (ID: `{cid}`)" for i, (cid, name, score) in enumerate(rows[:10], 1)]
        text = "\n".join(lines) if lines else "Кланов пока нет."
        await interaction.response.send_message(embed=discord.Embed(title="🏅 Топ кланов", description=text))


async def setup(bot: commands.Bot):
    await bot.add_cog(Clans(bot))
