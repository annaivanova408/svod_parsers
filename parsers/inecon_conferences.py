# parsers/inecon_conferences.py
from __future__ import annotations

import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class IneconConferencesParser:
    name = "inecon_conferences"

    # пробуем сначала без www (чаще пускает), потом www
    LIST_URLS = [
        "https://inecon.org/nauchnaya-zhizn/konferenczii/",
        "https://www.inecon.org/nauchnaya-zhizn/konferenczii/",
    ]

    DATE_PREFIX_RE = re.compile(
        r"^\s*\d{1,2}\s*(?:[-–—]{1,2}\s*\d{1,2}\s*)?"
        r"[а-яё]+\s+\d{4}\s*г\.?\s*",
        re.IGNORECASE,
    )

    EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    URL_RE = re.compile(r"https?://[^\s<>\"]+")

    POSITIVE_RE = re.compile(r"(конференц|конгресс|школа|симпозиум|форум|workshop|воркшоп)", re.IGNORECASE)
    NEGATIVE_RE = re.compile(r"(семинар|круглый\s+стол|заседани)", re.IGNORECASE)

    DEADLINE_HINT_RE = re.compile(
        r"(deadline|дедлайн|до\s+\d{1,2}\s+[а-яё]+|\bby\s+\d{1,2}|submission|submit|abstract|paper|"
        r"registration|регистрац|подач|при[её]м\s+заявок|заявк)",
        re.IGNORECASE,
    )

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/121.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )

    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip()

    def _fetch(self, url: str) -> BeautifulSoup:
        # лёгкий "браузерный" Referer
        headers = {"Referer": url.split("/nauchnaya-zhizn/")[0] + "/"}
        r = self.session.get(url, timeout=self.timeout, allow_redirects=True, headers=headers)
        if r.status_code == 403:
            r.raise_for_status()
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")

    def _is_target_title(self, title: str) -> bool:
        if self.NEGATIVE_RE.search(title or ""):
            return False
        return bool(self.POSITIVE_RE.search(title or ""))

    def _extract_date_raw_from_title(self, title: str) -> str | None:
        m = self.DATE_PREFIX_RE.search(title or "")
        return self._norm(m.group(0)) if m else None

    def _extract_deadlines(self, text: str) -> list[str]:
        lines = [self._norm(x) for x in (text or "").splitlines() if self._norm(x)]
        out: list[str] = []
        seen = set()
        for ln in lines:
            if self.DEADLINE_HINT_RE.search(ln):
                k = ln.lower()
                if k in seen:
                    continue
                seen.add(k)
                out.append(ln)
        return out[:30]

    def _extract_detail(self, url: str, title_from_list: str, source_url: str) -> Item | None:
        try:
            soup = self._fetch(url)
            main = soup.find("main") or soup

            for tag in main.select("script, style, nav, footer"):
                tag.decompose()

            h1 = main.find("h1")
            title = self._norm(h1.get_text(" ", strip=True)) if h1 else self._norm(title_from_list) or url

            text = main.get_text("\n", strip=True)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()

            date_raw = self._extract_date_raw_from_title(title) or self._extract_date_raw_from_title(title_from_list)
            deadlines = self._extract_deadlines(text)
            emails = list(dict.fromkeys(self.EMAIL_RE.findall(text)))

            urls = [url]
            for a in main.find_all("a", href=True):
                href = a["href"].strip()
                if href and not href.startswith("#"):
                    urls.append(urljoin(url, href))
            urls.extend([u.rstrip(").,;»") for u in self.URL_RE.findall(text)])
            urls = list(dict.fromkeys(urls))

            details = text
            if deadlines:
                details = "DEADLINES:\n" + "\n".join(deadlines) + "\n\n" + text

            return Item(
                parser=self.name,
                source_url=source_url,
                title=title,
                date_raw=date_raw,
                details=details or None,
                urls=urls,
                emails=emails,
            )
        except Exception:
            return None

    def run(self) -> ParseResult:
        try:
            # 1) выбираем доступный LIST_URL (если один даёт 403 — пробуем другой)
            last_err: str | None = None
            soup = None
            source_url = None
            for u in self.LIST_URLS:
                try:
                    soup = self._fetch(u)
                    source_url = u
                    break
                except Exception as e:
                    last_err = str(e)
                    continue
            if soup is None or source_url is None:
                return ParseResult(name=self.name, ok=False, error=last_err or "Failed to fetch list page")

            main = soup.find("main") or soup

            links: list[tuple[str, str]] = []
            upcoming_header = None
            for h in main.find_all(["h2", "h3"]):
                if "Предстоящие" in self._norm(h.get_text(" ", strip=True)):
                    upcoming_header = h
                    break

            if upcoming_header:
                ul = upcoming_header.find_next("ul")
                if ul:
                    for a in ul.find_all("a", href=True):
                        title = self._norm(a.get_text(" ", strip=True))
                        if title and self._is_target_title(title):
                            links.append((title, urljoin(source_url, a["href"])))

            if not links:
                for a in main.find_all("a", href=True):
                    t = self._norm(a.get_text(" ", strip=True))
                    href = urljoin(source_url, a["href"])
                    hdr = a.find_previous(["h3", "h4"])
                    title = self._norm(hdr.get_text(" ", strip=True)) if hdr else None
                    if title and self._is_target_title(title):
                        links.append((title, href))

            uniq: dict[str, str] = {}
            for t, u in links:
                if u not in uniq:
                    uniq[u] = t

            items: list[Item] = []
            for u, t in uniq.items():
                it = self._extract_detail(u, t, source_url)
                if it:
                    items.append(it)

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))