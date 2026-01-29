# storage.py
from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class Item:
    parser: str
    source_url: str
    title: str | None
    date_raw: str | None
    details: str | None
    urls: list[str]
    emails: list[str]


def _norm(s: str | None) -> str:
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def compute_hash(it: Item) -> str:
    main_url = it.urls[0] if it.urls else it.source_url
    payload = "|".join(
        [
            _norm(it.parser),
            _norm(main_url),
            _norm(it.title),
            _norm(it.details)[:500],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def init_db(db_path: str | Path) -> None:
    db_path = str(db_path)
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parser TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT,
                date_raw TEXT,
                details TEXT,
                urls_json TEXT NOT NULL,
                emails_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            );
            """
        )

        cols = {row[1] for row in con.execute("PRAGMA table_info(items);")}
        if "content_hash" not in cols:
            con.execute("ALTER TABLE items ADD COLUMN content_hash TEXT;")

        con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_items_hash ON items(content_hash);")
        con.commit()


def upsert_items(db_path: str | Path, items: Iterable[Item]) -> tuple[int, int, list[Item]]:
    db_path = str(db_path)
    inserted = 0
    skipped = 0
    inserted_items: list[Item] = []
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        for it in items:
            h = compute_hash(it)
            cur.execute(
                """
                INSERT OR IGNORE INTO items
                (parser, source_url, title, date_raw, details, urls_json, emails_json, fetched_at, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    it.parser,
                    it.source_url,
                    it.title,
                    it.date_raw,
                    it.details,
                    json.dumps(it.urls, ensure_ascii=False),
                    json.dumps(it.emails, ensure_ascii=False),
                    now,
                    h,
                ),
            )
            if cur.rowcount == 1:
                inserted += 1
                inserted_items.append(it)
            else:
                skipped += 1

        con.commit()

    return inserted, skipped, inserted_items


def write_csv(csv_path: str | Path, items: Iterable[Item]) -> None:
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["parser", "source_url", "title", "date_raw", "details", "urls", "emails"]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for it in items:
            w.writerow(
                {
                    "parser": it.parser,
                    "source_url": it.source_url,
                    "title": it.title,
                    "date_raw": it.date_raw,
                    "details": it.details,
                    "urls": "; ".join(it.urls),
                    "emails": "; ".join(it.emails),
                }
            )