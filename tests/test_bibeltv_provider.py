from __future__ import annotations

from datetime import date

from epgforgearr.providers.bibeltv import BibelTvImpulsProvider, _parse_schedule


def _page(items: list[dict]) -> str:
    import json

    payload = '3:{"page":{"items":' + json.dumps(items) + '}}'
    return '<script>self.__next_f.push([1,' + json.dumps(payload) + '])</script>'


def test_parse_schedule_extracts_impuls_programmes_and_filters_other_senders():
    page = _page([
        {"sender_ID": "14", "start": "2026-11-16T08:00:00.000Z", "ende": "2026-11-16T08:30:00.000Z",
         "termin_titel": "Sendung A", "titel_zusatz": "Untertitel", "episoden_text": "Beschreibung"},
        {"sender_ID": "15", "start": "2026-11-16T09:00:00.000Z", "ende": "2026-11-16T09:30:00.000Z",
         "termin_titel": "Falscher Sender"},
    ])
    programmes = _parse_schedule(page, date(2026, 11, 16))
    assert len(programmes) == 1
    assert programmes[0]["title"] == "Sendung A"
    assert programmes[0]["subtitle"] == "Untertitel"
    assert programmes[0]["description"] == "Beschreibung"
    assert programmes[0]["start"].isoformat() == "2026-11-16T09:00:00+01:00"
    assert programmes[0]["stop"].isoformat() == "2026-11-16T09:30:00+01:00"


def test_parse_schedule_filters_by_local_broadcast_date_and_rejects_empty():
    item = {"sender_ID": "14", "start": "2026-11-15T23:30:00.000Z", "ende": "2026-11-16T00:30:00.000Z",
            "termin_titel": "Mitternachtssendung"}
    assert _parse_schedule(_page([item]), date(2026, 11, 16))[0]["title"] == "Mitternachtssendung"
    assert _parse_schedule(_page([item]), date(2026, 11, 15)) == []
    assert _parse_schedule("<html>unbekannte Seite</html>", date(2026, 11, 16)) == []


def test_provider_channel_identity_and_day_limit():
    provider = BibelTvImpulsProvider()
    assert provider.list_channels() == [{"id": "BibelTVImpuls.de", "name": "Bibel TV Impuls"}]
    assert provider.MAX_DAYS == 14
