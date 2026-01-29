import re
import requests
from bs4 import BeautifulSoup

from parsers.base import ParseResult
from storage import Item


class HseConfStudentsParser:
    name = "hse_confstudents"
    URL = "https://lang.hse.ru/ric/confstudents"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        urls = re.findall(r"https?://[^\s<>\"]+", text)
        return [u.rstrip(").,;»") for u in urls]

    @staticmethod
    def _extract_emails(text: str) -> list[str]:
        return re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", text)

    @staticmethod
    def _parse_heading(heading: str) -> dict:
        parts = [p.strip() for p in heading.rsplit(" - ", 1)]
        if len(parts) == 2:
            return {"title": parts[0], "date_raw": parts[1]}
        return {"title": heading.strip(), "date_raw": None}

    def run(self) -> ParseResult:
        try:
            r = self.session.get(self.URL, timeout=30)
            r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")

            headers = soup.find_all("h4") or soup.find_all("h3")

            items: list[Item] = []
            for h in headers:
                heading = h.get_text(" ", strip=True)
                if not heading:
                    continue

                container = h.find_parent(["li", "div", "section"]) or h.parent
                block_text = container.get_text("\n", strip=True)

                details = block_text
                if block_text.startswith(heading):
                    details = block_text[len(heading):].strip()

                parsed = self._parse_heading(heading)

                items.append(
                    Item(
                        parser=self.name,
                        source_url=self.URL,
                        title=parsed["title"],
                        date_raw=parsed["date_raw"],
                        details=details,
                        urls=self._extract_urls(block_text),
                        emails=self._extract_emails(block_text),
                    )
                )

            return ParseResult(name=self.name, ok=True, data=items)

        except Exception as e:
            return ParseResult(name=self.name, ok=False, error=str(e))