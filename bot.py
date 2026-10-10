import glob as glob_module
import logging
import os

import discord
from discord.ext.commands.errors import ExtensionFailed
from discord.ext import commands
from discord.app_commands.errors import CommandLimitReached
from utils import target_guilds

log = logging.getLogger(__name__)


def _parse_disabled_commands(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.replace(";", ",").split(","):
        name = part.strip().lower().lstrip("/")
        if name:
            out.append(name)
    # preserve order, drop duplicates
    return list(dict.fromkeys(out))


def _disabled_app_commands() -> list[str]:
    """
    Список slash-команд для отключения из регистрации.
    Можно задать через DISABLED_APP_COMMANDS: "eco_select,audit_risk,..."
    """
    raw = os.getenv("DISABLED_APP_COMMANDS", "").strip()
    if not raw:
        # По умолчанию убираем дублирующее меню экономики.
        return ["eco_select"]
    return _parse_disabled_commands(raw)


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
            log.warning("Папка cogs не найдена")
            return
        # На бесплатных/ограниченных хостингах часто упираемся в лимит 100 глобальных slash-команд.
        # Поэтому по умолчанию загружаем "облегчённый" набор; нужные коги можно включить через env.
        default_disabled_cogs = {
            "games",       # много мини-игр (много slash-команд)
            "media",       # музыка/аудио команды
            "cs_monitor",  # мониторинг серверов
            "grow_tree",   # дерево (много команд)
            "market",      # рынок
            "tree_craft",  # крафт дерева
            "automation",  # авто-настройки
            "webpanel",    # webpanel токены
            "combat",      # боевка
        }
        enabled_env = os.getenv("ENABLED_COGS", "").strip()
        enabled_set: set[str] | None = None
        if enabled_env:
            enabled_set = {x.strip().lower() for x in enabled_env.split(",") if x.strip()}
            log.info("ENABLED_COGS активен: %s", ", ".join(sorted(enabled_set)))
        disabled_env = os.getenv("DISABLED_COGS", "").strip()
        disabled_set: set[str] = set(default_disabled_cogs)
        if disabled_env:
            disabled_set.update({x.strip().lower() for x in disabled_env.split(",") if x.strip()})
            log.info("DISABLED_COGS активен: %s", ", ".join(sorted(disabled_set)))
        lite_mode = (os.getenv("LITE_MODE", "1").strip().lower() not in {"0", "false", "off", "no"})
        if not lite_mode:
            disabled_set.clear()
            log.info("LITE_MODE выключен: попытка загрузить все коги")
        else:
            log.info("LITE_MODE включен: по умолчанию отключены второстепенные коги")

        files = [f for f in os.listdir(cogs_dir) if f.endswith(".py") and not f.startswith("__")]
        # Сначала важные коги, чтобы при лимите slash-команд первыми были профиль/экономика/игры.
        priority = [
            "profile.py",
            "economy.py",
            "games.py",
            "media.py",
        ]
        files.sort(key=lambda x: (priority.index(x) if x in priority else 999, x))

        for filename in files:
            if filename.endswith(".py") and not filename.startswith("__"):
                cog_name = filename[:-3]
                if enabled_set is not None and cog_name.lower() not in enabled_set:
                    log.info("Пропуск кога %s (не входит в ENABLED_COGS)", cog_name)
                    continue
                if enabled_set is None and cog_name.lower() in disabled_set:
                    log.info("Пропуск кога %s (облегчённый режим)", cog_name)
                    continue
                try:
                    await self.load_extension(f"cogs.{cog_name}")
                    log.info("Загружен ког: %s", cog_name)
                except CommandLimitReached as e:
                    log.error(
                        "Достигнут лимит slash-команд (%s) при загрузке %s. "
                        "Останавливаю загрузку оставшихся когов.",
                        e.limit,
                        filename,
                    )
                    break
                except ExtensionFailed as e:
                    cause = getattr(e, "__cause__", None)
                    if isinstance(cause, CommandLimitReached):
                        log.error(
                            "Достигнут лимит slash-команд (%s) при загрузке %s. "
                            "Останавливаю загрузку оставшихся когов.",
                            cause.limit,
                            filename,
                        )
                        break
                    log.exception("Ошибка загрузки %s: %s", filename, e)
                except Exception as e:
                    log.exception("Ошибка загрузки %s: %s", filename, e)
        print(f"[setup] cogs scanned={len(files)}")

        disabled_cmds = _disabled_app_commands()
        if disabled_cmds:
            for cmd_name in disabled_cmds:
                removed = self.tree.remove_command(cmd_name)
                if removed is not None:
                    log.info("Отключена глобальная slash-команда: /%s", cmd_name)
            guild_targets = target_guilds() or []
            for guild in guild_targets:
                for cmd_name in disabled_cmds:
                    removed = self.tree.remove_command(cmd_name, guild=guild)
                    if removed is not None:
                        log.info("Отключена guild slash-команда: /%s (guild=%s)", cmd_name, guild.id)

        # Sync делаем в on_ready (после подключения), один раз.
        self._synced_once = False

    async def _sync_all(self) -> list[str]:
        """Скопировать tree на гильдии и засинкать. Возвращает лог-строки."""
        lines: list[str] = []
        try:
            cmds = list(self.tree.walk_commands())
            names = [c.qualified_name for c in cmds]
            lines.append(f"tree={len(names)} :: {', '.join(names[:40])}")
            print(f"[sync] {lines[-1]}")
        except Exception as e:
            lines.append(f"walk_error={e}")

        # гильдии из env + все, где бот уже сидит
        targets = target_guilds() or []
        guild_objs: list[discord.Object] = list(targets)
        seen = {g.id for g in guild_objs}
        for g in self.guilds:
            if g.id not in seen:
                guild_objs.append(discord.Object(id=g.id))
                seen.add(g.id)

        if not guild_objs:
            # нет гильдий — только global
            try:
                synced = await self.tree.sync()
                lines.append(f"global_sync={len(synced)}")
                print(f"[sync][global] {len(synced)}")
            except Exception as e:
                lines.append(f"global_fail={e}")
                print(f"[sync][global] fail {e}")
            return lines

        for gobj in guild_objs:
            try:
                self.tree.copy_global_to(guild=gobj)
                synced = await self.tree.sync(guild=gobj)
                lines.append(f"guild={gobj.id} synced={len(synced)}")
                print(f"[sync][guild] id={gobj.id} commands={len(synced)}")
            except Exception as e:
                lines.append(f"guild={gobj.id} fail={e}")
                print(f"[sync][guild] fail id={gobj.id} {e}")

        # global тоже (фон)
        try:
            synced = await self.tree.sync()
            lines.append(f"global_sync={len(synced)}")
            print(f"[sync][global] commands={len(synced)}")
        except Exception as e:
            lines.append(f"global_fail={e}")
            print(f"[sync][global] fail {e}")
        return lines

    async def on_ready(self):
        log.info(
            "Бот запущен: %s | серверов=%s",
            getattr(self.user, "name", "?"),
            len(self.guilds),
        )
        print(f"[ready] user={getattr(self.user, 'name', '?')} guilds={len(self.guilds)}")

        if not getattr(self, "_synced_once", False):
            self._synced_once = True
            try:
                await self._sync_all()
            except Exception:
                log.exception("sync_all failed")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} серверов | /help | !sync",
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

