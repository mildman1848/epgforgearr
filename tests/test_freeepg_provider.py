from __future__ import annotations

import gzip
import io

import epgforgearr.providers.freeepg as module
from epgforgearr.providers.freeepg import FreeEpgProvider


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


def test_freeepg_parses_channels_programmes_and_caches_feed(monkeypatch):
    xml = b'''<?xml version="1.0"?><tv><channel id="EWTN.de"><display-name>EWTN Deutschland</display-name></channel>
    <channel id="ARD.de"><display-name>Das Erste</display-name></channel>
    <programme start="20261117120000 +0100" stop="20261117130000 +0100" channel="EWTN.de">
    <title lang="de">Mittagsmesse</title><desc lang="de">Live aus Deutschland</desc></programme></tv>'''
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as stream:
        stream.write(xml)
    calls = []
    monkeypatch.setattr(module, "urlopen", lambda request, timeout: (calls.append(request.full_url) or _Response(out.getvalue())))
    provider = FreeEpgProvider()
    assert provider.list_channels() == [{"id": "EWTN.de", "name": "EWTN Deutschland"}, {"id": "ARD.de", "name": "Das Erste"}]
    rows = provider.fetch_programmes("EWTN.de")
    assert len(rows) == 1
    assert rows[0]["title"] == "Mittagsmesse"
    assert rows[0]["start"].utcoffset().total_seconds() == 3600
    assert provider.fetch_programmes("ARD.de") == []
    assert len(calls) == 1


def test_freeepg_rejects_gzip_bomb_over_expansion_cap(monkeypatch):
    monkeypatch.setattr(FreeEpgProvider, "MAX_XML_BYTES", 10)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb") as stream:
        stream.write(b" " * 11)
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response(out.getvalue()))
    try:
        FreeEpgProvider().list_channels()
    except RuntimeError as exc:
        assert "size limit" in str(exc)
    else:
        raise AssertionError("oversized decompressed feed should be rejected")
