from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .generator import generate_xmltv, parse_mapping_config
from .providers import default_registry

DATA_DIR = Path("/data/epgforgearr")
DEFAULT_SUGGESTIONS_PATH = DATA_DIR / "review" / "suggestions.json"
DEFAULT_MAPPING_PATH = DATA_DIR / "review" / "mapping.selected.json"
DEFAULT_OUTPUT_PATH = DATA_DIR / "epgforgearr.xml"
PLUGIN_ID = "epgforgearr"
EPG_SOURCE_NAME = "EPGForgearr: Supplemental"

# Per-provider defaults for the "separate Dispatcharr EPGSource per provider"
# design: each usable provider gets its own output file and its own managed
# EPGSource so they never collide when several providers run side by side.
PROVIDER_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    "magenta": {
        "output_path": str(DATA_DIR / "magenta-full.xml"),
        "epg_source_name": "EPGForgearr: Magenta",
        "epg_source_priority": 60,
    },
    "tvdigital_de": {
        "output_path": str(DATA_DIR / "tvdigital-de-full.xml"),
        "epg_source_name": "EPGForgearr: TV Digital DE",
        "epg_source_priority": 70,
    },
}
DEFAULT_PROVIDER_PRIORITY = 100


def provider_profile(provider_id: str) -> dict[str, Any]:
    """Per-provider defaults: output path, Dispatcharr EPGSource name/priority.

    Explicit entries live in `PROVIDER_PROFILE_DEFAULTS`. Any other usable
    provider (registered later, before an explicit profile is added) still
    gets a distinct, derived profile instead of colliding with another
    provider's output file or EPGSource name.
    """
    profile = PROVIDER_PROFILE_DEFAULTS.get(provider_id)
    if profile is not None:
        return dict(profile)
    slug = provider_id.replace("_", "-")
    return {
        "output_path": str(DATA_DIR / f"{slug}-full.xml"),
        "epg_source_name": f"EPGForgearr: {provider_id}",
        "epg_source_priority": DEFAULT_PROVIDER_PRIORITY,
    }


def usable_provider_ids() -> list[str]:
    """Provider ids with a usable factory, in registry order (excludes 'planned' entries)."""
    return [entry["id"] for entry in default_registry.describe_all() if default_registry.is_registered(entry["id"])]


@dataclass(frozen=True)
class Candidate:
    provider: str
    provider_channel_id: str
    label: str
    confidence: str
    reason: str
    priority: int


@dataclass(frozen=True)
class ScanItem:
    channel_id: str
    channel_uuid: str
    channel_name: str
    tvg_id: str
    stream_id: int
    stream_name: str
    stream_tvg_id: str
    existing_epg: bool
    selected: bool
    linked_channel: bool
    candidates: tuple[Candidate, ...]


