from __future__ import annotations

import os

import discord

DEFAULT_GUILD_IDS = "573548126506451006,1489984514447900792"


def _parse_guild_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            gid = int(token)
        except ValueError:
            continue
        if gid > 0:
            out.append(gid)
    # сохраняем порядок и убираем дубли
    return list(dict.fromkeys(out))


def target_guilds() -> list[discord.Object] | None:
    """
    Возвращает список guild-объектов для точечной регистрации slash-команд.
    Поддерживает:
    - GUILD_IDS / DISCORD_GUILD_IDS (несколько id через запятую)
    - GUILD_ID / DISCORD_GUILD_ID (один id)
    """
    parts: list[str] = []
    for key in ("GUILD_IDS", "DISCORD_GUILD_IDS", "GUILD_ID", "DISCORD_GUILD_ID"):
        val = (os.getenv(key) or "").strip()
        if val:
            parts.append(val)
    raw = ",".join(parts).strip()
    if not raw:
        raw = DEFAULT_GUILD_IDS
    if not raw:
        return None
    ids = _parse_guild_ids(raw)
    if not ids:
        return None
    return [discord.Object(id=gid) for gid in ids]


def target_guild() -> discord.Object | None:
    """
    Если задана переменная окружения GUILD_ID (или DISCORD_GUILD_ID),
    регистрируем slash-команды как guild-команды (быстро и без лимита 100 глобальных).
    """
    guilds = target_guilds()
    if not guilds:
        return None
    # Для обратной совместимости старого API возвращаем первый guild.
    # Если задано несколько серверов, в когаx лучше использовать target_guilds().
    if len(guilds) != 1:
        return None
    return guilds[0]

