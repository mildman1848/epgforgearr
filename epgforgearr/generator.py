from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import tempfile
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .providers import default_registry


@dataclass(frozen=True)
class SourceRef:
    provider: str
    provider_channel_id: str
    label: str = ""
    priority: int = 100


@dataclass(frozen=True)
class ChannelMapping:
    channel_id: str
    display_name: str
    sources: tuple[SourceRef, ...]


def supported_sources() -> list[dict[str, Any]]:
    return default_registry.describe_all()


def parse_mapping_config(raw: str | list[dict[str, Any]]) -> list[ChannelMapping]:
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list):
        raise ValueError("mapping_config_json must be a JSON array")
    mappings: list[ChannelMapping] = []
    seen: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"mapping #{index} must be an object")
        channel_id = str(item.get("channel_id") or "").strip()
        display_name = str(item.get("display_name") or channel_id).strip()
        if not channel_id:
            raise ValueError(f"mapping #{index} missing channel_id")
        if channel_id in seen:
            raise ValueError(f"duplicate channel_id: {channel_id}")
        seen.add(channel_id)
        sources_raw = item.get("sources") or []
        if not isinstance(sources_raw, list) or not sources_raw:
            raise ValueError(f"mapping {channel_id} needs at least one source")
        sources: list[SourceRef] = []
        for sidx, source in enumerate(sources_raw):
            if not isinstance(source, dict):
                raise ValueError(f"source #{sidx} for {channel_id} must be an object")
            provider = str(source.get("provider") or "").strip()
            provider_channel_id = str(source.get("provider_channel_id") or "").strip()
            if not provider or not provider_channel_id:
                raise ValueError(f"source #{sidx} for {channel_id} missing provider/provider_channel_id")
            sources.append(
                SourceRef(
                    provider=provider,
                    provider_channel_id=provider_channel_id,
                    label=str(source.get("label") or provider_channel_id),
                    priority=int(source.get("priority", 100)),
                )
            )
        mappings.append(ChannelMapping(channel_id=channel_id, display_name=display_name, sources=tuple(sorted(sources, key=lambda x: x.priority))))
    return mappings


def _provider_factory(provider_id: str):
    return default_registry.create(provider_id)


def build_xmltv(mappings: list[ChannelMapping], days: int, provider_factory: Callable[[str], Any] = _provider_factory) -> tuple[ET.ElementTree, dict[str, Any]]:
    tv = ET.Element("tv", {
        "generator-info-name": "EPGForgearr supplemental XMLTV",
        "generator-info-url": "https://github.com/michaz1988/michaz1988.github.io/tree/main/.epg",
    })
    programme_count = 0
    errors: list[dict[str, str]] = []
    coverage_starts: list[datetime] = []
    coverage_ends: list[datetime] = []
    provider_cache: dict[str, Any] = {}

    for mapping in mappings:
        channel = ET.SubElement(tv, "channel", {"id": mapping.channel_id})
        ET.SubElement(channel, "display-name", {"lang": "de"}).text = mapping.display_name
        for source in mapping.sources:
            ET.SubElement(channel, "display-name", {"lang": "de"}).text = source.label

    for mapping in mappings:
        source_errors: list[str] = []
        for source in mapping.sources:
            provider = provider_cache.setdefault(source.provider, provider_factory(source.provider))
            try:
                programmes = provider.fetch_programmes(source.provider_channel_id, days=days)
            except Exception as exc:  # noqa: BLE001 - try next source
                source_errors.append(f"{source.provider}:{type(exc).__name__}")
                continue
            for prog in programmes:
                start = _xmltv_time(prog.get("start"))
                stop = _xmltv_time(prog.get("stop"))
                title = prog.get("title") or "No Program Information available"
                if not start or not stop:
                    continue
                coverage_starts.append(datetime.strptime(start, "%Y%m%d%H%M%S %z"))
                coverage_ends.append(datetime.strptime(stop, "%Y%m%d%H%M%S %z"))
                node = ET.SubElement(tv, "programme", {"start": start, "stop": stop, "channel": mapping.channel_id})
                ET.SubElement(node, "title", {"lang": "de"}).text = title
                if prog.get("subtitle"):
                    ET.SubElement(node, "sub-title", {"lang": "de"}).text = prog["subtitle"]
                if prog.get("description"):
                    ET.SubElement(node, "desc", {"lang": "de"}).text = prog["description"]
                programme_count += 1
            break
        else:
            errors.append({"channel_id": mapping.channel_id, "error": "; ".join(source_errors) or "no source returned data"})

    tree = ET.ElementTree(tv)
    ET.indent(tree, space="  ")
    return tree, {
        "channel_count": len(mappings),
        "programme_count": programme_count,
        "error_count": len(errors),
        "errors": errors,
        "coverage_start": min(coverage_starts).isoformat() if coverage_starts else None,
        "coverage_end": max(coverage_ends).isoformat() if coverage_ends else None,
    }


