"""
tests/test_retry.py — P2.9b commit 4: retrying the people a build could not
classify, and where the built network lives between reruns.

The invariant these tests exist for: a retry re-classifies and NOTHING else.
Coordinates, edges and centrality are carried across, because rebuilding the
layout would rearrange the canvas under someone who is halfway through a review
— and UMAP is not guaranteed to land in the same place twice, so "it usually
looks similar" is not a defence.

Run from the repo root:
    python -m pytest tests/test_retry.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.build import build_network, retry_unclassified
from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER
from src.dashboard.provenance import built_line
from src.dashboard.session_build import BUILT_KEY, TOUCHED_KEY, clear_built, get_built, set_built
from src.dashboard.state import (
    STATE_CLASSIFIED,
    STATE_NOT_CLASSIFIED,
    STATUS_COLUMN,
    STATUS_NOT_CLASSIFIED,
    apply_corrections,
)
from src.dashboard.unclassified import REASON_COLUMN
from src.failure_reasons import REASON_SERVICE_BUSY
from tests.test_build import _Client, _embed, _people, _project

LAYOUT = ["umap_3d_x", "umap_3d_y", "umap_3d_z",
          "degree_centrality", "strength", "betweenness", "pagerank",
          "closeness_wf"]


def _broken(n=40, client=None, cache=None, source=None):
    """A build whose classification stopped after the first batch."""
    return build_network(
        people=_people(n, titles=[f"Role {i}" for i in range(n)]),
        client=client or _Client(fail_at=2), cache_path=cache,
        embed=_embed, project=_project, source=source,
    )


# --- the retry ---------------------------------------------------------------


def test_a_retry_completes_the_network(tmp_path):
    before = _broken(cache=tmp_path / "c.json")
    assert not before.complete

    after = retry_unclassified(before, client=_Client(), cache_path=tmp_path / "c.json")
    assert after.complete and after.unclassified == {}
    assert not (after.nodes[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED).any()


def test_a_retry_moves_nobody(tmp_path):
    """The reason a retry is safe to offer at all."""
    before = _broken(cache=tmp_path / "c.json")
    after = retry_unclassified(before, client=_Client(), cache_path=tmp_path / "c.json")

    pd.testing.assert_frame_equal(before.nodes[LAYOUT], after.nodes[LAYOUT])
    assert before.nodes["person_index"].tolist() == after.nodes["person_index"].tolist()
    assert before.nodes["name"].tolist() == after.nodes["name"].tolist()


def test_a_retry_asks_only_about_the_people_it_is_retrying(tmp_path):
    """Everything classified first time is cached; a retry pays for the rest."""
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)
    client = _Client()
    retry_unclassified(before, client=client, cache_path=cache)

    asked = [t for call in client.calls for t in call]
    assert len(asked) == len(before.unclassified)
    assert set(asked) == set(
        before.nodes.loc[
            before.nodes["person_index"].isin(before.unclassified), "role"
        ]
    )


def test_a_retry_can_be_narrowed_to_some_people(tmp_path):
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)
    some = sorted(before.unclassified)[:5]

    after = retry_unclassified(before, some, client=_Client(), cache_path=cache)
    assert not after.complete
    assert set(after.unclassified) == set(before.unclassified) - set(some)


def test_a_retry_that_fails_again_keeps_the_network_and_the_reason(tmp_path):
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)
    after = retry_unclassified(
        before, client=_Client(fail_at=1), cache_path=cache
    )
    assert after.people == before.people
    assert set(after.unclassified) == set(before.unclassified)
    assert set(after.reasons) == {REASON_SERVICE_BUSY}


def test_retrying_a_complete_build_changes_nothing(tmp_path):
    good = build_network(
        people=_people(20), client=_Client(), cache_path=tmp_path / "c.json",
        embed=_embed, project=_project,
    )
    same = retry_unclassified(good, client=_Client(), cache_path=tmp_path / "c.json")
    assert same is good


def test_the_overlay_sees_the_retried_people_as_classified(tmp_path):
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)
    after = retry_unclassified(before, client=_Client(), cache_path=cache)

    shown_before = apply_corrections(before.nodes, {})
    shown_after = apply_corrections(after.nodes, {})
    assert (shown_before["display_state"] == STATE_NOT_CLASSIFIED).sum() == 20
    assert (shown_after["display_state"] == STATE_CLASSIFIED).all()
    assert set(after.nodes[REASON_COLUMN]) == {""}


def test_a_correction_made_before_a_retry_still_wins(tmp_path):
    """The user's own verdict outranks whatever the retry comes back with."""
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)
    corrected = sorted(before.unclassified)[0]

    after = retry_unclassified(before, client=_Client(), cache_path=cache)
    shown = apply_corrections(after.nodes, {corrected: "29"})
    assert shown.loc[corrected, "soc_major"] == "29"


