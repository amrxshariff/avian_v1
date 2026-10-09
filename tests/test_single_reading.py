"""
tests/test_single_reading.py — the profile panel shows one reading, not a comparison (D-84).

Six runs on identical input: the title-only reading never moved; the
About-informed one abstained three times. A side-by-side therefore made a claim
about the visitor's writing that the code could not support. The panel now
makes one call and shows one reading, with the caveat that it is one answer.
The two-reading form survives on the command line only, as the measurement path.
"""

from __future__ import annotations

import json
import sys

from streamlit.testing.v1 import AppTest

from src.dashboard import enrich
from src.dashboard.session_io import (
    FORMAT_VERSION,
    build_export,
    restore,
    restore_enrichment_reading,
)
from src.onet import Classification
from tests.test_assistant import make_df


def _reading(soc="15", tier="self_enriched", score=0.95) -> Classification:
    return Classification(query="Analyst", soc_code=None, soc_major=soc, occupation=None,
                          tier=tier, score=score, n_candidates=1, major_agreement=1.0)


# --- the panel ----------------------------------------------------------------


def _panel_app():
    from src.dashboard.enrich import render_enrichment_panel

    render_enrichment_panel()


def test_the_panel_makes_one_call_and_shows_one_reading_with_its_caveat(monkeypatch):
    calls = []

    def one(title, about, client=None):
        calls.append((title, about))
        return _reading()

    monkeypatch.setattr(enrich, "classify_from_about", one)
    at = AppTest.from_function(_panel_app, default_timeout=30).run()
    at.text_input[0].input("Analyst")
    at.text_area[0].input("I build pricing models for a retail bank and own the team's forecasting.")
    at.button[0].click().run()

    assert not at.exception
    assert len(calls) == 1
    shown = " | ".join([c.value for c in at.caption] + [s.value for s in at.success]
                       + [i.value for i in at.info])
    assert enrich.SINGLE_READING_CAVEAT in shown
    assert len(at.success) + len(at.info) == 1          # one reading, not two
    for withdrawn in ("title alone", "both readings", "two readings", "compar"):
        assert withdrawn not in shown.lower()


def test_no_panel_string_invites_a_comparison():
    texts = [enrich.INTRO, enrich.about_input_error(""), enrich.READING_LABEL,
             enrich.SINGLE_READING_CAVEAT]
    for text in texts:
        assert "compar" not in text.lower()
        assert "two readings" not in text.lower()


# --- the session file -----------------------------------------------------------


def _v1_two_reading_file() -> dict:
    """What a session file looked like while the panel compared two readings."""
    return {
        "format_version": 1, "app": "network-visualiser", "corrections": [], "notes": [],
        "enrichment": {
            "title": "Analyst", "about": "x" * 60, "generated_at": "2026-09-01T00:00:00",
            "result": {
                "title_only": {"query": "Analyst", "soc_major": "13", "tier": "claude", "score": 0.95},
                "enriched": {"query": "Analyst", "soc_major": "15", "tier": "self_enriched", "score": 0.75},
            },
        },
    }


def test_an_old_two_reading_file_restores_its_about_informed_half():
    payload = restore_enrichment_reading(_v1_two_reading_file())
    _, _, enrichment, _ = restore(payload, make_df(), result_cls=Classification, member_cls=None)

    reading = enrichment["result"]
    assert isinstance(reading, Classification)
    assert (reading.soc_major, reading.tier, reading.score) == ("15", "self_enriched", 0.75)


def test_a_new_file_round_trips_one_reading():
    exported = json.loads(json.dumps(build_export(
        make_df(), {}, {}, title="Analyst", about="x" * 60, result=_reading())))
    assert exported["format_version"] == FORMAT_VERSION == 2

    _, _, enrichment, _ = restore(restore_enrichment_reading(exported), make_df(),
                                  result_cls=Classification, member_cls=None)
    assert enrichment["result"] == _reading()


# --- the command line keeps the measurement ------------------------------------


def test_the_cli_prints_both_raw_readings_and_no_comparison_sentence(monkeypatch, tmp_path, capsys):
    import src.self_enrichment as se

    about = tmp_path / "about.txt"
    about.write_text("I build pricing models for a retail bank.", encoding="utf-8")
    monkeypatch.setattr(se, "compare", lambda title, about, client=None: se.Comparison(
        title_only=_reading("13", "claude", 0.95), enriched=_reading(None, "abstain", 0.40)))
    monkeypatch.setattr(sys, "argv", ["self_enrichment", "--title", "Analyst",
                                      "--about-file", str(about)])

    assert se.main() == 0
    out = capsys.readouterr().out
    assert "title only" in out and "title + about" in out
    assert "tier=abstain" in out
    assert "readings use different prompts" not in out
