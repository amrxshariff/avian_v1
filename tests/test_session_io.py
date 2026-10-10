"""
tests/test_session_io.py — P2.8c session save and restore.

No Streamlit, no disk, no network. The enrichment result classes are injected,
so the core is tested without importing anything that reaches an API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.dashboard.session_io import (
    FORMAT_VERSION,
    MISS_DUPLICATE,
    MISS_NO_MATCH,
    MISS_TITLE_CHANGED,
    RestoreReport,
    UnsupportedVersion,
    build_export,
    dump_result,
    export_filename,
    load_result,
    name_key,
    person_key,
    restore,
    to_json,
)


# --- fixtures ----------------------------------------------------------------


def make_df(rows=None) -> pd.DataFrame:
    rows = rows or [
        (0, "Ada Lovelace", "Data Analyst"),
        (1, "Grace Hopper", "Finance Intern"),
        (2, "Alan Turing", "Student Ambassador"),
    ]
    return pd.DataFrame(
        [{"person_index": i, "name": n, "role": r} for i, n, r in rows]
    )


@dataclass
class FakeClassification:
    query: str
    soc_major: str | None
    tier: str
    score: float


@dataclass
class FakeComparison:
    title_only: FakeClassification
    enriched: FakeClassification


def make_result() -> FakeComparison:
    return FakeComparison(
        title_only=FakeClassification("Analyst", None, "abstain", 0.40),
        enriched=FakeClassification("Analyst", "15", "self_enriched", 0.95),
    )


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


# --- keys --------------------------------------------------------------------


def test_keys_are_case_and_whitespace_insensitive():
    assert name_key("  Ada   LOVELACE ") == name_key("ada lovelace")
    assert person_key("Ada Lovelace", "Data  Analyst") == person_key(
        "ada lovelace", "data analyst"
    )


def test_person_key_distinguishes_title():
    assert person_key("Ada", "Analyst") != person_key("Ada", "Engineer")
    assert name_key("Ada") == name_key("Ada")


# --- export ------------------------------------------------------------------


def test_export_contains_no_person_index():
    """Criterion 4: index derives from export row order and would reattach
    everything to the wrong people after a re-export."""
    payload = build_export(make_df(), {0: "15", 1: "13"}, {0: "met at kings cross"})
    blob = json.dumps(payload)
    assert "person_index" not in blob
    for entry in payload["corrections"] + payload["notes"]:
        assert set(entry) <= {"name", "role", "soc_major", "text"}


def test_export_carries_format_version_and_app():
    payload = build_export(make_df(), {}, {})
    assert payload["format_version"] == FORMAT_VERSION
    assert payload["app"] == "network-visualiser"


def test_export_stores_the_title_a_note_was_written_against():
    """The drift flag on restore depends on this being the WRITE-TIME title."""
    payload = build_export(make_df(), {}, {1: "knows the Stripe team"})
    assert payload["notes"][0]["role"] == "Finance Intern"


def test_export_skips_empty_notes_and_unknown_indices():
    payload = build_export(make_df(), {99: "15"}, {0: "   ", 99: "orphan"})
    assert payload["corrections"] == []
    assert payload["notes"] == []


def test_export_includes_enrichment_inputs_and_result():
    payload = build_export(
        make_df(), {}, {}, title="Analyst", about="a" * 60, result=make_result(), now=NOW
    )
    enrichment = payload["enrichment"]
    assert enrichment["title"] == "Analyst"
    assert enrichment["result"]["enriched"]["soc_major"] == "15"
    assert enrichment["generated_at"].startswith("2026-08-28")


def test_export_omits_enrichment_when_there_is_none():
    assert "enrichment" not in build_export(make_df(), {}, {})


def test_export_is_json_serialisable():
    payload = build_export(make_df(), {0: "15"}, {0: "note"}, result=make_result())
    assert json.loads(to_json(payload))["corrections"][0]["soc_major"] == "15"


def test_filename_carries_the_date():
    assert export_filename(NOW) == "network-visualiser-session-2026-08-28.json"


# --- round trip --------------------------------------------------------------


def test_round_trip_reapplies_everything_when_nothing_changed():
    df = make_df()
    payload = build_export(df, {1: "13"}, {0: "met at kings cross"})
    corrections, notes, _, report = restore(payload, df)

    assert corrections == {1: "13"}
    assert notes == {0: "met at kings cross"}
    assert report.applied == 2 and report.total == 2
    assert report.misses == () and report.drifts == ()
    assert report.sentence() == "Re-applied 1 of 1 correction and 1 of 1 note."


def test_indices_are_remapped_when_row_order_changes():
    """The whole point of identity keying: a re-export shifts every index."""
    old = make_df()
    payload = build_export(old, {1: "13"}, {1: "knows the Stripe team"})

    # Same people, new export, forty new connections ahead of them.
    new = make_df(
        [(0, "Someone New", "Consultant"),
         (1, "Another New", "Teacher"),
         (2, "Ada Lovelace", "Data Analyst"),
         (3, "Grace Hopper", "Finance Intern")]
    )
    corrections, notes, _, report = restore(payload, new)

    assert corrections == {3: "13"}          # was index 1, now index 3
    assert notes == {3: "knows the Stripe team"}
    assert report.applied == 2


# --- misses ------------------------------------------------------------------


def test_departed_person_is_dropped_and_reported():
    df = make_df()
    payload = build_export(df, {1: "13"}, {1: "knows the Stripe team"})
    smaller = make_df([(0, "Ada Lovelace", "Data Analyst")])

    corrections, notes, _, report = restore(payload, smaller)
    assert corrections == {} and notes == {}
    assert report.applied == 0 and report.total == 2
    assert {m.reason for m in report.misses} == {MISS_NO_MATCH}
    # The stronger assertion is on the structured data: one correction miss
    # and one note miss (the departed person had both), not the sentence,
    # which is the weaker of the two places this is visible.
    assert len(report.misses) == 2
    assert {m.kind for m in report.misses} == {"correction", "note"}
    assert report.corrections_applied == 0 and report.corrections_total == 1
    assert report.notes_applied == 0 and report.notes_total == 1


def test_changed_title_misses_the_correction_but_keeps_the_note():
    """The two-key decision, asserted: a correction is a verdict on a title and
    should go stale; a note is about a person and should survive."""
    df = make_df()
    payload = build_export(df, {1: "13"}, {1: "knows the Stripe team"})
    promoted = make_df(
        [(0, "Ada Lovelace", "Data Analyst"), (1, "Grace Hopper", "Associate")]
    )

    corrections, notes, _, report = restore(payload, promoted)
    assert corrections == {}
    assert notes == {1: "knows the Stripe team"}

    assert [m.reason for m in report.misses] == [MISS_TITLE_CHANGED]
    assert len(report.drifts) == 1
    drift = report.drifts[0]
    assert drift.was == "Finance Intern" and drift.now == "Associate"


def test_duplicate_names_drop_and_report_rather_than_guess():
    """A coin-flip here is a fabrication about an individual."""
    df = make_df()
    payload = build_export(df, {}, {1: "knows the Stripe team"})
    twins = make_df(
        [(0, "Grace Hopper", "Finance Intern"), (1, "Grace Hopper", "Analyst")]
    )

    _, notes, _, report = restore(payload, twins)
    assert notes == {}
    assert [m.reason for m in report.misses] == [MISS_DUPLICATE]


def test_duplicate_person_key_drops_the_correction():
    df = make_df()
    payload = build_export(df, {1: "13"}, {})
    twins = make_df(
        [(0, "Grace Hopper", "Finance Intern"), (1, "Grace Hopper", "Finance Intern")]
    )
    corrections, _, _, report = restore(payload, twins)
    assert corrections == {}
    assert [m.reason for m in report.misses] == [MISS_DUPLICATE]


# --- versions and malformed input --------------------------------------------


def test_newer_format_version_refuses_and_changes_nothing():
    payload = build_export(make_df(), {0: "15"}, {})
    payload["format_version"] = FORMAT_VERSION + 1
    with pytest.raises(UnsupportedVersion) as exc:
        restore(payload, make_df())
    assert "Nothing has been changed" in str(exc.value)


def test_missing_format_version_is_refused():
    with pytest.raises(ValueError):
        restore({"corrections": []}, make_df())


def test_non_dict_payload_is_refused():
    with pytest.raises(ValueError):
        restore([1, 2, 3], make_df())


def test_malformed_entries_are_skipped_not_fatal():
    payload = {
        "format_version": FORMAT_VERSION,
        "corrections": ["nonsense", {"name": "Ada Lovelace", "role": "Data Analyst",
                                     "soc_major": "15"}],
        "notes": [42, {"name": "Ada Lovelace", "text": "keep me"}],
    }
    corrections, notes, _, report = restore(payload, make_df())
    assert corrections == {0: "15"}
    assert notes == {0: "keep me"}
    assert report.total == 2


def test_empty_session_round_trips_to_an_honest_sentence():
    payload = build_export(make_df(), {}, {})
    _, _, _, report = restore(payload, make_df())
    assert report.sentence() == "That file had no corrections or notes in it."


# --- enrichment codec --------------------------------------------------------


def test_result_round_trips_through_the_generic_codec():
    payload = build_export(make_df(), {}, {}, title="Analyst", about="x", result=make_result())
    _, _, enrichment, report = restore(
        payload, make_df(), result_cls=FakeComparison, member_cls=FakeClassification
    )
    assert isinstance(enrichment["result"], FakeComparison)
    assert enrichment["result"].enriched.score == 0.95
    assert enrichment["title"] == "Analyst"
    assert report.enrichment_restored is True


def test_result_is_skipped_when_the_classes_are_not_supplied():
    """Inputs still restore; only the rebuilt object needs the classes."""
    payload = build_export(make_df(), {}, {}, title="Analyst", about="x", result=make_result())
    _, _, enrichment, _ = restore(payload, make_df())
    assert "result" not in enrichment
    assert enrichment["title"] == "Analyst"


def test_unknown_fields_in_a_saved_result_are_ignored():
    """A file from a later build loads rather than raising."""
    data = {
        "title_only": {"query": "a", "soc_major": None, "tier": "abstain",
                       "score": 0.4, "future_field": "ignored"},
        "enriched": {"query": "a", "soc_major": "15", "tier": "self_enriched",
                     "score": 0.95},
    }
    rebuilt = load_result(data, FakeComparison, FakeClassification)
    assert rebuilt.enriched.soc_major == "15"


def test_a_partial_result_returns_none_rather_than_half_a_claim():
    rebuilt = load_result({"title_only": {"query": "a"}}, FakeComparison, FakeClassification)
    assert rebuilt is None


def test_dump_result_ignores_non_dataclasses():
    assert dump_result(None) is None
    assert dump_result({"already": "a dict"}) is None


# --- report ------------------------------------------------------------------


def test_report_sentence_never_rounds_a_miss_away():
    report = RestoreReport(
        corrections_applied=300, corrections_total=320,
        notes_applied=12, notes_total=20,
    )
    line = report.sentence()
    # The invariant, not the wording: for each kind, a reader can see both what
    # landed and what was saved. Asserting the exact string made this a
    # snapshot test that broke on a rewording (D-27) while no longer checking
    # the property it is named for.
    for applied, total in ((300, 320), (12, 20)):
        assert f"{applied} of {total}" in line


def test_report_sentence_invents_no_miss_when_all_applied():
    report = RestoreReport(
        corrections_applied=5, corrections_total=5,
        notes_applied=2, notes_total=2,
    )
    line = report.sentence()
    assert "5 of 5 corrections" in line
    assert "2 of 2 notes" in line