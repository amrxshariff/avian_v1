"""
tests/test_build.py — P2.9b commit 3: the shared build function, and the
failure-mode suite the design record asks for.

Three consumers will call build_network: the app, the API and the MCP server.
So the tests are about the CONTRACT rather than the happy path:

  * bad input raises InvalidExport, before a single call is made or paid for;
  * a classification that fails part-way still returns the whole network, says
    it is incomplete, and says who is missing and why;
  * the layout never depends on the classifier, so those people keep their
    coordinates and their edges;
  * nothing is written to disk.

The heavyweight steps are injected. Encoding 442 titles pulls in torch — 36 s
and 1.1 GB — and a test about what happens when a KEY dies has no business
paying that. The seam is the same one the notes overlay uses. Both fakes are
deterministic, so the failure tests compare against a known-good build rather
than an eyeballed shape.

Run from the repo root:
    python -m pytest tests/test_build.py -v
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pytest

from src.build import InvalidExport, MIN_PEOPLE, build_network
from src.dashboard.keys import KEY_PROJECT
from src.dashboard.state import (
    NOT_CLASSIFIED,
    STATE_CLASSIFIED,
    STATE_NOT_CLASSIFIED,
    STATUS_COLUMN,
    STATUS_NOT_CLASSIFIED,
    apply_corrections,
    review_counts,
)
from src.dashboard.unclassified import REASON_COLUMN, retry_targets
from src.failure_reasons import (
    REASON_BUDGET_REACHED,
    REASON_KEY_FAILED,
    REASON_SERVICE_BUSY,
    REASON_UNANSWERABLE,
)
from src.spend import DailyLedger, GenerationMeter, Meters


@dataclass
class _Person:
    id: str
    name: str
    role: str
    company: str = ""
    profile_text: str = ""


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _Resp:
    content: list
    stop_reason: str = "end_turn"
    usage: object = None


class RateLimitError(RuntimeError):
    status_code = 429


class AuthenticationError(RuntimeError):
    status_code = 401


@dataclass
class _Client:
    abstain: frozenset = frozenset()
    unanswerable: frozenset = frozenset()
    fail_at: int | None = None
    error: Exception | None = None
    calls: list = field(default_factory=list)
    # Output tokens reported per successful call. 0 (the default, and every
    # existing test) means no usage attribute at all, matching a fake that
    # predates the meters — Usage.add() no-ops on a response without one.
    tokens_per_call: int = 0

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, system, messages):
        titles = [line.split("title: ", 1)[1].split(" | ")[0].strip()
                  for line in messages[0]["content"].splitlines() if "title: " in line]
        self.calls.append(titles)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise self.error or RateLimitError("slow down")
        usage = _Usage(output_tokens=self.tokens_per_call) if self.tokens_per_call else None
        if any(t in self.unanswerable for t in titles):
            return _Resp([_Block("")], stop_reason="max_tokens", usage=usage)
        objs = []
        for i, t in enumerate(titles):
            if t in self.abstain:
                objs.append({"i": i, "soc": None, "confidence": "low", "why": "?"})
            else:
                objs.append({"i": i, "soc": "13", "confidence": "high", "why": "ok"})
        return _Resp([_Block(json.dumps(objs))], usage=usage)


def _people(n: int, titles: list[str] | None = None) -> list[_Person]:
    return [
        _Person(
            id=f"li{i:03d}", name=f"Person {i}",
            role=(titles[i % len(titles)] if titles else f"Title {i % 7}"),
        )
        for i in range(n)
    ]


def _embed(people, cache_path=None) -> np.ndarray:
    """Deterministic vectors, clustered by title so the graph has structure."""
    titles = sorted({p.role for p in people})
    rng = np.random.default_rng(7)
    centres = {t: rng.random(8) for t in titles}
    return np.array([
        np.clip(centres[p.role] + rng.normal(scale=0.01, size=8), 0, None)
        for p in people
    ])


def _project(embeddings, **params) -> np.ndarray:
    rng = np.random.default_rng(11)
    return rng.random((embeddings.shape[0], 3))


def _build(people, client=None, tmp_path=None, **kw):
    return build_network(
        people=people,
        client=client or _Client(),
        cache_path=(tmp_path / "cache.json") if tmp_path else None,
        embed=_embed, project=_project, **kw,
    )


# --- bad input raises, and costs nothing -------------------------------------


def test_a_missing_file_raises_before_anything_is_spent(tmp_path):
    client = _Client()
    with pytest.raises(InvalidExport, match="could not be found"):
        build_network(tmp_path / "nope.csv", client=client,
                      embed=_embed, project=_project)
    assert client.calls == []


def test_a_csv_that_is_not_an_export_raises_with_something_actionable(tmp_path):
    path = tmp_path / "wrong.csv"
    path.write_text("colour,animal\nred,fox\nblue,cat\n", encoding="utf-8")
    with pytest.raises(InvalidExport, match="LinkedIn"):
        build_network(path, client=_Client(), embed=_embed, project=_project)


def test_an_empty_export_raises(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("First Name,Last Name,Company,Position\n", encoding="utf-8")
    with pytest.raises(InvalidExport):
        build_network(path, client=_Client(), embed=_embed, project=_project)


def test_a_network_too_small_to_place_raises(tmp_path):
    with pytest.raises(InvalidExport, match="At least"):
        _build(_people(MIN_PEOPLE - 1), tmp_path=tmp_path)


def test_an_export_with_no_titles_raises(tmp_path):
    nameless = [_Person(id=f"li{i}", name=f"P{i}", role="", company="Acme")
                for i in range(8)]
    with pytest.raises(InvalidExport, match="position"):
        _build(nameless, tmp_path=tmp_path)


# --- the happy path ----------------------------------------------------------


def test_a_clean_build_is_complete_and_placed(tmp_path):
    result = _build(_people(40), tmp_path=tmp_path, source=KEY_PROJECT)

    assert result.complete and result.unclassified == {}
    assert result.people == 40
    assert result.nodes["person_index"].tolist() == list(range(40))
    assert not result.nodes[["umap_3d_x", "umap_3d_y", "umap_3d_z"]].isna().any().any()
    assert result.provenance["model"] and result.provenance["source"]


def test_a_keyless_build_records_what_a_later_classification_would_send(tmp_path):
    """The offer quotes this when a key arrives; `parsed` is gone by then."""
    result = _build(_people(30), tmp_path=tmp_path, classify=False)
    assert result.provenance["uncached_titles"] == 7   # "Title 0".."Title 6"


def test_a_cached_title_is_not_counted_as_a_cost(tmp_path):
    _build(_people(30), tmp_path=tmp_path)             # classifies, fills the cache
    again = _build(_people(30), tmp_path=tmp_path, classify=False)
    assert again.provenance["uncached_titles"] == 0


def test_source_is_absent_rather_than_guessed_when_no_caller_asserts_one(tmp_path):
    """D-63: KEY_PROJECT used to be the default, which told an unrecognised
    key-failed build it ran on the project's key even when nobody said so.
    None is the honest value for "nobody said" — reason_phrase treats it as
    its own neutral case rather than as a guess in either direction."""
    result = _build(_people(10), tmp_path=tmp_path)
    assert result.provenance["source"] is None


def test_the_frame_is_what_the_overlay_expects(tmp_path):
    """Straight from the build into apply_corrections, with nothing between."""
    result = _build(_people(20), client=_Client(abstain=frozenset({"Title 3"})),
                    tmp_path=tmp_path)
    shown = apply_corrections(result.nodes, {})
    assert set(shown["display_state"]) <= {STATE_CLASSIFIED, "needs_review"}
    assert review_counts(result.nodes, {})[1] > 0


def test_a_twelve_person_network_builds(tmp_path):
    """n_neighbors is clamped: the configured 15 is meaningless at this size."""
    assert _build(_people(12), tmp_path=tmp_path).people == 12


def test_duplicate_names_and_non_ascii_survive(tmp_path):
    roster = [
        _Person(id="li0", name="Jane Smith", role="Analyst"),
        _Person(id="li1", name="Jane Smith", role="Analyst"),
        _Person(id="li2", name="Zoë Müller", role="Ingénieur"),
        _Person(id="li3", name="李伟", role="数据分析师"),
        _Person(id="li4", name="Ana Ruiz", role="Analyst"),
        _Person(id="li5", name="Tom Ray", role="Nurse"),
    ]
    result = _build(roster, tmp_path=tmp_path)
    assert result.people == 6
    assert result.nodes["name"].tolist() == [p.name for p in roster]


# --- a partial build ---------------------------------------------------------


def test_a_dead_key_still_returns_the_whole_network(tmp_path):
    """The point of option B: the layout never needed the classifier."""
    result = _build(
        _people(30), client=_Client(fail_at=1, error=AuthenticationError("bad key")),
        tmp_path=tmp_path,
    )
    assert result.people == 30
    assert not result.complete
    assert set(result.reasons) == {REASON_KEY_FAILED}
    assert len(result.unclassified) == 30
    # Coordinates and edges are intact for people with no classification.
    assert not result.nodes[["umap_3d_x", "umap_3d_y", "umap_3d_z"]].isna().any().any()
    assert result.nodes["pagerank"].notna().all()


def test_a_mid_run_failure_keeps_what_it_paid_for(tmp_path):
    """Batch 1 succeeded; the people in it keep their groups."""
    result = _build(
        _people(60, titles=[f"Role {i}" for i in range(60)]),
        client=_Client(fail_at=2), tmp_path=tmp_path,
    )
    assert not result.complete
    assert set(result.reasons) == {REASON_SERVICE_BUSY}

    shown = apply_corrections(result.nodes, {})
    classified = (shown["display_state"] == STATE_CLASSIFIED).sum()
    pending = (shown["display_state"] == STATE_NOT_CLASSIFIED).sum()
    assert classified == 20 and pending == 40
    assert sorted(result.unclassified) == retry_targets(shown)


def test_one_unanswerable_title_marks_only_those_people(tmp_path):
    result = _build(
        _people(20, titles=["Analyst", "Nurse", "Chef", "Welder"]),
        client=_Client(unanswerable=frozenset({"Chef"})), tmp_path=tmp_path,
    )
    assert set(result.reasons) == {REASON_UNANSWERABLE}
    chefs = result.nodes[result.nodes["role"] == "Chef"]["person_index"].tolist()
    assert sorted(result.unclassified) == chefs
    assert len(chefs) == 5


def test_the_unplaced_are_never_counted_as_needing_review(tmp_path):
    """D-42 at the top of the stack: a failed call is not an abstention."""
    result = _build(
        _people(24, titles=["Analyst", "Nurse", "Chef"]),
        client=_Client(abstain=frozenset({"Nurse"}),
                       unanswerable=frozenset({"Chef"})),
        tmp_path=tmp_path,
    )
    pending = result.nodes[result.nodes[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED]
    assert not pending["is_uncertain"].any()
    assert set(pending["soc_major"]) == {NOT_CLASSIFIED}
    assert set(pending[REASON_COLUMN]) == {REASON_UNANSWERABLE}
    # The review backlog counts the abstentions and nobody else.
    assert review_counts(result.nodes, {}) == (8, 8)


def test_a_bug_in_the_client_crashes_the_build(tmp_path):
    with pytest.raises(TypeError):
        _build(_people(10), client=_Client(fail_at=1, error=TypeError("boom")),
               tmp_path=tmp_path)


# --- the free tier -------------------------------------------------------------


def _meters(tmp_path, generation_cap=1000.0, daily_cap=1000.0):
    return Meters(
        generation=GenerationMeter(cap=generation_cap),
        daily=DailyLedger(tmp_path / "daily.json", cap=daily_cap),
    )


def test_a_budget_cap_landing_mid_build_keeps_what_it_paid_for(tmp_path):
    """Batch 1's actual spend clears the cap; a second batch on top of it
    would not. Everyone is still placed — only the classifier stopped."""
    result = _build(
        _people(60, titles=[f"Role {i}" for i in range(60)]),
        client=_Client(tokens_per_call=20_000),  # $0.20/batch of 20 at $10/Mtok
        meters=_meters(tmp_path, generation_cap=0.22),
        tmp_path=tmp_path,
    )
    assert not result.complete
    assert set(result.reasons) == {REASON_BUDGET_REACHED}

    shown = apply_corrections(result.nodes, {})
    classified = (shown["display_state"] == STATE_CLASSIFIED).sum()
    pending = (shown["display_state"] == STATE_NOT_CLASSIFIED).sum()
    assert classified == 20 and pending == 40
    # The layout never depended on the classifier: everyone is still placed.
    assert not result.nodes[["umap_3d_x", "umap_3d_y", "umap_3d_z"]].isna().any().any()
    assert result.nodes["pagerank"].notna().all()


def test_pre_flight_refusal_classifies_nobody_and_spends_nothing(tmp_path):
    """A cap too small for even one title refuses before the first call."""
    client = _Client()
    result = _build(
        _people(30), client=client,
        meters=_meters(tmp_path, generation_cap=0.0), tmp_path=tmp_path,
    )
    assert client.calls == []
    assert not result.complete
    assert set(result.reasons) == {REASON_BUDGET_REACHED}
    assert len(result.unclassified) == 30
    # The network still renders: the refusal is about classifying, not building.
    assert not result.nodes[["umap_3d_x", "umap_3d_y", "umap_3d_z"]].isna().any().any()


def test_a_fully_cached_network_passes_pre_flight_with_a_zero_estimate(tmp_path):
    """Nothing left to price, so a cap of zero cannot refuse it."""
    people = _people(20, titles=["Analyst", "Nurse", "Chef", "Welder"])
    _build(people, tmp_path=tmp_path)  # warms the shared cache

    client = _Client()
    result = _build(
        people, client=client,
        meters=_meters(tmp_path, generation_cap=0.0, daily_cap=0.0),
        tmp_path=tmp_path,
    )
    assert client.calls == []          # every title was a cache hit
    assert result.complete


# --- the layout does not depend on the classifier ----------------------------


def test_coordinates_are_identical_with_and_without_classifications(tmp_path):
    """The invariant a retry relies on: re-classifying never moves anybody."""
    roster = _people(30, titles=["Analyst", "Nurse", "Chef"])
    good = _build(roster, tmp_path=tmp_path)
    broken = _build(roster, client=_Client(fail_at=1), tmp_path=tmp_path / "b")

    coords = ["umap_3d_x", "umap_3d_y", "umap_3d_z"]
    pd.testing.assert_frame_equal(good.nodes[coords], broken.nodes[coords])
    pd.testing.assert_series_equal(good.nodes["pagerank"], broken.nodes["pagerank"])


# --- nothing is written ------------------------------------------------------


def test_the_build_writes_nothing_but_the_title_cache(tmp_path, monkeypatch):
    """A raw export is real people's names; only (title -> group) is kept."""
    monkeypatch.chdir(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    _build(_people(15), tmp_path=tmp_path)
    assert list(workdir.iterdir()) == []