def scan_missing_epg(settings: dict[str, Any], logger: logging.Logger | None = None) -> dict[str, Any]:
    """Scan Dispatcharr channels/streams and write reviewable EPG suggestions.

    The scanner is intentionally conservative. It prefers user-managed Channels
    linked to Kodiboxarr streams and avoids auto-applying low confidence matches.
    """
    logger = logger or logging.getLogger(__name__)
    confidence_min = str(settings.get("scan_min_confidence") or "medium").lower()
    include_existing = bool(settings.get("scan_include_existing_epg", False))
    suggestions_path = Path(str(settings.get("suggestions_path") or DEFAULT_SUGGESTIONS_PATH))

    rows = _dispatcharr_kodibox_rows(include_existing=include_existing)
    # Scan heuristics below (name normalization, sport-number matching) are
    # Magenta-specific; the registry lookup just avoids a second hardcoded
    # constructor call alongside generate_full_provider_epg.
    provider = default_registry.create("magenta")
    magenta_channels = provider.list_channels()
    magenta_index = _index_magenta_channels(magenta_channels)

    items: list[ScanItem] = []
    for row in rows:
        candidates = tuple(_suggest_candidates(row["stream_name"], row.get("stream_tvg_id") or row.get("tvg_id") or "", magenta_index))
        candidates = tuple(c for c in candidates if _confidence_rank(c.confidence) >= _confidence_rank(confidence_min))
        if not candidates:
            continue
        selected = bool(settings.get("scan_auto_select", False)) and candidates[0].confidence in {"exact", "high", "medium"}
        items.append(
            ScanItem(
                channel_id=_mapping_channel_id(row),
                channel_uuid=row["channel_uuid"],
                channel_name=row["channel_name"],
                tvg_id=row.get("tvg_id") or "",
                stream_id=int(row["stream_id"]),
                stream_name=row["stream_name"],
                stream_tvg_id=row.get("stream_tvg_id") or "",
                existing_epg=bool(row.get("existing_epg")),
                selected=selected,
                linked_channel=bool(row.get("linked_channel")),
                candidates=candidates,
            )
        )

    payload = {
        "schema": "epgforgearr.suggestions.v1",
        "instructions": [
            "Review candidates before generating XMLTV.",
            "Set selected=false for uncertain mappings.",
            "Only selected items are exported into mapping.selected.json.",
        ],
        "counts": {
            "scanned_channels": len(rows),
            "suggested_channels": len(items),
            "selected_by_default": sum(1 for item in items if item.selected),
            "magenta_channels": len(magenta_channels),
        },
        "items": [_scan_item_to_dict(item) for item in items],
    }
    _write_json(suggestions_path, payload)
    logger.info("epgforgearr scan wrote %s suggestion(s) to %s", len(items), suggestions_path)
    return {
        "status": "ok",
        "message": f"scan complete: {len(items)} suggestion(s), {payload['counts']['selected_by_default']} selected by default",
        "suggestions_path": str(suggestions_path),
        **payload["counts"],
    }


def export_mapping_template(settings: dict[str, Any], logger: logging.Logger | None = None) -> dict[str, Any]:
    """Convert reviewed suggestions to generator mapping JSON."""
    logger = logger or logging.getLogger(__name__)
    suggestions_path = Path(str(settings.get("suggestions_path") or DEFAULT_SUGGESTIONS_PATH))
    mapping_path = Path(str(settings.get("mapping_path") or DEFAULT_MAPPING_PATH))
    if not suggestions_path.exists():
        raise FileNotFoundError(f"suggestions file not found: {suggestions_path}")
    payload = json.loads(suggestions_path.read_text(encoding="utf-8"))
    mappings: list[dict[str, Any]] = []
    skipped = 0
    for item in payload.get("items", []):
        if not item.get("selected", False):
            skipped += 1
            continue
        candidates = item.get("candidates") or []
        if not candidates:
            skipped += 1
            continue
        chosen = item.get("chosen_candidate") or candidates[0]
        mappings.append(
            {
                "channel_id": item["channel_id"],
                "display_name": item.get("channel_name") or item.get("stream_name") or item["channel_id"],
                "sources": [
                    {
                        "provider": chosen["provider"],
                        "provider_channel_id": str(chosen["provider_channel_id"]),
                        "label": chosen.get("label") or chosen["provider_channel_id"],
                        "priority": int(chosen.get("priority", 1)),
                        "confidence": chosen.get("confidence"),
                        "reason": chosen.get("reason"),
                    }
                ],
                "metadata": {
                    "channel_uuid": item.get("channel_uuid"),
                    "stream_id": item.get("stream_id"),
                    "stream_name": item.get("stream_name"),
                    "existing_epg": item.get("existing_epg", False),
                },
            }
        )
    parse_mapping_config(mappings)  # validation
    _write_json(mapping_path, mappings)
    logger.info("epgforgearr exported %s mapping(s) to %s", len(mappings), mapping_path)
    return {
        "status": "ok",
        "message": f"exported {len(mappings)} selected mapping(s), skipped {skipped}",
        "mapping_path": str(mapping_path),
        "mapping_count": len(mappings),
        "skipped_count": skipped,
    }


def generate_from_mapping_file(settings: dict[str, Any], logger: logging.Logger | None = None) -> dict[str, Any]:
    """Generate XMLTV from a reviewed mapping file."""
    mapping_path = Path(str(settings.get("mapping_path") or DEFAULT_MAPPING_PATH))
    if not mapping_path.exists():
        raise FileNotFoundError(f"mapping file not found: {mapping_path}")
    merged = dict(settings)
    merged["mapping_config_json"] = mapping_path.read_text(encoding="utf-8")
    merged.setdefault("output_path", str(DEFAULT_OUTPUT_PATH))
    return generate_xmltv(merged, logger=logger)


