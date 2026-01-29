# Conference Parser

Набор парсеров (HSE / CBR / econorus / inecon / na-konferencii / Telegram) с сохранением результатов в SQLite и опциональным экспортом в CSV.  
Парсеры запускаются разово или по расписанию (каждые 3 дня).

## Зависимости

pip install -U pip

pip install requests beautifulsoup4 lxml apscheduler

## Структура проекта

- `master.py` — главный запуск (разово + расписание, есть backfill)
- `storage.py` — SQLite-хранилище + дедупликация по `content_hash`
- `parsers/` — отдельные парсеры
- `data/app.db` — база SQLite (локально)
- `logs/parser.log` — логи (локально)

## Установка

### 1) Виртуальное окружение
```bash
python3 -m venv .venv
source .venv/bin/activate

