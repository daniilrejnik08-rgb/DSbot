import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


class TreeCraft(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tree = JSONHandler("data/trees.json")
        self.recipes = {
            "удобрение+": {"плоды": 10, "coins": 800},
            "антиболезнь": {"плоды": 15, "coins": 1200},
            "автополив": {"плоды": 30, "coins": 2500},
        }

    @app_commands.command(name="tree_craft", description="Скрафтить предметы для дерева")
    async def tree_craft(self, interaction: discord.Interaction, item: str):
        item = item.lower().strip()
        if item not in self.recipes:
            await interaction.response.send_message(f"❌ Рецепты: {', '.join(self.recipes.keys())}", ephemeral=True)
            return
        key = f"{interaction.guild.id}.{interaction.user.id}"
        tree = self.tree.get(key, {})
        eco = Wallet.get(interaction.guild.id, interaction.user.id)
        req = self.recipes[item]
        if tree.get("fruits", 0) < req["плоды"] or eco["balance"] < req["coins"]:
            await interaction.response.send_message("❌ Недостаточно ресурсов", ephemeral=True)
            return
        tree["fruits"] -= req["плоды"]
        eco["balance"] -= req["coins"]
        inv = eco.setdefault("inventory", [])
        inv.append(item)
        self.tree.set(key, tree)
        Wallet.save(interaction.guild.id, interaction.user.id, eco)
        await interaction.response.send_message(f"🛠️ Скрафчен предмет: **{item}**")

    @app_commands.command(name="tree_use_item", description="Использовать предмет дерева из инвентаря")
    async def tree_use_item(self, interaction: discord.Interaction, item: str):
        item = item.lower().strip()
        key = f"{interaction.guild.id}.{interaction.user.id}"
        tree = self.tree.get(key, {})
        eco = Wallet.get(interaction.guild.id, interaction.user.id)
        inv = eco.setdefault("inventory", [])
        if item not in inv:
            await interaction.response.send_message("❌ У вас нет этого предмета", ephemeral=True)
            return
        inv.remove(item)
        if item == "удобрение+":
            tree["xp"] = tree.get("xp", 0) + random.randint(130, 220)
            tree["fertilizer"] = tree.get("fertilizer", 0) + 1
        elif item == "антиболезнь":
            tree["disease"] = None
            tree["health"] = min(100, tree.get("health", 100) + 20)
        elif item == "автополив":
            tree["water"] = min(100, tree.get("water", 0) + 45)
        else:
            await interaction.response.send_message("❌ Неизвестный предмет", ephemeral=True)
            return
        self.tree.set(key, tree)
        Wallet.save(interaction.guild.id, interaction.user.id, eco)
        await interaction.response.send_message(f"✅ Использован предмет: **{item}**")


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(TreeCraft(bot))
    else:
        await bot.add_cog(TreeCraft(bot), guild=g)
