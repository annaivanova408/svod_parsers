# parsers/hse_april_conf.py
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class HseAprilConfParser:
    name = "hse_april_conf"

    DATE_RE = re.compile(
        r"(\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{1,2}\s+[а-яё]+\s+\d{4}|\d{4})",
        re.IGNORECASE,
    )

    def __init__(self, year: int | None = None):
        # если year не задан — берём следующий год
        self.year = year if year is not None else (datetime.now().year + 1)
        self.url = f"https://conf.hse.ru/en/{self.year}"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            }
        )

    def run(self) -> ParseResult:
        try:
            r = self.session.get(self.url, timeout=30, allow_redirects=True)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")

            # заголовок
            h1 = soup.find("h1")
            title = h1.get_text(" ", strip=True) if h1 else None
            if not title:
                title = soup.title.get_text(" ", strip=True) if soup.title else f"HSE Conference {self.year}"

            # текст страницы (кратко)
            main = soup.find("main") or soup.find("div", class_=re.compile(r"(content|container|main)", re.I)) or soup.body
            details = main.get_text("\n", strip=True) if main else None

            # дата (если найдём)
            date_raw = None
            if details:
                m = self.DATE_RE.search(details)
                if m:
                    date_raw = m.group(0).strip()

            # собираем ссылки со страницы (ограничим, чтобы не раздувать)
            urls = [r.url.rstrip("/")]
            if main:
                for a in main.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href or href.startswith("#"):
                        continue
                    full = urljoin(r.url, href)
                    urls.append(full)
            # уникализируем
            urls = list(dict.fromkeys(urls))

            item = Item(
                parser=self.name,
                source_url=r.url.rstrip("/"),
                title=title,
                date_raw=date_raw,
                details=details,
                urls=urls,
                emails=[],
            )

            return ParseResult(name=self.name, ok=True, data=[item])

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))