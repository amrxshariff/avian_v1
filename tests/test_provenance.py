"""
tests/test_provenance.py — P2.9b: the line that says who classified the
network on screen, and whose key paid.

The rules under test are honesty rules:

  * a claim about whose key paid is made only when the build recorded it;
  * a keyless build makes no claim at all;
  * the demo line never costs the screen: an unreadable file is silence.

Run from the repo root:
    python -m pytest tests/test_provenance.py -v
"""

from __future__ import annotations

from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER
from src.dashboard.provenance import (
    built_line,
    demo_line,
    load_demo_provenance,
    provenance_line,
)

MODEL = "claude-sonnet-5"


class _Built:
    """Stands in for a BuildResult — only provenance matters here."""

    def __init__(self, provenance: dict | None = None):
        self.provenance = provenance or {}


def test_a_build_on_a_user_key_names_the_model_and_says_it_was_theirs():
    line = built_line(_Built({"model": MODEL, "source": KEY_USER}))
    assert MODEL in line
    assert "your own API key" in line


def test_a_build_on_the_project_key_says_the_shared_allowance():
    line = built_line(_Built({"model": MODEL, "source": KEY_PROJECT}))
    assert MODEL in line
    assert "shared allowance" in line
    assert "your" not in line.lower()


def test_a_keyless_build_says_nothing():
    assert built_line(_Built({"model": MODEL, "source": KEY_NONE})) == ""


def test_a_build_with_no_recorded_source_names_the_model_and_claims_nothing():
    """D-63: no source recorded is no evidence, and neither is a value outside
    the vocabulary. "project_key" is build_network's default from before D-63
    removed it; the shipped demo file carries it because build_demo.py's own
    "source" (the data's origin) was overwritten by the build's. Nothing
    migrates it — the demo is rebuilt — so this only pins the fallback."""
    for provenance in ({"model": MODEL}, {"model": MODEL, "source": "project_key"}):
        line = built_line(_Built(provenance))
        assert line == f"Classified by {MODEL}."


def test_a_build_paid_for_by_more_than_one_key_names_the_model_and_claims_nothing():
    for source in (KEY_USER, KEY_PROJECT):
        line = built_line(_Built({"model": MODEL, "source": source,
                                  "mixed_sources": True}))
        assert line == f"Classified by {MODEL}."


def test_the_demo_line_names_the_model_and_states_no_real_person_appears():
    line = demo_line({"model": MODEL, "real_people": 0})
    assert MODEL in line
    assert "No real person appears in it." in line


def test_a_missing_demo_file_yields_an_empty_line_not_an_exception(tmp_path):
    provenance = load_demo_provenance(tmp_path / "absent.json")
    assert provenance == {}
    assert demo_line(provenance) == ""


def test_a_malformed_demo_file_yields_an_empty_line(tmp_path):
    path = tmp_path / "provenance.json"
    path.write_text("{ not json", encoding="utf-8")
    assert demo_line(load_demo_provenance(path)) == ""


def test_provenance_line_prefers_the_build_over_the_demo():
    built = _Built({"model": MODEL, "source": KEY_USER})
    demo = {"model": "some-other-model", "real_people": 0}
    line = provenance_line(built, demo_provenance=demo)
    assert line == built_line(built)
    assert "Example network" not in line
