"""Атомарный JSON-хранилище с блокировками и бэкапами (без SQL)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

# Сколько ротируемых бэкапов хранить рядом с файлом (data/foo.json.bak1 …)
_BACKUP_COUNT = 3
# Не чаще одного бэкапа раз в N секунд (чтобы не ддосить диск)
_BACKUP_MIN_INTERVAL = 60.0


class JSONHandler:
    """
    Универсальный обработчик JSON с:
    - потокобезопасностью (RLock);
    - атомарной записью (tmp + os.replace);
    - ротацией бэкапов;
    - восстановлением из бэкапа при битом JSON.
    """

    def __init__(self, filepath: str, *, backup_count: int = _BACKUP_COUNT):
        self.filepath = filepath
        self.backup_count = max(0, int(backup_count))
        self.data: dict[str, Any] = {}
        self._lock = threading.RLock()
        self._last_backup_ts = 0.0
        self._ensure_dir()
        self.load()

    def _ensure_dir(self) -> None:
        parent = os.path.dirname(self.filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _backup_paths(self) -> list[str]:
        return [f"{self.filepath}.bak{i}" for i in range(1, self.backup_count + 1)]

    def _rotate_backups(self) -> None:
        """data.json.bak2 → bak3, bak1 → bak2, data.json → bak1."""
        if self.backup_count <= 0 or not os.path.isfile(self.filepath):
            return
        now = time.monotonic()
        if now - self._last_backup_ts < _BACKUP_MIN_INTERVAL:
            return
        try:
            paths = self._backup_paths()
            for i in range(len(paths) - 1, 0, -1):
                src, dst = paths[i - 1], paths[i]
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
            shutil.copy2(self.filepath, paths[0])
            self._last_backup_ts = now
        except OSError as e:
            log.warning("Не удалось сделать бэкап %s: %s", self.filepath, e)

    def _try_load_file(self, path: str) -> dict[str, Any] | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return raw
            log.warning("%s: корень JSON не dict, игнорируем", path)
        except FileNotFoundError:
            return None
        except (json.JSONDecodeError, OSError, TypeError) as e:
            log.warning("Повреждённый JSON %s: %s", path, e)
        return None

    def load(self) -> None:
        """Загружает данные; при порче файла пробует бэкапы."""
        with self._lock:
            data = self._try_load_file(self.filepath)
            if data is not None:
                self.data = data
                return
            for bak in self._backup_paths():
                data = self._try_load_file(bak)
                if data is not None:
                    log.error(
                        "Восстановлен %s из бэкапа %s (основной файл был битый/отсутствовал)",
                        self.filepath,
                        bak,
                    )
                    self.data = data
                    self._atomic_write(self.data)
                    return
            self.data = {}
            self._atomic_write(self.data)

    def _atomic_write(self, payload: dict[str, Any]) -> None:
        """Пишет через временный файл в той же директории + os.replace (атомарно на POSIX)."""
        self._ensure_dir()
        directory = os.path.dirname(self.filepath) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.filepath)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def save(self) -> None:
        """Сохраняет данные атомарно и при необходимости делает бэкап."""
        with self._lock:
            self._rotate_backups()
            self._atomic_write(self.data)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.data[key] = value
            self._rotate_backups()
            self._atomic_write(self.data)

    def delete(self, key: str) -> None:
        with self._lock:
            if key in self.data:
                del self.data[key]
                self._rotate_backups()
                self._atomic_write(self.data)

    def update(self, mapping: dict[str, Any]) -> None:
        """Пакетное обновление нескольких ключей одним save."""
        with self._lock:
            self.data.update(mapping)
            self._rotate_backups()
            self._atomic_write(self.data)

    def get_nested(self, *keys: Any, default: Any = None) -> Any:
        with self._lock:
            current: Any = self.data
            for key in keys:
                if isinstance(current, dict):
                    current = current.get(str(key), default)
                else:
                    return default
            return current

    def set_nested(self, value: Any, *keys: Any) -> None:
        if not keys:
            return
        with self._lock:
            current = self.data
            for key in keys[:-1]:
                k = str(key)
                nxt = current.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    current[k] = nxt
                current = nxt
            current[str(keys[-1])] = value
            self._rotate_backups()
            self._atomic_write(self.data)

    def mutate(self, key: str, fn: Callable[[Any], Any]) -> Any:
        """
        Атомарно прочитать → изменить → сохранить.
        fn(value) -> new_value. Возвращает new_value.
        """
        with self._lock:
            old = self.data.get(key)
            new = fn(old)
            self.data[key] = new
            self._rotate_backups()
            self._atomic_write(self.data)
            return new

    def items(self):
        with self._lock:
            return list(self.data.items())

    def keys(self):
        with self._lock:
            return list(self.data.keys())

    def snapshot(self) -> dict[str, Any]:
        """Мелкая копия корня (для безопасного чтения снаружи)."""
        with self._lock:
            return dict(self.data)
