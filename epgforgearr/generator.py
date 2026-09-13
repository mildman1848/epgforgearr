from __future__ import annotations

import gzip
import json
import logging
import os
import tempfile
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
                source_errors.append(f"{source.provider}:{source.provider_channel_id}: {type(exc).__name__}: {exc}")
                continue
            for prog in programmes:
                start = _xmltv_time(prog.get("start"))
                stop = _xmltv_time(prog.get("stop"))
                title = prog.get("title") or "No Program Information available"
                if not start or not stop:
                    continue
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
    return tree, {"channel_count": len(mappings), "programme_count": programme_count, "error_count": len(errors), "errors": errors}


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_xml_tree_atomic(tree, output_path)
    gz_path = None
    if gzip_output:
        gz_path = output_path.with_suffix(output_path.suffix + ".gz")
        _write_gzip_atomic(gz_path, output_path.read_bytes())
    logger.info("epgforgearr generated %s programmes for %s channels", report["programme_count"], report["channel_count"])
    return {
        "status": "ok" if report["error_count"] == 0 else "warning",
        "message": f"generated {report['programme_count']} programme(s) for {report['channel_count']} channel(s)",
        "output_path": str(output_path),
        "gzip_path": str(gz_path) if gz_path else None,
        **report,
    }


def _write_xml_tree_atomic(tree: ET.ElementTree, output_path: Path) -> None:
    """Write XMLTV via same-directory replace to survive stale root-owned files."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as file:
            tree.write(file, encoding="utf-8", xml_declaration=True)
        os.chmod(tmp_path, 0o664)
        os.replace(tmp_path, output_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_gzip_atomic(gz_path: Path, payload: bytes) -> None:
    """Write gzip via same-directory replace to avoid existing-file permissions."""
    gz_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{gz_path.name}.", suffix=".tmp", dir=gz_path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as file:
                file.write(payload)
        os.chmod(tmp_path, 0o664)
        os.replace(tmp_path, gz_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


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
