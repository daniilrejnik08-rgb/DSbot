import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


class Combat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tree = JSONHandler("data/trees.json")
        self.boss = JSONHandler("data/boss.json")

    def eco(self, guild_id: int, user_id: int) -> dict:
        return Wallet.get(guild_id, user_id)

    @app_commands.command(name="duel", description="Дуэль на монеты")
    async def duel(self, interaction: discord.Interaction, member: discord.Member, bet: int):
        if member.bot or member.id == interaction.user.id or bet <= 0:
            await interaction.response.send_message("❌ Неверные параметры дуэли", ephemeral=True)
            return
        gid = interaction.guild.id
        # Списываем ставки атомарно у обоих; при нехватке у второго — откат первому
        ok_a, _ = Wallet.try_remove_balance(gid, interaction.user.id, bet, ledger=("Дуэль", f"ставка vs {member.display_name}"))
        if not ok_a:
            await interaction.response.send_message("❌ У вас не хватает монет", ephemeral=True)
            return
        ok_b, _ = Wallet.try_remove_balance(gid, member.id, bet, ledger=("Дуэль", f"ставка vs {interaction.user.display_name}"))
        if not ok_b:
            Wallet.add_balance(gid, interaction.user.id, bet, ledger=("Дуэль", "возврат ставки"))
            await interaction.response.send_message("❌ У соперника не хватает монет", ephemeral=True)
            return
        winner = interaction.user if random.random() < 0.5 else member
        Wallet.add_balance(gid, winner.id, bet * 2, ledger=("Дуэль", "победа"))
        await interaction.response.send_message(f"⚔️ Победитель дуэли: {winner.mention}. Выигрыш: **{bet}** 🪙")

    @app_commands.command(name="boss_join", description="Ударить серверного босса (кооп)")
    async def boss_join(self, interaction: discord.Interaction):
        gid = str(interaction.guild.id)
        state = self.boss.get(gid, {})
        if not state:
            state = {"hp": 5000, "max_hp": 5000, "participants": {}, "level": 1}
        dmg = random.randint(70, 220)
        state["hp"] = max(0, state["hp"] - dmg)
        state["participants"][str(interaction.user.id)] = state["participants"].get(str(interaction.user.id), 0) + dmg
        if state["hp"] == 0:
            total = max(1, sum(state["participants"].values()))
            rewards = []
            for uid, dealt in state["participants"].items():
                reward = int(400 + (dealt / total) * 2600)
                Wallet.add_balance(
                    interaction.guild.id,
                    int(uid),
                    reward,
                    ledger=("Босс", f"награда · dmg {dealt}"),
                )
                t = self.tree.get(f"{interaction.guild.id}.{uid}", {})
                if t:
                    t["xp"] = t.get("xp", 0) + reward // 20
                    self.tree.set(f"{interaction.guild.id}.{uid}", t)
                rewards.append((uid, reward))
            state["level"] += 1
            state["max_hp"] = int(state["max_hp"] * 1.25)
            state["hp"] = state["max_hp"]
            state["participants"] = {}
            self.boss.set(gid, state)
            top = ", ".join([f"<@{uid}> +{r}🪙" for uid, r in rewards[:5]])
            await interaction.response.send_message(f"🐉 Босс повержен! Награды: {top}")
            return
        self.boss.set(gid, state)
        await interaction.response.send_message(f"🗡️ Вы нанесли {dmg} урона. HP босса: {state['hp']}/{state['max_hp']}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Combat(bot))
