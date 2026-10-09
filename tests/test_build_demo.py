"""
tests/test_build_demo.py — the demo build names its cache, not a default.

The demo is the one build that should write the shared, tracked classification
cache (D-71). It says so by argument, so that when the session default stops
meaning the shared file, the demo does not silently switch to a fresh,
different draw (D-69).
"""

from __future__ import annotations

from types import SimpleNamespace

import src.build
import src.claude_classifier as cc
import tools.build_demo as build_demo
from src.dashboard.keys import KEY_PROJECT


def test_the_demo_build_passes_the_shared_cache_explicitly(tmp_path, monkeypatch):
    export = tmp_path / "Connections.csv"
    export.write_text("", encoding="utf-8")
    monkeypatch.setattr(build_demo, "SYNTHETIC_CSV", export)

    seen = {}

    def fake_build(*args, **kwargs):
        seen.update(kwargs)
        # Incomplete, so main() returns before writing any demo file.
        return SimpleNamespace(complete=False, unclassified=[], reasons={})

    monkeypatch.setattr(src.build, "build_network", fake_build)

    assert build_demo.main() == 1
    assert seen["source"] == KEY_PROJECT
    # Read at call time: the conftest fixture's redirect, never the real file.
    assert seen["cache_path"] == cc.CACHE_PATH
