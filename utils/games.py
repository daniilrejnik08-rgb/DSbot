import discord
from discord.ext import commands
from discord import app_commands
import random
import asyncio
from utils import JSONHandler

class BlackjackView(discord.ui.View):
    def __init__(self, player, bet, cog):
        super().__init__(timeout=60)
        self.player = player
        self.bet = bet
        self.cog = cog
        self.deck = self.create_deck()
        self.player_hand = []
        self.dealer_hand = []
        self.game_over = False
        
        # Раздаем начальные карты
        self.player_hand.append(self.draw_card())
        self.dealer_hand.append(self.draw_card())
        self.player_hand.append(self.draw_card())
        self.dealer_hand.append(self.draw_card())
    
    def create_deck(self):
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [{'rank': r, 'suit': s} for s in suits for r in ranks]
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
            rank = card['rank']
            if rank in ['J', 'Q', 'K']:
                value += 10
            elif rank == 'A':
                aces += 1
            else:
                value += int(rank)
        
        for _ in range(aces):
            if value + 11 <= 21:
                value += 11
            else:
                value += 1
        return value
    
    def hand_to_string(self, hand, hide_first=False):
        if hide_first:
            return f"🎴 [??] {hand[1]['rank']}{hand[1]['suit']}"
        return ' '.join([f"{card['rank']}{card['suit']}" for card in hand])
    
    async def update_message(self, interaction, message, status=''):
        embed = discord.Embed(
            title='🎰 Блэкджек',
            color=discord.Color.green()
        )
        embed.add_field(
            name=f'Ваша рука ({self.hand_value(self.player_hand)})',
            value=self.hand_to_string(self.player_hand),
            inline=False
        )
        
        dealer_value = self.hand_value(self.dealer_hand) if not status else self.hand_value(self.dealer_hand)
        embed.add_field(
            name=f'Рука дилера ({dealer_value})',
            value=self.hand_to_string(self.dealer_hand, hide_first=not self.game_over),
            inline=False
        )
        
        if status:
            embed.add_field(name='Результат', value=status, inline=False)
        
        embed.set_footer(text=f'Ставка: {self.bet} 🪙')
        await interaction.edit_original_response(embed=embed, view=self if not self.game_over else None)
    
    @discord.ui.button(label='Взять', style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message('Это не ваша игра!', ephemeral=True)
            return
        
        self.player_hand.append(self.draw_card())
        
        if self.hand_value(self.player_hand) > 21:
            self.game_over = True
            self.cog.remove_money(interaction.guild.id, self.player.id, self.bet)
            await self.update_message(interaction, 'Перебор! Вы проиграли 😢')
            self.stop()
        else:
            await self.update_message(interaction)
            await interaction.response.defer()
    
    @discord.ui.button(label='Хватит', style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.player.id:
            await interaction.response.send_message('Это не ваша игра!', ephemeral=True)
            return
        
        self.game_over = True
        
        # Дилер добирает до 17
        while self.hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.draw_card())
        
        player_value = self.hand_value(self.player_hand)
        dealer_value = self.hand_value(self.dealer_hand)
        
        if dealer_value > 21:
            status = 'У дилера перебор! Вы выиграли! 🎉'
            self.cog.add_money(interaction.guild.id, self.player.id, self.bet * 2)
        elif player_value > dealer_value:
            status = 'Вы выиграли! 🎉'
            self.cog.add_money(interaction.guild.id, self.player.id, self.bet * 2)
        elif player_value == dealer_value:
            status = 'Ничья! Ставка возвращена 🤝'
            self.cog.add_money(interaction.guild.id, self.player.id, self.bet)
        else:
            status = 'Дилер выиграл! 😢'
            self.cog.remove_money(interaction.guild.id, self.player.id, self.bet)
        
        await self.update_message(interaction, status)
        self.stop()
        await interaction.response.defer()

class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.economy_db = JSONHandler('data/economy.json')
    
    def get_user_data(self, guild_id: int, user_id: int):
        key = f"{guild_id}.{user_id}"
        data = self.economy_db.get(key, {})
        if not data:
            data = {'balance': 1000, 'bank': 0}
            self.economy_db.set(key, data)
        return data
    
    def add_money(self, guild_id: int, user_id: int, amount: int):
        data = self.get_user_data(guild_id, user_id)
        data['balance'] += amount
        self.economy_db.set(f"{guild_id}.{user_id}", data)
    
    def remove_money(self, guild_id: int, user_id: int, amount: int):
        data = self.get_user_data(guild_id, user_id)
        data['balance'] = max(0, data['balance'] - amount)
        self.economy_db.set(f"{guild_id}.{user_id}", data)
    
    @app_commands.command(name='coinflip', description='Подбросить монетку')
    async def coinflip(self, interaction: discord.Interaction, bet: int, choice: str):
        if choice.lower() not in ['орел', 'решка', 'heads', 'tails']:
            await interaction.response.send_message('❌ Выберите: орел или решка', ephemeral=True)
            return
        
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data['balance'] < bet or bet <= 0:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        result = random.choice(['орел', 'решка'])
        user_choice = 'орел' if choice.lower() in ['орел', 'heads'] else 'решка'
        
        if result == user_choice:
            winnings = bet * 2
            self.add_money(interaction.guild.id, interaction.user.id, winnings)
            
            embed = discord.Embed(
                title='🪙 Подбрасывание монетки',
                description=f'Выпало: **{result}**',
                color=discord.Color.green()
            )
            embed.add_field(name='Результат', value=f'✅ Вы выиграли **{winnings}** 🪙')
        else:
            self.remove_money(interaction.guild.id, interaction.user.id, bet)
            
            embed = discord.Embed(
                title='🪙 Подбрасывание монетки',
                description=f'Выпало: **{result}**',
                color=discord.Color.red()
            )
            embed.add_field(name='Результат', value=f'❌ Вы проиграли **{bet}** 🪙')
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='dice', description='Бросить кубик')
    async def dice(self, interaction: discord.Interaction, bet: int, number: int):
        if number < 1 or number > 6:
            await interaction.response.send_message('❌ Число должно быть от 1 до 6', ephemeral=True)
            return
        
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data['balance'] < bet or bet <= 0:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        result = random.randint(1, 6)
        
        if result == number:
            winnings = bet * 6
            self.add_money(interaction.guild.id, interaction.user.id, winnings)
            
            embed = discord.Embed(
                title='🎲 Бросок кубика',
                description=f'Выпало: **{result}**',
                color=discord.Color.green()
            )
            embed.add_field(name='Результат', value=f'✅ Джекпот! Выигрыш: **{winnings}** 🪙')
        else:
            self.remove_money(interaction.guild.id, interaction.user.id, bet)
            
            embed = discord.Embed(
                title='🎲 Бросок кубика',
                description=f'Выпало: **{result}**',
                color=discord.Color.red()
            )
            embed.add_field(name='Результат', value=f'❌ Вы проиграли **{bet}** 🪙')
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='slots', description='Игровой автомат')
    async def slots(self, interaction: discord.Interaction, bet: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data['balance'] < bet or bet <= 0:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        emojis = ['🍒', '🍋', '🍊', '🍇', '💎', '7️⃣']
        
        # Определяем выигрышную комбинацию
        if random.random() < 0.1:  # 10% шанс на выигрыш
            # Гарантированный выигрыш
            if random.random() < 0.3:  # Джекпот
                result = ['7️⃣', '7️⃣', '7️⃣']
                multiplier = 10
            else:
                symbol = random.choice(emojis[:4])
                result = [symbol, symbol, symbol]
                multiplier = 3
        else:
            result = [random.choice(emojis) for _ in range(3)]
            multiplier = 0
        
        # Проверка на совпадение двух символов
        if multiplier == 0 and len(set(result)) == 2:
            multiplier = 1.5
        
        if multiplier > 0:
            winnings = int(bet * multiplier)
            self.add_money(interaction.guild.id, interaction.user.id, winnings)
            result_text = f'✅ Выигрыш: **{winnings}** 🪙 (x{multiplier})'
            color = discord.Color.green()
        else:
            self.remove_money(interaction.guild.id, interaction.user.id, bet)
            result_text = f'❌ Проигрыш: **{bet}** 🪙'
            color = discord.Color.red()
        
        embed = discord.Embed(
            title='🎰 Игровой автомат',
            description=f'[ {result[0]} | {result[1]} | {result[2]} ]',
            color=color
        )
        embed.add_field(name='Результат', value=result_text)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='blackjack', description='Блэкджек против дилера')
    async def blackjack(self, interaction: discord.Interaction, bet: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data['balance'] < bet or bet <= 0:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        # Сразу списываем ставку
        self.remove_money(interaction.guild.id, interaction.user.id, bet)
        
        view = BlackjackView(interaction.user, bet, self)
        
        embed = discord.Embed(
            title='🎰 Блэкджек',
            description='Загрузка игры...',
            color=discord.Color.green()
        )
        
        await interaction.response.send_message(embed=embed, view=view)
        await view.update_message(interaction)
    
    @app_commands.command(name='roulette', description='Русская рулетка')
    async def roulette(self, interaction: discord.Interaction, bet: int):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if data['balance'] < bet or bet <= 0:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        # 1 из 6 шанс проиграть
        if random.randint(1, 6) == 1:
            self.remove_money(interaction.guild.id, interaction.user.id, bet)
            embed = discord.Embed(
                title='🔫 Русская рулетка',
                description='💥 **БАХ!** Вы проиграли...',
                color=discord.Color.red()
            )
        else:
            winnings = bet * 2
            self.add_money(interaction.guild.id, interaction.user.id, winnings)
            embed = discord.Embed(
                title='🔫 Русская рулетка',
                description=f'😅 Пронесло! Вы выиграли **{winnings}** 🪙',
                color=discord.Color.green()
            )
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Games(bot))