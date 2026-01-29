# master.py
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
from zoneinfo import ZoneInfo

from storage import init_db, upsert_items, write_csv, Item

from parsers.hse_confstudents import HseConfStudentsParser
from parsers.hse_science_hseconf import HseScienceHseconfParser
from parsers.na_konferencii_category import NaKonferenciiCategoryParser
from parsers.telegram_channel import TelegramChannelParser
from parsers.hse_april_conf import HseAprilConfParser
from parsers.econorus_conferences import EconorusConferencesParser
from parsers.cbr_ec_research_activity import CbrEcResearchActivityParser
# 1) добавь импорт в master.py
from parsers.hse_econ_science_conferences import HseEconScienceConferencesParser
from parsers.inecon_conferences import IneconConferencesParser


def setup_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "parser.log"
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # чтобы не дублировать хендлеры при повторном импорте/запуске
    if root.handlers:
        root.handlers.clear()

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)


setup_logging()
log = logging.getLogger("master")


def parse_bool(s: str) -> bool:
    return s.strip().lower() in {"1", "true", "yes", "y", "on"}


def run_once(db_path: Path, csv_enabled: bool, csv_path: str):
    init_db(db_path)


    parsers = [
        HseAprilConfParser(),          # следующий год автоматически (2027)
        # или явно:
        # HseAprilConfParser(year=2027),
        EconorusConferencesParser(),
        HseConfStudentsParser(),
        HseEconScienceConferencesParser(),  # <-- добавили
        HseScienceHseconfParser(),
        CbrEcResearchActivityParser(),
        IneconConferencesParser(),
        NaKonferenciiCategoryParser(
            "https://na-konferencii.ru/conference-cat/obshhestvennyie-gumanitarnyie-nauki/jekonomika-upravlenie-finansy",
            max_pages=30,
        ),
        TelegramChannelParser("@smuecon218", max_messages=200),
    ]

    all_items: list[Item] = []
    for p in parsers:
        log.info("Running %s ...", p.name)
        res = p.run()
        if not res.ok:
            log.error("❌ %s failed: %s", p.name, res.error)
            continue
        all_items.extend(res.data)

    inserted, skipped, new_items = upsert_items(db_path, all_items)
    log.info("DB write: inserted=%d, skipped(dupes)=%d", inserted, skipped)

    if csv_enabled:
        write_csv(csv_path, new_items)
        log.info("CSV written (only new): %s", csv_path)


def run_backfill(db_path: Path, csv_enabled: bool, csv_path: str, days: int):
    init_db(db_path)

    parsers = [
        HseAprilConfParser(),
        EconorusConferencesParser(),
        HseConfStudentsParser(),
        HseScienceHseconfParser(),
        CbrEcResearchActivityParser(),
        IneconConferencesParser(),
        HseEconScienceConferencesParser(),  # <-- добавили
        NaKonferenciiCategoryParser(
            "https://na-konferencii.ru/conference-cat/obshhestvennyie-gumanitarnyie-nauki/jekonomika-upravlenie-finansy",
            max_pages=60,
        ),
        TelegramChannelParser("@smuecon218", max_messages=1200),
    ]

    all_items: list[Item] = []
    for p in parsers:
        log.info("Backfill running %s ...", p.name)
        res = p.run()
        if not res.ok:
            log.error("❌ %s failed: %s", p.name, res.error)
            continue
        all_items.extend(res.data)

    inserted, skipped, new_items = upsert_items(db_path, all_items)
    log.info("Backfill DB write: inserted=%d, skipped(dupes)=%d", inserted, skipped)

    if csv_enabled:
        write_csv(csv_path, new_items)
        log.info("Backfill CSV written (only new): %s", csv_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/app.db")
    ap.add_argument("--csv", default="false")
    ap.add_argument("--csv-path", default="data/new_items.csv")
    ap.add_argument("--backfill-days", type=int, default=0)
    args = ap.parse_args()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    csv_enabled = parse_bool(args.csv)

    if args.backfill_days and args.backfill_days > 0:
        run_backfill(db_path, csv_enabled, args.csv_path, args.backfill_days)
        return

    scheduler = BlockingScheduler(timezone="Europe/Zurich")

    # запуск сразу
    run_once(db_path, csv_enabled, args.csv_path)

    # дальше раз в 3 дня
    scheduler.add_job(
        run_once,
        trigger="interval",
        days=3,
        args=[db_path, csv_enabled, args.csv_path],
        id="run_every_3_days",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    log.info("Scheduler started (runs every 3 days).")
    scheduler.start()


if __name__ == "__main__":
    main()