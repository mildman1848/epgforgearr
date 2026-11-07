from types import SimpleNamespace
from typing import ClassVar

import pytest

from epgforgearr import workflow


class FakeQS:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def update(self, **kw):
        for r in self.rows:
            r.__dict__.update(kw)


class FakeSource:
    store: ClassVar[dict] = {}
    next_id = 1

    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.id = self.pk = FakeSource.next_id
        FakeSource.next_id += 1

    def save(self, update_fields=None):
        pass

    class objects:
        @staticmethod
        def get_or_create(name, defaults):
            if name in FakeSource.store:
                return FakeSource.store[name], False
            FakeSource.store[name] = FakeSource(name=name, **defaults)
            return FakeSource.store[name], True

        @staticmethod
        def filter(pk):
            return FakeQS([s for s in FakeSource.store.values() if s.pk == pk])

        @staticmethod
        def get(pk):
            return next(s for s in FakeSource.store.values() if s.pk == pk)


class Rows:
    def __init__(self):
        self.n = 0

    def filter(self, **kw):
        return FakeQS([None] * self.n)


@pytest.fixture
def env(tmp_path, monkeypatch):
    FakeSource.store, FakeSource.next_id = {}, 1
    epg, prog = Rows(), Rows()
    queued = []
    hook = SimpleNamespace(status=None)  # status Dispatcharr's worker would set after the queued refresh

    def delay(*a, **k):
        queued.append((a, k))
        if hook.status:
            FakeSource.store[workflow.EPG_SOURCE_NAME].status = hook.status
    monkeypatch.setattr(workflow, "_import_epg_source_model", lambda: FakeSource)
    monkeypatch.setattr(workflow, "_import_epg_data_models", lambda: (SimpleNamespace(objects=epg), SimpleNamespace(objects=prog)))
    monkeypatch.setattr(
        workflow, "_import_refresh_task", lambda: SimpleNamespace(delay=delay)
    )
    monkeypatch.setattr(workflow.time, "sleep", lambda s: None)
    out = tmp_path / "x.xml"
    out.write_text("<tv/>")
    settings = {"output_path": str(out), "gzip_output": False, "epg_import_wait_seconds": 0}
    return SimpleNamespace(hook=hook, epg=epg, prog=prog, queued=queued, settings=settings)


def test_new_source_is_not_claimed_success_without_import(env):
    r = workflow.install_epg_source(env.settings)
    src = FakeSource.store[workflow.EPG_SOURCE_NAME]
    assert r["created"] and r["status"] == "pending"
    assert src.status == "idle"  # not pre-marked success
    # Rationale: Dispatcharr v0.33.0's post_save signal queues new active sources. This fake does
    # not run that signal, so the test only proves the plugin makes no direct delay() call.
    assert env.queued == []


def test_ok_only_with_readback_rows(env):
    workflow.install_epg_source(env.settings)
    env.hook.status = "success"
    env.epg.n, env.prog.n = 3, 0
    assert workflow.install_epg_source(env.settings)["status"] == "warning"
    env.prog.n = 10
    r = workflow.install_epg_source(env.settings)
    assert r["status"] == "ok" and r["epg_data_count"] == 3 and r["programme_count"] == 10


def test_existing_source_is_reused_and_one_refresh_queued(env):
    workflow.install_epg_source(env.settings)
    r = workflow.install_epg_source(env.settings)
    assert len(FakeSource.store) == 1 and not r["created"]
    assert env.queued == [((FakeSource.store[workflow.EPG_SOURCE_NAME].pk,), {"force": True})]
    assert r["status"] == "pending"


def test_no_duplicate_queue_while_refresh_in_flight(env):
    workflow.install_epg_source(env.settings)
    FakeSource.store[workflow.EPG_SOURCE_NAME].status = "parsing"
    workflow.install_epg_source(env.settings)
    assert env.queued == []


def test_queue_failure_is_reported_as_error(env, monkeypatch):
    workflow.install_epg_source(env.settings)

    def boom(*a, **k):
        raise ConnectionError("broker http://secret-host down")

    monkeypatch.setattr(workflow, "_import_refresh_task", lambda: SimpleNamespace(delay=boom))
    r = workflow.install_epg_source(env.settings)
    assert r["status"] == "error" and r["refresh_queued"] is False
    assert "secret-host" not in r["message"]


def test_dispatcharr_error_status_is_error(env):
    workflow.install_epg_source(env.settings)
    env.hook.status = "error"
    assert workflow.install_epg_source(env.settings)["status"] == "error"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, 3.0), (1, 1.0), (10**9, 5.0), (-4, 0.0), ("abc", 3.0), (float("nan"), 3.0)],
)
def test_import_wait_is_brief_and_capped(configured, expected):
    settings = {} if configured is None else {"epg_import_wait_seconds": configured}
    assert workflow._import_wait_seconds(settings) == expected


def test_huge_wait_setting_reaches_poll_loop_capped_without_sleeping(env, monkeypatch):
    seen = []
    monkeypatch.setattr(
        workflow, "_wait_for_import", lambda pk, name, wait: seen.append(wait) or {"status": "pending"}
    )
    env.settings["epg_import_wait_seconds"] = 10**9
    assert workflow.install_epg_source(env.settings)["status"] == "pending"
    assert seen == [5.0]
