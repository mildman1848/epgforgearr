from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

try:
    from .epgforgearr.generator import generate_xmltv, parse_mapping_config, sanitize_error_text, supported_sources
    from .epgforgearr.workflow import (
        export_mapping_template,
        generate_all_provider_sources,
        generate_from_mapping_file,
        generate_full_provider_epg,
        install_epg_source,
        provider_profile,
        scan_missing_epg,
    )
except ImportError:  # standalone tests
    # Dispatcharr action probes may run from /app where another package name can
    # shadow the plugin's bundled epgforgearr package. Put this plugin directory
    # first and evict a previously cached foreign epgforgearr module before
    # falling back to absolute imports.
    _plugin_dir = Path(__file__).resolve().parent
    _plugin_dir_str = str(_plugin_dir)
    if sys.path[0] != _plugin_dir_str:
        sys.path.insert(0, _plugin_dir_str)
    _cached_epgforgearr = sys.modules.get("epgforgearr")
    _cached_file = Path(str(getattr(_cached_epgforgearr, "__file__", ""))).resolve() if _cached_epgforgearr else None
    if _cached_file and not _cached_file.is_relative_to(_plugin_dir):
        for _name in list(sys.modules):
            if _name == "epgforgearr" or _name.startswith("epgforgearr."):
                sys.modules.pop(_name, None)
    from epgforgearr.generator import generate_xmltv, parse_mapping_config, sanitize_error_text, supported_sources
    from epgforgearr.workflow import (
        export_mapping_template,
        generate_all_provider_sources,
        generate_from_mapping_file,
        generate_full_provider_epg,
        install_epg_source,
        provider_profile,
        scan_missing_epg,
    )

_MANIFEST_PATH = Path(__file__).with_name("plugin.json")
MANIFEST = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Self-scheduler (daily full provider refresh), Twitcharr-style:
# daemon thread in the Celery worker process only, never in web workers.
# ---------------------------------------------------------------------------

PLUGIN_KEY = "epgforgearr"
SCHEDULER_POLL_SECONDS = 300
STATE_REFRESH_INTERVAL = 24 * 3600  # daily full regeneration

_scheduler_lock = threading.RLock()
_scheduler_stop = threading.Event()
_scheduler_thread: threading.Thread | None = None


def _is_web_server_process() -> bool:
    """True inside Dispatcharr uWSGI/Daphne processes; scheduler must not run there."""
    if "uwsgi" in sys.modules:
        return True
    try:
        import uwsgi  # type: ignore # noqa: F401  (only importable inside uWSGI)

        return True
    except ImportError:
        pass
    return any(
        server in (arg or "").lower()
        for arg in sys.argv[:2]
        for server in ("daphne", "gunicorn")
    )


def _is_celery_worker_process() -> bool:
    """Only long-lived Celery workers may run the scheduler.

    One-off Django/Python checks also import plugins. Starting a daemon scheduler
    there creates stale lock files when the process exits, so be strict.
    """
    argv = " ".join(sys.argv).lower()
    return "celery" in argv and "worker" in argv


def _load_settings() -> dict:
    """Load plugin settings from DB (PluginConfig), fall back to manifest defaults."""
    try:
        from apps.plugins.models import PluginConfig

        cfg = PluginConfig.objects.filter(key=PLUGIN_KEY).first()
        if cfg and isinstance(cfg.settings, dict):
            return _merge_defaults(dict(cfg.settings))
    except Exception as exc:
        _logger.error("epgforgearr: failed to load plugin settings from DB (%s)", type(exc).__name__)
    return _merge_defaults({})


def _data_dir(settings: dict) -> str:
    raw = (settings.get("data_dir") or "").strip()
    if raw:
        return raw
    return "/data/epgforgearr"


def _state_path(settings: dict) -> str:
    return os.path.join(_data_dir(settings), ".scheduler_state.json")


def _load_state(settings: dict) -> dict:
    try:
        with open(_state_path(settings), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(settings: dict, state: dict) -> None:
    os.makedirs(os.path.dirname(_state_path(settings)), exist_ok=True)
    tmp = _state_path(settings) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, _state_path(settings))


def _job_lock(name: str, ttl_seconds: int = 7200) -> str:
    settings = _load_settings()
    os.makedirs(_data_dir(settings), exist_ok=True)
    path = os.path.join(_data_dir(settings), f".{name}.lock")
    try:
        if os.path.exists(path):
            stale = time.time() - os.path.getmtime(path) > ttl_seconds
            try:
                with open(path, encoding="utf-8") as f:
                    pid_text = (f.read().strip().split() or [""])[0]
                pid = int(pid_text) if pid_text else 0
                if pid and not os.path.exists(f"/proc/{pid}"):
                    stale = True
            except Exception:
                stale = True
            if stale:
                os.unlink(path)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {int(time.time())}\n")
        return path
    except FileExistsError:
        return ""


