from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class CbrEcResearchActivityParser:
    name = "cbr_ec_research_activity"
    URL = "https://cbr.ru/ec_research/activity/"

    DATE_RE = re.compile(r"^\d{1,2}\s+[а-яё]+(?:\s*[-–]\s*\d{1,2}\s+[а-яё]+)?\s+\d{4}$", re.IGNORECASE)

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

    @staticmethod
    def _is_target(title: str, kind: str) -> bool:
        t = (title or "").lower()
        k = (kind or "").lower()
        return ("конкурс" in t or "конкурс" in k) or ("конференц" in t or "конференц" in k)

    @staticmethod
    def _clean_spaces(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    def run(self) -> ParseResult:
        try:
            r = self.session.get(self.URL, timeout=30)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")
            main = soup.find("main") or soup

            items: list[Item] = []

            # Берём только ссылки на карточки мероприятий (у ЦБ они вида /ec_research/activity/<id>/)
            for a in main.find_all("a", href=True):
                href = a["href"].strip()
                if "/ec_research/activity/" not in href:
                    continue

                title = self._clean_spaces(a.get_text(" ", strip=True))
                if not title:
                    continue

                full_url = urljoin(self.URL, href)

                # Пробуем вытащить дату и "тип" из ближайшего контейнера
                container = a.find_parent(["li", "div", "article", "section"]) or a.parent
                block_text = container.get_text("\n", strip=True) if container else title
                lines = [self._clean_spaces(x) for x in block_text.splitlines() if self._clean_spaces(x)]

                # дата обычно первой строкой
                date_raw = None
                kind = None

                for ln in lines:
                    if date_raw is None and self.DATE_RE.match(ln):
                        date_raw = ln
                        continue

                # тип обычно последней строкой (Конкурс/Конференция/Семинар/вебинар и т.п.)
                # но иногда это "гибридный формат" — это не тип, поэтому берём наиболее "короткую" строку из хвоста
                tail = [ln for ln in lines if ln.lower() not in {title.lower(), (date_raw or "").lower()}]
                if tail:
                    # часто тип — самая короткая строка в хвосте
                    kind = min(tail[-3:], key=len)

                if not self._is_target(title, kind or ""):
                    continue

                details = kind or None
                if details and details.lower() == title.lower():
                    details = None

                items.append(
                    Item(
                        parser=self.name,
                        source_url=self.URL,
                        title=title,
                        date_raw=date_raw,
                        details=details,
                        urls=[full_url],
                        emails=[],
                    )
                )

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))