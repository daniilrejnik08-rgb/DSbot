from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet


class Market(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = JSONHandler("data/market.json")
        self.trees = JSONHandler("data/trees.json")
        self.audit = JSONHandler("data/audit.json")
        self.fee_percent = 6

    def eco(self, guild_id: int, user_id: int) -> dict:
        return Wallet.get(guild_id, user_id)

    def market(self, guild_id: int) -> dict:
        key = str(guild_id)
        m = self.db.get(key, {})
        if not m:
            m = {"listings": {}, "history": [], "next_id": 1}
            self.db.set(key, m)
        return m

    @app_commands.command(name="market_sell", description="Выставить предмет/плоды на рынок")
    async def market_sell(self, interaction: discord.Interaction, item: str, amount: int, price_each: int):
        if amount <= 0 or price_each <= 0:
            await interaction.response.send_message("❌ Неверные параметры", ephemeral=True)
            return
        item = item.lower().strip()
        eco = self.eco(interaction.guild.id, interaction.user.id)
        trees = self.trees.get(f"{interaction.guild.id}.{interaction.user.id}", {})
        if item == "плоды":
            if trees.get("fruits", 0) < amount:
                await interaction.response.send_message("❌ Недостаточно плодов", ephemeral=True)
                return
            trees["fruits"] -= amount
            self.trees.set(f"{interaction.guild.id}.{interaction.user.id}", trees)
        else:
            inv = eco.setdefault("inventory", [])
            if inv.count(item) < amount:
                await interaction.response.send_message("❌ Недостаточно предметов", ephemeral=True)
                return
            removed = 0
            new_inv = []
            for x in inv:
                if x == item and removed < amount:
                    removed += 1
                else:
                    new_inv.append(x)
            eco["inventory"] = new_inv
            Wallet.save(interaction.guild.id, interaction.user.id, eco)

        market = self.market(interaction.guild.id)
        lid = str(market["next_id"])
        market["next_id"] += 1
        market["listings"][lid] = {
            "seller": interaction.user.id,
            "item": item,
            "amount": amount,
            "price_each": price_each,
            "created_at": datetime.now().isoformat(),
        }
        self.db.set(str(interaction.guild.id), market)
        await interaction.response.send_message(f"🛒 Лот #{lid} выставлен: {item} x{amount} за {price_each} 🪙/шт")

    @app_commands.command(name="market_list", description="Список лотов рынка")
    async def market_list(self, interaction: discord.Interaction):
        market = self.market(interaction.guild.id)
        listings = market["listings"]
        if not listings:
            await interaction.response.send_message("📭 Рынок пуст")
            return
        lines = []
        for lid, l in list(listings.items())[:15]:
            total = l["amount"] * l["price_each"]
            lines.append(f"#{lid} • {l['item']} x{l['amount']} • {total} 🪙 • продавец <@{l['seller']}>")
        await interaction.response.send_message(embed=discord.Embed(title="🏪 Рынок", description="\n".join(lines)))

    @app_commands.command(name="market_buy", description="Купить лот по ID")
    async def market_buy(self, interaction: discord.Interaction, listing_id: str):
        market = self.market(interaction.guild.id)
        listing = market["listings"].get(listing_id)
        if not listing:
            await interaction.response.send_message("❌ Лот не найден", ephemeral=True)
            return
        if listing["seller"] == interaction.user.id:
            await interaction.response.send_message("❌ Нельзя купить свой лот", ephemeral=True)
            return
        total = listing["amount"] * listing["price_each"]
        buyer = self.eco(interaction.guild.id, interaction.user.id)
        if buyer["balance"] < total:
            await interaction.response.send_message("❌ Недостаточно средств", ephemeral=True)
            return
        fee = max(1, total * self.fee_percent // 100)
        seller_get = total - fee
        seller = self.eco(interaction.guild.id, listing["seller"])
        buyer["balance"] -= total
        seller["balance"] += seller_get
        if listing["item"] == "плоды":
            tree = self.trees.get(f"{interaction.guild.id}.{interaction.user.id}", {})
            if tree:
                tree["fruits"] = tree.get("fruits", 0) + listing["amount"]
                self.trees.set(f"{interaction.guild.id}.{interaction.user.id}", tree)
        else:
            buyer.setdefault("inventory", []).extend([listing["item"]] * listing["amount"])
        Wallet.save(interaction.guild.id, interaction.user.id, buyer)
        Wallet.save(interaction.guild.id, listing["seller"], seller)
        market["history"].append(
            {"item": listing["item"], "amount": listing["amount"], "price_each": listing["price_each"], "at": datetime.now().isoformat()}
        )
        market["listings"].pop(listing_id, None)
        self.db.set(str(interaction.guild.id), market)
        self.audit.set(f"{interaction.guild.id}.market.{datetime.now().timestamp()}", {"buyer": interaction.user.id, "seller": listing["seller"], "total": total, "fee": fee})
        await interaction.response.send_message(f"✅ Лот куплен. Комиссия сервера: {fee} 🪙")

    @app_commands.command(name="market_history", description="История цен на предмет")
    async def market_history(self, interaction: discord.Interaction, item: str):
        market = self.market(interaction.guild.id)
        item = item.lower().strip()
        rows = [h for h in market["history"] if h["item"] == item][-10:]
        if not rows:
            await interaction.response.send_message("📉 История пуста", ephemeral=True)
            return
        lines = [f"{r['amount']} шт по {r['price_each']} 🪙" for r in rows]
        await interaction.response.send_message(embed=discord.Embed(title=f"История: {item}", description="\n".join(lines)))


async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
