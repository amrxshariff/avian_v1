"""
tests/test_metering.py — the app constructs the spend meters (D-81).

spend.py's caps were tested only by tests that built their own Meters, so every
one of them passed while the app passed none: no build or retry on the project
key was ever capped. These go through the upload panel and the retry handler,
the paths a visitor takes, and check what reaches the ledger.

The ledger is redirected per test by conftest (_isolate_spend_ledger).
"""

from __future__ import annotations

import json

import app
import src.spend as spend
from src.build import STATUS_COLUMN, STATUS_NOT_CLASSIFIED, build_network, retry_unclassified
from src.dashboard.keys import KEY_PROJECT, KEY_USER
from src.dashboard.metering import meters_for
from src.dashboard.unclassified import REASON_COLUMN
from src.dashboard.upload import render_upload_panel
from src.failure_reasons import REASON_BUDGET_REACHED
from src.spend import DailyLedger, GenerationMeter, Meters
from tests.test_build import _Client, _embed, _people, _project
from tests.test_upload import FakeStreamlit, _Upload, _build, _csv


def _ledger() -> dict:
    return json.loads(spend.LEDGER_PATH.read_text(encoding="utf-8"))


def _spend_the_day() -> None:
    spend.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    spend.LEDGER_PATH.write_text(json.dumps({
        "date": spend._today(), "spent": 30.0, "calls": 0, "networks": 0,
    }), encoding="utf-8")


def _on(monkeypatch, source):
    monkeypatch.setattr("src.dashboard.keys.key_source", lambda store=None: source)


# --- the build ----------------------------------------------------------------


def test_an_upload_on_the_project_key_is_charged_to_the_daily_ledger(monkeypatch):
    _on(monkeypatch, KEY_PROJECT)
    result = render_upload_panel(
        st=FakeStreamlit(upload=_Upload(_csv(10))), store={},
        build_fn=lambda s, **k: _build(s, client=_Client(tokens_per_call=500), **k),
    )

    assert result.complete
    ledger = _ledger()
    assert ledger["spent"] > 0
    assert ledger["networks"] == 1


def test_an_upload_on_the_visitors_own_key_is_not_metered(monkeypatch):
    _on(monkeypatch, KEY_USER)
    seen = {}

    def spy(upload, **kw):
        seen.update(kw)
        return _build(upload, client=_Client(tokens_per_call=500), **kw)

    render_upload_panel(st=FakeStreamlit(upload=_Upload(_csv(10))), store={}, build_fn=spy)

    assert seen["meters"] is None
    assert not spend.LEDGER_PATH.exists()


def test_a_build_is_refused_at_the_preflight_when_the_days_budget_is_spent(monkeypatch):
    """Design item 6: the network still builds; everyone lands in the fourth
    state; nothing is sent."""
    _on(monkeypatch, KEY_PROJECT)
    _spend_the_day()
    client = _Client()

    result = render_upload_panel(
        st=FakeStreamlit(upload=_Upload(_csv(10))), store={},
        build_fn=lambda s, **k: _build(s, client=client, **k),
    )

    assert client.calls == []
    assert result.people == 10
    assert set(result.nodes[STATUS_COLUMN]) == {STATUS_NOT_CLASSIFIED}
    assert set(result.nodes[REASON_COLUMN]) == {REASON_BUDGET_REACHED}
    assert _ledger()["networks"] == 0


# --- the retry ----------------------------------------------------------------


def _retry_through_handler(monkeypatch, source) -> dict:
    seen: dict = {}

    def fake_retry(built, person_indices, source=None, cache_path=None, meters=None):
        seen["meters"] = meters
        return "updated"

    from tests.test_app import FakeStreamlit as AppStreamlit

    monkeypatch.setattr(app, "st", AppStreamlit())
    monkeypatch.setattr(app, "key_source", lambda: source)
    monkeypatch.setattr(app, "set_built", lambda result: None)
    monkeypatch.setattr("src.build.retry_unclassified", fake_retry)
    app._retry_handler(built=object())([1])
    return seen


def test_a_retry_on_the_project_key_is_metered(monkeypatch):
    meters = _retry_through_handler(monkeypatch, KEY_PROJECT)["meters"]
    assert isinstance(meters, Meters)


def test_a_retry_on_the_visitors_own_key_is_not_metered(monkeypatch):
    assert _retry_through_handler(monkeypatch, KEY_USER)["meters"] is None


def test_a_retry_against_a_spent_day_sends_nothing():
    before = build_network(people=_people(10), client=_Client(fail_at=1),
                           embed=_embed, project=_project)
    assert not before.complete
    _spend_the_day()
    client = _Client()

    after = retry_unclassified(before, client=client, meters=meters_for(KEY_PROJECT))

    assert client.calls == []
    assert REASON_BUDGET_REACHED in set(after.nodes[REASON_COLUMN])


def test_each_build_gets_its_own_generation_meter_over_one_ledger():
    first, second = meters_for(KEY_PROJECT), meters_for(KEY_PROJECT)
    assert isinstance(first.generation, GenerationMeter)
    assert first.generation is not second.generation
    assert isinstance(first.daily, DailyLedger)
    assert first.daily.path == second.daily.path == spend.LEDGER_PATH
