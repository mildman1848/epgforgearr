from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen


class FreeEpgProvider:
    BASE_URL = "https://free-epg.de/api/epg"
    MAX_COMPRESSED_BYTES = 25 * 1024 * 1024
    MAX_XML_BYTES = 200 * 1024 * 1024
    HEADERS = {"User-Agent": "EPGForgearr/1.0 (+XMLTV guide generator)", "Accept-Encoding": "identity"}

    def __init__(self, country: str = "de") -> None:
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            raise ValueError("country must be a two-letter ISO code")
        self.url = f"{self.BASE_URL}/{country.lower()}.xml.gz"
        self._channels: list[dict[str, str]] | None = None
        self._programmes: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> None:
        if self._programmes is not None:
            return
        request = Request(self.url, headers=self.HEADERS)
        with urlopen(request, timeout=45) as response:
            compressed = response.read(self.MAX_COMPRESSED_BYTES + 1)
        if len(compressed) > self.MAX_COMPRESSED_BYTES:
            raise RuntimeError("FreeEPG feed exceeds compressed size limit")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            xml = stream.read(self.MAX_XML_BYTES + 1)
        if len(xml) > self.MAX_XML_BYTES:
            raise RuntimeError("FreeEPG feed exceeds XML size limit")
        channels: list[dict[str, str]] = []
        programmes: dict[str, list[dict[str, Any]]] = {}
        for _, elem in ET.iterparse(io.BytesIO(xml), events=("end",)):
            if elem.tag == "channel":
                channel_id = elem.get("id", "").strip()
                names = [node.text.strip() for node in elem.findall("display-name") if node.text and node.text.strip()]
                if channel_id and names:
                    channels.append({"id": channel_id, "name": names[0]})
                elem.clear()
            elif elem.tag == "programme":
                channel_id = elem.get("channel", "").strip()
                start = _xmltv_datetime(elem.get("start"))
                stop = _xmltv_datetime(elem.get("stop"))
                title = elem.findtext("title")
                if channel_id and start and stop and title:
                    programmes.setdefault(channel_id, []).append({
                        "title": title,
                        "subtitle": elem.findtext("sub-title"),
                        "description": elem.findtext("desc"),
                        "start": start,
                        "stop": stop,
                    })
                elem.clear()
        if not channels:
            raise RuntimeError("FreeEPG feed contained no channels")
        self._channels = channels
        self._programmes = programmes

    def list_channels(self) -> list[dict[str, str]]:
        self._load()
        return list(self._channels or [])

    def fetch_programmes(self, provider_channel_id: str, days: int = 1) -> list[dict[str, Any]]:
        self._load()
        return list((self._programmes or {}).get(provider_channel_id, []))


def _xmltv_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z")
    except ValueError:
        return None
