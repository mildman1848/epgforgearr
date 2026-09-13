from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import quote

import requests

# Default allowed TV Digital channel IDs, taken from the tvdids list in
# michaz1988/.epg/make_guide.py. This keeps our channel list scoped to the
# channels Michaz curates today; callers can override it via the constructor
# once we want a broader/narrower set.
DEFAULT_CHANNEL_IDS: tuple[int, ...] = (
    37, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52, 54, 55, 56, 57,
    58, 59, 60, 64, 66, 70, 71, 100, 104, 115, 133, 138, 146, 154, 175, 194,
    276, 277, 402, 450, 451, 452, 453, 468, 471, 472, 485, 492, 507, 511, 527,
    528, 529, 531, 532, 537, 551, 552, 564, 568, 590, 597, 603, 610, 613, 614,
    615, 625, 626, 627, 633, 656, 659, 694, 756, 757, 759, 761, 763, 765, 766,
    767, 770, 771, 778, 782, 783, 1183, 4002, 4003, 4004, 12033, 12035, 12042,
    12043, 12045, 12046, 12125, 12147, 12148, 12184, 12188, 12189, 12195,
)


class TvDigitalProvider:
    """TV Digital (DE) EPG provider adapter.

    Talks to the same public mobile.tvdigital.de endpoints used by the
    michaz1988/.epg/make_guide.py reference flow, directly. EPGForgearr must
    consume upstream sources itself, not Michaz's generated XMLTV file - that
    file is reference-only for discovering the endpoints/fields below.
    """

    CHANNELS_URL = "https://mobile.tvdigital.de/appdata?appVersion=50&bundleId=de.funke.tvdigital"
    PROGRAM_URL = "https://mobile.tvdigital.de/programbystation"
    DETAILS_URL = "https://mobile.tvdigital.de/broadcastdetails"
    APP_QUERY = "tmpl=app&device=androidv14&displayDensity=200&sdkInt=35"
    HEADERS = {"user-agent": "PIT-TVdigital-Android/14", "accept-encoding": "gzip"}

    # Safety cap so a bad `days` setting can't turn into an unbounded number of
    # per-day requests; the reference flow itself never grabs more than a week.
    MAX_DAYS = 7

    def __init__(
        self,
        allowed_channel_ids: Iterable[int] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        ids = DEFAULT_CHANNEL_IDS if allowed_channel_ids is None else allowed_channel_ids
        self.allowed_channel_ids = {int(channel_id) for channel_id in ids}
        self.session = session

    def _session(self) -> requests.Session:
        if self.session is None:
            self.session = requests.Session()
        return self.session

    def _request_json(self, url: str, *, attempts: int = 3, timeout: int = 20) -> Any:
        """GET JSON with bounded retries and a useful final error."""
        error: Exception | None = None
        session = self._session()
        for attempt in range(attempts):
            try:
                response = session.get(url, headers=self.HEADERS, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                error = exc
                if attempt + 1 < attempts:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"TV Digital request failed for {url}: {error}")

    def list_channels(self) -> list[dict[str, Any]]:
        data = self._request_json(self.CHANNELS_URL)
        channels = data.get("channels", []) if isinstance(data, dict) else []
        result: list[dict[str, Any]] = []
        for channel in channels:
            try:
                channel_id = int(channel.get("id"))
            except (TypeError, ValueError):
                continue
            if channel_id not in self.allowed_channel_ids:
                continue
            result.append({"id": str(channel_id), "name": channel.get("name"), "img": channel.get("img")})
        return result

    def fetch_programmes(self, provider_channel_id: str, days: int = 1) -> list[dict[str, Any]]:
        try:
            channel_id = int(provider_channel_id)
        except (TypeError, ValueError):
            return []
        days = max(1, min(int(days), self.MAX_DAYS))

        # The programbystation endpoint is scoped to a single calendar day, so
        # fetching a multi-day window means one bounded request per day
        # (days + 1, matching the reference flow's yesterday-inclusive range).
        day_start = datetime.now(timezone.utc) - timedelta(days=1)
        day_timestamps = [int((day_start + timedelta(days=offset)).timestamp()) for offset in range(days + 1)]

        broadcast_ids: list[int] = []
        for day_ts in day_timestamps:
            params = json.dumps({"date": day_ts, "channels": [channel_id]}, separators=(",", ":"))
            url = f"{self.PROGRAM_URL}?data={quote(params)}&{self.APP_QUERY}"
            response = self._request_json(url)
            for entry in response if isinstance(response, list) else []:
                broadcast_ids.extend(
                    broadcast["id"]
                    for broadcast in entry.get("broadcasts", [])
                    if isinstance(broadcast, dict) and broadcast.get("id") is not None
                )

        if not broadcast_ids:
            return []

        params_detail = json.dumps({"broadcasts": broadcast_ids}, separators=(",", ":"))
        detail_url = f"{self.DETAILS_URL}?data={quote(params_detail)}&{self.APP_QUERY}"
        details = self._request_json(detail_url)

        programmes: list[dict[str, Any]] = []
        for item in details if isinstance(details, list) else []:
            if str(item.get("n")) != str(channel_id):
                continue
            start = _to_utc_datetime(item.get("startTime"))
            stop = _to_utc_datetime(item.get("z"))
            if not start or not stop:
                continue
            description = _text(item.get("o") or item.get("H"))
            if item.get("o") and item.get("H"):
                description = f"{_text(item.get('o'))}\n{_text(item.get('H'))}"
            programmes.append(
                {
                    "title": _text(item.get("title")),
                    "subtitle": _text(item.get("E")),
                    "description": description or None,
                    "genre": _text(item.get("t")),
                    "country": _text(item.get("u")),
                    "image": _text(item.get("w")),
                    "date": _text(item.get("v")),
                    "season": _text(item.get("B")),
                    "episode": _text(item.get("C")),
                    "age_rating": _text(item.get("K")),
                    "credits": _parse_credits(item.get("G")),
                    "start": start,
                    "stop": stop,
                    "raw": item,
                }
            )
        return programmes


def _text(value: Any) -> str:
    """Return XML-safe text for TV Digital's occasionally mixed field shapes."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_text(part) for part in value if _text(part))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _to_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _parse_credits(pairs: Any) -> dict[str, list[str]] | None:
    """Turn the flat `G` name/role pair list into director/actor lists.

    Matches the reference flow: a "Regie" role is a director, everything else
    is rendered as "<name> als <role>" under actor.
    """
    if not pairs:
        return None
    names = pairs[0::2]
    roles = pairs[1::2]
    credits: dict[str, list[str]] = {"director": [], "actor": []}
    for name, role in zip(names, roles):
        if role == "Regie":
            credits["director"].append(name)
        else:
            credits["actor"].append(f"{name} als {role}")
    return credits if (credits["director"] or credits["actor"]) else None
