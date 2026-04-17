import json
import os
from typing import Any, Dict, List, Optional

class JSONHandler:
    """Универсальный обработчик JSON файлов с автосохранением"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data: Dict = {}
        self._ensure_file()
        self.load()
    
    def _ensure_file(self):
        """Создает файл и папку, если их нет"""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            self.save()
    
    def load(self):
        """Загружает данные из файла"""
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            self.data = {}
            self.save()
    
    def save(self):
        """Сохраняет данные в файл"""
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=4, ensure_ascii=False)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение по ключу"""
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any):
        """Установить значение и сохранить"""
        self.data[key] = value
        self.save()
    
    def delete(self, key: str):
        """Удалить ключ и сохранить"""
        if key in self.data:
            del self.data[key]
            self.save()
    
    def get_nested(self, *keys, default: Any = None) -> Any:
        """Получить вложенное значение"""
        current = self.data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(str(key), default)
            else:
                return default
        return current
    
    def set_nested(self, value: Any, *keys):
        """Установить вложенное значение и сохранить"""
        if not keys:
            return
        current = self.data
        for key in keys[:-1]:
            key = str(key)
            if key not in current:
                current[key] = {}
            current = current[key]
        current[str(keys[-1])] = value
        self.save()