from __future__ import annotations

from typing import Any

from utils.json_handler import JSONHandler

ECONOMY_PATH = "data/economy.json"
DEFAULT_BALANCE = 2000


def _default_user() -> dict[str, Any]:
    return {
        "balance": DEFAULT_BALANCE,
        "bank": 0,
        "inventory": [],
        "last_daily": None,
        "last_work": None,
        "suspicion": 0,
    }


class Wallet:
    """Единая экономика сервера: один JSON и одинаковая структура пользователя."""

    _db: JSONHandler | None = None

    @classmethod
    def db(cls) -> JSONHandler:
        if cls._db is None:
            cls._db = JSONHandler(ECONOMY_PATH)
        return cls._db

    @classmethod
    def user_key(cls, guild_id: int, user_id: int) -> str:
        return f"{guild_id}.{user_id}"

    @classmethod
    def get(cls, guild_id: int, user_id: int) -> dict[str, Any]:
        key = cls.user_key(guild_id, user_id)
        data = cls.db().get(key, {})
        if not data:
            data = _default_user()
            cls.db().set(key, data)
            return data
        for k, v in _default_user().items():
            if k not in data:
                data[k] = v
        return data

    @classmethod
    def save(cls, guild_id: int, user_id: int, data: dict[str, Any]) -> None:
        cls.db().set(cls.user_key(guild_id, user_id), data)

    @classmethod
    def add_balance(cls, guild_id: int, user_id: int, amount: int) -> dict[str, Any]:
        d = cls.get(guild_id, user_id)
        d["balance"] += amount
        cls.save(guild_id, user_id, d)
        return d

    @classmethod
    def remove_balance(cls, guild_id: int, user_id: int, amount: int) -> dict[str, Any]:
        d = cls.get(guild_id, user_id)
        d["balance"] = max(0, d["balance"] - amount)
        cls.save(guild_id, user_id, d)
        return d

    @classmethod
    def guild_leaderboard(cls, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        prefix = f"{guild_id}."
        rows: list[tuple[int, int]] = []
        for key, data in cls.db().data.items():
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            rest = key[len(prefix) :]
            try:
                uid = int(rest)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            total = int(data.get("balance", 0)) + int(data.get("bank", 0))
            rows.append((uid, total))
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows[:limit]
