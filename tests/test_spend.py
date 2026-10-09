"""The meters, including the awkward paths: a stale file, a broken one, a
read-only disk."""

import json
from datetime import timedelta, datetime, timezone

import pytest

from src import config
from src.claude_classifier import Usage
from src.spend import (
    BudgetExceeded,
    DailyLedger,
    GenerationMeter,
    Meters,
    estimate_titles,
)


def usage(dollars: float) -> Usage:
    """A Usage costing roughly `dollars`, via output tokens alone."""
    return Usage(output_tokens=int(dollars * 1_000_000 / config.OUTPUT_PER_MTOK),
                 calls=1)


# --- GenerationMeter -------------------------------------------------------

def test_fresh_meter_has_spent_nothing():
    m = GenerationMeter()
    assert m.spent == 0.0
    m.check()


def test_meter_accumulates_across_calls():
    m = GenerationMeter()
    m.record(usage(0.10))
    m.record(usage(0.10))
    assert m.spent == pytest.approx(0.20, abs=1e-6)


def test_meter_refuses_when_estimate_would_breach():
    m = GenerationMeter(cap=1.00)
    m.record(usage(0.90))
    m.check(0.05)
    with pytest.raises(BudgetExceeded) as e:
        m.check(0.20)
    assert e.value.scope == "generation"


def test_meter_keeps_token_counts_for_provenance():
    m = GenerationMeter()
    m.record(Usage(input_tokens=100, output_tokens=200, calls=1))
    m.record(Usage(input_tokens=50, output_tokens=25, calls=1))
    assert (m.usage.input_tokens, m.usage.output_tokens, m.usage.calls) == (
        150, 225, 2
    )


# --- DailyLedger -----------------------------------------------------------

def test_ledger_starts_empty(tmp_path):
    assert DailyLedger(tmp_path / "d.json").spent == 0.0


def test_ledger_survives_a_new_instance(tmp_path):
    p = tmp_path / "d.json"
    DailyLedger(p).record(usage(0.25))
    assert DailyLedger(p).spent == pytest.approx(0.25, abs=1e-6)


def test_yesterdays_ledger_reads_as_zero(tmp_path):
    p = tmp_path / "d.json"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    p.write_text(json.dumps({"date": yesterday.isoformat(), "spent": 99.0}))
    assert DailyLedger(p).spent == 0.0


def test_a_corrupt_ledger_reads_as_zero_rather_than_raising(tmp_path):
    """Fail open: a dead app is worse than an unrecorded build."""
    p = tmp_path / "d.json"
    p.write_text("{not json")
    assert DailyLedger(p).spent == 0.0


def test_recording_over_a_corrupt_ledger_repairs_it(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{not json")
    DailyLedger(p).record(usage(0.10))
    assert DailyLedger(p).spent == pytest.approx(0.10, abs=1e-6)


def test_ledger_refuses_when_estimate_would_breach(tmp_path):
    led = DailyLedger(tmp_path / "d.json", cap=1.00)
    led.record(usage(0.95))
    with pytest.raises(BudgetExceeded) as e:
        led.check(0.10)
    assert e.value.scope == "day"


def test_an_unwritable_ledger_does_not_raise(tmp_path):
    """The disk being full must not take the app down."""
    p = tmp_path / "nodir" / "d.json"
    p.parent.mkdir()
    p.parent.chmod(0o500)
    try:
        DailyLedger(p).record(usage(0.10))  # must not raise
    finally:
        p.parent.chmod(0o700)


def test_networks_counted_separately_from_spend(tmp_path):
    p = tmp_path / "d.json"
    led = DailyLedger(p)
    led.record(usage(0.35))
    led.record_network()
    assert led.spent == pytest.approx(0.35, abs=1e-6)
    assert json.loads(p.read_text())["networks"] == 1


# --- Meters ------------------------------------------------------------------


def test_daily_breach_is_reported_as_day_not_generation(tmp_path):
    """When both would breach, the message must say the demo is spent, not
    that this build is too big — the daily figure is the real limit."""
    meters = Meters(
        generation=GenerationMeter(cap=1.00),
        daily=DailyLedger(tmp_path / "d.json", cap=1.00),
    )
    meters.generation.record(usage(0.95))
    meters.daily.record(usage(0.95))
    with pytest.raises(BudgetExceeded) as e:
        meters.check(0.10)
    assert e.value.scope == "day"


def test_meters_checks_and_records_both(tmp_path):
    """Both or neither: metering one cap but not the other lets the daily cap
    be breached one build at a time."""
    meters = Meters(
        generation=GenerationMeter(cap=1.00),
        daily=DailyLedger(tmp_path / "d.json", cap=1.00),
    )
    meters.check(0.50)
    meters.record(usage(0.50))
    assert meters.generation.spent == pytest.approx(0.50, abs=1e-6)
    assert meters.daily.spent == pytest.approx(0.50, abs=1e-6)


# --- the estimate ----------------------------------------------------------

def test_estimate_matches_the_assumption():
    assert estimate_titles(371) == pytest.approx(
        371 * config.ASSUMED_COST_PER_TITLE
    )


def test_a_normal_network_estimate_clears_the_generation_cap():
    assert estimate_titles(371) < config.MAX_SPEND_PER_GENERATION