def generate_full_provider_epg(
    settings: dict[str, Any],
    logger: logging.Logger | None = None,
    provider_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Generate XMLTV for a complete provider channel list.

    This is the better base mode for Dispatcharr: the EPG source contains all
    provider channels, and the user maps Dispatcharr Channels to the desired EPG
    IDs. Suggestions remain advisory and do not limit the generated guide.

    The provider is resolved through the shared provider registry so adding a
    source beyond Magenta only means registering it there, not branching here.
    `provider_factory` is injectable for tests; it defaults to the registry.
    """
    logger = logger or logging.getLogger(__name__)
    provider_factory = provider_factory or default_registry.create
    provider_id = str(settings.get("full_provider") or "magenta").strip().lower()
    if not default_registry.is_registered(provider_id):
        raise ValueError(f"unsupported full_provider: {provider_id}")

    provider = provider_factory(provider_id)
    channels = provider.list_channels()
    mappings: list[dict[str, Any]] = []
    for channel in channels:
        content_id = str(channel.get("contentId") or channel.get("contentid") or channel.get("id") or "").strip()
        name = str(channel.get("name") or "").strip()
        if not content_id or not name:
            continue
        mappings.append(
            {
                "channel_id": f"{provider_id}.{content_id}",
                "display_name": name,
                "sources": [
                    {
                        "provider": provider_id,
                        "provider_channel_id": content_id,
                        "label": name,
                        "priority": 1,
                    }
                ],
                "metadata": {"provider": provider_id, "content_id": content_id},
            }
        )

    output_path = Path(str(settings.get("output_path") or provider_profile(provider_id)["output_path"]))
    merged = dict(settings)
    merged["mapping_config_json"] = mappings
    merged["output_path"] = str(output_path)
    result = generate_xmltv(merged, logger=logger, provider_factory=provider_factory)
    result["provider_channel_count"] = len(mappings)
    result["provider"] = provider_id
    logger.info("epgforgearr generated full %s EPG: %s channel(s), %s programme(s)", provider_id, result.get("channel_count"), result.get("programme_count"))
    return result


def _settings_for_provider(settings: dict[str, Any], provider_id: str) -> dict[str, Any]:
    """Build per-provider settings: shared knobs from `settings`, identity from the profile.

    Shared knobs (days, gzip_output, epg_source_active, ...) keep coming from
    the plugin settings so a user can still tune fetch depth/activation once.
    Identity fields (output_path, epg_source_name, epg_source_priority) always
    come from `provider_profile` so multiple providers never collide on one
    output file or one Dispatcharr EPGSource.
    """
    profile = provider_profile(provider_id)
    merged = dict(settings)
    merged["full_provider"] = provider_id
    merged["output_path"] = profile["output_path"]
    merged["epg_source_name"] = profile["epg_source_name"]
    merged["epg_source_priority"] = profile["epg_source_priority"]
    return merged


def generate_all_provider_sources(
    settings: dict[str, Any],
    logger: logging.Logger | None = None,
    provider_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Generate and install a separate Dispatcharr EPGSource per usable provider.

    Implements the "separate EPGSource per provider" design: every provider
    that has a usable factory (not merely 'planned', e.g. simpli_tv) is
    generated and installed independently, each with its own output file and
    EPGSource (see `provider_profile`). One provider failing does not stop
    the others; per-provider outcomes are returned under `providers` so the
    caller (action handler or scheduler) can record/report them individually.
    Channels are never auto-mapped and no Channel objects are created here.
    """
    logger = logger or logging.getLogger(__name__)
    provider_ids = usable_provider_ids()
    results: dict[str, dict[str, Any]] = {}
    ok_count = 0
    error_count = 0
    for provider_id in provider_ids:
        provider_settings = _settings_for_provider(settings, provider_id)
        try:
            generated = generate_full_provider_epg(provider_settings, logger=logger, provider_factory=provider_factory)
            if generated.get("status") not in {"ok", "warning"}:
                results[provider_id] = {"status": "error", "message": generated.get("message"), "generated": generated}
                error_count += 1
                continue
            installed = install_epg_source(provider_settings, logger=logger)
            status = installed.get("status", "ok")
            results[provider_id] = {
                "status": status,
                "message": f"{generated.get('message')}; {installed.get('message')}",
                "generated": generated,
                "installed": installed,
            }
            if status == "ok":
                ok_count += 1
            else:
                error_count += 1
        except Exception as exc:  # noqa: BLE001 - one provider failing must not abort the rest
            logger.exception("epgforgearr: full generation failed for provider %s", provider_id)
            results[provider_id] = {"status": "error", "message": f"{type(exc).__name__}: {exc}"}
            error_count += 1

    overall = "ok" if error_count == 0 else ("warning" if ok_count else "error")
    return {
        "status": overall,
        "message": f"generated {ok_count}/{len(provider_ids)} provider EPG source(s), {error_count} failed",
        "providers": results,
        "provider_ids": provider_ids,
    }


def install_epg_source(settings: dict[str, Any], logger: logging.Logger | None = None) -> dict[str, Any]:
    """Create/update the Dispatcharr EPGSource for the generated XMLTV file."""
    logger = logger or logging.getLogger(__name__)
    output_path = Path(str(settings.get("output_path") or DEFAULT_OUTPUT_PATH))
    gzip_output = bool(settings.get("gzip_output", True))
    source_path = output_path.with_suffix(output_path.suffix + ".gz") if gzip_output else output_path
    if not source_path.exists():
        raise FileNotFoundError(f"generated EPG file not found: {source_path}")

    EPGSource = _import_epg_source_model()
    defaults = {
        "source_type": "xmltv",
        "url": "",
        "file_path": str(source_path),
        "is_active": bool(settings.get("epg_source_active", True)),
        "priority": int(settings.get("epg_source_priority", 60)),
        "refresh_interval": int(settings.get("epg_source_refresh_hours", 24)),
        "custom_properties": {"managed_by": PLUGIN_ID, "output_path": str(source_path)},
        "status": "success",
        "last_message": "Managed by EPGForgearr",
    }
    source, created = EPGSource.objects.update_or_create(name=str(settings.get("epg_source_name") or EPG_SOURCE_NAME), defaults=defaults)
    readback = EPGSource.objects.get(pk=source.pk)
    logger.info("epgforgearr %s Dispatcharr EPGSource id=%s path=%s", "created" if created else "updated", source.pk, source_path)
    return {
        "status": "ok",
        "message": f"EPGSource {'created' if created else 'updated'}: {readback.name}",
        "epg_source_id": readback.id,
        "epg_source_name": readback.name,
        "file_path": getattr(readback, "file_path", ""),
        "is_active": bool(readback.is_active),
        "priority": int(readback.priority),
        "created": created,
    }


def _dispatcharr_kodibox_rows(include_existing: bool) -> list[dict[str, Any]]:
    from apps.channels.models import ChannelStream, Stream

    streams = (
        Stream.objects.select_related("m3u_account")
        .filter(m3u_account__name="Kodiboxarr: Kodibox TV")
        .order_by("name", "id")
    )
    first_link_by_stream: dict[int, Any] = {}
    any_epg_by_stream: dict[int, bool] = {}
    links = ChannelStream.objects.select_related("channel", "stream").filter(stream__m3u_account__name="Kodiboxarr: Kodibox TV").order_by("order", "id")
    for link in links:
        first_link_by_stream.setdefault(link.stream_id, link)
        any_epg_by_stream[link.stream_id] = any_epg_by_stream.get(link.stream_id, False) or bool(getattr(link.channel, "epg_data_id", None))

    rows: list[dict[str, Any]] = []
    for stream in streams:
        link = first_link_by_stream.get(stream.id)
        channel = link.channel if link else None
        # A tvg_id alone is not enough; Dispatcharr may know the ID but still
        # have no EPGData object/programmes for it. For gap scanning, only a
        # linked epg_data_id counts as existing EPG coverage.
        existing_epg = bool(any_epg_by_stream.get(stream.id, False))
        if existing_epg and not include_existing:
            continue
        rows.append(
            {
                "channel_id": getattr(channel, "id", None),
                "channel_uuid": str(getattr(channel, "uuid", "")),
                "channel_name": getattr(channel, "name", "") or stream.name,
                "channel_number": getattr(channel, "channel_number", None),
                "tvg_id": getattr(channel, "tvg_id", "") or "",
                "stream_id": stream.id,
                "stream_name": stream.name,
                "stream_tvg_id": stream.tvg_id or "",
                "existing_epg": existing_epg,
                "linked_channel": bool(channel),
            }
        )
    return rows


def _import_epg_source_model():
    from apps.epg.models import EPGSource

    return EPGSource


def _index_magenta_channels(channels: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    by_norm: dict[str, dict[str, str]] = {}
    sport_by_number: dict[str, dict[str, str]] = {}
    for channel in channels:
        content_id = str(channel.get("contentId") or channel.get("contentid") or channel.get("id") or "").strip()
        name = str(channel.get("name") or "").strip()
        if not content_id or not name:
            continue
        row = {"content_id": content_id, "name": name, "norm": _norm(name)}
        rows.append(row)
        by_norm.setdefault(row["norm"], row)
        match = re.search(r"\bSport\s+(\d+)\b", name, flags=re.I)
        if match and "myteamtv" in row["norm"]:
            sport_by_number.setdefault(match.group(1), row)
    return {"rows": rows, "by_norm": by_norm, "sport_by_number": sport_by_number}


def _suggest_candidates(stream_name: str, tvg_id: str, index: dict[str, Any]) -> list[Candidate]:
    candidates: list[Candidate] = []
    norm_name = _norm(stream_name)
    norm_tvg = _norm(tvg_id)
    by_norm = index["by_norm"]
    for needle, reason_base in ((norm_name, "stream name exact"), (norm_tvg, "tvg-id exact")):
        if needle and needle in by_norm:
            row = by_norm[needle]
            candidates.append(_candidate(row, "exact", reason_base, 1))

    number_match = re.search(r"\b(?:MAGENTA\s+)?(?:SPORT|FUSSBALL|BUNDESLIGA)\s*(\d+)\b", stream_name, flags=re.I)
    if number_match:
        number = number_match.group(1)
        row = index["sport_by_number"].get(number)
        if row:
            confidence = "medium" if re.search(r"\bMAGENTA\s+SPORT\b", stream_name, flags=re.I) else "low"
            candidates.append(_candidate(row, confidence, f"Magenta sports/event channel number {number} -> myTeamTV Sport {number}", 10 if confidence == "medium" else 30))

    # Conservative contains match: only for long names to avoid VOX/VOX UP style mistakes.
    if len(norm_name) >= 7:
        for row in index["rows"]:
            if norm_name in row["norm"] or row["norm"] in norm_name:
                candidates.append(_candidate(row, "low", "normalized contains match", 50))
                break

    dedup: dict[tuple[str, str], Candidate] = {}
    for candidate in candidates:
        key = (candidate.provider, candidate.provider_channel_id)
        old = dedup.get(key)
        if old is None or candidate.priority < old.priority:
            dedup[key] = candidate
    return sorted(dedup.values(), key=lambda c: (-_confidence_rank(c.confidence), c.priority, c.label))[:5]


def _candidate(row: dict[str, str], confidence: str, reason: str, priority: int) -> Candidate:
    return Candidate("magenta", row["content_id"], row["name"], confidence, reason, priority)


def _mapping_channel_id(row: dict[str, Any]) -> str:
    tvg = str(row.get("tvg_id") or row.get("stream_tvg_id") or "").strip()
    if tvg:
        return tvg
    safe = re.sub(r"[^A-Za-z0-9_.-]+", ".", str(row.get("channel_name") or row.get("stream_name") or row["channel_uuid"]).strip()).strip(".")
    return f"epgforgearr.{safe or row['channel_uuid']}"


def _scan_item_to_dict(item: ScanItem) -> dict[str, Any]:
    data = asdict(item)
    data["candidates"] = [asdict(candidate) for candidate in item.candidates]
    data["chosen_candidate"] = data["candidates"][0] if data["candidates"] else None
    return data


def _norm(value: str) -> str:
    value = value.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    value = re.sub(r"\b(hd|fhd|uhd|4k|de|tv)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _confidence_rank(value: str) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3, "exact": 4}.get(str(value).lower(), 0)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
