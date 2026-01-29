# Conference Parser

Набор парсеров (HSE / CBR / econorus / inecon / na-konferencii / Telegram) с сохранением результатов в SQLite и опциональным экспортом в CSV.  
Парсеры запускаются разово или по расписанию (каждые 3 дня).

## Зависимости

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
```

## Запуск (разовый)

python master.py --backfill-days 30 --csv false

## Запуск (постоянный, парсинг автоматически происходит раз в 3 дня)

python master.py --csv false

## Переход с SQLite на PostgreSQL

### 1) Поднять PostgreSQL локально (Docker)
```bash
docker run --name conf-postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=confparser \
  -p 5432:5432 \
  -d postgres:16
```

### 2) Создать таблицу в PostgreSQL

CREATE TABLE IF NOT EXISTS items (
  id BIGSERIAL PRIMARY KEY,
  parser TEXT NOT NULL,
  source_url TEXT NOT NULL,
  title TEXT,
  date_raw TEXT,
  details TEXT,
  urls_json TEXT NOT NULL,
  emails_json TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL,
  content_hash TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_items_parser ON items(parser);
CREATE INDEX IF NOT EXISTS idx_items_fetched_at ON items(fetched_at);

### 3) Логика вставки без дублей (upsert/ignore)

В PostgreSQL вместо INSERT OR IGNORE используется:

INSERT INTO items (parser, source_url, title, date_raw, details, urls_json, emails_json, fetched_at, content_hash)
VALUES (...)
ON CONFLICT (content_hash) DO NOTHING;




