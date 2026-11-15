from __future__ import annotations

import re
import time
from datetime import date, datetime, time as day_time, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class _ScheduleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.programmes: list[dict[str, str]] = []
        self._depth = 0
        self._field = ""
        self._current: dict[str, str] = {}
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "li" and "cd-program-spot" in classes:
            self._depth = 1
            self._current = {}
        elif self._depth:
            if tag == "li":
                self._depth += 1
            for field, css in (("start", "cd-spot-start"), ("title", "cd-spot-title"),
                               ("subtitle", "cd-spot-sub-title"), ("description", "cd-spot-description-short")):
                if css in classes:
                    self._field = field
                    self._chunks = []

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag == "li":
            self._depth -= 1
            if self._depth == 0:
                if self._current.get("start") and self._current.get("title"):
                    self.programmes.append(self._current)
                self._current = {}
                self._field = ""
        elif self._field and tag in {"div", "h3", "h4", "span", "p"}:
            self._current[self._field] = " ".join("".join(self._chunks).split())
            self._field = ""

    def handle_data(self, data: str) -> None:
        if self._field:
            self._chunks.append(data)


class EwtnProvider:
    URL = "https://ewtn.de/programm/{year}/{month}/{day}/"
    CHANNEL_ID = "EWTN.de"
    MAX_DAYS = 7
    HEADERS = {"User-Agent": "EPGForgearr/1.0 (+XMLTV guide generator)"}

    def __init__(self) -> None:
        self._cache: dict[date, list[dict[str, Any]]] = {}

    def list_channels(self) -> list[dict[str, str]]:
        return [{"id": self.CHANNEL_ID, "name": "EWTN Deutschland"}]

    def fetch_programmes(self, provider_channel_id: str, days: int = 1) -> list[dict[str, Any]]:
        if provider_channel_id != self.CHANNEL_ID:
            return []
        days = max(1, min(int(days), self.MAX_DAYS))
        today = datetime.now(ZoneInfo("Europe/Berlin")).date()
        for offset in range(days + 1):
            current = today + timedelta(days=offset)
            if current not in self._cache:
                self._cache[current] = self._fetch_day(current)
        return [programme for offset in range(days + 1) for programme in self._cache[today + timedelta(days=offset)]]

    def _fetch_day(self, current: date) -> list[dict[str, Any]]:
        url = self.URL.format(year=current.year, month=current.month, day=current.day)
        error: Exception | None = None
        for attempt in range(3):
            try:
                request = Request(url, headers=self.HEADERS)
                with urlopen(request, timeout=20) as response:
                    html = response.read().decode("utf-8", "replace")
                parser = _ScheduleParser()
                parser.feed(html)
                zone = ZoneInfo("Europe/Berlin")
                entries = parser.programmes
                result = []
                for index, item in enumerate(entries):
                    match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*Uhr", item["start"])
                    if not match:
                        continue
                    start = datetime.combine(current, day_time(int(match.group(1)), int(match.group(2))), zone)
                    if index + 1 < len(entries):
                        next_match = re.fullmatch(r"(\d{1,2}):(\d{2})\s*Uhr", entries[index + 1]["start"])
                    else:
                        next_match = None
                    if next_match:
                        stop = datetime.combine(current, day_time(int(next_match.group(1)), int(next_match.group(2))), zone)
                        if stop <= start:
                            stop += timedelta(days=1)
                    else:
                        stop = datetime.combine(current + timedelta(days=1), day_time.min, zone)
                    result.append({"title": item["title"], "subtitle": item.get("subtitle"),
                                   "description": item.get("description"), "start": start, "stop": stop})
                if not result:
                    raise RuntimeError("EWTN schedule page contained no programme entries")
                return result
            except Exception as exc:
                error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"EWTN schedule request failed ({type(error).__name__})") from error
