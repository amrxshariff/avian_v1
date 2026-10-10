"""
tests/test_unclassified.py — P2.9b slice 3: the wording for a build that lost
some of its classifications, and the injected retry seam.

The rules under test are honesty rules, not formatting ones:

  * these people are never described as needing review or as uncertain;
  * the reason shown is the one recorded, and an unrecognised reason raises
    rather than being shown as something else;
  * a retry is offered only where it could work without the user acting;
  * the key-failed wording never tells a user their own key was rejected when
    the build ran on the project's key.

Run from the repo root:
    python -m pytest tests/test_unclassified.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.keys import KEY_NONE, KEY_PROJECT, KEY_USER
from src.dashboard.state import (
    NOT_CLASSIFIED,
    NOT_CLASSIFIED_NAME,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
)
from src.dashboard.unclassified import (
    ALL_REASONS,
    MIXED_REASONS,
    REASON_BUDGET_REACHED,
    REASON_COLUMN,
    REASON_KEY_FAILED,
    REASON_SERVICE_BUSY,
    REASON_UNANSWERABLE,
    can_retry,
    is_unknown_source_phrase,
    pending,
    pending_clause,
    reason_phrase,
    reasons_in,
    render_notice,
    retry_targets,
)


class FakeStreamlit:
    """Records what a render call would have drawn. No Streamlit runtime."""

    def __init__(self, click: bool = False):
        self.captions: list[str] = []
        self.buttons: list[str] = []
        self._click = click

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def button(self, label: str, **kwargs) -> bool:
        self.buttons.append(label)
        return self._click

    @property
    def text(self) -> str:
        return " ".join(self.captions).lower()


def _df(states, reasons=None) -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": list(range(len(states))),
        "name": [f"P{i}" for i in range(len(states))],
        "role": ["Analyst"] * len(states),
        "soc_major": [NOT_CLASSIFIED if s == STATE_NOT_CLASSIFIED else "13"
                      for s in states],
        "soc_major_name": [NOT_CLASSIFIED_NAME if s == STATE_NOT_CLASSIFIED
                           else "Business and Financial Operations"
                           for s in states],
        "display_state": states,
        REASON_COLUMN: reasons if reasons is not None else [None] * len(states),
    })


# --- the vocabulary ----------------------------------------------------------


@pytest.mark.parametrize("reason", ALL_REASONS)
def test_every_reason_has_wording(reason):
    phrase = reason_phrase(reason)
    assert phrase and not phrase.endswith(".")


def test_an_unrecognised_reason_raises():
    with pytest.raises(ValueError, match="Unrecognised"):
        reason_phrase("gremlins")


def test_a_dead_key_is_described_by_whose_key_it_was():
    """Telling a user their key was rejected when it was ours is a false claim."""
    own = reason_phrase(REASON_KEY_FAILED, source=KEY_USER)
    project = reason_phrase(REASON_KEY_FAILED, source=KEY_PROJECT)
    assert own != project
    assert "your api key" in own.lower()
    assert "your" not in project.lower()


def test_an_unrecorded_source_gives_the_neutral_phrase_neither_claim():
    """D-63: None is a build that recorded no source. Both other phrases are
    claims; this one is only what is certain."""
    unknown = reason_phrase(REASON_KEY_FAILED, source=None)
    assert unknown not in (reason_phrase(REASON_KEY_FAILED, source=KEY_USER),
                           reason_phrase(REASON_KEY_FAILED, source=KEY_PROJECT))
    assert "your" not in unknown.lower()
    assert "unavailable" not in unknown.lower()
    assert reason_phrase(REASON_KEY_FAILED) == unknown     # the default claims nothing


def test_only_the_unrecorded_source_phrase_is_the_one_that_claims_nothing():
    """Callers drop this phrase rather than restate their own sentence. The
    predicate must track what reason_phrase actually returns, or a rewording
    would silently bring the repetition back."""
    assert is_unknown_source_phrase(reason_phrase(REASON_KEY_FAILED, source=None))
    for source in (KEY_USER, KEY_PROJECT, KEY_NONE):
        assert not is_unknown_source_phrase(
            reason_phrase(REASON_KEY_FAILED, source=source))
    for reason in ALL_REASONS:
        if reason != REASON_KEY_FAILED:
            assert not is_unknown_source_phrase(reason_phrase(reason))


def test_a_keyless_source_is_not_described_as_the_users_key():
    """upload.py records KEY_NONE on a keyless build. It is not the user's."""
    assert "your" not in reason_phrase(REASON_KEY_FAILED, source=KEY_NONE).lower()


@pytest.mark.parametrize("reason", ALL_REASONS)
def test_no_reason_calls_these_people_reviewed_or_uncertain(reason):
    phrase = reason_phrase(reason, source=KEY_USER).lower()
    for forbidden in ("review", "uncertain", "unclassifiable", "abstain"):
        assert forbidden not in phrase


