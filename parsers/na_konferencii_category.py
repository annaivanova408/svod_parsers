from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag

from parsers.base import ParseResult
from storage import Item


class NaKonferenciiCategoryParser:
    name = "na_konferencii_category"

    # Русские даты (пример: "26 февраля - 27 февраля 2026 г.")
    DATE_RE = re.compile(
        r"\d{1,2}\s+[а-яё]+(?:\s+\d{4})?(?:\s*[-–]\s*\d{1,2}\s+[а-яё]+(?:\s+\d{4})?)?(?:\s*г\.)?",
        re.IGNORECASE,
    )

    def __init__(self, category_url: str, max_pages: int = 20):
        self.category_url = category_url.rstrip("/")
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    def _fetch(self, url: str) -> BeautifulSoup:
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")

    def _find_cards(self, soup: BeautifulSoup) -> list[Tag]:
        """
        На WP-страницах карточки часто лежат в article / .post / .type-post.
        Делаем несколько попыток, чтобы не зависеть от конкретных классов.
        """
        candidates = []

        # 1) article — самый частый вариант
        candidates = soup.select("article")
        if candidates:
            return candidates

        # 2) посты/карточки
        candidates = soup.select(".post, .type-post, .conference, .conf, .item")
        if candidates:
            return candidates

        # 3) fallback: блоки с заголовком-ссылкой внутри основного контента
        main = soup.select_one("main") or soup.select_one(".content") or soup.body
        if not main:
            return []
        return main.select("h2, h3")  # дальше будем аккуратно обрабатывать

    def _extract_title_and_link(self, card: Tag) -> tuple[str | None, str | None]:
        # Ищем заголовок-ссылку
        a = None
        for sel in ("h2 a[href]", "h3 a[href]", "a[href]"):
            a = card.select_one(sel)
            if a:
                break

        if not a:
            return None, None

        title = a.get_text(" ", strip=True) or None
        href = a.get("href")
        if href:
            href = urljoin(self.category_url + "/", href)
        return title, href

    def _extract_date_raw(self, text: str) -> str | None:
        m = self.DATE_RE.search(text)
        return m.group(0).strip() if m else None

    def _next_page_url(self, soup: BeautifulSoup, current_url: str) -> str | None:
        # 1) rel=next (редко, но бывает)
        link = soup.find("a", rel=lambda v: v and "next" in v)
        if link and link.get("href"):
            return urljoin(current_url, link["href"])

        # 2) стандартная WP пагинация
        nxt = soup.select_one("a.next.page-numbers[href]")
        if nxt:
            return urljoin(current_url, nxt["href"])

        # 3) fallback: ссылка с текстом "Следующая"
        for a in soup.find_all("a", href=True):
            t = a.get_text(" ", strip=True).lower()
            if "след" in t or "next" in t:
                return urljoin(current_url, a["href"])

        return None

    def run(self) -> ParseResult:
        try:
            items: list[Item] = []
            url = self.category_url
            seen_page_urls = set()

            for _ in range(self.max_pages):
                if url in seen_page_urls:
                    break
                seen_page_urls.add(url)

                soup = self._fetch(url)
                cards = self._find_cards(soup)

                page_count_before = len(items)

                for card in cards:
                    text = card.get_text("\n", strip=True)

                    title, link = self._extract_title_and_link(card)
                    if not title or not link:
                        continue

                    # На всякий случай отсекаем "мусорные" ссылки (меню/хлебные крошки)
                    if "conference-cat" in link and title.lower().startswith("категория"):
                        continue

                    date_raw = self._extract_date_raw(text)

                    # details — всё текстом (локация/дедлайн/статус), но без заголовка
                    details = text
                    if title and details.startswith(title):
                        details = details[len(title):].strip()
                    details = details or None

                    items.append(
                        Item(
                            parser=self.name,
                            source_url=url,
                            title=title,
                            date_raw=date_raw,
                            details=details,
                            urls=[link],
                            emails=[],  # на списке обычно нет
                        )
                    )

                # если на странице не нашли ничего — выходим
                if len(items) == page_count_before:
                    break

                next_url = self._next_page_url(soup, url)
                if not next_url:
                    break
                url = next_url

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))