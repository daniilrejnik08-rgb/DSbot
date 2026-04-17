import discord
from discord.ext import commands
from discord import app_commands
import random
import time
from datetime import datetime, timedelta
from utils import JSONHandler

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = JSONHandler('data/economy.json')
        self.cooldowns = {}
    
    def get_user_data(self, guild_id: int, user_id: int):
        """Получить данные пользователя"""
        key = f"{guild_id}.{user_id}"
        data = self.db.get(key, {})
        if not data:
            data = {
                'balance': 1000,  # Стартовый баланс
                'bank': 0,
                'last_daily': None,
                'last_work': None,
                'inventory': []
            }
            self.db.set(key, data)
        return data
    
    def save_user_data(self, guild_id: int, user_id: int, data: dict):
        """Сохранить данные пользователя"""
        self.db.set(f"{guild_id}.{user_id}", data)
    
    @app_commands.command(name='balance', description='Проверить баланс')
    async def balance(self, interaction: discord.Interaction, member: discord.Member = None):
        if member is None:
            member = interaction.user
        
        data = self.get_user_data(interaction.guild.id, member.id)
        
        embed = discord.Embed(
            title=f'💰 Баланс {member.display_name}',
            color=discord.Color.gold()
        )
        embed.add_field(name='💵 Наличные', value=f'{data["balance"]:,} 🪙', inline=True)
        embed.add_field(name='🏦 Банк', value=f'{data["bank"]:,} 🪙', inline=True)
        embed.add_field(name='💎 Всего', value=f'{data["balance"] + data["bank"]:,} 🪙', inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='daily', description='Получить ежедневный бонус')
    async def daily(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        # Проверка кулдауна
        if data['last_daily']:
            last = datetime.fromisoformat(data['last_daily'])
            if datetime.now() - last < timedelta(hours=24):
                remaining = timedelta(hours=24) - (datetime.now() - last)
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                await interaction.response.send_message(
                    f'⏰ Следующий бонус через {hours}ч {minutes}мин',
                    ephemeral=True
                )
                return
        
        # Случайный бонус
        bonus = random.randint(500, 2000)
        data['balance'] += bonus
        data['last_daily'] = datetime.now().isoformat()
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        
        embed = discord.Embed(
            title='🎁 Ежедневный бонус',
            description=f'Вы получили **{bonus}** 🪙!',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='pay', description='Перевести деньги пользователю')
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if member == interaction.user:
            await interaction.response.send_message('❌ Нельзя перевести деньги себе', ephemeral=True)
            return
        
        if amount <= 0:
            await interaction.response.send_message('❌ Сумма должна быть положительной', ephemeral=True)
            return
        
        sender_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        if sender_data['balance'] < amount:
            await interaction.response.send_message('❌ Недостаточно наличных', ephemeral=True)
            return
        
        receiver_data = self.get_user_data(interaction.guild.id, member.id)
        
        sender_data['balance'] -= amount
        receiver_data['balance'] += amount
        
        self.save_user_data(interaction.guild.id, interaction.user.id, sender_data)
        self.save_user_data(interaction.guild.id, member.id, receiver_data)
        
        embed = discord.Embed(
            title='💸 Перевод средств',
            description=f'{interaction.user.mention} перевел {member.mention} **{amount}** 🪙',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='work', description='Заработать деньги работой')
    async def work(self, interaction: discord.Interaction):
        data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        # Проверка кулдауна (1 час)
        if data['last_work']:
            last = datetime.fromisoformat(data['last_work'])
            if datetime.now() - last < timedelta(hours=1):
                remaining = timedelta(hours=1) - (datetime.now() - last)
                minutes = remaining.seconds // 60
                await interaction.response.send_message(
                    f'⏰ Вы устали! Отдохните ещё {minutes} мин',
                    ephemeral=True
                )
                return
        
        jobs = [
            ('Программист', (100, 500)),
            ('Таксист', (50, 300)),
            ('Строитель', (80, 400)),
            ('Бариста', (40, 250)),
            ('Фрилансер', (60, 350)),
        ]
        
        job, (min_salary, max_salary) = random.choice(jobs)
        salary = random.randint(min_salary, max_salary)
        
        # Шанс премии
        if random.random() < 0.1:  # 10% шанс
            salary *= 2
            bonus_text = '🎉 **ПРЕМИЯ!** '
        else:
            bonus_text = ''
        
        data['balance'] += salary
        data['last_work'] = datetime.now().isoformat()
        self.save_user_data(interaction.guild.id, interaction.user.id, data)
        
        embed = discord.Embed(
            title='💼 Работа',
            description=f'Вы поработали **{job}** и заработали {bonus_text}**{salary}** 🪙',
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='rob', description='Попытаться ограбить пользователя')
    async def rob(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            await interaction.response.send_message('❌ Нельзя ограбить себя', ephemeral=True)
            return
        
        # Кулдаун на ограбление
        user_id = interaction.user.id
        if user_id in self.cooldowns:
            if time.time() - self.cooldowns[user_id] < 3600:
                remaining = int(3600 - (time.time() - self.cooldowns[user_id]))
                await interaction.response.send_message(
                    f'⏰ Ограбление будет доступно через {remaining//60} мин',
                    ephemeral=True
                )
                return
        
        robber_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        victim_data = self.get_user_data(interaction.guild.id, member.id)
        
        if victim_data['balance'] < 100:
            await interaction.response.send_message('❌ У цели слишком мало наличных', ephemeral=True)
            return
        
        self.cooldowns[user_id] = time.time()
        
        # Шанс успеха: 40%
        if random.random() < 0.4:
            # Успешное ограбление
            stolen = min(random.randint(50, 300), victim_data['balance'])
            robber_data['balance'] += stolen
            victim_data['balance'] -= stolen
            
            self.save_user_data(interaction.guild.id, interaction.user.id, robber_data)
            self.save_user_data(interaction.guild.id, member.id, victim_data)
            
            embed = discord.Embed(
                title='💰 Успешное ограбление!',
                description=f'Вы украли **{stolen}** 🪙 у {member.mention}',
                color=discord.Color.green()
            )
        else:
            # Провал - штраф
            fine = random.randint(100, 500)
            robber_data['balance'] = max(0, robber_data['balance'] - fine)
            self.save_user_data(interaction.guild.id, interaction.user.id, robber_data)
            
            embed = discord.Embed(
                title='🚔 Провал ограбления',
                description=f'Вас поймали! Штраф: **{fine}** 🪙',
                color=discord.Color.red()
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='leaderboard', description='Топ богачей сервера')
    async def leaderboard(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        
        # Собираем всех пользователей сервера
        users_data = []
        for key, data in self.db.data.get(guild_id, {}).items():
            total = data.get('balance', 0) + data.get('bank', 0)
            users_data.append((int(key), total))
        
        # Сортируем по убыванию
        users_data.sort(key=lambda x: x[1], reverse=True)
        
        embed = discord.Embed(
            title='🏆 Топ богачей сервера',
            color=discord.Color.gold()
        )
        
        description = ''
        for i, (user_id, total) in enumerate(users_data[:10], 1):
            user = interaction.guild.get_member(user_id)
            name = user.display_name if user else f'Пользователь {user_id}'
            
            medals = ['🥇', '🥈', '🥉']
            prefix = medals[i-1] if i <= 3 else f'{i}.'
            description += f'{prefix} **{name}**: {total:,} 🪙\n'
        
        if not description:
            description = 'Пока никто не заработал денег!'
        
        embed.description = description
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Economy(bot))