@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def prefix_sync(ctx: commands.Context):
    """Принудительный sync slash-команд (если / не видно)."""
    msg = await ctx.send("⏳ Синхронизация slash-команд…")
    try:
        lines = await bot._sync_all()
        text = "\n".join(lines)[:1800]
        await msg.edit(content=f"✅ Sync готов:\n```\n{text}\n```")
    except Exception as e:
        await msg.edit(content=f"❌ Sync error: `{e}`")


@bot.command(name="cmds")
@commands.has_permissions(administrator=True)
async def prefix_cmds(ctx: commands.Context):
    """Список команд в tree (диагностика)."""
    names = sorted({c.qualified_name for c in bot.tree.walk_commands()})
    cogs = sorted(bot.cogs.keys())
    chunk = ", ".join(f"/{n}" for n in names[:60])
    extra = f" … +{len(names)-60}" if len(names) > 60 else ""
    await ctx.send(
        f"**Cogs ({len(cogs)}):** {', '.join(cogs)}\n"
        f"**Slash ({len(names)}):** {chunk}{extra}"
    )






@bot.tree.command(name='sync', description='Принудительно синхронизировать slash-команды (админ)')
@discord.app_commands.default_permissions(administrator=True)
async def sync_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        if interaction.guild:
            bot.tree.copy_global_to(guild=interaction.guild)
            synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(
                f"✅ Синхронизировано **{len(synced)}** команд на этот сервер.\n"
                f"Примеры: {', '.join('/' + c.name for c in synced[:15])}…",
                ephemeral=True,
            )
        else:
            synced = await bot.tree.sync()
            await interaction.followup.send(
                f"✅ Глобальный sync: **{len(synced)}** команд (может занять до часа).",
                ephemeral=True,
            )
    except Exception as e:
        await interaction.followup.send(f"❌ Ошибка sync: `{e}`", ephemeral=True)


