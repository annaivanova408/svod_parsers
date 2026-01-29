# parsers/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class ParseResult:
    name: str
    ok: bool
    data: Any = None
    error: str | None = None