def _release_job_lock(path: str) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _sanitize_health_message(value: Any) -> str:
    return sanitize_error_text(value)


def _sanitize_health_value(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_health_message(value)
    if isinstance(value, dict):
        return {_sanitize_health_message(key): _sanitize_health_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_health_value(item) for item in value]
    return value


def _provider_health_results(results: dict, previous: dict, now: int) -> dict:
    previous = previous if isinstance(previous, dict) else {}
    health = {
        provider_id: {**_sanitize_health_value(old), "observed_in_last_attempt": False}
        for provider_id, old in previous.items()
        if isinstance(old, dict)
    }
    for provider_id, result in results.items():
        old = previous.get(provider_id, {})
        old = old if isinstance(old, dict) else {}
        generated = result.get("generated", {})
        success = result.get("status") == "ok" and generated.get("error_count", 0) == 0
        safe_result = _sanitize_health_value(result)
        coverage = None
        if success and (generated.get("coverage_start") or generated.get("coverage_end")):
            coverage = {"start": generated.get("coverage_start"), "end": generated.get("coverage_end")}
        health[provider_id] = {
            **safe_result,
            "last_attempt_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "last_success_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)) if success else old.get("last_success_at"),
            "coverage_window": coverage if success else old.get("coverage_window"),
            "channel_count": generated.get("channel_count", old.get("channel_count")) if success else old.get("channel_count"),
            "programme_count": generated.get("programme_count", old.get("programme_count")) if success else old.get("programme_count"),
            "error": None if success else _sanitize_health_message(result.get("message")),
            "observed_in_last_attempt": True,
        }
    return health


def compute_scheduler_status(
    settings: dict,
    state: dict,
    thread_alive: bool,
    refresh_interval_seconds: int = STATE_REFRESH_INTERVAL,
    now: int | None = None,
) -> dict:
    """Pure status calculation, no Django/IO - kept separate so it is unit testable.

    `state` is the persisted scheduler state dict (see `_load_state`/`_save_state`).
    `next_due`/`seconds_until_due` are None when the schedule is disabled; a
    refresh that has never run is treated as due immediately.
    """
    now = int(time.time()) if now is None else int(now)
    schedule_enabled = bool(settings.get("schedule_enabled", True))
    last_refresh = int(state.get("last_full_refresh") or 0)

    next_due: int | None = None
    seconds_until_due: int | None = None
    if schedule_enabled:
        next_due = now if last_refresh <= 0 else last_refresh + refresh_interval_seconds
        seconds_until_due = max(0, next_due - now)

    return {
        "schedule_enabled": schedule_enabled,
        "thread_alive": bool(thread_alive),
        "refresh_interval_seconds": refresh_interval_seconds,
        "refresh_interval_hours": refresh_interval_seconds // 3600,
        "last_refresh": last_refresh or None,
        "last_refresh_at": state.get("last_full_refresh_at"),
        "last_refresh_status": state.get("last_full_refresh_status"),
        "next_due": next_due,
        "next_due_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(next_due)) if next_due else None,
        "seconds_until_due": seconds_until_due,
    }


