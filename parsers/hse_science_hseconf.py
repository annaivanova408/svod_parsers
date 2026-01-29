from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from parsers.base import ParseResult
from storage import Item


class HseScienceHseconfParser:
    name = "hse_science_hseconf"
    URL = "https://www.hse.ru/science/HSEconf"

    # Месяцы на странице идут отдельными h4 (их пропускаем)
    MONTH_HEADERS = {
        "ЯНВАРЬ", "ФЕВРАЛЬ", "МАРТ", "АПРЕЛЬ", "МАЙ", "ИЮНЬ",
        "ИЮЛЬ", "АВГУСТ", "СЕНТЯБРЬ", "ОКТЯБРЬ", "НОЯБРЬ", "ДЕКАБРЬ",
    }

    DATE_RE = re.compile(r"\d{1,2}(\s*[-–]\s*\d{1,2})?\s+[а-яё]+", re.IGNORECASE)
    EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    URL_RE = re.compile(r"https?://[^\s<>\"]+")

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _is_month_header(self, text: str) -> bool:
        t = text.strip().upper()
        return t in self.MONTH_HEADERS

    def _extract_emails(self, text: str) -> list[str]:
        return self.EMAIL_RE.findall(text)

    def _extract_urls_from_text(self, text: str) -> list[str]:
        urls = self.URL_RE.findall(text)
        return [u.rstrip(").,;»") for u in urls]

    def _collect_block_until_next_h4(self, h4: Tag) -> tuple[list[str], list[str]]:
        """
        Возвращает (lines, hrefs) — текстовые строки блока и все ссылки из блока.
        """
        lines: list[str] = []
        hrefs: list[str] = []

        for sib in h4.next_siblings:
            if isinstance(sib, Tag) and sib.name == "h4":
                break

            if isinstance(sib, NavigableString):
                t = str(sib).strip()
                if t:
                    lines.append(t)
                continue

            if isinstance(sib, Tag):
                # ссылки
                for a in sib.find_all("a", href=True):
                    href = a["href"].strip()
                    if href and href != "#":
                        hrefs.append(urljoin(self.URL, href))

                t = sib.get_text(" ", strip=True)
                if t:
                    lines.append(t)

        # чистим "Подробнее" как строку (ссылку мы и так сохранили)
        lines = [ln for ln in lines if ln.strip() and ln.strip() != "Подробнее"]
        return lines, hrefs

    def run(self) -> ParseResult:
        try:
            r = self.session.get(self.URL, timeout=30)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")
            h4s = soup.find_all("h4")

            items: list[Item] = []

            for h4 in h4s:
                title = h4.get_text(" ", strip=True)
                if not title:
                    continue
                if self._is_month_header(title):
                    continue

                lines, hrefs = self._collect_block_until_next_h4(h4)
                block_text = "\n".join([title] + lines)

                # date_raw = первая строка, похожая на дату
                date_raw = None
                remaining_lines: list[str] = []
                for ln in lines:
                    if date_raw is None and self.DATE_RE.search(ln):
                        date_raw = ln.strip()
                        continue
                    remaining_lines.append(ln)

                details = "\n".join(remaining_lines).strip() or None

                # urls: из hrefs + из текста
                urls = list(dict.fromkeys(hrefs + self._extract_urls_from_text(block_text)))
                emails = list(dict.fromkeys(self._extract_emails(block_text)))

                items.append(
                    Item(
                        parser=self.name,
                        source_url=self.URL,
                        title=title,
                        date_raw=date_raw,
                        details=details,
                        urls=urls,
                        emails=emails,
                    )
                )

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))