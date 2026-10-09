"""
tests/test_notes.py — P2.2b pure-function tests.

Plain pytest: no Streamlit runtime. The glue (get_notes, set_note, render_notes)
needs a session and is not tested here; everything with logic in it was pulled
out into pure functions precisely so it could be.

Two of these matter more than the rest:

  * non-mutation of the input frame — the same invariant C5 checks at dashboard
    level on the corrections overlay, and the one that breaks silently the day
    someone removes a .copy() to save an allocation;
  * stable schema on an empty overlay — what stops filter_nodes throwing on the
    first session of every user, when nobody has written a note yet.
"""

from __future__ import annotations

import pandas as pd

from src.dashboard.notes import (
    MAX_NOTE_CHARS,
    NOTE_COLUMN,
    apply_notes,
    normalise_note,
    note_count,
)


def frame(indices=(1, 2, 3)) -> pd.DataFrame:
    return pd.DataFrame({
        "person_index": list(indices),
        "name": [f"Person {i}" for i in indices],
    })


# --- normalise_note ----------------------------------------------------------

def test_normalise_none_is_empty():
    assert normalise_note(None) == ""


def test_normalise_whitespace_only_is_empty():
    """A user who selects-all-and-deletes must land in the same state as one who
    never typed. Otherwise 'has a note' has two answers."""
    assert normalise_note("   \n\t ") == ""


def test_normalise_trims_surrounding_whitespace():
    assert normalise_note("  met at Roche  ") == "met at Roche"


def test_normalise_truncates_at_the_cap():
    assert len(normalise_note("x" * (MAX_NOTE_CHARS + 500))) == MAX_NOTE_CHARS


def test_normalise_preserves_internal_newlines():
    """Notes are written as lists as often as prose — the test note in the
    dashboard was three lines. Internal structure is content, not whitespace."""
    assert normalise_note("presentation\nteam work") == "presentation\nteam work"


# --- apply_notes: schema -----------------------------------------------------

def test_empty_overlay_still_creates_the_column():
    """Every reader — filter_nodes, the card — reads `note` unconditionally.
    A frame with no notes must still have the column, or the first session of
    every user throws."""
    out = apply_notes(frame(), {})
    assert NOTE_COLUMN in out.columns
    assert (out[NOTE_COLUMN] == "").all()


def test_column_is_string_dtype_when_all_notes_empty():
    """Without the explicit astype(str), pandas infers float64 from an all-NaN
    map and .str.contains in filter_nodes fails on the whole column."""
    out = apply_notes(frame(), {})
    assert out[NOTE_COLUMN].map(type).eq(str).all()


def test_column_is_string_dtype_with_partial_notes():
    out = apply_notes(frame(), {2: "knows Collibra"})
    assert out[NOTE_COLUMN].map(type).eq(str).all()


# --- apply_notes: mapping ----------------------------------------------------

def test_notes_land_on_the_right_person():
    out = apply_notes(frame(), {2: "knows Collibra"})
    by_index = dict(zip(out["person_index"], out[NOTE_COLUMN]))
    assert by_index == {1: "", 2: "knows Collibra", 3: ""}


def test_notes_are_normalised_on_the_way_in():
    out = apply_notes(frame(), {1: "  padded  ", 2: "   "})
    by_index = dict(zip(out["person_index"], out[NOTE_COLUMN]))
    assert by_index[1] == "padded"
    assert by_index[2] == ""


def test_string_keys_are_coerced():
    """Session state round-trips can hand back a string index. Coercing beats
    silently dropping the note — a note that vanishes looks like data loss."""
    out = apply_notes(frame(), {"2": "knows Collibra"})
    by_index = dict(zip(out["person_index"], out[NOTE_COLUMN]))
    assert by_index[2] == "knows Collibra"


def test_unknown_person_index_is_ignored_not_raised():
    """A session can outlive a data reload, exactly as corrections can. A stale
    key is a no-op, never a crash."""
    out = apply_notes(frame(), {999: "stale"})
    assert (out[NOTE_COLUMN] == "").all()


def test_notes_survive_a_non_contiguous_index():
    """The display frame arrives filtered and merged, so its row labels are not
    guaranteed to be 0..n. Mapping is on person_index, never on position."""
    df = frame().set_index(pd.Index([10, 20, 30]))
    out = apply_notes(df, {3: "third"})
    assert out.loc[30, NOTE_COLUMN] == "third"


# --- apply_notes: purity -----------------------------------------------------

def test_input_frame_is_not_mutated():
    """The invariant C5 checks on the corrections overlay at dashboard level.
    Breaks silently and late if a .copy() is ever optimised away."""
    df = frame()
    apply_notes(df, {1: "a note"})
    assert NOTE_COLUMN not in df.columns


def test_input_frame_is_not_mutated_on_the_empty_path():
    """The early return for an empty overlay is a second code path and needs
    its own test — it is the one that runs on every rerun before any note is
    written, so a mutation there would corrupt the base frame immediately."""
    df = frame()
    apply_notes(df, {})
    assert NOTE_COLUMN not in df.columns


def test_returns_a_new_object():
    df = frame()
    assert apply_notes(df, {}) is not df


def test_row_count_and_order_are_preserved():
    out = apply_notes(frame(), {2: "note"})
    assert list(out["person_index"]) == [1, 2, 3]


# --- note_count --------------------------------------------------------------

def test_note_count_ignores_whitespace_only_entries():
    """Coverage is low by design (P2.2b criterion 6), so whatever counts notes
    must at least count them honestly."""
    assert note_count({1: "real", 2: "   ", 3: ""}) == 1


def test_note_count_of_empty_overlay():
    assert note_count({}) == 0