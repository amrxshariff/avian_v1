"""
tests/test_display_states.py — every consumer handles every display state.

D-54: three renderers ended their branching in an `else` that meant "one of
the states I know about". A state they did not recognise was therefore shown
to the user as one they did — the canvas borrowed the needs-review grey, the
card borrowed its label, and a chat record simply carried no flag at all.

These tests are the guard rail for slice 2 and for every state added after it:
add a fifth member to ALL_STATES and each parametrised case below fails until
the consumer is taught what to do with it.

Run from the repo root:
    python -m pytest tests/test_display_states.py -v
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.assistant import build_payload, resolve_people
from src.dashboard.canvas import (
    NOT_CLASSIFIED_SYMBOL,
    MARKER_SYMBOL,
    _point_colour,
    _point_symbol,
)
from src.dashboard.card import PROV_NOT_CLASSIFIED, group_label, provenance_label
from src.dashboard.state import (
    ALL_STATES,
    NOT_CLASSIFIED,
    NOT_CLASSIFIED_NAME,
    NOT_OCCUPATION,
    NOT_OCCUPATION_NAME,
    NEEDS_REVIEW_NAME,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATE_NOT_OCCUPATION,
    UNREVIEWED_CODE,
)
from src.dashboard.summaries import coverage_counts

UNKNOWN = "deferred"          # a state no consumer has been taught

# soc_major / soc_major_name as apply_corrections leaves them, per state.
_VALUES = {
    STATE_CLASSIFIED: ("15", "Computer and Mathematical"),
    STATE_NEEDS_REVIEW: (UNREVIEWED_CODE, NEEDS_REVIEW_NAME),
    STATE_NOT_OCCUPATION: (NOT_OCCUPATION, NOT_OCCUPATION_NAME),
    STATE_NOT_CLASSIFIED: (NOT_CLASSIFIED, NOT_CLASSIFIED_NAME),
}


def _row(state: str) -> pd.Series:
    major, name = _VALUES.get(state, ("15", "Computer and Mathematical"))
    return pd.Series({
        "person_index": 0,
        "name": "A",
        "role": "Data Scientist",
        "soc_major": major,
        "soc_major_name": name,
        "display_state": state,
        "classifier_tier": "claude",
        "classifier_confidence": 0.95,
    })


def _frame(states=ALL_STATES) -> pd.DataFrame:
    rows = []
    for i, state in enumerate(states):
        row = _row(state)
        row["person_index"] = i
        row["name"] = f"P{i}"
        rows.append(row)
    return pd.DataFrame(rows)


# --- every state is handled --------------------------------------------------


@pytest.mark.parametrize("state", ALL_STATES)
def test_every_state_has_a_colour_and_a_symbol(state):
    assert _point_colour(_row(state)).startswith("#")
    assert _point_symbol(_row(state)) in (MARKER_SYMBOL, NOT_CLASSIFIED_SYMBOL)


def test_the_four_states_are_visually_distinguishable():
    """Same grey plus same symbol would make two states one state on screen."""
    marks = {s: (_point_colour(_row(s)), _point_symbol(_row(s))) for s in ALL_STATES}
    assert len(set(marks.values())) == len(ALL_STATES)
    assert marks[STATE_NOT_CLASSIFIED][1] == NOT_CLASSIFIED_SYMBOL
    assert all(
        symbol == MARKER_SYMBOL
        for state, (_, symbol) in marks.items()
        if state != STATE_NOT_CLASSIFIED
    )


@pytest.mark.parametrize("state", ALL_STATES)
def test_every_state_has_a_card_label(state):
    label = group_label(_row(state))
    assert label and isinstance(label, str)


def test_a_failed_call_is_never_labelled_as_an_abstention():
    """The card must not say the classifier declined when it never answered."""
    row = _row(STATE_NOT_CLASSIFIED)
    assert group_label(row) == NOT_CLASSIFIED_NAME
    assert group_label(row) != NEEDS_REVIEW_NAME
    # Even with a tier left behind by an earlier attempt.
    row["classifier_tier"] = "abstain"
    assert provenance_label(row, corrected=False) == PROV_NOT_CLASSIFIED


def test_payload_gives_each_state_exactly_one_meaning():
    """g, u, x and f are mutually exclusive, and every row carries one."""
    rows = build_payload(_frame())
    flags = [{k for k in ("g", "u", "x", "f") if k in rec} for rec in rows]
    assert flags == [{"g"}, {"u"}, {"x"}, {"f"}]


def test_resolve_people_keeps_the_two_reasons_apart():
    df = _frame()
    refs, dropped = resolve_people(
        df, [{"i": f"p{i}", "why": "x"} for i in range(len(ALL_STATES))]
    )
    assert dropped == 0
    by_state = dict(zip(ALL_STATES, refs))

    failed = by_state[STATE_NOT_CLASSIFIED]
    assert failed.not_classified and not failed.unreviewed and failed.group is None

    unreviewed = by_state[STATE_NEEDS_REVIEW]
    assert unreviewed.unreviewed and not unreviewed.not_classified


def test_state_counts_partition_the_table():
    c = coverage_counts(_frame())
    assert (
        c.classified + c.needs_review + c.not_occupation + c.not_classified
    ) == c.total


# --- an unknown state is never guessed ---------------------------------------


@pytest.mark.parametrize(
    "consumer",
    [
        pytest.param(lambda: _point_colour(_row(UNKNOWN)), id="canvas colour"),
        pytest.param(lambda: _point_symbol(_row(UNKNOWN)), id="canvas symbol"),
        pytest.param(lambda: group_label(_row(UNKNOWN)), id="card label"),
        pytest.param(
            lambda: provenance_label(_row(UNKNOWN), corrected=False),
            id="card provenance",
        ),
        pytest.param(lambda: build_payload(_frame([UNKNOWN])), id="chat payload"),
        pytest.param(
            lambda: resolve_people(_frame([UNKNOWN]), [{"i": "p0", "why": "x"}]),
            id="chat resolver",
        ),
        pytest.param(lambda: coverage_counts(_frame([UNKNOWN])), id="coverage counts"),
    ],
)
def test_an_unknown_state_raises_rather_than_rendering(consumer):
    with pytest.raises(ValueError, match="Unrecognised display_state"):
        consumer()


def test_the_card_names_the_reason_when_the_build_recorded_one():
    """The provenance line carries WHY, without claiming an abstention."""
    from src.dashboard.unclassified import REASON_COLUMN, REASON_SERVICE_BUSY

    row = _row(STATE_NOT_CLASSIFIED)
    row[REASON_COLUMN] = REASON_SERVICE_BUSY
    label = provenance_label(row, corrected=False)
    assert label.startswith(PROV_NOT_CLASSIFIED)
    assert "service was busy" in label
    assert "abstain" not in label.lower()


def test_the_card_falls_back_to_the_bare_line_without_a_reason():
    assert provenance_label(_row(STATE_NOT_CLASSIFIED),
                            corrected=False) == PROV_NOT_CLASSIFIED


def test_the_card_names_the_key_the_build_used():
    """Same source as the notice, so the two never explain one failure two ways."""
    from src.dashboard.keys import KEY_PROJECT, KEY_USER
    from src.dashboard.unclassified import REASON_COLUMN, REASON_KEY_FAILED

    row = _row(STATE_NOT_CLASSIFIED)
    row[REASON_COLUMN] = REASON_KEY_FAILED
    assert "your api key" in provenance_label(row, False, KEY_USER).lower()
    assert "unavailable" in provenance_label(row, False, KEY_PROJECT)


def test_the_card_claims_nothing_when_the_build_recorded_no_source():
    """D-63, and no "did not complete: the classification did not complete"."""
    from src.dashboard.unclassified import REASON_COLUMN, REASON_KEY_FAILED

    row = _row(STATE_NOT_CLASSIFIED)
    row[REASON_COLUMN] = REASON_KEY_FAILED
    assert provenance_label(row, corrected=False) == PROV_NOT_CLASSIFIED
