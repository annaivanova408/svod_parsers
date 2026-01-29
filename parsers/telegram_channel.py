# parsers/telegram_channel.py
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


@dataclass
class TgMessage:
    msg_id: int
    text: str
    dt_iso: str | None
    link: str


class TelegramChannelParser:
    name = "telegram_channel"

    EMAIL_RE = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    URL_RE = re.compile(r"https?://[^\s<>\"]+")

    # строго про конференции
    POSITIVE = [
        r"\bконференц", r"\bмеждународн(ая|ый)\s+конференц",
        r"\bворкшоп\b|\bworkshop\b",
        r"\bсимпозиум\b|\bsymposium\b",
        r"\bфорум\b",
        r"\bcfp\b|call for papers|call for abstracts|paper submission|abstract submission",
    ]

    # явно не конференции
    NEGATIVE = [
        r"\bсеминар(ы)?\b", r"\bнаучн(ый|ые)\s+семинар",
        r"\bлекци(я|и)\b", r"\bвебинар\b|\bwebinar\b",
        r"\bмастер-?класс\b",
        r"\bкурс\b",
        r"\bхакатон\b|\bhackathon\b",
        r"\bконкурс\b",
        r"\bстипенди(я|и)\b|\bгрант\b",
        r"\bваканси(я|и)\b",
        r"\bновост(ь|и)\b|\bнобелев",
    ]

    DATE_HINT_RE = re.compile(
        r"\b(\d{1,2}[./]\d{1,2}([./]\d{2,4})?|\d{1,2}\s+[а-яё]+(\s+\d{4})?)\b",
        re.IGNORECASE,
    )

    def __init__(self, username: str, max_messages: int = 200, sleep_s: float = 0.8):
        self.username = username.lstrip("@")
        self.max_messages = max_messages
        self.sleep_s = sleep_s

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )

        self._pos_re = re.compile("|".join(self.POSITIVE), re.IGNORECASE)
        self._neg_re = re.compile("|".join(self.NEGATIVE), re.IGNORECASE)

    def _list_url(self, before: int | None = None) -> str:
        base = f"https://t.me/s/{self.username}"
        return f"{base}?before={before}" if before else base

    def _extract_emails(self, text: str) -> list[str]:
        return self.EMAIL_RE.findall(text)

    def _extract_urls(self, text: str) -> list[str]:
        urls = self.URL_RE.findall(text)
        return [u.rstrip(").,;»") for u in urls]

    def _is_conference_post(self, text: str) -> bool:
        t = text.strip()
        if not t:
            return False

        # если явно семинар/лекция/вебинар и т.п. — сразу нет
        if self._neg_re.search(t):
            return False

        # должен быть сильный маркер конференции/CFP/воркшопа/симпозиума
        if not self._pos_re.search(t):
            return False

        # чаще всего в конфо-постах есть даты
        # если дат нет, всё равно можно пропустить — но тогда будет шум.
        if not self.DATE_HINT_RE.search(t):
            return False

        return True

    def _parse_page(self, html: str) -> list[TgMessage]:
        soup = BeautifulSoup(html, "lxml")
        wraps = soup.select(".tgme_widget_message_wrap")
        out: list[TgMessage] = []

        for wrap in wraps:
            a = wrap.select_one("a.tgme_widget_message_date[href]")
            if not a:
                continue
            link = a.get("href", "").strip()
            m = re.search(r"/(\d+)$", link)
            if not m:
                continue
            msg_id = int(m.group(1))

            text_div = wrap.select_one(".tgme_widget_message_text")
            text = text_div.get_text("\n", strip=True) if text_div else ""

            time_tag = wrap.select_one("time[datetime]")
            dt_iso = time_tag.get("datetime") if time_tag else None

            out.append(TgMessage(msg_id=msg_id, text=text, dt_iso=dt_iso, link=link))

        return out

    def run(self) -> ParseResult:
        try:
            collected: list[TgMessage] = []
            before: int | None = None

            while len(collected) < self.max_messages:
                url = self._list_url(before=before)
                r = self.session.get(url, timeout=30)
                r.raise_for_status()

                page_msgs = self._parse_page(r.text)
                if not page_msgs:
                    break

                page_msgs.sort(key=lambda x: x.msg_id, reverse=True)

                existing_ids = {m.msg_id for m in collected}
                for msg in page_msgs:
                    if msg.msg_id not in existing_ids:
                        collected.append(msg)

                min_id = min(m.msg_id for m in page_msgs)
                before = min_id

                time.sleep(self.sleep_s)

            items: list[Item] = []
            for m in collected[: self.max_messages]:
                if not self._is_conference_post(m.text):
                    continue

                title = m.text.splitlines()[0].strip()[:300] if m.text else None
                urls = list(dict.fromkeys([m.link] + self._extract_urls(m.text)))
                emails = list(dict.fromkeys(self._extract_emails(m.text)))

                items.append(
                    Item(
                        parser=self.name,
                        source_url=m.link,
                        title=title,
                        date_raw=m.dt_iso,
                        details=m.text,
                        urls=urls,
                        emails=emails,
                    )
                )

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))