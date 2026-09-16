# Orbis-DSbot

Discord-бот на **discord.py 2.x** с экономикой, мини-играми, приватными голосовыми, музыкой, профилями (PIL), кланами, деревом и мониторингом CS/Minecraft.

Данные хранятся в **JSON** (без SQL): атомарная запись, бэкапы, блокировки от гонок.

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# отредактируйте .env — минимум DISCORD_TOKEN и GUILD_IDS

python main.py
```

На Linux для музыки/голоса нужны системные пакеты:

```bash
# Debian/Ubuntu
sudo apt install libopus0 ffmpeg
# или укажите путь: OPUS_LIBRARY_PATH=/usr/lib/.../libopus.so.0
```

## Переменные окружения

См. `.env.example`. Кратко:

| Переменная | Зачем |
|------------|--------|
| `DISCORD_TOKEN` | Токен бота (обязательно) |
| `GUILD_IDS` | ID серверов для быстрой регистрации slash-команд |
| `LITE_MODE` | `1` (по умолчанию) — не грузить тяжёлые коги |
| `ENABLED_COGS` / `DISABLED_COGS` | Точечное управление когами |
| `OPENAI_API_KEY` | Для `/chat` |
| `OPUS_LIBRARY_PATH` | libopus, если не находится автоматически |
| `VIP_CARD_ROLE_ID` | Роль за VIP-карту в магазине |

## Структура

```
Orbis-DSbot/
├── main.py              # точка входа
├── bot.py               # ProBot, загрузка когов, /help
├── cogs/                # команды
│   ├── economy.py       # баланс, daily, work, pay, банк, shop, rob
│   ├── games.py         # слоты, блэкджек, crash, mines…
│   ├── profile.py       # карточки профиля (Pillow)
│   ├── voice.py         # приватные комнаты
│   ├── media.py         # музыка (yt-dlp)
│   ├── grow_tree.py     # дерево
│   ├── clans.py, combat.py, seasons.py, …
│   └── …
├── utils/
│   ├── json_handler.py  # атомарный JSON + бэкапы + lock
│   ├── wallet.py        # экономика (transfer, bank, ledger)
│   ├── ui_render.py     # PNG-карточки
│   ├── theme.py         # цвета бренда
│   └── appcmd.py        # guild-режим slash
├── assets/fonts/        # Noto Sans (кириллица)
└── data/                # JSON (создаётся автоматически)
```

## Хранение данных (JSON)

- Файлы: `data/economy.json`, `data/audit.json`, и т.д.
- **Атомарная запись**: temp-файл + `os.replace` (не портится при падении процесса).
- **Бэкапы**: `*.json.bak1` … `bak3` (не чаще раза в минуту).
- При битом основном файле — автовосстановление из бэкапа.
- **Wallet**: per-user lock, `transfer` / `try_remove_balance` / `deposit_bank` / `withdraw_bank`.

Не запускайте несколько инстансов бота на одну папку `data/` — JSON не рассчитан на multi-process.

## LITE_MODE и лимит slash-команд

Discord ограничивает **100 глобальных** slash-команд. Поэтому по умолчанию:

- команды регистрируются на указанные `GUILD_IDS` (без лимита и мгновенно);
- тяжёлые коги (`games`, `media`, `grow_tree`, `market`, …) отключены.

Включить всё:

```env
LITE_MODE=0
```

или выборочно:

```env
ENABLED_COGS=games,media,voice
```

## Основные команды

- Экономика: `/balance`, `/daily`, `/work`, `/pay`, `/deposit`, `/withdraw`, `/shop`, `/rob`, `/leaderboard`
- Игры: `/coinflip`, `/slots`, `/blackjack`, `/crash`, `/mines`, …
- Профиль: `/profile`, карточки
- Голос: `/voice_setup`, панель приватных комнат
- Музыка: `/play`, `/skip`, `/queue`, …
- Дерево: `/tree`, `/tree_water`, …
- Прочее: `/chat`, `/servers`, `/season_status`, модерация

Полный список — `/help` в Discord.

## Разработка

```bash
# только нужные коги при отладке
ENABLED_COGS=economy,profile LITE_MODE=1 python main.py
```

Мёртвые legacy-коги из `utils/` (старые Economy/Games/Shop) удалены — актуальный код только в `cogs/`.
