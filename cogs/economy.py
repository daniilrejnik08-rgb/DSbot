import asyncio
import io
import random
import time
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from utils import JSONHandler, Wallet
from utils.ui_render import (
    has_pillow,
    render_arcade_result_png,
    render_daily_rewards_png,
    render_economy_card_png,
    render_list_card_png,
)

# Монеты за день 1…7 (лестница); «конфеты» на картинке — отдельно, в ui_render.DAILY_VISUAL_CANDIES
DAILY_COIN_REWARDS = [900, 1100, 1300, 1600, 2000, 2400, 3000]

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
        self._abuse_freeze_until: dict[int, float] = {}

    async def _send_economy_card(
        self,
        interaction: discord.Interaction,
        *,
        member: discord.Member,
        ephemeral: bool = False,
    ) -> None:
        data = self.get_user_data(interaction.guild.id, member.id)
        if not has_pillow():
            embed = discord.Embed(title=f"💰 Баланс {member.display_name}", color=GOLD)
            embed.add_field(name="💵 Наличные", value=f'{data["balance"]:,} 🪙', inline=True)
            embed.add_field(name="🏦 Банк", value=f'{data["bank"]:,} 🪙', inline=True)
            embed.add_field(name="💎 Всего", value=f'{data["balance"] + data["bank"]:,} 🪙', inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
            return

        png = await asyncio.to_thread(
            render_economy_card_png,
            member_name=member.display_name,
            balance=int(data.get("balance", 0)),
            bank=int(data.get("bank", 0)),
            streak=int(data.get("daily_streak", 0)),
            title="Экономика",
            variant=member.id,
        )
        file = discord.File(io.BytesIO(png), filename="economy.png")
        emb = discord.Embed(title=f"💰 Баланс {member.display_name}", color=GOLD)
        emb.set_image(url="attachment://economy.png")
        await interaction.response.send_message(embed=emb, file=file, ephemeral=ephemeral)

    async def _send_result_card(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        headline: str,
        detail: str = "",
        footer: str = "",
        fallback_text: str,
        accent_rgb: tuple[int, int, int] = (120, 180, 255),
    ) -> None:
        if not has_pillow():
            await interaction.response.send_message(fallback_text)
            return
        png = await asyncio.to_thread(
            render_arcade_result_png,
            title=title,
            headline=headline,
            detail=detail,
            footer="",
            accent_rgb=accent_rgb,
        )
        file = discord.File(io.BytesIO(png), filename="eco_result.png")
        emb = discord.Embed(color=GOLD)
        emb.set_image(url="attachment://eco_result.png")
        await interaction.response.send_message(embed=emb, file=file)

    async def _send_list_card(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        subtitle: str,
        lines: list[str],
        fallback_embed: discord.Embed,
        accent_rgb: tuple[int, int, int] = (120, 180, 255),
    ) -> None:
        if not has_pillow():
            await interaction.response.send_message(embed=fallback_embed)
            return
        png = await asyncio.to_thread(
            render_list_card_png,
            title=title,
            subtitle="",
            lines=lines,
            accent_rgb=accent_rgb,
        )
        file = discord.File(io.BytesIO(png), filename="eco_list.png")
        emb = discord.Embed(title=title, color=GOLD)
        emb.set_image(url="attachment://eco_list.png")
        await interaction.response.send_message(embed=emb, file=file)

    def get_user_data(self, guild_id: int, user_id: int) -> dict:
        return Wallet.get(guild_id, user_id)

    def save_user_data(self, guild_id: int, user_id: int, data: dict):
        Wallet.save(guild_id, user_id, data)

    def _abuse_check(self, user_id: int, data: dict) -> str | None:
        now = time.time()
        frozen_to = self._abuse_freeze_until.get(user_id, 0.0)
        if frozen_to > now:
            remain = int((frozen_to - now) // 60) + 1
            return f"🚫 Аккаунт временно ограничен анти-абузом. Повторите через {remain} мин."

        suspicion = int(data.get("suspicion", 0))
        if suspicion >= 15:
            self._abuse_freeze_until[user_id] = now + 60 * 30
            return "🚫 Выявлена подозрительная активность. Экономика заморожена на 30 минут."
        return None

    @app_commands.command(name="balance", description="Проверить баланс")
    async def balance(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        await self._send_economy_card(interaction, member=member, ephemeral=False)

    @app_commands.command(name="daily", description="Получить ежедневный бонус")
    async def daily(self, interaction: discord.Interaction):
        gid, uid = interaction.guild.id, interaction.user.id
        data = self.get_user_data(gid, uid)
        blocked = self._abuse_check(interaction.user.id, data)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return

        tier = int(data.get("daily_tier", 1))
        if tier < 1 or tier > 7:
            tier = 1
            data["daily_tier"] = tier
        streak = int(data.get("daily_streak", 0))
        if streak < 0:
            streak = 0
            data["daily_streak"] = 0

        if data["last_daily"]:
            last = datetime.fromisoformat(data["last_daily"])
            # если пропуск больше 48ч — сброс лестницы и стрика (классическое daily)
            if datetime.now() - last > timedelta(hours=48):
                tier = 1
                streak = 0
                data["daily_tier"] = 1
                data["daily_streak"] = 0
            if datetime.now() - last < timedelta(hours=24):
                remaining = timedelta(hours=24) - (datetime.now() - last)
                h, m = remaining.seconds // 3600, (remaining.seconds % 3600) // 60
                await interaction.response.defer()
                files: list[discord.File] = []
                if has_pillow():
                    png = await asyncio.to_thread(render_daily_rewards_png, tier_next=tier)
                    files.append(discord.File(io.BytesIO(png), filename="daily.png"))
                emb = discord.Embed(
                    title="⏰ Ежедневная награда",
                    description=f"Следующий бонус через **{h}** ч **{m}** мин.\nСтрик: **{streak}**",
                    color=GOLD,
                )
                if files:
                    emb.set_image(url="attachment://daily.png")
                kw: dict = {"embed": emb}
                if files:
                    kw["files"] = files
                await interaction.followup.send(**kw)
                return

        # успешное получение: повышаем стрик и двигаем лестницу
        streak += 1
        data["daily_streak"] = streak
        bonus = DAILY_COIN_REWARDS[tier - 1]
        new_tier = 1 if tier >= 7 else tier + 1
        data["last_daily"] = datetime.now().isoformat()
        data["daily_tier"] = new_tier
        self.save_user_data(gid, uid, data)
        Wallet.add_balance(gid, uid, bonus, ledger=("Ежедневный бонус", f"/daily · день {tier}"))

        await interaction.response.defer()
        files: list[discord.File] = []
        if has_pillow():
            png = await asyncio.to_thread(render_daily_rewards_png, tier_next=new_tier)
            files.append(discord.File(io.BytesIO(png), filename="daily.png"))
        emb = discord.Embed(
            title="🎁 Ежедневная награда",
            description=f"День **{tier}/7** — начислено **{bonus:,}** 🪙\nСтрик: **{streak}**",
            color=GOLD,
        )
        if files:
            emb.set_image(url="attachment://daily.png")
        kw = {"embed": emb}
        if files:
            kw["files"] = files
        await interaction.followup.send(**kw)

    @app_commands.command(name="work", description="Заработать деньги работой")
    async def work(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        blocked = self._abuse_check(interaction.user.id, data)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return
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

        data["last_work"] = datetime.now().isoformat()
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        Wallet.add_balance(interaction.guild.id, interaction.user.id, salary, ledger=("Работа", job))
        await self._send_result_card(
            interaction,
            title="💼 Работа",
            headline=f"+{salary} 🪙",
            detail=f"Профессия: {job}",
            footer="Команда: /work",
            fallback_text=text,
            accent_rgb=(120, 220, 170),
        )

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
        blocked = self._abuse_check(interaction.user.id, sender)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return
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
        if amount >= 150000:
            sender["suspicion"] = sender.get("suspicion", 0) + 2
        if member.bot:
            sender["suspicion"] = sender.get("suspicion", 0) + 3
        history.append(now)
        self.pay_limits[interaction.user.id] = history
        self.save_user_data(interaction.guild.id, interaction.user.id, sender)
        self.save_user_data(interaction.guild.id, member.id, receiver)
        Wallet.log_ledger(
            interaction.guild.id,
            interaction.user.id,
            -amount,
            "Перевод",
            f"→ {member.display_name}, налог {tax} 🪙",
        )
        Wallet.log_ledger(
            interaction.guild.id,
            member.id,
            transfer,
            "Перевод",
            f"← {interaction.user.display_name}",
        )
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
        await self._send_result_card(
            interaction,
            title="💸 Перевод",
            headline=f"{member.display_name} +{transfer} 🪙",
            detail=f"Сумма: {amount} · Налог: {tax}",
            footer="Команда: /pay",
            fallback_text=f"💸 Перевод выполнен: {member.mention} получил **{transfer}** 🪙 (налог {tax} 🪙)",
            accent_rgb=(120, 180, 255),
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
        Wallet.log_ledger(interaction.guild.id, interaction.user.id, -amount, "В банк", f"наличные → банк")
        await self._send_result_card(
            interaction,
            title="🏦 Пополнение банка",
            headline=f"+{amount} 🪙 в банк",
            detail=f"Остаток наличных: {int(data['balance']):,} 🪙",
            footer="Команда: /deposit",
            fallback_text=f"🏦 В банк зачислено **{amount}** 🪙",
            accent_rgb=(120, 180, 255),
        )

    @app_commands.command(name="withdraw", description="Снять деньги из банка")
    async def withdraw(self, interaction: discord.Interaction, amount: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if amount <= 0 or data["bank"] < amount:
            await interaction.response.send_message("❌ Недостаточно средств на счете", ephemeral=True)
            return
        data["bank"] -= amount
        data["balance"] += amount
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        Wallet.log_ledger(interaction.guild.id, interaction.user.id, amount, "Снятие", "банк → наличные")
        await self._send_result_card(
            interaction,
            title="💵 Снятие с банка",
            headline=f"-{amount} 🪙 из банка",
            detail=f"Остаток в банке: {int(data['bank']):,} 🪙",
            footer="Команда: /withdraw",
            fallback_text=f"💵 Снято из банка: **{amount}** 🪙",
            accent_rgb=(255, 210, 120),
        )

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
        blocked = self._abuse_check(interaction.user.id, robber)
        if blocked:
            await interaction.response.send_message(blocked, ephemeral=True)
            return
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
            Wallet.log_ledger(interaction.guild.id, interaction.user.id, stolen, "Ограбление", f"у {member.display_name}")
            Wallet.log_ledger(interaction.guild.id, member.id, -stolen, "Ограбление", f"вор: {interaction.user.display_name}")
            await self._send_result_card(
                interaction,
                title="🕶️ Ограбление",
                headline=f"Успех: +{stolen} 🪙",
                detail=f"Цель: {member.display_name}",
                footer="Команда: /rob",
                fallback_text=f"🕶️ Успех! Вы украли **{stolen}** 🪙 у {member.mention}",
                accent_rgb=(120, 220, 170),
            )
        else:
            fine = min(random.randint(180, 520), robber["balance"])
            robber["balance"] -= fine
            self.save_user_data(interaction.guild.id, interaction.user.id, robber)
            Wallet.log_ledger(interaction.guild.id, interaction.user.id, -fine, "Ограбление провал", "штраф")
            await self._send_result_card(
                interaction,
                title="🚔 Ограбление",
                headline=f"Провал: -{fine} 🪙",
                detail="Наложен штраф",
                footer="Команда: /rob",
                fallback_text=f"🚔 Провал! Штраф: **{fine}** 🪙",
                accent_rgb=(235, 90, 110),
            )

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
        plain_lines = [line.replace("**", "") for line in lines]
        await self._send_list_card(
            interaction,
            title="🏆 Лидерборд экономики",
            subtitle=f"Сервер: {interaction.guild.name}",
            lines=plain_lines,
            fallback_embed=embed,
            accent_rgb=(255, 210, 120),
        )

    @app_commands.command(name="shop", description="Открыть магазин")
    async def shop(self, interaction: discord.Interaction):
        lines = [f"**{name}** — {price:,} 🪙" for name, price in self.shop_items.items()]
        embed = discord.Embed(title="🛒 Магазин", description="\n".join(lines), color=BRAND)
        embed.set_footer(text="Покупка: /buy item amount")
        plain_lines = [f"{name} — {price:,} 🪙" for name, price in self.shop_items.items()]
        await self._send_list_card(
            interaction,
            title="🛒 Магазин",
            subtitle="Покупка: /buy item amount",
            lines=plain_lines,
            fallback_embed=embed,
            accent_rgb=(120, 180, 255),
        )

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
        Wallet.log_ledger(interaction.guild.id, interaction.user.id, -total, "Магазин", f"{item_name} x{amount}")
        await self._send_result_card(
            interaction,
            title="🛒 Покупка",
            headline=f"{item_name} x{amount}",
            detail=f"Списано: {total:,} 🪙",
            footer="Команда: /buy",
            fallback_text=f"✅ Куплено: **{item_name} x{amount}** за **{total}** 🪙",
            accent_rgb=(120, 220, 170),
        )

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
        plain_lines = [f"{name}: x{count}" for name, count in sorted(counts.items())]
        await self._send_list_card(
            interaction,
            title=f"🎒 Инвентарь {member.display_name}",
            subtitle=f"Всего предметов: {len(inventory)}",
            lines=plain_lines,
            fallback_embed=embed,
            accent_rgb=(160, 110, 255),
        )

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

    @app_commands.command(name="economy_hub", description="Панель экономики и игр (кнопки)")
    async def economy_hub(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        total = int(data.get("balance", 0)) + int(data.get("bank", 0))
        emb = discord.Embed(
            title="💎 Экономика и аркада",
            description=(
                f"**{interaction.user.display_name}**\n"
                f"Всего: **{total:,}** 🪙"
            ),
            color=GOLD,
        )
        if has_pillow():
            png = await asyncio.to_thread(
                render_economy_card_png,
                member_name=interaction.user.display_name,
                balance=int(data.get("balance", 0)),
                bank=int(data.get("bank", 0)),
                streak=int(data.get("daily_streak", 0)),
                title="Экономика и аркада",
                variant=interaction.user.id + interaction.guild.id,
            )
            file = discord.File(io.BytesIO(png), filename="economy_hub.png")
            emb.set_image(url="attachment://economy_hub.png")
            await interaction.response.send_message(embed=emb, file=file, view=EconomyHubView(self))
            return
        await interaction.response.send_message(embed=emb, view=EconomyHubView(self))

    @app_commands.command(name="eco_select", description="Экономика в одном Select-меню")
    async def eco_select(self, interaction: discord.Interaction):
        emb = discord.Embed(
            title="💎 Экономика · Select",
            description="Выберите действие из списка ниже.",
            color=GOLD,
        )
        await interaction.response.send_message(embed=emb, view=EconomySelectView(self), ephemeral=True)


class EconomyHubView(discord.ui.View):
    def __init__(self, cog: Economy):
        super().__init__(timeout=420)
        self.cog = cog

    @discord.ui.button(label="Баланс", style=discord.ButtonStyle.primary, emoji="💰", row=0)
    async def bal(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog._send_economy_card(interaction, member=interaction.user, ephemeral=True)


class EconomySelect(discord.ui.Select):
    def __init__(self, cog: Economy):
        self.cog = cog
        options = [
            discord.SelectOption(label="Баланс", value="bal", emoji="💰"),
            discord.SelectOption(label="Ежедневная награда", value="daily", emoji="🎁"),
            discord.SelectOption(label="Работа", value="work", emoji="💼"),
            discord.SelectOption(label="Положить в банк", value="dep", emoji="🏦"),
            discord.SelectOption(label="Снять из банка", value="wd", emoji="💵"),
            discord.SelectOption(label="Магазин", value="shop", emoji="🛒"),
            discord.SelectOption(label="Инвентарь", value="inv", emoji="🎒"),
            discord.SelectOption(label="Топ богачей", value="top", emoji="🏆"),
        ]
        super().__init__(placeholder="Выберите действие…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]
        if action == "bal":
            await self.cog.balance.callback(self.cog, interaction, None)
            return
        if action == "daily":
            await self.cog.daily.callback(self.cog, interaction)
            return
        if action == "work":
            await self.cog.work.callback(self.cog, interaction)
            return
        if action == "dep":
            await interaction.response.send_modal(EcoAmountModal(self.cog, mode="deposit"))
            return
        if action == "wd":
            await interaction.response.send_modal(EcoAmountModal(self.cog, mode="withdraw"))
            return
        if action == "shop":
            await self.cog.shop.callback(self.cog, interaction)
            return
        if action == "inv":
            await self.cog.inventory.callback(self.cog, interaction, None)
            return
        if action == "top":
            await self.cog.leaderboard.callback(self.cog, interaction)
            return
        await interaction.response.send_message("Неизвестное действие.", ephemeral=True)


class EcoAmountModal(discord.ui.Modal):
    amount = discord.ui.TextInput(
        label="Сумма",
        placeholder="Например: 500",
        required=True,
        max_length=10,
    )

    def __init__(self, cog: Economy, *, mode: str):
        title = "Положить в банк" if mode == "deposit" else "Снять из банка"
        super().__init__(title=title)
        self.cog = cog
        self.mode = mode

    async def on_submit(self, interaction: discord.Interaction):
        try:
            value = int(str(self.amount.value).strip())
        except ValueError:
            await interaction.response.send_message("❌ Введите целое число.", ephemeral=True)
            return
        if self.mode == "deposit":
            await self.cog.deposit.callback(self.cog, interaction, value)
            return
        await self.cog.withdraw.callback(self.cog, interaction, value)


class EconomySelectView(discord.ui.View):
    def __init__(self, cog: Economy):
        super().__init__(timeout=300)
        self.cog = cog
        self.add_item(EconomySelect(cog))

    @discord.ui.button(label="Магазин", style=discord.ButtonStyle.secondary, emoji="🛒", row=0)
    async def shop_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.shop.callback(self.cog, interaction)

    @discord.ui.button(label="Топ-5 богачей", style=discord.ButtonStyle.secondary, emoji="🏆", row=0)
    async def top5(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self.cog.leaderboard.callback(self.cog, interaction)

    @discord.ui.button(label="Игры", style=discord.ButtonStyle.success, emoji="🎰", row=1)
    async def games(self, interaction: discord.Interaction, _: discord.ui.Button):
        emb = discord.Embed(
            title="🎰 Игры",
            description=(
                "Ставка — целое число 🪙 с баланса.\n"
                "**Быстрые:** `/coinflip` · `/slots` · `/dice`\n"
                "**Карточные:** `/blackjack` · `/highlow`\n"
                "**Риск:** `/roulette` · `/crash` · `/mines`"
            ),
            color=BRAND,
        )
        await interaction.response.send_message(embed=emb, ephemeral=True)


async def setup(bot: commands.Bot):
    from utils import target_guilds

    guilds = target_guilds()
    if guilds is None:
        await bot.add_cog(Economy(bot))
    else:
        await bot.add_cog(Economy(bot), guilds=guilds)
