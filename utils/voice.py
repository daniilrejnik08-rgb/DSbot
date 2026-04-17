import discord
from discord.ext import commands
from discord import app_commands
from utils import JSONHandler
import asyncio

class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_db = JSONHandler('data/temp_channels.json')
        self.temp_channels = {}
    
    @app_commands.command(name='voice', description='Управление временными голосовыми каналами')
    async def voice(self, interaction: discord.Interaction):
        pass
    
    @voice.command(name='setup', description='Настроить создание временных каналов')
    @app_commands.default_permissions(administrator=True)
    async def voice_setup(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        guild_id = str(interaction.guild.id)
        
        config = {
            'creator_channel': channel.id,
            'category': channel.category_id if channel.category else None
        }
        
        self.voice_db.set(guild_id, config)
        
        embed = discord.Embed(
            title='✅ Настройка голосовых каналов',
            description=f'При входе в {channel.mention} будет создаваться временный канал',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
    
    @voice.command(name='lock', description='Закрыть канал от других участников')
    async def voice_lock(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message('❌ Вы не в голосовом канале', ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        guild_id = str(interaction.guild.id)
        
        # Проверяем, является ли канал временным
        temp_channels = self.voice_db.get_nested(guild_id, 'active', default={})
        if str(channel.id) not in temp_channels:
            await interaction.response.send_message('❌ Это не временный канал', ephemeral=True)
            return
        
        if temp_channels[str(channel.id)]['owner'] != interaction.user.id:
            await interaction.response.send_message('❌ Вы не владелец этого канала', ephemeral=True)
            return
        
        # Блокируем канал
        await channel.set_permissions(interaction.guild.default_role, connect=False)
        
        await interaction.response.send_message('🔒 Канал закрыт для других участников', ephemeral=True)
    
    @voice.command(name='unlock', description='Открыть канал для всех')
    async def voice_unlock(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message('❌ Вы не в голосовом канале', ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        guild_id = str(interaction.guild.id)
        
        temp_channels = self.voice_db.get_nested(guild_id, 'active', default={})
        if str(channel.id) not in temp_channels:
            await interaction.response.send_message('❌ Это не временный канал', ephemeral=True)
            return
        
        if temp_channels[str(channel.id)]['owner'] != interaction.user.id:
            await interaction.response.send_message('❌ Вы не владелец этого канала', ephemeral=True)
            return
        
        await channel.set_permissions(interaction.guild.default_role, connect=True)
        await interaction.response.send_message('🔓 Канал открыт для всех', ephemeral=True)
    
    @voice.command(name='kick', description='Выгнать участника из канала')
    async def voice_kick(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice:
            await interaction.response.send_message('❌ Вы не в голосовом канале', ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        guild_id = str(interaction.guild.id)
        
        temp_channels = self.voice_db.get_nested(guild_id, 'active', default={})
        if str(channel.id) not in temp_channels:
            await interaction.response.send_message('❌ Это не временный канал', ephemeral=True)
            return
        
        if temp_channels[str(channel.id)]['owner'] != interaction.user.id:
            await interaction.response.send_message('❌ Вы не владелец этого канала', ephemeral=True)
            return
        
        if member.voice and member.voice.channel == channel:
            await member.move_to(None)
            await interaction.response.send_message(f'👢 {member.mention} выгнан из канала', ephemeral=True)
        else:
            await interaction.response.send_message('❌ Участник не в вашем канале', ephemeral=True)
    
    @voice.command(name='limit', description='Установить лимит участников')
    async def voice_limit(self, interaction: discord.Interaction, limit: int):
        if not interaction.user.voice:
            await interaction.response.send_message('❌ Вы не в голосовом канале', ephemeral=True)
            return
        
        if limit < 1 or limit > 99:
            await interaction.response.send_message('❌ Лимит должен быть от 1 до 99', ephemeral=True)
            return
        
        channel = interaction.user.voice.channel
        guild_id = str(interaction.guild.id)
        
        temp_channels = self.voice_db.get_nested(guild_id, 'active', default={})
        if str(channel.id) not in temp_channels:
            await interaction.response.send_message('❌ Это не временный канал', ephemeral=True)
            return
        
        if temp_channels[str(channel.id)]['owner'] != interaction.user.id:
            await interaction.response.send_message('❌ Вы не владелец этого канала', ephemeral=True)
            return
        
        await channel.edit(user_limit=limit)
        await interaction.response.send_message(f'👥 Лимит участников установлен: {limit}', ephemeral=True)
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # Проверяем, зашел ли участник в канал-создатель
        if after.channel:
            guild_id = str(member.guild.id)
            config = self.voice_db.get(guild_id, {})
            
            if config.get('creator_channel') == after.channel.id:
                # Создаем временный канал
                category = member.guild.get_channel(config['category']) if config.get('category') else after.channel.category
                
                temp_channel = await member.guild.create_voice_channel(
                    name=f'🔊 {member.display_name}',
                    category=category,
                    user_limit=after.channel.user_limit
                )
                
                # Перемещаем создателя
                await member.move_to(temp_channel)
                
                # Сохраняем информацию о канале
                active = self.voice_db.get_nested(guild_id, 'active', default={})
                active[str(temp_channel.id)] = {
                    'owner': member.id,
                    'created': discord.utils.utcnow().isoformat()
                }
                self.voice_db.set_nested(active, guild_id, 'active')
                
                # Даем права владельцу
                await temp_channel.set_permissions(member, connect=True, manage_channels=True, mute_members=True, deafen_members=True, move_members=True)
        
        # Проверяем, не опустел ли временный канал
        if before.channel:
            guild_id = str(member.guild.id)
            active = self.voice_db.get_nested(guild_id, 'active', default={})
            
            if str(before.channel.id) in active:
                if len(before.channel.members) == 0:
                    # Удаляем пустой канал
                    try:
                        await before.channel.delete()
                    except:
                        pass
                    
                    # Удаляем из БД
                    if str(before.channel.id) in active:
                        del active[str(before.channel.id)]
                        self.voice_db.set_nested(active, guild_id, 'active')

async def setup(bot):
    await bot.add_cog(Voice(bot))