def _scheduled_job() -> dict:
    """One scheduled tick: regenerate + install every usable provider's EPG if stale.

    Each usable provider (see `usable_provider_ids`) gets its own XMLTV file
    and its own Dispatcharr EPGSource; results are recorded per provider in
    the persisted scheduler state under `providers`. This never auto-maps
    Dispatcharr Channels and never creates Channel objects - only EPGSources.
    """
    settings = _load_settings()
    if not settings.get("schedule_enabled", True):
        return {"status": "ok", "message": "schedule disabled"}

    state = _load_state(settings)
    now = int(time.time())
    last = int(state.get("last_full_refresh") or 0)
    if now - last < STATE_REFRESH_INTERVAL:
        return {"status": "ok", "message": "not due yet"}

    lock = _job_lock("full_refresh")
    if not lock:
        return {"status": "ok", "message": "refresh already running elsewhere"}
    try:
        _logger.info("epgforgearr scheduled full refresh starting for all usable providers")
        result = generate_all_provider_sources(settings)
        if result.get("status") == "error":
            # Nothing succeeded: keep last_full_refresh unchanged so the next
            # poll tick retries soon instead of waiting a full day.
            state.update({
                "last_full_refresh_status": "error",
                "last_full_refresh_error": _sanitize_health_message(result.get("message")),
                "last_full_refresh_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "last_summary": _sanitize_health_message(result.get("message")),
                "providers": _provider_health_results(result.get("providers", {}), state.get("providers", {}), now),
            })
            _save_state(settings, state)
            return {"status": "error", "message": f"full refresh failed: {_sanitize_health_message(result.get('message'))}"}
        state.update({
            "last_full_refresh_status": result.get("status"),
            "last_full_refresh_error": None if result.get("status") == "ok" else _sanitize_health_message(result.get("message")),
            "last_full_refresh_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "last_summary": _sanitize_health_message(result.get("message")),
            "providers": _provider_health_results(result.get("providers", {}), state.get("providers", {}), now),
        })
        if result.get("status") == "ok":
            state["last_full_refresh"] = now
        _save_state(settings, state)
        return {"status": "ok", "message": state["last_summary"]}
    finally:
        _release_job_lock(lock)


def _scheduler_loop() -> None:
    own_module = __name__
    _logger.info("epgforgearr self-scheduler started")
    while not _scheduler_stop.is_set():
        if own_module not in sys.modules:
            _logger.info("epgforgearr scheduler exiting: module %s was unloaded", own_module)
            return
        try:
            from django.db import close_old_connections

            close_old_connections()
            result = _scheduled_job()
            if result.get("status") != "ok":
                _logger.warning("epgforgearr scheduled tick: %s", result.get("message"))
        except ImportError as exc:
            _logger.info("epgforgearr scheduler exiting after plugin reload: %s", exc)
            return
        except Exception as exc:
            _logger.error("epgforgearr scheduler tick failed (%s)", type(exc).__name__)
        finally:
            try:
                from django.db import close_old_connections

                close_old_connections()
            except Exception as exc:
                _logger.error("epgforgearr scheduler could not close its database connection (%s)", type(exc).__name__)
        _scheduler_stop.wait(SCHEDULER_POLL_SECONDS)
    _logger.info("epgforgearr self-scheduler stopped")


def _start_scheduler() -> bool:
    global _scheduler_thread
    if _is_web_server_process() or not _is_celery_worker_process():
        _logger.info(
            "epgforgearr scheduler not started in this process; "
            "it runs only in long-lived Celery worker processes"
        )
        return False
    with _scheduler_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return False
        _scheduler_stop.clear()
        _scheduler_thread = threading.Thread(target=_scheduler_loop, name="EpgforgearrScheduler", daemon=True)
        _scheduler_thread.start()
        return True


def _stop_superseded_schedulers() -> int:
    """Stop scheduler threads left behind by an older epgforgearr module import."""
    current_module = sys.modules.get(__name__)
    stopped = 0
    for module_name, module in list(sys.modules.items()):
        if module is None or module is current_module:
            continue
        plugin_class = getattr(module, "Plugin", None)
        if getattr(plugin_class, "name", None) != MANIFEST["name"]:
            continue
        stop_event = getattr(module, "_scheduler_stop", None)
        thread = getattr(module, "_scheduler_thread", None)
        if not callable(getattr(stop_event, "set", None)):
            continue
        is_alive = getattr(thread, "is_alive", None)
        if not callable(is_alive) or not is_alive():
            continue
        stop_event.set()
        if thread is not threading.current_thread():
            join = getattr(thread, "join", None)
            if callable(join):
                join(timeout=5)
        stopped += 1
        _logger.info("Stopped superseded epgforgearr scheduler from %s", module_name)
    return stopped


