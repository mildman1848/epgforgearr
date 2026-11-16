from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


class _Scripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self._script = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._script = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._script:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script:
            self.scripts.append("".join(self._parts))
            self._script = False


def _parse_schedule(html: str, broadcast_date: date) -> list[dict[str, Any]]:
    parser = _Scripts()
    parser.feed(html)
    programmes = []
    marker = '"items":[{"sender_ID"'
    for script in parser.scripts:
        push_marker = "self.__next_f.push("
        position = script.find(push_marker)
        if position < 0:
            continue
        try:
            push, _ = json.JSONDecoder().raw_decode(script[position + len(push_marker):])
            if not isinstance(push, list) or len(push) != 2 or push[0] != 1 or not isinstance(push[1], str):
                continue
            payload = push[1]
            offset = payload.find(marker)
            if offset < 0:
                continue
            offset += len('"items":')
            items, _ = json.JSONDecoder().raw_decode(payload[offset:])
        except json.JSONDecodeError:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or item.get("sender_ID") != "14" or not item.get("termin_titel"):
                continue
            try:
                start = datetime.fromisoformat(item["start"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
                stop = datetime.fromisoformat(item["ende"].replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
            except (KeyError, TypeError, ValueError):
                continue
            if start.date() != broadcast_date or stop <= start:
                continue
            programmes.append({
                "title": item["termin_titel"],
                "subtitle": item.get("titel_zusatz"),
                "description": item.get("episoden_text"),
                "start": start,
                "stop": stop,
            })
    return programmes


class BibelTvImpulsProvider:
    URL = "https://www.bibeltv.de/programm/impuls?tag={date}"
    CHANNEL_ID = "BibelTVImpuls.de"
    MAX_DAYS = 14
    MAX_PAGE_BYTES = 5 * 1024 * 1024
    HEADERS = {"User-Agent": "EPGForgearr/1.0 (+XMLTV guide generator)"}

    def __init__(self) -> None:
        self._cache: dict[date, list[dict[str, Any]]] = {}

    def list_channels(self) -> list[dict[str, str]]:
        return [{"id": self.CHANNEL_ID, "name": "Bibel TV Impuls"}]

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
        error: Exception | None = None
        for attempt in range(3):
            try:
                request = Request(self.URL.format(date=current.isoformat()), headers=self.HEADERS)
                with urlopen(request, timeout=20) as response:
                    html = response.read(self.MAX_PAGE_BYTES + 1)
                if len(html) > self.MAX_PAGE_BYTES:
                    raise RuntimeError("Bibel TV Impuls page exceeds size limit")
                result = _parse_schedule(html.decode("utf-8", "replace"), current)
                if not result:
                    raise RuntimeError("Bibel TV Impuls page contained no programme entries")
                return result
            except Exception as exc:
                error = exc
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Bibel TV Impuls schedule request failed ({type(error).__name__})") from error
