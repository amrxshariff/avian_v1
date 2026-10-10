"""
tests/test_classify_pipeline_status.py — P2.9b commit 2: what the producer
writes is exactly what the overlay reads.

Slice 1 taught state.py to read three columns that no producer wrote yet. This
is the other half, and the tests are written as a pair: the frame classify_people
produces goes straight into apply_corrections, and the display states that come
back are asserted there rather than here. A producer and a consumer that agree
only in their own test files agree until they do not.

Run from the repo root:
    python -m pytest tests/test_classify_pipeline_status.py -v
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd
import pytest

from src import classify_pipeline as cp
from src.dashboard.state import (
    NOT_CLASSIFIED,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATUS_ABSTAINED,
    STATUS_ASSIGNED,
    STATUS_COLUMN,
    STATUS_NOT_CLASSIFIED,
    apply_corrections,
    review_counts,
)
from src.dashboard.unclassified import REASON_COLUMN, retry_targets
from src.failure_reasons import REASON_SERVICE_BUSY, REASON_UNANSWERABLE


@dataclass
class _Person:
    id: str
    name: str
    role: str
    company: str = ""


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Resp:
    content: list
    stop_reason: str = "end_turn"


class RateLimitError(RuntimeError):
    status_code = 429


@dataclass
class _Client:
    """Answers titles, except those it is told it cannot answer.

    `abstain` returns a low-confidence record, which the classifier treats as a
    declined answer. `unanswerable` never answers at all, which the splitter
    isolates down to the single title. `fail_at` raises on that call.
    """

    abstain: frozenset = frozenset()
    unanswerable: frozenset = frozenset()
    fail_at: int | None = None
    calls: list = field(default_factory=list)

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, system, messages):
        titles = [line.split("title: ", 1)[1].split(" | ")[0].strip()
                  for line in messages[0]["content"].splitlines() if "title: " in line]
        self.calls.append(titles)
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise RateLimitError("slow down")
        if any(t in self.unanswerable for t in titles):
            return _Resp([_Block("")], stop_reason="max_tokens")
        objs = []
        for i, t in enumerate(titles):
            if t in self.abstain:
                objs.append({"i": i, "soc": None, "confidence": "low", "why": "unclear"})
            else:
                objs.append({"i": i, "soc": "13", "confidence": "high", "why": "ok"})
        return _Resp([_Block(json.dumps(objs))])


def people(n, start=0):
    return [_Person(id=f"p{i}", name=f"Person {i}", role=f"Title {i}")
            for i in range(start, start + n)]


def _display(frame: pd.DataFrame) -> pd.DataFrame:
    """The producer's frame as the overlay sees it, with no corrections.

    The one rename centrality.py performs at the canonical-output boundary
    (soc_name -> soc_major_name). Everything else reaches the overlay exactly
    as classify_people wrote it, which is the point of these tests.
    """
    return apply_corrections(
        frame.rename(columns={"soc_name": "soc_major_name"}), {}
    )


# --- the command-line chain is unchanged -------------------------------------


def test_the_raising_path_still_raises(tmp_path):
    with pytest.raises(Exception):
        cp.classify_people(
            people(3), client=_Client(unanswerable=frozenset({"Title 1"})),
            cache_path=tmp_path / "c.json",
        )


def test_a_complete_run_writes_only_the_two_resolved_statuses(tmp_path):
    frame = cp.classify_people(
        people(4), client=_Client(abstain=frozenset({"Title 2"})),
        cache_path=tmp_path / "c.json",
    )
    assert set(frame[STATUS_COLUMN]) == {STATUS_ASSIGNED, STATUS_ABSTAINED}
    assert set(frame[REASON_COLUMN]) == {""}
    assert list(_display(frame)["display_state"]) == [
        STATE_CLASSIFIED, STATE_CLASSIFIED, STATE_NEEDS_REVIEW, STATE_CLASSIFIED,
    ]


# --- a partial run -----------------------------------------------------------


def test_a_failed_title_becomes_the_fourth_state_end_to_end(tmp_path):
    """The producer's output, read by the overlay, with nothing in between."""
    frame = cp.classify_people(
        people(4), partial=True,
        client=_Client(unanswerable=frozenset({"Title 1"})),
        cache_path=tmp_path / "c.json",
    )
    row = frame.loc[frame["person_index"] == 1].iloc[0]
    assert row[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED
    assert row[REASON_COLUMN] == REASON_UNANSWERABLE
    assert row["soc_major"] == NOT_CLASSIFIED
    assert row["classifier_tier"] == ""          # never "abstain"

    shown = _display(frame)
    assert shown.loc[1, "display_state"] == STATE_NOT_CLASSIFIED
    assert retry_targets(shown) == [1]


def test_a_failed_call_never_counts_as_needing_review(tmp_path):
    """D-42, end to end: is_uncertain stays False, so the backlog is honest."""
    frame = cp.classify_people(
        people(6), partial=True,
        client=_Client(abstain=frozenset({"Title 0"}),
                       unanswerable=frozenset({"Title 4"})),
        cache_path=tmp_path / "c.json",
    )
    assert not bool(frame.loc[frame["person_index"] == 4, "is_uncertain"].iloc[0])
    assert bool(frame.loc[frame["person_index"] == 0, "is_uncertain"].iloc[0])
    assert review_counts(frame, {}) == (1, 1)     # the abstention only


def test_a_stopped_run_marks_everyone_it_never_reached(tmp_path):
    frame = cp.classify_people(
        people(40), partial=True,
        client=_Client(fail_at=2), cache_path=tmp_path / "c.json",
    )
    shown = _display(frame)
    assert list(shown["display_state"][:20]) == [STATE_CLASSIFIED] * 20
    assert list(shown["display_state"][20:]) == [STATE_NOT_CLASSIFIED] * 20
    assert set(frame[REASON_COLUMN][20:]) == {REASON_SERVICE_BUSY}


def test_people_sharing_a_failed_title_all_carry_the_reason(tmp_path):
    """Titles are classified once and deduped; the failure follows the title."""
    roster = people(2) + [_Person(id="p9", name="Twin", role="Title 1")]
    frame = cp.classify_people(
        roster, partial=True,
        client=_Client(unanswerable=frozenset({"Title 1"})),
        cache_path=tmp_path / "c.json",
    )
    pending = frame[frame[STATUS_COLUMN] == STATUS_NOT_CLASSIFIED]
    assert sorted(pending["person_index"]) == [1, 2]


# --- the files on disk cannot hold the fourth state --------------------------


def test_writing_cluster_files_refuses_a_partial_frame(tmp_path, monkeypatch):
    """cluster is an integer per person: 'never answered' would land as 99."""
    frame = cp.classify_people(
        people(3), partial=True,
        client=_Client(unanswerable=frozenset({"Title 0"})),
        cache_path=tmp_path / "c.json",
    )
    monkeypatch.setattr(cp, "CLUSTERED_CSV", tmp_path / "clustered.csv")
    monkeypatch.setattr(cp, "LABELS_CSV", tmp_path / "labels.csv")
    monkeypatch.setattr(cp, "CLASSIFIED_CSV", tmp_path / "classified.csv")

    with pytest.raises(ValueError, match="cannot represent"):
        cp.write_cluster_files(frame)
    assert not (tmp_path / "clustered.csv").exists()