class Plugin:
    """Dispatcharr plugin entry point."""

    name = MANIFEST["name"]
    version = MANIFEST["version"]
    description = MANIFEST["description"]
    author = MANIFEST.get("author", "")
    fields = MANIFEST.get("fields", [])
    actions = MANIFEST.get("actions", [])

    def __init__(self):
        try:
            _stop_superseded_schedulers()
            _start_scheduler()
        except Exception as exc:
            _logger.error("epgforgearr: could not start persisted scheduler (%s)", type(exc).__name__)

    def run(self, action: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        logger = context.get("logger") or logging.getLogger(__name__)
        settings = _merge_defaults(_settings_from_context_and_params(context, params))
        try:
            if action == "list_sources":
                sources = supported_sources()
                return {"status": "ok", "message": f"{len(sources)} source adapter(s)", "sources": sources}
            if action == "scheduler_status":
                persisted_settings = _load_settings()
                state = _load_state(persisted_settings)
                info = compute_scheduler_status(
                    persisted_settings,
                    state,
                    thread_alive=bool(_scheduler_thread and _scheduler_thread.is_alive()),
                )
                return {
                    "status": "ok",
                    "message": "scheduler state",
                    "state": state,
                    **info,
                }
            if action == "validate_mapping":
                mappings = parse_mapping_config(settings.get("mapping_config_json", "[]"))
                return {"status": "ok", "message": f"mapping valid: {len(mappings)} channel(s)", "channel_count": len(mappings)}
            if action == "scan_missing_epg":
                return scan_missing_epg(settings, logger=logger)
            if action == "export_mapping_template":
                return export_mapping_template(settings, logger=logger)
            if action == "generate_epg":
                return generate_xmltv(settings, logger=logger)
            if action == "generate_from_mapping":
                return generate_from_mapping_file(settings, logger=logger)
            if action == "generate_full_provider_epg":
                return generate_full_provider_epg(_single_provider_settings(settings), logger=logger)
            if action == "install_epg_source":
                return install_epg_source(settings, logger=logger)
            if action == "generate_and_install":
                generated = generate_from_mapping_file(settings, logger=logger)
                if generated.get("status") not in {"ok", "warning"}:
                    return generated
                installed = install_epg_source(settings, logger=logger)
                return {"status": installed["status"], "message": f"{generated.get('message')}; {installed.get('message')}", "generated": generated, "installed": installed}
            if action == "generate_full_and_install":
                provider_settings = _single_provider_settings(settings)
                generated = generate_full_provider_epg(provider_settings, logger=logger)
                if generated.get("status") not in {"ok", "warning"}:
                    return generated
                installed = install_epg_source(provider_settings, logger=logger)
                return {"status": installed["status"], "message": f"{generated.get('message')}; {installed.get('message')}", "generated": generated, "installed": installed}
            if action == "generate_all_provider_sources":
                return generate_all_provider_sources(settings, logger=logger)
            return {"status": "error", "message": f"Unknown action: {action}"}
        except Exception as exc:  # noqa: BLE001 - plugin boundary should report typed failure
            logger.error("epgforgearr: action %s failed (%s)", action, type(exc).__name__)
            return {"status": "error", "message": f"{action} failed ({type(exc).__name__}); details redacted"}


def _settings_from_context_and_params(context: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(context.get("settings") or {})
    params = params or {}
    runtime_settings = params.get("settings") if isinstance(params.get("settings"), dict) else {}
    merged.update(runtime_settings)
    for field in MANIFEST.get("fields", []):
        field_id = field.get("id")
        if field_id in params and field_id != "status":
            merged[field_id] = params[field_id]
    return merged


def _merge_defaults(settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(settings)
    for field in MANIFEST.get("fields", []):
        if "id" in field and "default" in field and field["id"] not in merged:
            merged[field["id"]] = field["default"]
    return merged


def _field_default(field_id: str, fallback: Any = None) -> Any:
    for field in MANIFEST.get("fields", []):
        if field.get("id") == field_id:
            return field.get("default", fallback)
    return fallback


def _single_provider_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Apply provider identity for single-provider full actions.

    The UI still exposes legacy Magenta defaults for output/source fields. If a
    user selects TV Digital DE but leaves those defaults untouched, this keeps
    the single-provider actions from overwriting the Magenta-managed XMLTV file
    or EPGSource. Explicit user overrides are preserved.
    """
    provider_id = str(settings.get("full_provider") or "magenta")
    selected = provider_profile(provider_id)
    magenta = provider_profile("magenta")
    adjusted = dict(settings)

    default_output_path = _field_default("output_path", magenta["output_path"])
    default_source_name = _field_default("epg_source_name", magenta["epg_source_name"])
    default_priority = _field_default("epg_source_priority", magenta["epg_source_priority"])

    if adjusted.get("output_path") in (None, "", default_output_path, magenta["output_path"]):
        adjusted["output_path"] = selected["output_path"]
    if adjusted.get("epg_source_name") in (None, "", default_source_name, magenta["epg_source_name"]):
        adjusted["epg_source_name"] = selected["epg_source_name"]
    if adjusted.get("epg_source_priority") in (None, "", default_priority, magenta["epg_source_priority"]):
        adjusted["epg_source_priority"] = selected["epg_source_priority"]
    return adjusted
