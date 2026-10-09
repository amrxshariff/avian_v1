"""
tests/test_ingestion.py — the command-line chain's entry point runs (D-79).

Every command-line module starts at ingestion.load_profiles(): embeddings,
classify_pipeline, ingestion itself, and graph.load_nodes(), which graph and
centrality run. A rename of load_linkedin_profiles' parameter left it raising
TypeError for twelve days, because the only test that touched the module
imported it. This one calls it, on the tracked synthetic export, so the
common prefix of every CLI module is exercised.

(tests/test_ingestion.py.broken is an unrelated Phase 0 stub, quarantined in
bc614af.)
"""

from __future__ import annotations

from pathlib import Path

from src.ingestion import load_profiles

SYNTHETIC_CSV = Path("data/synthetic/Connections.csv")


def test_load_profiles_reads_an_export():
    people = load_profiles(SYNTHETIC_CSV)

    assert len(people) == 442
    assert all(p.name and (p.role or p.company) for p in people)


def test_load_profiles_with_no_path_reads_the_configured_export(monkeypatch):
    """None must reach load_linkedin_profiles as its default, not as a keyword
    it no longer has."""
    import src.config as config

    monkeypatch.setattr(config, "LINKEDIN_CSV", SYNTHETIC_CSV)
    assert len(load_profiles()) == 442
