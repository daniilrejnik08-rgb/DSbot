"""Единая экономика сервера на JSON (без SQL) с защитой от гонок."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from utils.json_handler import JSONHandler

ECONOMY_PATH = "data/economy.json"
DEFAULT_BALANCE = 2000
_LEDGER_MAX = 45


def _default_user() -> dict[str, Any]:
    return {
        "balance": DEFAULT_BALANCE,
        "bank": 0,
        "inventory": [],
        "last_daily": None,
        "daily_tier": 1,
        "daily_streak": 0,
        "last_work": None,
        "suspicion": 0,
        "ledger": [],
    }


class Wallet:
    """
    Единая экономика: один JSON и одинаковая структура пользователя.

    Все мутации баланса идут через lock на уровне Wallet + JSONHandler,
    чтобы два одновременных /pay или /rob не портили данные.
    """

    _db: JSONHandler | None = None
    _global_lock = threading.RLock()
    # Порядок захвата замков по ключу (guild.user) — защита от deadlock при transfer
    _user_locks: dict[str, threading.RLock] = {}
    _user_locks_guard = threading.Lock()

    @classmethod
    def db(cls) -> JSONHandler:
        if cls._db is None:
            with cls._global_lock:
                if cls._db is None:
                    cls._db = JSONHandler(ECONOMY_PATH)
        return cls._db

    @classmethod
    def user_key(cls, guild_id: int, user_id: int) -> str:
        return f"{guild_id}.{user_id}"

    @classmethod
    def _lock_for(cls, key: str) -> threading.RLock:
        with cls._user_locks_guard:
            lock = cls._user_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                cls._user_locks[key] = lock
            return lock

    @classmethod
    def _normalize(cls, data: dict[str, Any] | None) -> dict[str, Any]:
        if not data:
            return _default_user()
        out = dict(data)
        for k, v in _default_user().items():
            if k not in out:
                out[k] = v
        out["balance"] = int(out.get("balance") or 0)
        out["bank"] = int(out.get("bank") or 0)
        if not isinstance(out.get("inventory"), list):
            out["inventory"] = []
        if not isinstance(out.get("ledger"), list):
            out["ledger"] = []
        return out

    @classmethod
    def get(cls, guild_id: int, user_id: int) -> dict[str, Any]:
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            data = cls.db().get(key)
            if not data:
                data = _default_user()
                cls.db().set(key, data)
                return dict(data)
            normalized = cls._normalize(data)
            if normalized != data:
                cls.db().set(key, normalized)
            return dict(normalized)

    @classmethod
    def _append_ledger(cls, data: dict[str, Any], delta: int, kind: str, note: str = "") -> None:
        if delta == 0:
            return
        entries = data.setdefault("ledger", [])
        if not isinstance(entries, list):
            entries = []
            data["ledger"] = entries
        entries.append(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "k": kind[:32],
                "d": int(delta),
                "n": (note or "")[:96],
            }
        )
        data["ledger"] = entries[-_LEDGER_MAX:]

    @classmethod
    def save(cls, guild_id: int, user_id: int, data: dict[str, Any]) -> None:
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            cls.db().set(key, cls._normalize(data))

    @classmethod
    def log_ledger(cls, guild_id: int, user_id: int, delta: int, kind: str, note: str = "") -> None:
        """Запись в журнал без изменения баланса (банк, переводы и т.п.)."""
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            cls._append_ledger(d, delta, kind, note)
            cls.db().set(key, d)

    @classmethod
    def add_balance(
        cls,
        guild_id: int,
        user_id: int,
        amount: int,
        *,
        ledger: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        amount = int(amount)
        if amount < 0:
            raise ValueError("add_balance: amount must be >= 0")
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            d["balance"] = int(d["balance"]) + amount
            if ledger and amount:
                cls._append_ledger(d, amount, ledger[0], ledger[1])
            cls.db().set(key, d)
            return dict(d)

    @classmethod
    def remove_balance(
        cls,
        guild_id: int,
        user_id: int,
        amount: int,
        *,
        ledger: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        """Списать до 0 (не уходит в минус)."""
        amount = int(amount)
        if amount < 0:
            raise ValueError("remove_balance: amount must be >= 0")
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            before = int(d["balance"])
            d["balance"] = max(0, before - amount)
            spent = before - int(d["balance"])
            if ledger and spent > 0:
                cls._append_ledger(d, -spent, ledger[0], ledger[1])
            cls.db().set(key, d)
            return dict(d)

    @classmethod
    def try_remove_balance(
        cls,
        guild_id: int,
        user_id: int,
        amount: int,
        *,
        ledger: tuple[str, str] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Списать ровно amount, если хватает средств.
        Возвращает (ok, data). При нехватке — (False, data) без изменений.
        """
        amount = int(amount)
        if amount < 0:
            raise ValueError("try_remove_balance: amount must be >= 0")
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            if int(d["balance"]) < amount:
                return False, dict(d)
            d["balance"] = int(d["balance"]) - amount
            if ledger and amount:
                cls._append_ledger(d, -amount, ledger[0], ledger[1])
            cls.db().set(key, d)
            return True, dict(d)

    @classmethod
    def transfer(
        cls,
        guild_id: int,
        from_user: int,
        to_user: int,
        amount: int,
        *,
        ledger_kind: str = "transfer",
        note: str = "",
    ) -> tuple[bool, str]:
        """
        Атомарный перевод между двумя пользователями одного гильдии.
        Возвращает (ok, reason).
        """
        amount = int(amount)
        if amount <= 0:
            return False, "amount must be > 0"
        if from_user == to_user:
            return False, "same user"

        k1 = cls.user_key(guild_id, from_user)
        k2 = cls.user_key(guild_id, to_user)
        first, second = (k1, k2) if k1 < k2 else (k2, k1)

        with cls._lock_for(first):
            with cls._lock_for(second):
                d_from = cls._normalize(cls.db().get(k1))
                d_to = cls._normalize(cls.db().get(k2))
                if int(d_from["balance"]) < amount:
                    return False, "insufficient funds"
                d_from["balance"] = int(d_from["balance"]) - amount
                d_to["balance"] = int(d_to["balance"]) + amount
                cls._append_ledger(d_from, -amount, ledger_kind, note or f"to:{to_user}")
                cls._append_ledger(d_to, amount, ledger_kind, note or f"from:{from_user}")
                cls.db().update({k1: d_from, k2: d_to})
                return True, "ok"

    @classmethod
    def deposit_bank(cls, guild_id: int, user_id: int, amount: int) -> tuple[bool, dict[str, Any]]:
        amount = int(amount)
        if amount <= 0:
            return False, cls.get(guild_id, user_id)
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            if int(d["balance"]) < amount:
                return False, dict(d)
            d["balance"] = int(d["balance"]) - amount
            d["bank"] = int(d["bank"]) + amount
            cls._append_ledger(d, -amount, "bank_deposit", f"bank+{amount}")
            cls.db().set(key, d)
            return True, dict(d)

    @classmethod
    def withdraw_bank(cls, guild_id: int, user_id: int, amount: int) -> tuple[bool, dict[str, Any]]:
        amount = int(amount)
        if amount <= 0:
            return False, cls.get(guild_id, user_id)
        key = cls.user_key(guild_id, user_id)
        with cls._lock_for(key):
            d = cls._normalize(cls.db().get(key))
            if int(d["bank"]) < amount:
                return False, dict(d)
            d["bank"] = int(d["bank"]) - amount
            d["balance"] = int(d["balance"]) + amount
            cls._append_ledger(d, amount, "bank_withdraw", f"bank-{amount}")
            cls.db().set(key, d)
            return True, dict(d)

    @classmethod
    def guild_leaderboard(cls, guild_id: int, limit: int = 10) -> list[tuple[int, int]]:
        prefix = f"{guild_id}."
        rows: list[tuple[int, int]] = []
        for key, data in cls.db().items():
            if not isinstance(key, str) or not key.startswith(prefix):
                continue
            rest = key[len(prefix) :]
            try:
                uid = int(rest)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            total = int(data.get("balance", 0) or 0) + int(data.get("bank", 0) or 0)
            rows.append((uid, total))
        rows.sort(key=lambda x: x[1], reverse=True)
        return rows[:limit]
