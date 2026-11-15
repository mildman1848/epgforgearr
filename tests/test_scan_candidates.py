from __future__ import annotations

import json

import epgforgearr.workflow as workflow
from epgforgearr.workflow import export_mapping_template, scan_missing_epg

MAGENTA = [{"contentId": "m1", "name": "ZDF HD"}, {"contentId": "m2", "name": "RTL"}]
TVDIGITAL = [{"id": "37", "name": "ZDF"}, {"id": "38", "name": "Das Erste"}]


class FakeLister:
    def __init__(self, channels=None, error=None):
        self._channels, self._error = channels or [], error

    def list_channels(self):
        if self._error:
            raise self._error
        return self._channels


def _row(stream_id, name, existing=False):
    return {"channel_id": stream_id, "channel_uuid": f"u{stream_id}", "channel_name": name, "tvg_id": "",
            "stream_id": stream_id, "stream_name": name, "stream_tvg_id": "", "existing_epg": existing,
            "linked_channel": True}


def _scan(tmp_path, monkeypatch, rows, providers, provider_state=None, **settings):
    monkeypatch.setattr(workflow, "_dispatcharr_kodibox_rows", lambda include_existing: rows)
    monkeypatch.setattr(workflow, "usable_provider_ids", lambda: list(providers))
    path = tmp_path / "suggestions.json"
    result = scan_missing_epg({"suggestions_path": str(path), **settings}, provider_factory=lambda pid: providers[pid],
                          provider_state=provider_state)
    return result, json.loads(path.read_text(encoding="utf-8"))


def test_candidates_aggregate_across_providers_in_stable_order(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(MAGENTA), "tvdigital_de": FakeLister(TVDIGITAL)}
    result, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers)
    cands = payload["items"][0]["candidates"]
    # Both exact; tie broken by registry order, then label.
    assert [(c["provider"], c["provider_channel_id"], c["confidence"]) for c in cands] == [
        ("magenta", "m1", "exact"), ("tvdigital_de", "37", "exact")]
    assert payload["items"][0]["chosen_candidate"] == cands[0]
    # Ambiguous tie: never auto-selected, even when auto-select is on.
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers, scan_auto_select=True)
    assert payload["items"][0]["selected"] is False


def test_exact_match_outranks_contains_match_and_unique_exact_can_autoselect(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister([{"contentId": "m9", "name": "Das Erste Live"}]), "tvdigital_de": FakeLister(TVDIGITAL)}
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "Das Erste")], providers, scan_auto_select=True, scan_min_confidence="low")
    item = payload["items"][0]
    assert [c["provider"] for c in item["candidates"]] == ["tvdigital_de", "magenta"]
    assert item["candidates"][1]["confidence"] == "low"
    assert item["selected"] is True


def test_no_match_is_not_suggested_and_counted(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(MAGENTA), "tvdigital_de": FakeLister(TVDIGITAL)}
    result, payload = _scan(tmp_path, monkeypatch, [_row(1, "Unknown Channel XY")], providers)
    assert payload["items"] == []
    assert result["unmatched_channels"] == 1
    assert payload["provider_coverage"]["magenta"]["streams_with_candidate"] == 0


def test_coverage_is_per_provider_and_separate_from_stream_availability(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(MAGENTA), "tvdigital_de": FakeLister(TVDIGITAL)}
    rows = [_row(1, "ZDF"), _row(2, "RTL"), _row(3, "Nothing", existing=True)]
    result, payload = _scan(tmp_path, monkeypatch, rows, providers)
    cov = payload["provider_coverage"]
    assert cov["magenta"] == {"status": "ok", "provider_channels": 2, "streams_with_candidate": 2, "streams_top_candidate": 2}
    assert cov["tvdigital_de"]["streams_with_candidate"] == 1
    assert cov["tvdigital_de"]["streams_top_candidate"] == 0
    assert payload["stream_availability"] == {"scanned_streams": 3, "streams_with_existing_epg": 1}
    assert result["magenta_channels"] == 2  # legacy count key preserved


