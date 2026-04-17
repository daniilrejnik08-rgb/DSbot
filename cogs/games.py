import random

import discord
from discord import app_commands
from discord.ext import commands

from utils import Wallet

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
            Wallet.add_balance(gid, uid, self.bet * 2)
            status = f"Победа! Получено **{self.bet * 2}** 🪙"
        elif p == d:
            Wallet.add_balance(gid, uid, self.bet)
            status = "Ничья — ставка возвращена."
        else:
            status = "Дилер выиграл."
        await self.update_message(interaction, status)
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
            Wallet.add_balance(gid, uid, self.bet)
            text = f"Выпало **{self._label(b)}** — ничья, ставка возвращена."
            col = GOLD
        else:
            higher = b > a
            win = (pick == "higher" and higher) or (pick == "lower" and not higher)
            if win:
                Wallet.add_balance(gid, uid, self.bet * 2)
                text = f"Выпало **{self._label(b)}** — выигрыш **{self.bet * 2}** 🪙"
                col = SUCCESS
            else:
                text = f"Выпало **{self._label(b)}** — проигрыш."
                col = DANGER
        embed = discord.Embed(
            title="📈 Higher / Lower",
            description=f"Первая карта: **{self._label(a)}**\n{text}",
            color=col,
        )
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


class Games(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _ensure_bet(self, interaction: discord.Interaction, bet: int) -> bool:
        if bet <= 0:
            return False
        data = Wallet.get(interaction.guild.id, interaction.user.id)
        return data["balance"] >= bet

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
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        result = random.choice(["heads", "tails"])
        win = choice == result
        side_ru = "орёл" if result == "heads" else "решка"
        embed = discord.Embed(title="🪙 Coinflip", color=SUCCESS if win else DANGER)
        if win:
            Wallet.add_balance(interaction.guild.id, interaction.user.id, bet * 2)
            embed.description = f"Выпало **{side_ru}** — выигрыш **{bet * 2}** 🪙"
        else:
            embed.description = f"Выпало **{side_ru}** — **-{bet}** 🪙"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="dice", description="Угадать число на кубике 1–6")
    async def dice(self, interaction: discord.Interaction, bet: int, number: app_commands.Range[int, 1, 6]):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        result = random.randint(1, 6)
        embed = discord.Embed(title="🎲 Кубик", color=BRAND)
        if result == number:
            win = bet * 6
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = f"Выпало **{result}** — джекпот **{win}** 🪙"
        else:
            embed.description = f"Выпало **{result}**, вы выбрали **{number}**."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="slots", description="Слоты — три в ряд")
    async def slots(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        emojis = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        result = [random.choice(emojis) for _ in range(3)]
        if result[0] == result[1] == result[2]:
            x = 12 if result[0] == "7️⃣" else 5
        elif len(set(result)) == 2:
            x = 2
        else:
            x = 0
        embed = discord.Embed(title="🎰 Слоты", description=f"**{result[0]} │ {result[1]} │ {result[2]}**", color=GOLD)
        if x > 0:
            win = int(bet * x)
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.add_field(name="Выигрыш", value=f"**{win}** 🪙  (×{x})", inline=False)
        else:
            embed.add_field(name="Результат", value=f"Ставка **{bet}** 🪙", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="blackjack", description="Блэкджек против дилера")
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
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
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        embed = discord.Embed(title="🔫 Русская рулетка", color=DANGER)
        if random.randint(1, 6) == 1:
            embed.description = "💥 Проигрыш всей ставки."
        else:
            win = bet * 2
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = f"Пронесло! **+{win}** 🪙"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="guess", description="Угадать число от 1 до 10")
    async def guess(self, interaction: discord.Interaction, bet: int, number: app_commands.Range[int, 1, 10]):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        secret = random.randint(1, 10)
        embed = discord.Embed(title="🎯 Угадай число", color=BRAND)
        if number == secret:
            win = bet * 9
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = f"Загадано **{secret}** — точное попадание! **{win}** 🪙"
        else:
            embed.description = f"Загадано **{secret}**, вы выбрали **{number}**."
        await interaction.response.send_message(embed=embed)

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
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        bot_pick = random.choice(["rock", "scissors", "paper"])
        names = {"rock": "Камень", "scissors": "Ножницы", "paper": "Бумага"}
        beats = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
        embed = discord.Embed(title="✊ КНБ", color=BRAND)
        embed.add_field(name="Вы", value=names[pick], inline=True)
        embed.add_field(name="Бот", value=names[bot_pick], inline=True)
        if pick == bot_pick:
            Wallet.add_balance(interaction.guild.id, interaction.user.id, bet)
            embed.description = "Ничья — ставка возвращена."
        elif beats[pick] == bot_pick:
            Wallet.add_balance(interaction.guild.id, interaction.user.id, bet * 2)
            embed.description = f"Победа! **{bet * 2}** 🪙"
        else:
            embed.description = "Поражение."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wheel", description="Колесо фортуны")
    async def wheel(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        sectors = [0, 0.5, 1, 1.5, 2, 2.5, 3, 0.5]
        mult = random.choice(sectors)
        embed = discord.Embed(title="🎡 Колесо", color=GOLD)
        if mult == 0:
            embed.description = "Сектор **0** — ставка сгорела."
        else:
            win = int(bet * mult)
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = f"Множитель **×{mult}** → **{win}** 🪙"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crash", description="Краш: успейте до обрыва множителя")
    async def crash(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
        crash_at = round(random.uniform(1.15, 6.5), 2)
        cashout = round(random.uniform(0.8, 7.0), 2)
        embed = discord.Embed(title="📉 Crash", color=BRAND)
        if cashout < crash_at:
            win = int(bet * cashout)
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = (
                f"Краш на **{crash_at}×**, вы вышли на **{cashout}×**\n"
                f"Выигрыш: **{win}** 🪙"
            )
        else:
            embed.description = f"Краш на **{crash_at}×**, вы на **{cashout}×** — ставка сгорела."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="highlow", description="Следующая карта выше или ниже?")
    async def highlow(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
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
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
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
                    Wallet.add_balance(gid, player_id, win)
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
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
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
            Wallet.add_balance(interaction.guild.id, interaction.user.id, win)
            embed.description = f"Множитель **×{m}** → **{win}** 🪙"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mines", description="Мини-сапёр 3×3 — одна мина")
    async def mines(self, interaction: discord.Interaction, bet: int):
        if not self._ensure_bet(interaction, bet):
            await interaction.response.send_message("❌ Недостаточно монет.", ephemeral=True)
            return
        Wallet.remove_balance(interaction.guild.id, interaction.user.id, bet)
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
                    Wallet.add_balance(gid, uid, win)
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
    await bot.add_cog(Games(bot))
