"""
src/dashboard/notes.py — Phase 2, P2.2b: per-person notes.

A free-text field on any node, holding the user's own words about that person.
Empty until typed in. Session-scoped, never written to disk.

Why this is not the skills section
----------------------------------
Amendment 2 forbids attributing taxonomy-derived skills to an individual. A note
is the opposite case — it IS the user's own words — so it is allowed. But it is
still not a skills claim: "met at the Roche data day, knows Collibra well" and
"good with clustering" are different kinds of statement, and rendering the first
under a heading that says Skills would launder an observation into an
attribution. Notes therefore get their own section, and card.skills_note() is
left exactly as it is.

Why there is no generation here (DoD-6)
---------------------------------------
This module imports nothing from claude_classifier or self_enrichment and makes
no API call. There is no suggestion, no autocomplete, no "shall I draft this for
you". That is enforced by the absence of the import, not by a comment — the same
way enrich.py's scope is enforced by the absence of a person_index argument. A
generated note about a real person, sitting in a field the user will later read
as their own recollection, is precisely the confidently-wrong failure the whole
project is built to avoid.

Why notes are a separate overlay, not part of apply_corrections
---------------------------------------------------------------
apply_corrections has one clear job, pinned by tests/test_state.py: resolving
occupation group and display_state. Notes touch neither. Composing them as a second,
independent layer in app.py keeps that function and its tests untouched, and
keeps this one trivially testable in isolation.

Version A: notes live in st.session_state and are dropped when the tab closes.
They are the user's observations about named real people, which is exactly the
category of data this product does not persist.
"""

from __future__ import annotations

import pandas as pd

NOTES_KEY = "notes"

# The column apply_notes writes and search.filter_nodes reads.
NOTE_COLUMN = "note"

# Bounds one note. Long enough for a paragraph of recollection, short enough
# that the session state stays small at 430 people.
MAX_NOTE_CHARS = 2000

NOTES_HEADING = "Your notes"
NOTES_PLACEHOLDER = "how you know them, what they work on, anything worth remembering"
NOTES_HELP = (
    "Your own words, kept for this session only. Never sent anywhere, never "
    "written to disk, never used to classify anyone."
)
NOTE_SAVED = "Saved for this session."
NOTE_SAVE_LABEL = "Save note"
NOTE_UNSAVED_HINT = "Press Save note to keep it. Typing alone does not save."


# --- pure core ---------------------------------------------------------------

def normalise_note(text: str | None) -> str:
    """Trim and bound one note. Whitespace-only becomes empty.

    Empty and whitespace-only collapse to the same value so that "has a note"
    is a single unambiguous test downstream, and so a user who clears a field
    by selecting-all-and-deleting gets the same result as one who never typed.
    """
    return (text or "").strip()[:MAX_NOTE_CHARS]


def apply_notes(df: pd.DataFrame, notes: dict[int, str]) -> pd.DataFrame:
    """Return a COPY of `df` with a `note` column holding the user's notes.

    Every row gets the column — empty string where there is no note — so
    filter_nodes and the card can read it unconditionally without a presence
    check, and so a frame with no notes at all still has a stable schema.

    Pure: no Streamlit, no disk, no mutation of `df`. Notes keyed by a
    person_index absent from the table are ignored, exactly as corrections are:
    a session can outlive a data reload.
    """
    out = df.copy()
    if not notes:
        out[NOTE_COLUMN] = ""
        return out

    clean = {int(k): normalise_note(v) for k, v in notes.items()}
    out[NOTE_COLUMN] = (
        out["person_index"].astype(int).map(clean).fillna("").astype(str)
    )
    return out


def note_count(notes: dict[int, str]) -> int:
    """How many people currently carry a non-empty note."""
    return sum(1 for v in notes.values() if normalise_note(v))


# --- streamlit glue (lazy import) --------------------------------------------

def get_notes() -> dict[int, str]:
    import streamlit as st

    if NOTES_KEY not in st.session_state:
        st.session_state[NOTES_KEY] = {}
    return st.session_state[NOTES_KEY]


def set_note(person_index: int, text: str) -> None:
    """Record or clear one note.

    An emptied note DELETES the key rather than storing "". Presence of a key
    then means "this person has a note", with no empty-string special case for
    every reader to remember — the same reasoning as the corrections overlay,
    where presence means the user has resolved the node.
    """
    notes = get_notes()
    clean = normalise_note(text)
    if clean:
        notes[int(person_index)] = clean
    else:
        notes.pop(int(person_index), None)


def apply_notes_from_session(df: pd.DataFrame) -> pd.DataFrame:
    """apply_notes() against the live session overlay. Called from app.py."""
    return apply_notes(df, get_notes())


def _on_note_save(person_index: int, widget_key: str) -> None:
    """Copy the field's value into the overlay when Save note is pressed.

    Runs as the Save button's callback, which Streamlit fires BEFORE the script
    reruns — so the note is in the overlay by the time app.py rebuilds the
    display table, and a note becomes searchable on the same rerun in which it
    was saved. Reading the widget key after the fact instead would be one rerun
    behind, and the search box would silently miss a note the user could see on
    screen.
    """
    import streamlit as st

    set_note(person_index, st.session_state.get(widget_key, ""))


def render_notes(person_index: int) -> None:
    """The notes field for one node. Called at the foot of the profile card."""
    import streamlit as st

    person_index = int(person_index)
    widget_key = f"note_input_{person_index}"
    existing = get_notes().get(person_index, "")

    st.markdown(f"**{NOTES_HEADING}**")
    # D-51: an explicit Save button. Before, a note was kept only on Ctrl+Enter
    # or on leaving the box, with nothing on screen to say so. In a form the
    # field's value is sent only on submit, so typing alone never saves.
    with st.form(f"note_form_{person_index}", border=False):
        st.text_area(
            NOTES_HEADING,
            value=existing,
            key=widget_key,
            height=110,
            max_chars=MAX_NOTE_CHARS,
            placeholder=NOTES_PLACEHOLDER,
            label_visibility="collapsed",
        )
        st.form_submit_button(
            NOTE_SAVE_LABEL,
            on_click=_on_note_save,
            args=(person_index, widget_key),
        )
    if existing:
        st.info("Your words, not the classifier's")
    st.caption(NOTE_SAVED if existing else f"{NOTES_HELP} {NOTE_UNSAVED_HINT}")