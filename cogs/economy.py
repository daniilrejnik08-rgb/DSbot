import random
import time
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet

try:
    from utils.theme import BRAND, GOLD
except Exception:
    BRAND = discord.Color.blurple()
    GOLD = discord.Color.gold()


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.audit = JSONHandler("data/audit.json")
        self.cooldowns: dict[int, float] = {}
        self.pay_limits: dict[int, list[float]] = {}
        self.shop_items = {
            "удобрение": 1200,
            "лейка": 900,
            "лопата": 1700,
            "суперсемя": 2500,
            "VIP-карта": 5000,
        }

    def get_user_data(self, guild_id: int, user_id: int) -> dict:
        return Wallet.get(guild_id, user_id)

    def save_user_data(self, guild_id: int, user_id: int, data: dict):
        Wallet.save(guild_id, user_id, data)

    @app_commands.command(name="balance", description="Проверить баланс")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        data = self.get_user_data(interaction.guild.id, member.id)

        embed = discord.Embed(title=f"💰 Баланс {member.display_name}", color=GOLD)
        embed.add_field(name="💵 Наличные", value=f'{data["balance"]:,} 🪙', inline=True)
        embed.add_field(name="🏦 Банк", value=f'{data["bank"]:,} 🪙', inline=True)
        embed.add_field(name="💎 Всего", value=f'{data["balance"] + data["bank"]:,} 🪙', inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Получить ежедневный бонус")
    async def daily(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data["last_daily"]:
            last = datetime.fromisoformat(data["last_daily"])
            if datetime.now() - last < timedelta(hours=24):
                remaining = timedelta(hours=24) - (datetime.now() - last)
                await interaction.response.send_message(
                    f"⏰ Следующий бонус через {remaining.seconds // 3600}ч {(remaining.seconds % 3600) // 60}мин",
                    ephemeral=True,
                )
                return

        bonus = random.randint(900, 2600)
        data["balance"] += bonus
        data["last_daily"] = datetime.now().isoformat()
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        await interaction.response.send_message(f"🎁 Ежедневный бонус: **{bonus}** 🪙")

    @app_commands.command(name="work", description="Заработать деньги работой")
    async def work(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data["last_work"]:
            last = datetime.fromisoformat(data["last_work"])
            if datetime.now() - last < timedelta(minutes=35):
                remaining = timedelta(minutes=35) - (datetime.now() - last)
                await interaction.response.send_message(
                    f"⏰ Вы устали, вернитесь через {remaining.seconds // 60} мин", ephemeral=True
                )
                return

        jobs = [("Программист", 220, 780), ("Бариста", 120, 450), ("Таксист", 160, 530), ("Дизайнер", 180, 610)]
        job, low, high = random.choice(jobs)
        salary = random.randint(low, high)
        if random.random() < 0.12:
            salary *= 2
            text = f"💼 Работа: **{job}**\n🎉 Премия! Вы получили **{salary}** 🪙"
        else:
            text = f"💼 Работа: **{job}**\nВы получили **{salary}** 🪙"

        data["balance"] += salary
        data["last_work"] = datetime.now().isoformat()
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        await interaction.response.send_message(text)

    @app_commands.command(name="pay", description="Перевести деньги пользователю")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if member.id == interaction.user.id or amount <= 0:
            await interaction.response.send_message("❌ Неверные данные перевода", ephemeral=True)
            return
        # Лимит: не больше 6 переводов в 10 минут.
        now = time.time()
        history = [t for t in self.pay_limits.get(interaction.user.id, []) if now - t < 600]
        if len(history) >= 6:
            await interaction.response.send_message("🚫 Лимит переводов: подождите несколько минут", ephemeral=True)
            return
        sender = self.get_user_data(interaction.guild.id, interaction.user.id)
        if sender["balance"] < amount:
            await interaction.response.send_message("❌ Недостаточно средств", ephemeral=True)
            return

        receiver = self.get_user_data(interaction.guild.id, member.id)
        tax = max(1, amount * 3 // 100)
        transfer = amount - tax
        sender["balance"] -= amount
        receiver["balance"] += transfer
        if amount >= 50000:
            sender["suspicion"] = sender.get("suspicion", 0) + 1
        history.append(now)
        self.pay_limits[interaction.user.id] = history
        self.save_user_data(interaction.guild.id, interaction.user.id, sender)
        self.save_user_data(interaction.guild.id, member.id, receiver)
        self.audit.set(
            f"{interaction.guild.id}.pay.{now}",
            {
                "from": interaction.user.id,
                "to": member.id,
                "amount": amount,
                "tax": tax,
                "net": transfer,
            },
        )
        await interaction.response.send_message(
            f"💸 Перевод выполнен: {member.mention} получил **{transfer}** 🪙 (налог {tax} 🪙)"
        )

    @app_commands.command(name="deposit", description="Положить деньги в банк")
    async def deposit(self, interaction: discord.Interaction, amount: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if amount <= 0 or data["balance"] < amount:
            await interaction.response.send_message("❌ Недостаточно наличных", ephemeral=True)
            return
        data["balance"] -= amount
        data["bank"] += amount
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        await interaction.response.send_message(f"🏦 В банк зачислено **{amount}** 🪙")

    @app_commands.command(name="withdraw", description="Снять деньги из банка")
    async def withdraw(self, interaction: discord.Interaction, amount: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if amount <= 0 or data["bank"] < amount:
            await interaction.response.send_message("❌ Недостаточно средств на счете", ephemeral=True)
            return
        data["bank"] -= amount
        data["balance"] += amount
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        await interaction.response.send_message(f"💵 Снято из банка: **{amount}** 🪙")

    @app_commands.command(name="rob", description="Попытаться ограбить пользователя")
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ Нельзя ограбить себя", ephemeral=True)
            return
        now = time.time()
        last = self.cooldowns.get(interaction.user.id, 0)
        if now - last < 3600:
            remain = int((3600 - (now - last)) // 60)
            await interaction.response.send_message(f"⏰ Ограбление снова будет через {remain} мин", ephemeral=True)
            return

        robber = self.get_user_data(interaction.guild.id, interaction.user.id)
        victim = self.get_user_data(interaction.guild.id, member.id)
        if victim["balance"] < 200:
            await interaction.response.send_message("❌ У цели слишком мало наличных", ephemeral=True)
            return
        self.cooldowns[interaction.user.id] = now
        if random.random() < 0.45:
            stolen = min(random.randint(120, 450), victim["balance"])
            victim["balance"] -= stolen
            robber["balance"] += stolen
            self.save_user_data(interaction.guild.id, member.id, victim)
            self.save_user_data(interaction.guild.id, interaction.user.id, robber)
            await interaction.response.send_message(f"🕶️ Успех! Вы украли **{stolen}** 🪙 у {member.mention}")
        else:
            fine = min(random.randint(180, 520), robber["balance"])
            robber["balance"] -= fine
            self.save_user_data(interaction.guild.id, interaction.user.id, robber)
            await interaction.response.send_message(f"🚔 Провал! Штраф: **{fine}** 🪙")

    @app_commands.command(name="leaderboard", description="Топ богатейших игроков сервера")
    async def leaderboard(self, interaction: discord.Interaction):
        rating = Wallet.guild_leaderboard(interaction.guild.id, 10)

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (user_id, total) in enumerate(rating, start=1):
            user = interaction.guild.get_member(user_id)
            name = user.display_name if user else f"Пользователь {user_id}"
            prefix = medals[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{prefix} **{name}** — {total:,} 🪙")
        description = "\n".join(lines) if lines else "Пока данных нет."
        embed = discord.Embed(title="🏆 Лидерборд экономики", description=description, color=GOLD)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop", description="Открыть магазин")
    async def shop(self, interaction: discord.Interaction):
        lines = [f"**{name}** — {price:,} 🪙" for name, price in self.shop_items.items()]
        embed = discord.Embed(title="🛒 Магазин", description="\n".join(lines), color=BRAND)
        embed.set_footer(text="Покупка: /buy item amount")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Купить предмет")
    async def buy(self, interaction: discord.Interaction, item: str, amount: int = 1):
        if amount <= 0:
            await interaction.response.send_message("❌ Количество должно быть положительным", ephemeral=True)
            return
        item_name = item.strip()
        if item_name not in self.shop_items:
            await interaction.response.send_message("❌ Такого предмета нет в магазине", ephemeral=True)
            return
        total = self.shop_items[item_name] * amount
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data["balance"] < total:
            await interaction.response.send_message("❌ Недостаточно средств", ephemeral=True)
            return
        data["balance"] -= total
        inventory = data.setdefault("inventory", [])
        inventory.extend([item_name] * amount)
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        await interaction.response.send_message(f"✅ Куплено: **{item_name} x{amount}** за **{total}** 🪙")

    @app_commands.command(name="inventory", description="Посмотреть инвентарь")
    async def inventory(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        data = self.get_user_data(interaction.guild.id, member.id)
        inventory = data.get("inventory", [])
        if not inventory:
            await interaction.response.send_message("🎒 Инвентарь пуст")
            return
        counts: dict[str, int] = {}
        for name in inventory:
            counts[name] = counts.get(name, 0) + 1
        lines = [f"• {name}: x{count}" for name, count in sorted(counts.items())]
        embed = discord.Embed(title=f"🎒 Инвентарь {member.display_name}", description="\n".join(lines))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="audit_risk", description="Показать риск-профиль экономики пользователя")
    @app_commands.default_permissions(administrator=True)
    async def audit_risk(self, interaction: discord.Interaction, member: discord.Member):
        data = self.get_user_data(interaction.guild.id, member.id)
        risk = data.get("suspicion", 0)
        level = "низкий" if risk < 3 else "средний" if risk < 7 else "высокий"
        await interaction.response.send_message(
            f"🧾 Риск-профиль {member.mention}: **{level}** (очки подозрения: {risk})",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