def test_retry_is_offered_only_where_it_could_work():
    assert can_retry([REASON_SERVICE_BUSY])
    assert can_retry([REASON_UNANSWERABLE])
    assert not can_retry([REASON_BUDGET_REACHED])
    assert not can_retry([REASON_KEY_FAILED])
    assert not can_retry([])
    # Mixed: the retryable people would come back, so do not strand them.
    assert can_retry([REASON_SERVICE_BUSY, REASON_BUDGET_REACHED])


def test_one_budget_reason_only():
    """Two reasons for one fact drift apart. See D-53.

    The meters raise BudgetExceeded; it maps to exactly one reason.
    """
    budget_reasons = [r for r in ALL_REASONS if "budget" in r or "allowance" in r]
    assert budget_reasons == [REASON_BUDGET_REACHED]


# --- selecting the pending people -------------------------------------------


def test_pending_selects_only_the_fourth_state():
    df = _df([STATE_CLASSIFIED, STATE_NEEDS_REVIEW, STATE_NOT_CLASSIFIED])
    assert retry_targets(df) == [2]
    assert len(pending(df)) == 1


def test_reasons_are_reported_in_a_stable_order():
    df = _df([STATE_NOT_CLASSIFIED] * 3,
             [REASON_UNANSWERABLE, REASON_SERVICE_BUSY, REASON_SERVICE_BUSY])
    assert reasons_in(df) == [REASON_SERVICE_BUSY, REASON_UNANSWERABLE]


def test_a_table_with_no_reason_column_still_reports_the_people():
    df = _df([STATE_NOT_CLASSIFIED, STATE_CLASSIFIED]).drop(columns=[REASON_COLUMN])
    assert retry_targets(df) == [0]
    assert reasons_in(df) == []


def test_the_clause_names_one_reason_and_summarises_several():
    assert pending_clause(12, ()) == "12 not classified yet"
    assert "service was busy" in pending_clause(12, [REASON_SERVICE_BUSY])
    assert MIXED_REASONS in pending_clause(
        12, [REASON_SERVICE_BUSY, REASON_UNANSWERABLE]
    )
    assert pending_clause(0, [REASON_SERVICE_BUSY]) == ""


# --- the notice --------------------------------------------------------------


def test_a_healthy_build_renders_nothing():
    st = FakeStreamlit()
    assert render_notice(_df([STATE_CLASSIFIED, STATE_NEEDS_REVIEW]), st=st) is None
    assert st.captions == [] and st.buttons == []


def test_the_notice_says_what_the_state_does_not_mean():
    st = FakeStreamlit()
    df = _df([STATE_NOT_CLASSIFIED], [REASON_SERVICE_BUSY])
    render_notice(df, st=st)
    assert "belong to no group" in st.text
    assert "service was busy" in st.text
    assert "need review" not in st.text


def test_no_button_until_a_build_function_is_injected():
    """Slice 3 ships the sentence; the control arrives with something to call."""
    st = FakeStreamlit()
    render_notice(_df([STATE_NOT_CLASSIFIED], [REASON_SERVICE_BUSY]),
                  on_retry=None, st=st)
    assert st.captions and st.buttons == []


def test_the_injected_handler_receives_exactly_the_pending_people():
    st = FakeStreamlit(click=True)
    called: list[list[int]] = []
    df = _df(
        [STATE_CLASSIFIED, STATE_NOT_CLASSIFIED, STATE_NEEDS_REVIEW,
         STATE_NOT_CLASSIFIED],
        [None, REASON_SERVICE_BUSY, None, REASON_SERVICE_BUSY],
    )
    requested = render_notice(df, on_retry=called.append, st=st)

    assert called == [[1, 3]]
    assert requested == [1, 3]
    assert st.buttons == ["Retry 2"]


def test_no_retry_control_when_retrying_cannot_help():
    st = FakeStreamlit(click=True)
    called: list[list[int]] = []
    df = _df([STATE_NOT_CLASSIFIED], [REASON_BUDGET_REACHED])
    assert render_notice(df, on_retry=called.append, st=st) is None
    assert called == []
    assert st.buttons == []
    assert "allowance" in st.text


def test_the_notice_names_the_key_it_was_given():
    df = _df([STATE_NOT_CLASSIFIED], [REASON_KEY_FAILED])
    own, project = FakeStreamlit(), FakeStreamlit()
    render_notice(df, st=own, source=KEY_USER)
    render_notice(df, st=project, source=KEY_PROJECT)
    assert "your api key" in own.text
    assert "unavailable" in project.text and "your" not in project.text


def test_an_unknown_source_does_not_repeat_itself():
    """The neutral phrase is the sentence's own lead; "did not complete,
    because the classification did not complete" says nothing twice."""
    st = FakeStreamlit()
    render_notice(_df([STATE_NOT_CLASSIFIED], [REASON_KEY_FAILED]), st=st)
    assert st.text.count("did not complete") == 1
    assert "because" not in st.text
