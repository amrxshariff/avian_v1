"""
tests/test_cache_isolation.py — D-64: every path that defaults to the
classification cache follows the conftest redirect.

The fixture patches one module attribute. That reaches a code path only if the
path looks CACHE_PATH up when it runs. Each test here calls one such path with
no cache_path at all and checks the answer landed in the redirected file. A new
default argument bound at import, or a module importing the constant by value,
fails one of these instead of writing to data/.

The build is the exception since D-71: its default is a private mapping, not
CACHE_PATH, so its test checks that no file is written at all.
"""

from __future__ import annotations

import json

import src.claude_classifier as cc
from src.build import build_network
from tests.test_build import _Client, _embed, _people, _project


def _redirected() -> dict:
    return json.loads(cc.CACHE_PATH.read_text(encoding="utf-8"))


def test_the_fixture_points_away_from_data():
    assert "data" not in cc.CACHE_PATH.parts


def test_classify_claude_writes_to_the_redirected_cache():
    cc.classify_claude([("Isolation Title", "")], client=_Client())
    assert "isolation title||" in _redirected()


def test_classify_claude_outcome_writes_to_the_redirected_cache():
    cc.classify_claude_outcome([("Isolation Title", "")], client=_Client())
    assert "isolation title||" in _redirected()


def test_count_uncached_titles_reads_the_redirected_cache():
    people = _people(3, titles=["Isolation Title"])
    assert cc.count_uncached_titles(people) == 1
    cc.classify_claude([("Isolation Title", "")], client=_Client())
    assert cc.count_uncached_titles(people) == 0


def test_a_classifying_build_with_no_cache_path_writes_no_file():
    """The exact shape of the call that wrote "title 6" into data/.

    D-64 asserted this landed in the redirected file, which pinned the
    default as correct. D-71 reverses it: with no cache_path, a build keeps
    its cache in memory, so neither file is written."""
    build_network(people=_people(10), client=_Client(),
                  embed=_embed, project=_project)
    assert not cc.CACHE_PATH.exists()