def test_failing_provider_is_reported_and_others_still_searched(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(error=RuntimeError("secret-token")), "tvdigital_de": FakeLister(TVDIGITAL)}
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers)
    assert payload["provider_coverage"]["magenta"]["status"] == "error"
    assert "secret-token" not in json.dumps(payload)
    assert [c["provider"] for c in payload["items"][0]["candidates"]] == ["tvdigital_de"]


def test_suggestions_stay_unselected_by_default_and_export_remains_compatible(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(MAGENTA), "tvdigital_de": FakeLister(TVDIGITAL)}
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers)
    assert payload["items"][0]["selected"] is False
    assert export_mapping_template({"suggestions_path": str(tmp_path / "suggestions.json"),
                                    "mapping_path": str(tmp_path / "m.json")})["mapping_count"] == 0
    # Old-format suggestions without the new keys still export.
    old = {"items": [{"selected": True, "channel_id": "zdf", "candidates": [
        {"provider": "magenta", "provider_channel_id": "m1", "label": "ZDF HD", "confidence": "exact", "reason": "r", "priority": 1}]}]}
    (tmp_path / "old.json").write_text(json.dumps(old), encoding="utf-8")
    assert export_mapping_template({"suggestions_path": str(tmp_path / "old.json"), "mapping_path": str(tmp_path / "m2.json")})["mapping_count"] == 1


def test_magenta_sport_heuristic_is_not_applied_to_other_providers(tmp_path, monkeypatch):
    other = [{"id": "Sport 1", "name": "myTeamTV Sport 1"}]
    providers = {"magenta": FakeLister(other), "tvdigital_de": FakeLister(other)}
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "Sport 1")], providers, scan_min_confidence="low")
    assert [(c["provider"], c["confidence"]) for c in payload["items"][0]["candidates"]] == [("magenta", "low")]


def test_programme_availability_unknown_without_state(tmp_path, monkeypatch):
    providers = {"magenta": FakeLister(MAGENTA)}
    result, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers)
    pa = payload["programme_availability"]["magenta"]
    assert pa["known"] is False and pa["cached"] is True
    assert pa["programme_count"] is None and pa["coverage_window"] is None and pa["last_success_at"] is None
    assert result["programme_availability"] == payload["programme_availability"]


def test_programme_availability_from_state_is_distinct_and_kept_after_failure(tmp_path, monkeypatch):
    window = {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-03T00:00:00+00:00"}
    state = {
        "magenta": {"status": "ok", "last_success_at": "2025-01-01T00:00:00Z", "last_attempt_at": "2025-01-01T00:00:00Z",
                    "programme_count": 300, "coverage_window": window},
        # failed refresh after an earlier success: last-known values retained by the scheduler
        "tvdigital_de": {"status": "error", "last_success_at": "2024-12-31T00:00:00Z",
                         "last_attempt_at": "2025-01-01T00:00:00Z", "programme_count": 80, "coverage_window": window},
    }
    providers = {"magenta": FakeLister(MAGENTA), "tvdigital_de": FakeLister(TVDIGITAL), "other": FakeLister([])}
    _, payload = _scan(tmp_path, monkeypatch, [_row(1, "ZDF")], providers, provider_state=state)
    pa = payload["programme_availability"]
    assert pa["magenta"]["programme_count"] == 300 and pa["magenta"]["coverage_window"] == window
    assert pa["tvdigital_de"]["last_status"] == "error" and pa["tvdigital_de"]["programme_count"] == 80
    assert pa["other"]["programme_count"] is None
    # mapping coverage and stream availability are untouched by programme data
    assert payload["provider_coverage"]["magenta"]["provider_channels"] == 2
    assert "programme_count" not in payload["provider_coverage"]["magenta"]
    assert payload["stream_availability"] == {"scanned_streams": 1, "streams_with_existing_epg": 0}
