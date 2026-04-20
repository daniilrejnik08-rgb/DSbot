import asyncio
import io
import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import Wallet
from utils.ui_render import has_pillow, render_arcade_result_png, render_crash_result_png, render_slots_filmstrip_png

try:
    from utils.theme import BRAND, DANGER, GOLD, SUCCESS
except Exception:
    BRAND = discord.Color.blurple()
    SUCCESS = discord.Color.green()
    DANGER = discord.Color.red()
    GOLD = discord.Color.gold()


class BlackjackView(discord.ui.View):
    def __init__(self, player: discord.Member, bet: int, cog: "Games"):
        super().__init__(timeout=90)
        self.player = player
        self.bet = bet
        self.cog = cog
        self.deck = self.create_deck()
        self.player_hand = [self.draw_card(), self.draw_card()]
        self.dealer_hand = [self.draw_card(), self.draw_card()]
        self.game_over = False

    def create_deck(self):
        suits = ["♠", "♥", "♦", "♣"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = [{"rank": r, "suit": s} for s in suits for r in ranks]
        random.shuffle(deck)
        return deck

    def draw_card(self):
        if not self.deck:
            self.deck = self.create_deck()
        return self.deck.pop()

    def hand_value(self, hand):
        value = 0
        aces = 0
        for card in hand:
            rank = card["rank"]
            if rank in ["J", "Q", "K"]:
                value += 10
            elif rank == "A":
                aces += 1
            else:
                value += int(rank)
        for _ in range(aces):
            value += 11 if value + 11 <= 21 else 1
        return value

    def hand_to_string(self, hand, hide_first=False):
        if hide_first:
            return f"🂠 **??**  •  {hand[1]['rank']}{hand[1]['suit']}"
        return "  ".join([f"{c['rank']}{c['suit']}" for c in hand])

    async def update_message(self, interaction: discord.Interaction, status: str = ""):
        embed = discord.Embed(title="🃏 Блэкджек", color=BRAND)
        embed.add_field(
            name=f"Ваша рука — **{self.hand_value(self.player_hand)}**",
            value=self.hand_to_string(self.player_hand),
            inline=False,
        )
        dealer_value = self.hand_value(self.dealer_hand) if self.game_over else "?"
        embed.add_field(
            name=f"Дилер — **{dealer_value}**",
            value=self.hand_to_string(self.dealer_hand, hide_first=not self.game_over),
            inline=False,
        )
        if status:
            embed.add_field(name="Итог", value=status, inline=False)
        embed.set_footer(text=f"Ставка: {self.bet} 🪙  •  DS Arcade")
        await interaction.edit_original_response(embed=embed, view=None if self.game_over else self)

    @discord.ui.button(label="Взять", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Это не ваша игра.", ephemeral=True)
            return
        await interaction.response.defer()
        self.player_hand.append(self.draw_card())
        if self.hand_value(self.player_hand) > 21:
            self.game_over = True
            await self.update_message(interaction, "Перебор — ставка сгорает.")
            await self.cog._send_arcade_card(
                interaction,
                title="🃏 Блэкджек",
                headline="Перебор",
                detail=f"Ваш счёт: **{self.hand_value(self.player_hand)}**",
                footer=f"Ставка {self.bet} 🪙",
                accent_rgb=(235, 90, 110),
                embed_color=DANGER,
            )
            self.stop()
            return
        await self.update_message(interaction)

    @discord.ui.button(label="Стоп", style=discord.ButtonStyle.danger)
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Это не ваша игра.", ephemeral=True)
            return
        await interaction.response.defer()
        self.game_over = True
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.draw_card())
        p = self.hand_value(self.player_hand)
        d = self.hand_value(self.dealer_hand)
        gid, uid = interaction.guild.id, self.player.id
        if d > 21 or p > d:
            Wallet.add_balance(gid, uid, self.bet * 2, ledger=("Игры", "блэкджек · победа"))
            status = f"Победа! Получено **{self.bet * 2}** 🪙"
            headline = "Победа!"
            accent = (120, 220, 170)
            col = SUCCESS
        elif p == d:
            Wallet.add_balance(gid, uid, self.bet, ledger=("Игры", "блэкджек · ничья"))
            status = "Ничья — ставка возвращена."
            headline = "Ничья"
            accent = (170, 185, 210)
            col = GOLD
        else:
            status = "Дилер выиграл."
            headline = "Проигрыш"
            accent = (235, 90, 110)
            col = DANGER
        await self.update_message(interaction, status)
        await self.cog._send_arcade_card(
            interaction,
            title="🃏 Блэкджек",
            headline=headline,
            detail=f"Вы: **{p}**   Дилер: **{d}**",
            footer=f"Ставка {self.bet} 🪙",
            accent_rgb=accent,
            embed_color=col,
        )
        self.stop()


class HighLowView(discord.ui.View):
    """Угадать: следующая карта выше или ниже первой (ранги 2–14)."""

    def __init__(self, player: discord.Member, bet: int, first: int):
        super().__init__(timeout=45)
        self.player = player
        self.bet = bet
        self.first = first
        self.second = random.randint(2, 14)

    def _label(self, v: int) -> str:
        if v == 14:
            return "Туз"
        if v == 11:
            return "Валет"
        if v == 12:
            return "Дама"
        if v == 13:
            return "Король"
        return str(v)

    @discord.ui.button(label="Выше ⬆️", style=discord.ButtonStyle.success)
    async def higher(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._resolve(interaction, "higher")

    @discord.ui.button(label="Ниже ⬇️", style=discord.ButtonStyle.danger)
    async def lower(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._resolve(interaction, "lower")

    async def _resolve(self, interaction: discord.Interaction, pick: str):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("Не ваш раунд.", ephemeral=True)
            return
        gid = interaction.guild.id
        uid = self.player.id
        a, b = self.first, self.second
        if a == b:
            Wallet.add_balance(gid, uid, self.bet, ledger=("Игры", "Hi-Lo · ничья"))
            text = f"Выпало **{self._label(b)}** — ничья, ставка возвращена."
            col = GOLD
            headline = "Ничья"
            accent = (170, 185, 210)
        else:
            higher = b > a
            win = (pick == "higher" and higher) or (pick == "lower" and not higher)
            if win:
                Wallet.add_balance(gid, uid, self.bet * 2, ledger=("Игры", "Hi-Lo · победа"))
                text = f"Выпало **{self._label(b)}** — выигрыш **{self.bet * 2}** 🪙"
                col = SUCCESS
                headline = "Победа!"
                accent = (120, 220, 170)
            else:
                text = f"Выпало **{self._label(b)}** — проигрыш."
                col = DANGER
                headline = "Проигрыш"
                accent = (235, 90, 110)
        embed = discord.Embed(
            title="📈 Higher / Lower",
            description=f"Первая карта: **{self._label(a)}**\n{text}",
            color=col,
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        await self.cog._send_arcade_card(
            interaction,
            title="📈 Higher / Lower",
            headline=headline,
            detail=f"Было: **{self._label(a)}**  →  Стало: **{self._label(b)}**",
            footer=f"Ставка {self.bet} 🪙",
            accent_rgb=accent,
            embed_color=col,
        )
        self.stop()


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _ensure_bet(self, interaction: discord.Interaction, bet: int) -> bool:
        if bet <= 0:
            return False
        data = Wallet.get(interaction.guild.id, interaction.user.id)
        return data["balance"] >= bet

    async def _send_arcade_card(
        self,
        interaction: discord.Interaction,
        *,
        title: str,
        headline: str,
        detail: str,
        footer: str,
        accent_rgb: tuple[int, int, int],
        embed_color: discord.Color,
    ) -> None:
        parts = [headline, detail, footer]
        desc = "\n".join(p for p in parts if p)
        if has_pillow():
            if not interaction.response.is_done():
                await interaction.response.defer()
            png = await asyncio.to_thread(
                render_arcade_result_png,
                title=title,
                headline=headline,
                detail=detail,
                footer=footer,
                accent_rgb=accent_rgb,
            )
            emb = discord.Embed(title=title, description=desc, color=embed_color)
            emb.set_image(url="attachment://arcade.png")
            await interaction.followup.send(embed=emb, file=discord.File(io.BytesIO(png), filename="arcade.png"))
        else:
            emb = discord.Embed(title=title, description=desc, color=embed_color)
            if interaction.response.is_done():
                await interaction.followup.send(embed=emb)
            else:
                await interaction.response.send_message(embed=emb)

    @app_commands.command(name="coinflip", description="Монетка: орёл или решка")
    @app_commands.describe(bet="Ставка", choice="Сторона")
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Орёл", value="heads"),
            app_commands.Choice(name="Решка", value="tails"),
        ]
    )
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: str):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет или неверная ставка.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        result = random.choice(["heads", "tails"])
        win = choice == result
        side_ru = "орёл" if result == "heads" else "решка"
        if win:
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, bet * 2, ledger=("Игры", "coinflip · выигрыш")
            )
            headline, detail = "Победа!", f"Выпало **{side_ru}** — выигрыш **{bet * 2}** 🪙"
            accent = (95, 220, 160)
        else:
            headline, detail = "Проигрыш", f"Выпало **{side_ru}** — **−{bet}** 🪙"
            accent = (230, 90, 110)
        await self._send_arcade_card(
            interaction,
            title="🪙 Монетка",
            headline=headline,
            detail=detail,
            footer=f"Ставка {bet} 🪙",
            accent_rgb=accent,
            embed_color=SUCCESS if win else DANGER,
        )

    @app_commands.command(name="dice", description="Угадать число на кубике 1–6")
    async def dice(self, interaction: discord.Interaction, bet: int, number: app_commands.Range[int, 1, 6]):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        result = random.randint(1, 6)
        if result == number:
            win = bet * 6
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "кубик · джекпот")
            )
            headline, detail = "Джекпот!", f"Выпало **{result}** — **{win}** 🪙"
            accent = (255, 200, 110)
            col = GOLD
        else:
            headline, detail = "Мимо", f"Выпало **{result}**, вы выбрали **{number}**."
            accent = (140, 170, 220)
            col = BRAND
        await self._send_arcade_card(
            interaction,
            title="🎲 Кубик",
            headline=headline,
            detail=detail,
            footer=f"Ставка {bet} 🪙",
            accent_rgb=accent,
            embed_color=col,
        )

    @app_commands.command(name="slots", description="Слоты — три в ряд")
    async def slots(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        emojis = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        result = [random.choice(emojis) for _ in range(3)]
        if result[0] == result[1] == result[2]:
            x = 12 if result[0] == "7️⃣" else 5
        elif len(set(result)) == 2:
            x = 2
        else:
            x = 0
        win = int(bet * x) if x > 0 else 0
        if win > 0:
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win, ledger=("Игры", "слоты · выигрыш"))
        if has_pillow():
            if not interaction.response.is_done():
                await interaction.response.defer()
            png = await asyncio.to_thread(
                render_slots_filmstrip_png,
                bet=bet,
                symbols=result,
                mult=float(x),
                win=win,
                frames=3,
            )
            desc = f"Результат: **{result[0]} │ {result[1]} │ {result[2]}**"
            if win > 0:
                desc += f"\nВыигрыш **+{win}** 🪙 (×{x})"
            emb = discord.Embed(title="🎰 Слоты", description=desc, color=GOLD if win > 0 else BRAND)
            emb.set_image(url="attachment://slots.png")
            await interaction.followup.send(embed=emb, file=discord.File(io.BytesIO(png), filename="slots.png"))
        else:
            line = f"{result[0]} │ {result[1]} │ {result[2]}"
            if x > 0:
                headline = f"Выигрыш ×{x}"
                detail = f"{line}\n**+{win}** 🪙"
                accent = (255, 215, 120)
                col = GOLD
            else:
                headline = "Без совпадений"
                detail = f"{line}"
                accent = (130, 150, 190)
                col = BRAND
            await self._send_arcade_card(
                interaction,
                title="🎰 Слоты",
                headline=headline,
                detail=detail,
                footer=f"Ставка {bet} 🪙",
                accent_rgb=accent,
                embed_color=col,
            )

    @app_commands.command(name="blackjack", description="Блэкджек против дилера")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        view = BlackjackView(interaction.user, bet, self)
        embed = discord.Embed(
            title="🃏 Блэкджек",
            description="Нажмите **Взять** или **Стоп**.",
            color=BRAND,
        )
        await interaction.response.send_message(embed=embed, view=view)
        await view.update_message(interaction)

    @app_commands.command(name="roulette", description="Риск: 1 из 6 — проигрыш")
    async def roulette(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        if random.randint(1, 6) == 1:
            await self._send_arcade_card(
                interaction,
                title="🔫 Рулетка",
                headline="Выстрел",
                detail="Проигрыш всей ставки.",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(235, 90, 110),
                embed_color=DANGER,
            )
        else:
            win = bet * 2
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "рулетка · выигрыш")
            )
            await self._send_arcade_card(
                interaction,
                title="🔫 Рулетка",
                headline="Повезло!",
                detail=f"Выигрыш **+{win}** 🪙",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(120, 220, 170),
                embed_color=SUCCESS,
            )

    @app_commands.command(name="guess", description="Угадать число от 1 до 10")
    async def guess(self, interaction: discord.Interaction, bet: int, number: app_commands.Range[int, 1, 10]):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        secret = random.randint(1, 10)
        if number == secret:
            win = bet * 9
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "угадай число")
            )
            await self._send_arcade_card(
                interaction,
                title="🎯 Угадай число",
                headline="Точное попадание!",
                detail=f"Загадано **{secret}** — выигрыш **{win}** 🪙",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(255, 205, 120),
                embed_color=GOLD,
            )
        else:
            await self._send_arcade_card(
                interaction,
                title="🎯 Угадай число",
                headline="Не угадали",
                detail=f"Загадано **{secret}**, вы выбрали **{number}**.",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(140, 170, 220),
                embed_color=BRAND,
            )

    @app_commands.command(name="rps", description="Камень, ножницы, бумага")
    @app_commands.choices(
        pick=[
            app_commands.Choice(name="Камень", value="rock"),
            app_commands.Choice(name="Ножницы", value="scissors"),
            app_commands.Choice(name="Бумага", value="paper"),
        ]
    )
    async def rps(self, interaction: discord.Interaction, bet: int, pick: str):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        bot_pick = random.choice(["rock", "scissors", "paper"])
        names = {"rock": "Камень", "scissors": "Ножницы", "paper": "Бумага"}
        beats = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
        if pick == bot_pick:
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "КНБ · ничья")
            )
            await self._send_arcade_card(
                interaction,
                title="✊ КНБ",
                headline="Ничья",
                detail=f"Вы: **{names[pick]}**\nБот: **{names[bot_pick]}**",
                footer=f"Ставка {bet} 🪙 (возврат)",
                accent_rgb=(170, 185, 210),
                embed_color=GOLD,
            )
        elif beats[pick] == bot_pick:
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, bet * 2, ledger=("Игры", "КНБ · победа")
            )
            await self._send_arcade_card(
                interaction,
                title="✊ КНБ",
                headline="Победа!",
                detail=f"Вы: **{names[pick]}**\nБот: **{names[bot_pick]}**\nВыигрыш **{bet * 2}** 🪙",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(120, 220, 170),
                embed_color=SUCCESS,
            )
        else:
            await self._send_arcade_card(
                interaction,
                title="✊ КНБ",
                headline="Поражение",
                detail=f"Вы: **{names[pick]}**\nБот: **{names[bot_pick]}**",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(235, 90, 110),
                embed_color=DANGER,
            )

    @app_commands.command(name="wheel", description="Колесо фортуны")
    async def wheel(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        sectors = [0, 0.5, 1, 1.5, 2, 2.5, 3, 0.5]
        mult = random.choice(sectors)
        if mult == 0:
            await self._send_arcade_card(
                interaction,
                title="🎡 Колесо",
                headline="Сектор 0",
                detail="Ставка сгорела.",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(235, 90, 110),
                embed_color=DANGER,
            )
        else:
            win = int(bet * mult)
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "колесо фортуны")
            )
            await self._send_arcade_card(
                interaction,
                title="🎡 Колесо",
                headline=f"Множитель ×{mult}",
                detail=f"Выигрыш **{win}** 🪙",
                footer=f"Ставка {bet} 🪙",
                accent_rgb=(255, 210, 120),
                embed_color=GOLD,
            )

    @app_commands.command(name="crash", description="Краш: успейте до обрыва множителя")
    async def crash(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        crash_at = round(random.uniform(1.15, 6.5), 2)
        cashout = round(random.uniform(0.8, 7.0), 2)
        if cashout < crash_at:
            win = int(bet * cashout)
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "crash · кэшаут")
            )
            if has_pillow():
                if not interaction.response.is_done():
                    await interaction.response.defer()
                png = await asyncio.to_thread(
                    render_crash_result_png,
                    bet=bet,
                    crash_at=crash_at,
                    cashout=cashout,
                    win=win,
                )
                emb = discord.Embed(
                    title="📉 Crash",
                    description=f"Краш **{crash_at}×** · выход **{cashout}×** · выигрыш **{win}** 🪙",
                    color=SUCCESS,
                )
                emb.set_image(url="attachment://crash.png")
                await interaction.followup.send(embed=emb, file=discord.File(io.BytesIO(png), filename="crash.png"))
            else:
                await self._send_arcade_card(
                    interaction,
                    title="📉 Crash",
                    headline="Успешный кэшаут",
                    detail=f"Краш {crash_at}× • выход {cashout}× • +{win} 🪙",
                    footer=f"Ставка {bet} 🪙",
                    accent_rgb=(120, 220, 170),
                    embed_color=SUCCESS,
                )
        else:
            if has_pillow():
                if not interaction.response.is_done():
                    await interaction.response.defer()
                png = await asyncio.to_thread(
                    render_crash_result_png,
                    bet=bet,
                    crash_at=crash_at,
                    cashout=cashout,
                    win=None,
                )
                emb = discord.Embed(
                    title="📉 Crash",
                    description=f"Краш **{crash_at}×** · вы на **{cashout}×** — ставка сгорела",
                    color=DANGER,
                )
                emb.set_image(url="attachment://crash.png")
                await interaction.followup.send(embed=emb, file=discord.File(io.BytesIO(png), filename="crash.png"))
            else:
                await self._send_arcade_card(
                    interaction,
                    title="📉 Crash",
                    headline="Краш",
                    detail=f"Краш {crash_at}× • вы на {cashout}× — ставка сгорела",
                    footer=f"Ставка {bet} 🪙",
                    accent_rgb=(235, 90, 110),
                    embed_color=DANGER,
                )

    @app_commands.command(name="highlow", description="Следующая карта выше или ниже?")
    async def highlow(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        first = random.randint(2, 14)
        labels = {14: "Туз", 11: "Валет", 12: "Дама", 13: "Король"}
        lab = labels.get(first, str(first))
        embed = discord.Embed(
            title="📈 Higher / Lower",
            description=f"Первая карта: **{lab}**\nКуда дальше?",
            color=BRAND,
        )
        view = HighLowView(interaction.user, bet, first)
        await interaction.response.send_message(embed=embed, view=view)

    # --- Популярные мини-игры ---

    TRIVIA_BANK = [
        {"q": "Столица Франции?", "opts": ["Лондон", "Париж", "Берлин", "Рим"], "a": 1},
        {"q": "Сколько планет в Солнечной системе (классика)?", "opts": ["7", "8", "9", "10"], "a": 1},
        {"q": "2 + 2 × 2 = ?", "opts": ["6", "8", "4", "10"], "a": 0},
        {"q": "Какой язык программирования у этого бота?", "opts": ["Java", "Python", "C#", "Rust"], "a": 1},
        {"q": "Сколько бит в одном байте?", "opts": ["4", "8", "16", "32"], "a": 1},
        {"q": "H₂O — это…", "opts": ["Кислород", "Вода", "Соль", "Углекислый газ"], "a": 1},
        {"q": "Сколько часовых поясов в России (примерно)?", "opts": ["9", "10", "11", "12"], "a": 2},
        {"q": "Кто написал «Войну и мир»?", "opts": ["Пушкин", "Толстой", "Достоевский", "Чехов"], "a": 1},
        {"q": "Сколько сторон у шестиугольника?", "opts": ["5", "6", "7", "8"], "a": 1},
        {"q": "Какая планета ближе всего к Солнцу?", "opts": ["Венера", "Меркурий", "Марс", "Земля"], "a": 1},
        {"q": "Сколько дней в високосном году?", "opts": ["364", "365", "366", "367"], "a": 2},
        {"q": "Какой цвет получится при смешении красного и синего?", "opts": ["Жёлтый", "Зелёный", "Фиолетовый", "Оранжевый"], "a": 2},
    ]

    @app_commands.command(name="trivia", description="Викторина на монеты")
    async def trivia(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        q = random.choice(self.TRIVIA_BANK)
        player_id = interaction.user.id
        gid = interaction.guild.id

        class TriviaView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=45)
                self.answered = False

            async def answer(self, interaction: discord.Interaction, idx: int) -> None:
                if interaction.user.id != player_id:
                    await interaction.response.send_message("Чужая игра.", ephemeral=True)
                    return
                if self.answered:
                    await interaction.response.send_message("Уже отвечено.", ephemeral=True)
                    return
                self.answered = True
                for c in self.children:
                    c.disabled = True
                if idx == q["a"]:
                    win = int(bet * 2.2)
                    Wallet.add_balance(gid, player_id, win, ledger=("Игры", "викторина"))
                    text = f"✅ Верно! **+{win}** 🪙"
                    col = SUCCESS
                else:
                    right = q["opts"][q["a"]]
                    text = f"❌ Неверно. Правильно: **{right}**"
                    col = DANGER
                emb = discord.Embed(title="🧠 Викторина", description=text, color=col)
                emb.add_field(name="Вопрос", value=q["q"], inline=False)
                await interaction.response.edit_message(embed=emb, view=self)
                self.stop()

        view = TriviaView()
        for i, label in enumerate(q["opts"]):

            async def make_handler(ix: int):
                async def _h(inter: discord.Interaction) -> None:
                    await view.answer(inter, ix)

                return _h

            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary, row=i // 2)
            btn.callback = make_handler(i)
            view.add_item(btn)

        embed = discord.Embed(
            title="🧠 Викторина",
            description=f"**{q['q']}**\nСтавка: **{bet}** 🪙",
            color=BRAND,
        )
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="plinko", description="Plinko — шарик и множитель")
    async def plinko(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        x = 0.0
        path = []
        for _ in range(10):
            step = random.choice([-1, 1])
            x += step
            path.append("⬅" if step < 0 else "➡")
        slot = abs(x) % 9
        mults = [0.0, 0.4, 0.8, 1.2, 1.8, 2.5, 1.8, 1.2, 0.6]
        m = mults[slot]
        embed = discord.Embed(title="🪩 Plinko", color=GOLD)
        embed.add_field(name="Шарик", value="".join(path[:16]) + ("…" if len(path) > 16 else ""), inline=False)
        if m == 0:
            embed.description = "Слот **0×** — ставка сгорела."
        else:
            win = int(bet * m)
            Wallet.add_balance(
                interaction.guild.id, interaction.user.id, win, ledger=("Игры", "plinko")
            )
            embed.description = f"Множитель **×{m}** → **{win}** 🪙"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mines", description="Мини-сапёр 3×3 — одна мина")
    async def mines(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(
            interaction.guild.id, interaction.user.id, bet, ledger=("Игры", "ставка")
        )
        bomb = random.randint(0, 8)
        uid = interaction.user.id
        gid = interaction.guild.id

        class MinesView(discord.ui.View):
            def __init__(self, bomb_pos: int):
                super().__init__(timeout=60)
                self.done = False
                self.bomb_pos = bomb_pos

            async def open_cell(self, interaction: discord.Interaction, idx: int):
                if interaction.user.id != uid:
                    await interaction.response.send_message("Не ваша игра.", ephemeral=True)
                    return
                if self.done:
                    await interaction.response.send_message("Игра окончена.", ephemeral=True)
                    return
                self.done = True
                for c in self.children:
                    c.disabled = True
                if idx == self.bomb_pos:
                    emb = discord.Embed(
                        title="💣 Мина",
                        description="Бум! Ставка сгорела.",
                        color=DANGER,
                    )
                else:
                    win = int(bet * 1.35)
                    Wallet.add_balance(gid, uid, win, ledger=("Игры", "сапёр"))
                    emb = discord.Embed(
                        title="✅ Безопасно",
                        description=f"Выигрыш **{win}** 🪙 (ставка {bet})",
                        color=SUCCESS,
                    )
                await interaction.response.edit_message(embed=emb, view=self)
                self.stop()

        view = MinesView(bomb)
        for idx in range(9):
            b = discord.ui.Button(label=f"{idx + 1}", style=discord.ButtonStyle.primary, row=idx // 3)

            async def handler(inter: discord.Interaction, i: int = idx):
                await view.open_cell(inter, i)

            b.callback = handler
            view.add_item(b)

        embed = discord.Embed(
            title="💣 Мини-сапёр",
            description="Выберите **одну** клетку (1–9). Одна мина — если попали, ставка сгорает.",
            color=BRAND,
        )
        embed.set_footer(text=f"Ставка {bet} 🪙")
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    from utils import target_guild

    g = target_guild()
    if g is None:
        await bot.add_cog(Games(bot))
    else:
        await bot.add_cog(Games(bot), guild=g)
