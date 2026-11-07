from __future__ import annotations

import gzip
import os
from pathlib import Path

import pytest

import epgforgearr.generator as generator
from epgforgearr.generator import generate_xmltv


class EmptyProvider:
    def fetch_programmes(self, provider_channel_id: str, days: int = 1):
        return []


def _settings(output_path: Path):
    return {
        "output_path": str(output_path),
        "gzip_output": True,
        "days": 1,
        "mapping_config_json": [{
            "channel_id": "demo.channel",
            "display_name": "Demo Channel",
            "sources": [{"provider": "demo", "provider_channel_id": "demo", "label": "Demo", "priority": 1}],
        }],
    }


def test_generate_xmltv_replaces_non_writable_existing_files(tmp_path: Path):
    """Atomic replace must survive stale files created by the wrong user/mode."""
    output_path = tmp_path / "epg.xml"
    gz_path = tmp_path / "epg.xml.gz"
    output_path.write_text("old xml")
    gz_path.write_bytes(b"old gz")
    output_path.chmod(0o444)
    gz_path.chmod(0o444)

    try:
        result = generate_xmltv(_settings(output_path), provider_factory=lambda _provider: EmptyProvider())
    finally:
        for path in (output_path, gz_path):
            if path.exists():
                os.chmod(path, 0o664)

    assert result["status"] == "ok"
    assert output_path.read_text().startswith("<?xml")
    assert gzip.open(gz_path, "rb").read().startswith(b"<?xml")
    assert output_path.stat().st_mode & 0o777 == 0o664
    assert gz_path.stat().st_mode & 0o777 == 0o664


def test_failed_refresh_preserves_last_good_xmltv_and_gzip(tmp_path: Path):
    output_path = tmp_path / "epg.xml"
    settings = _settings(output_path)
    generate_xmltv(settings, provider_factory=lambda _provider: EmptyProvider())
    prior_xml = output_path.read_bytes()
    prior_gzip = output_path.with_suffix(".xml.gz").read_bytes()

    class FailingProvider:
        def fetch_programmes(self, provider_channel_id: str, days: int = 1):
            raise RuntimeError("token=secret-token; Authorization: Bearer abc123")

    result = generate_xmltv(settings, provider_factory=lambda _provider: FailingProvider())

    assert result["status"] == "error"
    assert "secret-token" not in str(result)
    assert "abc123" not in str(result)
    assert output_path.read_bytes() == prior_xml
    assert output_path.with_suffix(".xml.gz").read_bytes() == prior_gzip


def test_empty_schedule_is_successful_fresh_output(tmp_path: Path):
    result = generate_xmltv(_settings(tmp_path / "empty.xml"), provider_factory=lambda _provider: EmptyProvider())
    assert result["status"] == "ok"
    assert result["programme_count"] == 0


def test_coverage_window_comes_from_programme_times(tmp_path: Path):
    class ProgrammeProvider:
        def fetch_programmes(self, provider_channel_id: str, days: int = 1):
            return [
                {"start": "2025-01-02 04:15:00", "stop": "2025-01-02 05:00:00", "title": "First"},
                {"start": "2025-01-02 05:00:00", "stop": "2025-01-02 06:30:00", "title": "Second"},
            ]

    result = generate_xmltv(_settings(tmp_path / "coverage.xml"), provider_factory=lambda _provider: ProgrammeProvider())

    assert result["status"] == "ok"
    assert result["programme_count"] == 2
    assert result["coverage_start"] == "2025-01-02T04:15:00+00:00"
    assert result["coverage_end"] == "2025-01-02T06:30:00+00:00"


