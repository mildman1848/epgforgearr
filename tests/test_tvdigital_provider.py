from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

import epgforgearr.providers.tvdigital as tvdigital_module
from epgforgearr.providers.tvdigital import TvDigitalProvider


class FakeResponse:
    """Minimal requests.Response stand-in; no live network involved."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Records every GET and answers via a caller-supplied responder(url)."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        return FakeResponse(self.responder(url))


def test_list_channels_filters_to_default_allowed_ids():
    payload = {
        "channels": [
            {"id": 37, "name": "Das Erste", "img": "das-erste.png"},
            {"id": 999999, "name": "Not In Michaz Allowlist", "img": "x.png"},
        ]
    }
    provider = TvDigitalProvider(session=FakeSession(lambda url: payload))
    assert provider.list_channels() == [{"id": "37", "name": "Das Erste", "img": "das-erste.png"}]


def test_list_channels_respects_custom_allowed_ids():
    payload = {"channels": [{"id": 5, "name": "Custom Channel", "img": ""}, {"id": 6, "name": "Excluded", "img": ""}]}
    provider = TvDigitalProvider(allowed_channel_ids=[5], session=FakeSession(lambda url: payload))
    assert provider.list_channels() == [{"id": "5", "name": "Custom Channel", "img": ""}]


def test_fetch_programmes_converts_timestamps_and_fields():
    start_dt = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    stop_dt = datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc)
    start_ts = int(start_dt.timestamp())
    stop_ts = int(stop_dt.timestamp())

    def responder(url):
        if "programbystation" in url:
            return [{"broadcasts": [{"id": 1001}, {"id": 1002}]}]
        assert "broadcastdetails" in url
        return [
            {
                "n": 37,
                "title": ["Tagesschau"],
                "startTime": start_ts,
                "z": stop_ts,
                "o": "Nachrichten",
                "H": ["Zusatzinfo"],
                "E": ["Untertitel"],
                "t": "Nachrichten",
                "u": "DE",
                "w": "image.jpg",
                "v": "2026",
                "B": "1",
                "C": "2",
                "K": "0",
                "G": ["Max Mustermann", "Regie", "Erika Musterfrau", "Reporterin"],
            },
            {"n": 999, "title": "Different channel, must be filtered out", "startTime": start_ts, "z": stop_ts},
        ]

    session = FakeSession(responder)
    provider = TvDigitalProvider(session=session)
    programmes = provider.fetch_programmes("37", days=1)

    assert len(programmes) == 1
    prog = programmes[0]
    assert prog["title"] == "Tagesschau"
    assert prog["subtitle"] == "Untertitel"
    assert prog["description"] == "Nachrichten\nZusatzinfo"
    assert prog["start"] == start_dt
    assert prog["stop"] == stop_dt
    assert prog["start"].tzinfo is timezone.utc
    assert prog["stop"].tzinfo is timezone.utc
    assert prog["genre"] == "Nachrichten"
    assert prog["season"] == "1"
    assert prog["episode"] == "2"
    assert prog["credits"] == {"director": ["Max Mustermann"], "actor": ["Erika Musterfrau als Reporterin"]}

    # One programbystation request per day in the (days + 1)-day window, no
    # extra/unbounded requests.
    assert len([c for c in session.calls if "programbystation" in c]) == 2


def test_fetch_programmes_returns_empty_for_non_numeric_channel_id():
    provider = TvDigitalProvider(session=FakeSession(lambda url: {}))
    assert provider.fetch_programmes("not-a-number") == []


def test_fetch_programmes_returns_empty_when_no_broadcasts_found():
    session = FakeSession(lambda url: [{"broadcasts": []}])
    provider = TvDigitalProvider(session=session)
    assert provider.fetch_programmes("37", days=1) == []
    # No broadcast ids means no detail lookup at all.
    assert all("programbystation" in call for call in session.calls)


def test_fetch_programmes_days_setting_is_clamped_not_unbounded():
    session = FakeSession(lambda url: [{"broadcasts": []}])
    provider = TvDigitalProvider(session=session)
    provider.fetch_programmes("37", days=10_000)
    assert len([c for c in session.calls if "programbystation" in c]) == provider.MAX_DAYS + 1


def test_request_json_retries_are_bounded_then_raise(monkeypatch):
    monkeypatch.setattr(tvdigital_module.time, "sleep", lambda *_args: None)

    class AlwaysFailingSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, headers=None, timeout=None):
            self.calls += 1
            raise requests.exceptions.ConnectionError("boom")

    session = AlwaysFailingSession()
    provider = TvDigitalProvider(session=session)
    with pytest.raises(RuntimeError, match="TV Digital request failed"):
        provider.list_channels()
    assert session.calls == 3
