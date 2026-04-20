from __future__ import annotations

import os

import discord


def target_guild() -> discord.Object | None:
    """
    Если задана переменная окружения GUILD_ID (или DISCORD_GUILD_ID),
    регистрируем slash-команды как guild-команды (быстро и без лимита 100 глобальных).
    """
    raw = (os.getenv("GUILD_ID") or os.getenv("1489984514447900792") or "").strip()
    if not raw:
        return None
    try:
        gid = int(raw)
    except ValueError:
        return None
    if gid <= 0:
        return None
    return discord.Object(id=gid)