@bot.tree.command(name='help', description='Показать все команды бота')
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title='🤖 Помощь по командам',
        color=BRAND,
        description='Единая экономика 🪙 на все мини-игры, рынок и активности.',
    )

    embed.add_field(
        name='💰 Экономика',
        value='`/economy_hub` (панель кнопками), `/balance`, `/daily`, `/work`, `/pay`, `/deposit`, `/withdraw`, `/rob`, `/leaderboard`, `/shop`, `/buy`, `/inventory`, `/audit_risk`',
        inline=False
    )
    embed.add_field(
        name='👤 Профиль',
        value='`/profile` (картинка + кнопки), `/daily_login`, фоны (`/profile_bg_*`), `/rep`, `/achievement_claim`',
        inline=False
    )
    embed.add_field(
        name='🛡️ Кланы',
        value='`/clan_create`, `/clan_join`, `/clan_info`, `/clan_show`, `/clan_bank_deposit`, `/clan_quest_claim`, `/clan_war`, `/clan_top`',
        inline=False
    )
    embed.add_field(
        name='🛡️ Модерация',
        value='`/warn`, `/warnings`, `/clearwarn`, `/kick`, `/ban`, `/mute`, `/unmute`, `/purge`, `/botsay`, `!say`',
        inline=False
    )
    embed.add_field(
        name='🎮 Игры',
        value='Ставки с баланса 🪙 — `/coinflip`, `/dice`, `/slots`, `/blackjack`, `/roulette`, `/guess`, `/rps`, `/wheel`, `/crash`, `/highlow`, `/trivia`, `/plinko`, `/mines`, `/duel`, `/boss_join`',
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
        value='`/voice_setup`, `/voice_customize`, `/voice_prefs`, `/voice_panel`, `/voice_claim`, `/voice_repost_panel` + панель',
        inline=False
    )
    embed.add_field(
        name='🎵 Музыка',
        value='`/play` (поиск/ссылка/файл), `/mix`, `/queue`, `/music_queue`, `/skip`, `/pause`, `/resume`, `/volume`, `/stopmusic`, `/leave`',
        inline=False
    )
    embed.add_field(
        name='⚙️ Сервер и сезоны',
        value='`/season_status`, `/season_roll`, `/battlepass_claim`, `/autorole_set`, `/welcome_set`, `/modlog_set`, `/webpanel_token`',
        inline=False
    )
    embed.add_field(
        name='🎯 Мониторинг CS / Minecraft',
        value='`/servers`, `/server_add`, `/server_remove`, `/server_edit`, `/server_list`, `/servers_panel_setup`, `/servers_refresh`',
        inline=False
    )
    embed.add_field(
        name='🎉 Розыгрыши · Тикеты · Инвайты · XP · Анкеты',
        value=(
            '`/gstart` `/gend` `/greroll` · '
            '`/ticket_setup` `/ticket_add` `/ticket_close` · '
            '`/invites` `/invite_leaderboard` `/invite_setup` · '
            '`/rank` `/levels_top` `/level_setup` · '
            '`/form_setup` `/form_panel` `/form_questions` `/form_list`'
        ),
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
    guilds = target_guilds()
    if guilds:
        guild_ids = ", ".join(str(g.id) for g in guilds)
        log.info("Guild-режим slash-команд: %s", guild_ids)
        print(f"[config] guild_mode={guild_ids}")
    else:
        log.warning(
            "GUILD_ID/GUILD_IDS не заданы — бот попытается регистрировать slash-команды глобально (лимит 100)."
        )
        print("[config] guild_mode=global")
    bot.run(token)


if __name__ == '__main__':
    run_bot()
