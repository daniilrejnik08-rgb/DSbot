import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from utils import JSONHandler
import asyncio

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.warnings_db = JSONHandler('data/warnings.json')
        self.mutes_db = JSONHandler('data/mutes.json')
    
    @app_commands.command(name='warn', description='Выдать предупреждение')
    @app_commands.default_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message('❌ Нельзя предупредить этого пользователя', ephemeral=True)
            return
        
        guild_id = str(interaction.guild.id)
        user_id = str(member.id)
        
        # Получаем текущие предупреждения
        warnings = self.warnings_db.get_nested(guild_id, user_id, default=[])
        
        # Добавляем новое
        warning = {
            'moderator': interaction.user.id,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'id': len(warnings) + 1
        }
        warnings.append(warning)
        
        self.warnings_db.set_nested(warnings, guild_id, user_id)
        
        embed = discord.Embed(
            title='⚠️ Предупреждение',
            description=f'{member.mention} получил предупреждение',
            color=discord.Color.yellow()
        )
        embed.add_field(name='Модератор', value=interaction.user.mention, inline=True)
        embed.add_field(name='Причина', value=reason, inline=True)
        embed.add_field(name='Всего предупреждений', value=str(len(warnings)), inline=True)
        
        await interaction.response.send_message(embed=embed)
        
        # Авто-наказание при 3 предупреждениях
        if len(warnings) == 3:
            try:
                await member.timeout(timedelta(hours=1), reason='3 предупреждения')
                await interaction.channel.send(f'🔨 {member.mention} получил тайм-аут на 1 час за 3 предупреждения')
            except:
                pass
    
    @app_commands.command(name='warnings', description='Посмотреть предупреждения пользователя')
    @app_commands.default_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        guild_id = str(interaction.guild.id)
        user_id = str(member.id)
        
        warnings = self.warnings_db.get_nested(guild_id, user_id, default=[])
        
        if not warnings:
            await interaction.response.send_message(f'✅ У {member.mention} нет предупреждений', ephemeral=True)
            return
        
        embed = discord.Embed(
            title=f'⚠️ Предупреждения {member.display_name}',
            color=discord.Color.orange()
        )
        
        for warn in warnings[-10:]:  # Последние 10
            moderator = interaction.guild.get_member(warn['moderator'])
            mod_name = moderator.mention if moderator else 'Неизвестный'
            date = datetime.fromisoformat(warn['timestamp']).strftime('%d.%m.%Y %H:%M')
            
            embed.add_field(
                name=f'Предупреждение #{warn["id"]}',
                value=f'**Модератор:** {mod_name}\n**Причина:** {warn["reason"]}\n**Дата:** {date}',
                inline=False
            )
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='clearwarn', description='Снять все предупреждения')
    @app_commands.default_permissions(administrator=True)
    async def clearwarn(self, interaction: discord.Interaction, member: discord.Member):
        guild_id = str(interaction.guild.id)
        user_id = str(member.id)
        
        self.warnings_db.set_nested([], guild_id, user_id)
        
        await interaction.response.send_message(f'✅ Предупреждения {member.mention} сняты')
    
    @app_commands.command(name='kick', description='Кикнуть пользователя')
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = 'Нарушение правил'):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message('❌ Нельзя кикнуть этого пользователя', ephemeral=True)
            return
        
        await member.kick(reason=reason)
        
        embed = discord.Embed(
            title='👢 Кик',
            description=f'{member.mention} был кикнут',
            color=discord.Color.red()
        )
        embed.add_field(name='Модератор', value=interaction.user.mention)
        embed.add_field(name='Причина', value=reason)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='ban', description='Забанить пользователя')
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: str = 'Нарушение правил', days: int = 0):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message('❌ Нельзя забанить этого пользователя', ephemeral=True)
            return
        
        await member.ban(reason=reason, delete_message_days=days)
        
        embed = discord.Embed(
            title='🔨 Бан',
            description=f'{member.mention} был забанен',
            color=discord.Color.dark_red()
        )
        embed.add_field(name='Модератор', value=interaction.user.mention)
        embed.add_field(name='Причина', value=reason)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='mute', description='Замутить пользователя')
    @app_commands.default_permissions(moderate_members=True)
    async def mute(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = 'Нарушение правил'):
        if member.top_role >= interaction.user.top_role:
            await interaction.response.send_message('❌ Нельзя замутить этого пользователя', ephemeral=True)
            return
        
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        
        embed = discord.Embed(
            title='🔇 Мут',
            description=f'{member.mention} замьючен на {minutes} мин',
            color=discord.Color.orange()
        )
        embed.add_field(name='Модератор', value=interaction.user.mention)
        embed.add_field(name='Причина', value=reason)
        
        await interaction.response.send_message(embed=embed)
    
    @app_commands.command(name='unmute', description='Размутить пользователя')
    @app_commands.default_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f'✅ {member.mention} размьючен')
    
    @app_commands.command(name='purge', description='Очистить сообщения')
    @app_commands.default_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: int):
        if amount < 1 or amount > 100:
            await interaction.response.send_message('❌ Можно удалить от 1 до 100 сообщений', ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        deleted = await interaction.channel.purge(limit=amount)
        
        await interaction.followup.send(f'✅ Удалено {len(deleted)} сообщений', ephemeral=True)

async def setup(bot):
    await bot.add_cog(Moderation(bot))