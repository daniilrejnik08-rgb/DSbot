import discord
from discord.ext import commands
from discord import app_commands
from utils import JSONHandler

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.shop_db = JSONHandler('data/shop.json')
        self.economy_db = JSONHandler('data/economy.json')
    
    def get_user_data(self, guild_id: int, user_id: int):
        key = f"{guild_id}.{user_id}"
        data = self.economy_db.get(key, {})
        if not data:
            data = {
                'balance': 1000,
                'bank': 0,
                'inventory': []
            }
            self.economy_db.set(key, data)
        return data
    
    @app_commands.command(name='shop', description='Открыть магазин')
    async def shop(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        items = self.shop_db.get(guild_id, {})
        
        if not items:
            embed = discord.Embed(
                title='🛒 Магазин',
                description='В магазине пока нет товаров. Администратор может добавить их командой `/additem`',
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title='🛒 Магазин сервера',
                color=discord.Color.gold()
            )
            
            for item_id, item in items.items():
                role = interaction.guild.get_role(item['role_id'])
                role_name = role.mention if role else 'Роль не найдена'
                embed.add_field(
                    name=f"{item['name']} (ID: {item_id})",
                    value=f'**Цена:** {item["price"]} 🪙\n**Роль:** {role_name}\n**Описание:** {item.get("description", "Нет описания")}',
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='buy', description='Купить предмет из магазина')
    async def buy(self, interaction: discord.Interaction, item_id: int):
        guild_id = str(interaction.guild.id)
        items = self.shop_db.get(guild_id, {})
        
        item_id = str(item_id)
        if item_id not in items:
            await interaction.response.send_message('❌ Товар не найден', ephemeral=True)
            return
        
        item = items[item_id]
        user_data = self.get_user_data(interaction.guild.id, interaction.user.id)
        
        if user_data['balance'] < item['price']:
            await interaction.response.send_message('❌ Недостаточно средств', ephemeral=True)
            return
        
        role = interaction.guild.get_role(item['role_id'])
        if not role:
            await interaction.response.send_message('❌ Роль не найдена на сервере', ephemeral=True)
            return
        
        if role in interaction.user.roles:
            await interaction.response.send_message('❌ У вас уже есть эта роль', ephemeral=True)
            return
        
        # Списываем деньги
        user_data['balance'] -= item['price']
        
        # Добавляем в инвентарь
        if 'inventory' not in user_data:
            user_data['inventory'] = []
        user_data['inventory'].append(item_id)
        
        self.economy_db.set(f"{interaction.guild.id}.{interaction.user.id}", user_data)
        
        # Выдаем роль
        try:
            await interaction.user.add_roles(role)
        except:
            await interaction.response.send_message('❌ Ошибка выдачи роли', ephemeral=True)
            return
        
        embed = discord.Embed(
            title='✅ Покупка успешна',
            description=f'Вы купили **{item["name"]}** за {item["price"]} 🪙',
            color=discord.Color.green()
        )
        embed.add_field(name='Полученная роль', value=role.mention)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='inventory', description='Посмотреть инвентарь')
    async def inventory(self, interaction: discord.Interaction, member: discord.Member = None):
        if member is None:
            member = interaction.user
        
        user_data = self.get_user_data(interaction.guild.id, member.id)
        inventory = user_data.get('inventory', [])
        
        if not inventory:
            embed = discord.Embed(
                title='🎒 Инвентарь',
                description=f'У {member.display_name} пока нет предметов',
                color=discord.Color.blue()
            )
        else:
            guild_id = str(interaction.guild.id)
            items = self.shop_db.get(guild_id, {})
            
            description = ''
            for item_id in inventory:
                item = items.get(item_id, {'name': 'Неизвестный предмет'})
                description += f'• {item["name"]}\n'
            
            embed = discord.Embed(
                title=f'🎒 Инвентарь {member.display_name}',
                description=description,
                color=discord.Color.purple()
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='additem', description='Добавить товар в магазин')
    @app_commands.default_permissions(administrator=True)
    async def additem(self, interaction: discord.Interaction, name: str, price: int, role: discord.Role, description: str = 'Нет описания'):
        guild_id = str(interaction.guild.id)
        items = self.shop_db.get(guild_id, {})
        
        # Генерируем ID
        item_id = str(len(items) + 1)
        while item_id in items:
            item_id = str(int(item_id) + 1)
        
        items[item_id] = {
            'name': name,
            'price': price,
            'role_id': role.id,
            'description': description
        }
        
        self.shop_db.set(guild_id, items)
        
        embed = discord.Embed(
            title='✅ Товар добавлен',
            description=f'**{name}** добавлен в магазин',
            color=discord.Color.green()
        )
        embed.add_field(name='ID', value=item_id, inline=True)
        embed.add_field(name='Цена', value=f'{price} 🪙', inline=True)
        embed.add_field(name='Роль', value=role.mention, inline=True)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='removeitem', description='Удалить товар из магазина')
    @app_commands.default_permissions(administrator=True)
    async def removeitem(self, interaction: discord.Interaction, item_id: int):
        guild_id = str(interaction.guild.id)
        items = self.shop_db.get(guild_id, {})
        
        item_id = str(item_id)
        if item_id not in items:
            await interaction.response.send_message('❌ Товар не найден', ephemeral=True)
            return
        
        item_name = items[item_id]['name']
        del items[item_id]
        self.shop_db.set(guild_id, items)
        
        await interaction.response.send_message(f'✅ Товар **{item_name}** удален из магазина')

async def setup(bot):
    await bot.add_cog(Shop(bot))