def test_gzip_publish_failure_rolls_back_xml_and_preserves_old_gzip(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "paired.xml"
    gzip_path = output_path.with_suffix(".xml.gz")
    settings = _settings(output_path)
    generate_xmltv(settings, provider_factory=lambda _provider: EmptyProvider())
    old_xml = output_path.read_bytes()
    old_gzip = gzip_path.read_bytes()

    class ProgrammeProvider:
        def fetch_programmes(self, provider_channel_id: str, days: int = 1):
            return [{"start": "2025-01-02 04:15:00", "stop": "2025-01-02 05:00:00", "title": "New"}]

    real_replace = generator.os.replace
    failed = False

    def fail_gzip_replace(source, destination):
        nonlocal failed
        if Path(destination) == gzip_path and not failed:
            failed = True
            raise OSError("simulated gzip publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(generator.os, "replace", fail_gzip_replace)
    try:
        generate_xmltv(settings, provider_factory=lambda _provider: ProgrammeProvider())
    except OSError as exc:
        assert "simulated gzip publication failure" in str(exc)
    else:
        raise AssertionError("expected the staged gzip publish to fail")

    assert failed
    assert output_path.read_bytes() == old_xml
    assert gzip_path.read_bytes() == old_gzip
    assert output_path.stat().st_mode & 0o777 == 0o664
    assert sorted(p.name for p in tmp_path.iterdir()) == ["paired.xml", "paired.xml.gz"]


def test_rollback_failure_preserves_backup_and_reports_path(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "paired.xml"
    gzip_path = output_path.with_suffix(".xml.gz")
    settings = _settings(output_path)
    generate_xmltv(settings, provider_factory=lambda _provider: EmptyProvider())
    old_xml = output_path.read_bytes()

    real_replace = generator.os.replace

    def fail_gzip_and_rollback(source, destination):
        # Fail gzip publication, then fail the backup -> XML restore.
        if Path(destination) == gzip_path or ".backup." in Path(source).name:
            raise OSError("simulated replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(generator.os, "replace", fail_gzip_and_rollback)
    try:
        generate_xmltv(settings, provider_factory=lambda _provider: EmptyProvider())
    except RuntimeError as exc:
        message = str(exc)
        assert "simulated replace failure" in message
        assert isinstance(exc.__cause__, OSError)
    else:
        raise AssertionError("expected rollback failure")

    backups = [p for p in tmp_path.iterdir() if ".backup." in p.name]
    assert len(backups) == 1
    assert str(backups[0]) in message
    assert backups[0].read_bytes() == old_xml
    assert not [p for p in tmp_path.iterdir() if p.name not in {"paired.xml", "paired.xml.gz", backups[0].name}]


def test_gzip_failure_without_previous_xml_removes_new_xml(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "fresh.xml"
    gzip_path = output_path.with_suffix(".xml.gz")
    real_replace = generator.os.replace

    def fail_gzip(source, destination):
        if Path(destination) == gzip_path:
            raise OSError("simulated gzip publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(generator.os, "replace", fail_gzip)
    try:
        generate_xmltv(_settings(output_path), provider_factory=lambda _provider: EmptyProvider())
    except OSError:
        pass
    else:
        raise AssertionError("expected the staged gzip publish to fail")

    assert list(tmp_path.iterdir()) == []


def _fail_source_open(monkeypatch, source: Path):
    """Make opening `source` fail; return the list of mkstemp fds created."""
    fds = []
    real_mkstemp = generator.tempfile.mkstemp
    real_open = Path.open

    def mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        fds.append(fd)
        return fd, name

    def fake_open(self, *args, **kwargs):
        if self == source:
            raise OSError("source open failed")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(generator.tempfile, "mkstemp", mkstemp)
    monkeypatch.setattr(Path, "open", fake_open)
    return fds


def _assert_closed_and_clean(fds, tmp_path: Path):
    assert len(fds) == 1
    try:
        os.fstat(fds[0])
    except OSError:
        pass
    else:
        raise AssertionError("mkstemp descriptor leaked")
    assert not list(tmp_path.glob(".*.tmp"))


def test_stage_gzip_file_closes_fd_when_source_open_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "in.xml"
    source.write_text("x")
    fds = _fail_source_open(monkeypatch, source)
    try:
        generator._stage_gzip_file(source, tmp_path / "out.xml.gz")
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    _assert_closed_and_clean(fds, tmp_path)


def test_stage_backup_closes_fd_when_source_open_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "out.xml"
    source.write_text("x")
    fds = _fail_source_open(monkeypatch, source)
    try:
        generator._stage_backup(source)
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError")
    _assert_closed_and_clean(fds, tmp_path)


def test_zero_mapping_result_does_not_overwrite_non_empty_output(tmp_path: Path):
    output_path = tmp_path / "epg.xml"
    settings = _settings(output_path)
    generate_xmltv(settings, provider_factory=lambda _provider: EmptyProvider())
    prior_xml = output_path.read_bytes()
    prior_gzip = output_path.with_suffix(".xml.gz").read_bytes()

    result = generate_xmltv({**settings, "mapping_config_json": []}, provider_factory=lambda _provider: EmptyProvider())

    assert result["status"] == "error"
    assert output_path.read_bytes() == prior_xml
    assert output_path.with_suffix(".xml.gz").read_bytes() == prior_gzip


def test_zero_mapping_first_output_is_allowed(tmp_path: Path):
    result = generate_xmltv({**_settings(tmp_path / "first.xml"), "mapping_config_json": []}, provider_factory=lambda _provider: EmptyProvider())
    assert result["status"] == "ok"
    assert (tmp_path / "first.xml").exists()


GUIDE = b'<tv><channel id="a"><display-name>A</display-name></channel><programme start="20260101000000 +0000" stop="20260101010000 +0000" channel="a"/></tv>'




@pytest.mark.parametrize("xml", [None, b"<tv/>"])
def test_zero_mapping_blocked_when_only_gzip_has_guide(tmp_path: Path, xml):
    output_path = tmp_path / "epg.xml"
    gz_path = tmp_path / "epg.xml.gz"
    gz_path.write_bytes(gzip.compress(GUIDE))
    if xml is not None:
        output_path.write_bytes(xml)
    prior_gzip = gz_path.read_bytes()

    result = generate_xmltv({**_settings(output_path), "mapping_config_json": []}, provider_factory=lambda _provider: EmptyProvider())

    assert result["status"] == "error"
    assert gz_path.read_bytes() == prior_gzip
    assert output_path.exists() == (xml is not None)
    if xml is not None:
        assert output_path.read_bytes() == xml


def test_zero_mapping_with_malformed_gzip_is_allowed_without_leaking(tmp_path: Path):
    output_path = tmp_path / "epg.xml"
    (tmp_path / "epg.xml.gz").write_bytes(b"not gzip")
    result = generate_xmltv({**_settings(output_path), "mapping_config_json": []}, provider_factory=lambda _provider: EmptyProvider())
    assert result["status"] == "ok"