# --- whose key paid, across a retry ------------------------------------------


def test_a_retry_on_the_same_key_leaves_mixed_sources_absent(tmp_path):
    cache = tmp_path / "c.json"
    before = _broken(cache=cache, source=KEY_PROJECT)
    after = retry_unclassified(before, client=_Client(), cache_path=cache,
                               source=KEY_PROJECT)
    assert "mixed_sources" not in after.provenance
    assert "shared allowance" in built_line(after)


def test_a_retry_on_a_different_key_sets_mixed_sources_and_drops_the_key_clause(tmp_path):
    """D-63's shape: most of this network was paid for by the project, the
    rest by the user. Neither is the answer for the whole of it."""
    cache = tmp_path / "c.json"
    before = _broken(cache=cache, source=KEY_PROJECT)
    after = retry_unclassified(before, client=_Client(), cache_path=cache,
                               source=KEY_USER)
    assert after.provenance["mixed_sources"] is True
    assert after.provenance["source"] == KEY_USER   # still the latest attempt
    line = built_line(after)
    assert line.startswith("Classified by ") and line.endswith(".")
    assert "your" not in line.lower()
    assert "allowance" not in line


def test_a_key_arriving_after_a_keyless_build_is_one_payer(tmp_path):
    """The offer after a key arrives (slice 3) is the common retry. A keyless
    build classified nobody, so the key that arrives paid for everyone."""
    cache = tmp_path / "c.json"
    before = build_network(
        people=_people(30, titles=[f"Role {i}" for i in range(30)]),
        classify=False, cache_path=cache, embed=_embed, project=_project,
        source=KEY_NONE,
    )
    after = retry_unclassified(before, client=_Client(), cache_path=cache,
                               source=KEY_USER)
    assert after.complete
    assert "mixed_sources" not in after.provenance
    assert "your own API key" in built_line(after)


def test_a_retry_after_an_unrecorded_source_claims_no_single_payer(tmp_path):
    """Someone paid for the earlier people and nothing says who. A key now
    must not become a claim about all of them."""
    cache = tmp_path / "c.json"
    before = _broken(cache=cache)                     # source not recorded
    after = retry_unclassified(before, client=_Client(), cache_path=cache,
                               source=KEY_USER)
    assert after.provenance["mixed_sources"] is True
    assert "your" not in built_line(after).lower()


def test_mixed_sources_survives_a_later_retry_on_the_same_key(tmp_path):
    cache = tmp_path / "c.json"
    before = _broken(n=60, client=_Client(fail_at=2), cache=cache,
                     source=KEY_PROJECT)
    middle = retry_unclassified(before, client=_Client(fail_at=2),
                                cache_path=cache, source=KEY_USER)
    after = retry_unclassified(middle, client=_Client(), cache_path=cache,
                               source=KEY_USER)
    assert after.provenance["mixed_sources"] is True


# --- the session holder ------------------------------------------------------


def test_the_store_holds_one_network_at_a_time(tmp_path):
    store: dict = {}
    assert get_built(store) is None

    first = _broken(cache=tmp_path / "c.json")
    set_built(first, store)
    assert get_built(store) is first

    second = _broken(n=20, cache=tmp_path / "c.json")
    set_built(second, store)
    assert get_built(store) is second
    assert list(store) == [BUILT_KEY, TOUCHED_KEY]   # replaced, not accumulated


def test_clearing_returns_to_the_demo():
    store = {BUILT_KEY: object()}
    clear_built(store)
    assert get_built(store) is None
    clear_built(store)                        # idempotent