def generate_xmltv(
    settings: dict[str, Any],
    logger: logging.Logger | None = None,
    provider_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    logger = logger or logging.getLogger(__name__)
    provider_factory = provider_factory or _provider_factory
    days = max(1, int(settings.get("days") or 1))
    output_path = Path(str(settings.get("output_path") or "/data/epgforgearr/epgforgearr.xml"))
    gzip_output = bool(settings.get("gzip_output", True))
    mappings = parse_mapping_config(settings.get("mapping_config_json", "[]"))
    tree, report = build_xmltv(mappings, days=days, provider_factory=provider_factory)
    # Failed fetches and malformed/empty programme payloads must not replace
    # a previously usable guide. A genuinely empty schedule is still valid.
    if report["error_count"]:
        return {
            "status": "error",
            "message": f"refresh failed for {report['error_count']} channel(s); existing output preserved",
            "output_path": str(output_path),
            "gzip_path": str(output_path.with_suffix(output_path.suffix + ".gz")) if gzip_output else None,
            **report,
            "errors": [{"channel_id": error["channel_id"], "error": sanitize_error_text(error["error"])} for error in report["errors"]],
        }
    gz_path = output_path.with_suffix(output_path.suffix + ".gz") if gzip_output else None
    # No usable mappings must never wipe an existing non-empty guide.
    if report["channel_count"] == 0 and report["programme_count"] == 0 and (_has_guide_content(output_path) or (gz_path is not None and _has_guide_content(gz_path))):
        return {
            "status": "error",
            "message": "generation blocked: zero usable mappings would overwrite existing non-empty output; existing output preserved",
            "output_path": str(output_path),
            "gzip_path": str(gz_path) if gz_path else None,
            **report,
        }
    _publish_outputs(tree, output_path, gz_path)
    logger.info("epgforgearr generated %s programmes for %s channels", report["programme_count"], report["channel_count"])
    return {
        "status": "ok" if report["error_count"] == 0 else "warning",
        "message": f"generated {report['programme_count']} programme(s) for {report['channel_count']} channel(s)",
        "output_path": str(output_path),
        "gzip_path": str(gz_path) if gz_path else None,
        **report,
    }


def _has_guide_content(path: Path) -> bool:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                data = handle.read()
        else:
            data = path.read_bytes()
    except (OSError, EOFError, zlib.error):
        return False
    return b"<channel" in data or b"<programme" in data


def sanitize_error_text(message: Any) -> str:
    """Remove URLs and credential-like values before an error is persisted or logged."""
    text = str(message or "")
    text = re.sub(r"(?i)https?://[^\s\"'<>]+", "<URL REDACTED>", text)
    text = re.sub(
        r"(?i)\b(authorization|proxy-authorization|token|password|passwd|secret|api[_-]?key|signature|sig|cookie)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+",
        r"\1=REDACTED",
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer REDACTED", text)
    return re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "REDACTED", text)


def _stage_xml_tree(tree: ET.ElementTree, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            tree.write(file, encoding="utf-8", xml_declaration=True)
        os.chmod(tmp_path, 0o664)
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _stage_gzip_file(source_path: Path, gzip_path: Path) -> Path:
    gzip_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{gzip_path.name}.", suffix=".tmp", dir=gzip_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as raw, source_path.open("rb") as source:
            with gzip.GzipFile(fileobj=raw, mode="wb") as compressed:
                shutil.copyfileobj(source, compressed)
        os.chmod(tmp_path, 0o664)
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _stage_backup(path: Path) -> Path | None:
    """Copy an existing file to a same-directory temp file, keeping its mode."""
    if not path.exists():
        return None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.backup.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as backup, path.open("rb") as source:
            shutil.copyfileobj(source, backup)
        os.chmod(tmp_path, path.stat().st_mode & 0o777)
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _publish_outputs(tree: ET.ElementTree, output_path: Path, gzip_path: Path | None) -> None:
    """Stage both outputs and roll XML back if publishing the gzip file fails.

    The old XML is backed up before anything is published, so rollback is a
    single rename that writes no new bytes. A backup is kept if rollback fails.
    """
    xml_tmp = _stage_xml_tree(tree, output_path)
    gzip_tmp = None
    backup = None
    keep_backup = False
    try:
        backup = _stage_backup(output_path)
        if gzip_path is not None:
            gzip_tmp = _stage_gzip_file(xml_tmp, gzip_path)
        os.replace(xml_tmp, output_path)
        xml_tmp = None
        if gzip_path is not None and gzip_tmp is not None:
            try:
                os.replace(gzip_tmp, gzip_path)
                gzip_tmp = None
            except Exception as exc:
                try:
                    if backup is not None:
                        os.replace(backup, output_path)
                        backup = None
                    else:
                        output_path.unlink(missing_ok=True)
                except Exception as rollback_exc:
                    keep_backup = True
                    where = f"old XML preserved at {backup}" if backup is not None else f"new XML left at {output_path}"
                    raise RuntimeError(
                        f"gzip publish failed ({type(exc).__name__}: {exc}) and XML rollback failed "
                        f"({type(rollback_exc).__name__}: {rollback_exc}); {where}; restore it manually"
                    ) from exc
                raise
    finally:
        for leftover in (xml_tmp, gzip_tmp):
            if leftover is not None:
                leftover.unlink(missing_ok=True)
        if backup is not None and not keep_backup:
            backup.unlink(missing_ok=True)


def _xmltv_time(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y%m%d%H%M%S +0000")
    text = str(value).replace(" UTC+00:00", "").replace(" UTC", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y%m%d%H%M%S +0000")
        except ValueError:
            pass
    return None
