# parsers/hse_econ_science_conferences.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class HseEconScienceConferencesParser:
    name = "hse_econ_science_conferences"
    LIST_URL = "https://economics.hse.ru/science_conferences"

    # даты (рус/англ)
    DATE_RE = re.compile(
        r"(\d{1,2}\s*[–-]\s*\d{1,2}\s+[A-Za-z]+\s+\d{4})"
        r"|(\d{1,2}\s+[A-Za-z]+\s+\d{4})"
        r"|(\d{1,2}\s*[–-]\s*\d{1,2}\s+[а-яё]+\s+\d{4})"
        r"|(\d{1,2}\s+[а-яё]+\s+\d{4})",
        re.IGNORECASE,
    )

    EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    DEADLINE_HINT_RE = re.compile(
        r"(deadline|дедлайн|submit|submission|abstract|paper|application|registration|"
        r"заявк|подач|прием|регистрац|до\s+\d{1,2}\s+[а-яё]+|\bby\s+\d{1,2})",
        re.IGNORECASE,
    )

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

    @staticmethod
    def _norm_space(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _fetch_html(self, url: str) -> str:
        r = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        r.raise_for_status()
        # HSE обычно utf-8, но оставим безопасный fallback
        enc = r.encoding or "utf-8"
        try:
            return r.content.decode(enc, errors="replace")
        except Exception:
            return r.content.decode("utf-8", errors="replace")

    def _extract_list_links(self, html: str) -> list[tuple[str, str]]:
        """
        Возвращает [(title, url)] только из содержательной части страницы (после H1).
        """
        soup = BeautifulSoup(html, "lxml")
        main = soup.find("main") or soup

        h1 = main.find("h1")
        if not h1:
            # fallback: если структура изменилась — возьмём только ссылки, похожие на конференции
            links = []
            for a in main.find_all("a", href=True):
                t = self._norm_space(a.get_text(" ", strip=True))
                href = a["href"].strip()
                if not t or not href:
                    continue
                full = urljoin(self.LIST_URL, href)
                links.append((t, full))
            # уникализируем
            uniq: dict[str, str] = {}
            for t, u in links:
                uniq[u] = t
            return [(t, u) for u, t in uniq.items()]

        # берём всё, что "после" h1 в DOM, и вытаскиваем ссылки из этого блока
        # (на странице список ссылок идёт сразу под заголовком)
        container = h1.parent or main
        anchors: list[tuple[str, str]] = []

        for a in container.find_all("a", href=True):
            t = self._norm_space(a.get_text(" ", strip=True))
            href = a["href"].strip()
            if not t or not href or href.startswith("#"):
                continue
            full = urljoin(self.LIST_URL, href)

            # отсекаем меню/футер: на нужном блоке обычно короткий список,
            # поэтому уберём явные системные ссылки
            if "www.hse.ru" in full and "/science_conferences" not in full and "hse.ru" in full:
                # оставляем только если это реально внешняя страница конференции (поддомены/разные разделы)
                pass

            anchors.append((t, full))

        # в текущей верстке список конференций — несколько ссылок без повторов
        uniq: dict[str, str] = {}
        for t, u in anchors:
            if u not in uniq:
                uniq[u] = t
        return [(t, u) for u, t in uniq.items()]

    def _pick_description_block(self, soup: BeautifulSoup) -> str:
        main = soup.find("main") or soup
        # убираем лишние элементы, если они есть
        for tag in main.select("script, style, nav, footer"):
            tag.decompose()

        # часто контент внутри article/section
        candidate = main.find("article") or main.find("section") or main
        text = candidate.get_text("\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _extract_deadlines(self, text: str) -> list[str]:
        lines = [self._norm_space(x) for x in text.splitlines()]
        lines = [x for x in lines if x]

        hits: list[str] = []
        for ln in lines:
            if self.DEADLINE_HINT_RE.search(ln) and (self.DATE_RE.search(ln) or len(ln) <= 220):
                hits.append(ln)

        # уникализируем, но порядок сохраняем
        seen = set()
        out: list[str] = []
        for h in hits:
            k = h.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(h)
        return out[:30]

    def _extract_page(self, title_from_list: str, url: str) -> Item | None:
        try:
            html = self._fetch_html(url)
            soup = BeautifulSoup(html, "lxml")

            h1 = soup.find("h1")
            title = self._norm_space(h1.get_text(" ", strip=True)) if h1 else self._norm_space(title_from_list)
            if not title:
                title = self._norm_space(title_from_list) or url

            full_text = self._pick_description_block(soup)

            # date_raw: первая найденная дата в тексте
            m = self.DATE_RE.search(full_text)
            date_raw = m.group(0).strip() if m else None

            deadlines = self._extract_deadlines(full_text)
            emails = list(dict.fromkeys(self.EMAIL_RE.findall(full_text)))

            details_parts: list[str] = []
            if deadlines:
                details_parts.append("DEADLINES:\n" + "\n".join(deadlines))
            details_parts.append(full_text)

            details = "\n\n".join(details_parts).strip()
            if not details:
                details = None

            return Item(
                parser=self.name,
                source_url=self.LIST_URL,
                title=title,
                date_raw=date_raw,
                details=details,
                urls=[url],
                emails=emails,
            )
        except Exception:
            # если какая-то конференция (например stm.hse.ru) временно не отдаётся — пропускаем
            return None

    def run(self) -> ParseResult:
        try:
            list_html = self._fetch_html(self.LIST_URL)
            links = self._extract_list_links(list_html)

            items: list[Item] = []
            for t, u in links:
                it = self._extract_page(t, u)
                if it is not None:
                    items.append(it)

            return ParseResult(name=self.name, ok=True, data=items)
        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))