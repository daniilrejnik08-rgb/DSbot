import glob as glob_module
import logging
import os

import discord
from discord.ext import commands

log = logging.getLogger(__name__)


def _opus_candidate_paths() -> list[str]:
    """Пути к libopus на Debian/Ubuntu/Alpine и кастомных хостингах (bothost и др.)."""
    out: list[str] = []
    env = os.getenv("OPUS_LIBRARY_PATH", "").strip()
    if env:
        out.append(env)

    try:
        import ctypes.util

        found = ctypes.util.find_library("opus")
        if found:
            out.append(found)
    except Exception:
        pass

    out.extend(
        (
            "/usr/lib/x86_64-linux-gnu/libopus.so.0",
            "/usr/lib/aarch64-linux-gnu/libopus.so.0",
            "/lib/x86_64-linux-gnu/libopus.so.0",
            "/lib/aarch64-linux-gnu/libopus.so.0",
            "/usr/lib/libopus.so.0",
            "/lib/libopus.so.0",
            "/usr/lib/libopus.so",
            "libopus.so.0",
        )
    )

    for pattern in (
        "/usr/lib/*/libopus.so.0",
        "/usr/lib/*/libopus.so",
        "/lib/*/libopus.so.0",
        "/lib/*/libopus.so",
    ):
        try:
            out.extend(glob_module.glob(pattern))
        except OSError:
            continue

    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def ensure_opus_loaded() -> bool:
    """Подключает libopus; на хостинге без пакета задайте OPUS_LIBRARY_PATH к файлу .so."""
    try:
        if discord.opus.is_loaded():
            return True
    except AttributeError:
        pass

    for path in _opus_candidate_paths():
        try:
            discord.opus.load_opus(path)
            log.info("Opus загружен (%s)", path)
            return True
        except Exception:
            continue

    log.warning(
        "Opus не загружен — музыка в голосе не будет работать. "
        "В панели bothost.ru: установите системный пакет opus/libopus "
        "(или соберите образ с ffmpeg + libopus0 / apk add opus) "
        "либо укажите полный путь к библиотеке в переменной OPUS_LIBRARY_PATH."
    )
    return False


try:
    from utils.theme import BRAND
except Exception:
    BRAND = discord.Color.blurple()


class ProBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix='!',
            intents=intents,
            help_command=None,
            case_insensitive=True
        )

    async def setup_hook(self):
        cogs_dir = "cogs"
        if not os.path.isdir(cogs_dir):
            print("⚠️ Папка cogs не найдена")
            return
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                try:
                    await self.load_extension(f"cogs.{filename[:-3]}")
                    print(f'✅ Загружен ког: {filename[:-3]}')
                except Exception as e:
                    print(f'❌ Ошибка загрузки {filename}: {e}')

        await self.tree.sync()
        print('🌍 Слеш-команды синхронизированы')

    async def on_ready(self):
        print(f'''
╔══════════════════════════════════════╗
║  🤖 Бот запущен: {self.user.name}
║  📊 Серверов: {len(self.guilds)}
║  👥 Пользователей: {len(self.users)}
║  💾 База данных: JSON
╚══════════════════════════════════════╝
        ''')

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f'{len(self.guilds)} серверов | /help'
            )
        )

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Недостаточно прав для этой команды.")
            return
        if isinstance(error, commands.CheckFailure):
            return
        log.exception("Prefix command error: %s", error)


bot = ProBot()


@bot.tree.command(name='help', description='Показать все команды бота')
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title='🤖 Помощь по командам',
        color=BRAND,
        description='Единая экономика 🪙 на все мини-игры, рынок и активности.',
    )

    embed.add_field(
        name='💰 Экономика',
        value='`/balance`, `/daily`, `/work`, `/pay`, `/deposit`, `/withdraw`, `/rob`, `/leaderboard`, `/shop`, `/buy`, `/inventory`, `/audit_risk`',
        inline=False
    )
    embed.add_field(
        name='👤 Профиль',
        value='`/profile` (картинка с аниме-фоном), `/daily_login`',
        inline=False
    )
    embed.add_field(
        name='🛡️ Кланы',
        value='`/clan_create`, `/clan_join`, `/clan_info`, `/clan_bank_deposit`, `/clan_quest_claim`, `/clan_war`, `/clan_top`',
        inline=False
    )
    embed.add_field(
        name='🛡️ Модерация',
        value='`/warn`, `/warnings`, `/clearwarn`, `/kick`, `/ban`, `/mute`, `/unmute`, `/purge`, `/botsay`, `!say`',
        inline=False
    )
    embed.add_field(
        name='🎮 Игры',
        value='`/coinflip`, `/dice`, `/slots`, `/blackjack`, `/roulette`, `/guess`, `/rps`, `/wheel`, `/crash`, `/highlow`, `/trivia`, `/plinko`, `/mines`, `/duel`, `/boss_join`',
        inline=False
    )
    embed.add_field(
        name='🏪 Рынок и крафт',
        value='`/market_sell`, `/market_list`, `/market_buy`, `/market_history`, `/tree_craft`, `/tree_use_item`',
        inline=False
    )
    embed.add_field(
        name='🌲 Grow a Tree',
        value='`/tree`, `/tree_water`, `/tree_fertilize`, `/tree_prune`, `/tree_cure`, `/tree_harvest`, `/tree_seed`, `/tree_quest`, `/tree_top`, `/tree_panel_setup`',
        inline=False
    )
    embed.add_field(
        name='🎤 Голосовые',
        value='`/voice_setup`, `/voice_toggle` + панель кнопок приватных комнат',
        inline=False
    )
    embed.add_field(
        name='🎵 Музыка',
        value='`/play` (поиск/ссылка/файл), `/mix`, `/queue`, `/music_queue`, `/skip`, `/pause`, `/resume`, `/volume`, `/stopmusic`, `/leave`',
        inline=False
    )
    embed.add_field(
        name='⚙️ Сервер и сезоны',
        value='`/season_status`, `/season_roll`, `/battlepass_claim`, `/autorole_set`, `/welcome_set`, `/modlog_set`, `/ticket_setup`, `/webpanel_token`',
        inline=False
    )
    embed.add_field(
        name='🎯 Мониторинг CS / Minecraft',
        value='`/servers`, `/server_add`, `/server_remove`, `/server_edit`, `/server_list`, `/servers_panel_setup`, `/servers_refresh`',
        inline=False
    )
    embed.add_field(
        name='🧠 ИИ-чат',
        value='`/chat` — общение с ИИ',
        inline=False
    )

    avatar = interaction.user.display_avatar.url if interaction.user.display_avatar else None
    embed.set_footer(text=f'Запрошено: {interaction.user.name}', icon_url=avatar)
    await interaction.response.send_message(embed=embed)


def run_bot() -> None:
    ensure_opus_loaded()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Переменная окружения DISCORD_TOKEN не задана.")
    bot.run(token)


if __name__ == '__main__':
    run_bot()
