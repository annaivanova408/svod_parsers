from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class EconorusConferencesParser:
    name = "econorus_conferences"
    URL = "https://www.econorus.org/conference.phtml"

    # вытащим что-то похожее на дату (часто "14-15 октября 2024 г.")
    DATE_RE = re.compile(
        r"\d{1,2}\s*(?:[-–]\s*\d{1,2}\s*)?[а-яё]+\s*\d{4}\s*г\.?",
        re.IGNORECASE,
    )

    # фильтр по “конференционным” названиям, чтобы не цеплять меню
    TITLE_OK_RE = re.compile(
        r"конференц|симпозиум|конгресс|воркшоп|workshop|forum|форум|кругл(ый|ые)\s+стол",
        re.IGNORECASE,
    )

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

    def _get_html(self, url: str) -> str:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()

        # econorus часто в windows-1251
        ctype = (r.headers.get("content-type") or "").lower()
        if "windows-1251" in ctype or "cp1251" in ctype:
            return r.content.decode("cp1251", errors="replace")

        # fallback: requests иногда сам угадывает, но на всякий
        enc = r.encoding or "utf-8"
        try:
            return r.content.decode(enc, errors="replace")
        except Exception:
            return r.content.decode("cp1251", errors="replace")

    def run(self) -> ParseResult:
        try:
            html = self._get_html(self.URL)
            soup = BeautifulSoup(html, "lxml")

            items: list[Item] = []

            for a in soup.find_all("a", href=True):
                title = a.get_text(" ", strip=True)
                if not title:
                    continue
                if not self.TITLE_OK_RE.search(title):
                    continue

                href = a["href"].strip()
                full_url = urljoin(self.URL, href)

                # берём строку-описание вокруг ссылки (обычно там "(Москва, ...)")
                line = a.parent.get_text(" ", strip=True) if a.parent else title
                line = re.sub(r"\s+", " ", line).strip()

                m = self.DATE_RE.search(line)
                date_raw = m.group(0).strip() if m else None

                items.append(
                    Item(
                        parser=self.name,
                        source_url=self.URL,
                        title=title,
                        date_raw=date_raw,
                        details=line,
                        urls=[full_url],
                        emails=[],
                    )
                )

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))