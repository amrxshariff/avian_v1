"""
src/dashboard/chat.py — Phase 2, P2.8: the chat panel (Streamlit glue).

Thin layer over src.assistant. Everything that could be tested without a server
lives there; what remains here is session state, widgets, and the two rules that
follow from person_index being a within-render handle.

The display table is PASSED IN, never read here. app.py calls
state.get_display_table() and hands the frame over. P2.8b's shared loader
therefore changes app.py alone — there is no read in this module to swap.

Rule 1 — history stores RENDERED TEXT, not indices.
    Turns persist across reruns. If an answer were stored as index references
    and re-resolved later, a mid-session table change would silently re-point it
    at different people. format_answer() resolves names once, at render time,
    and the resulting string is what persists. History becomes immutable prose
    and the failure class disappears.

Rule 2 — the live highlight is dropped when the table changes.
    The canvas highlight from the last answer IS a set of live indices. A
    fingerprint of the table is stored alongside it; when the fingerprint moves
    (P2.8b's mid-session upload, or a data reload) the highlight is discarded
    rather than carried onto a table it does not describe.

Streamlit is imported lazily inside functions, so importing this module for a
test never requires a running server — the module-level helpers below are pure
and unit-tested.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

import pandas as pd

from src.assistant import (
    STATUS_OK,
    ChatAnswer,
    answer_question,
    coverage_sentence,
)

HISTORY_KEY = "chat_history"
HIGHLIGHT_KEY = "chat_highlight"
FINGERPRINT_KEY = "chat_table_fingerprint"

PRIVACY_NOTE = (
    "Job titles, your notes and your own About text are sent to the Anthropic "
    "API to answer each question. Names are not — the assistant works from row "
    "handles and names are filled in on your machine. Nothing is stored "
    "server-side, and everything is discarded when this session ends."
)

ABOUT_NOTE_ACTIVE = (
    "Your About text is in use. It goes out with every question as context "
    "about you, so the assistant can judge what you are actually looking for "
    "rather than answering in the abstract. It is never attributed to anyone "
    "in your network. You do not need to run the enrichment comparison for "
    "this — writing it is enough. Clear the About box to stop sending it."
)

ABOUT_NOTE_IDLE = (
    "You have not written any About text. If you add one in the enrichment "
    "panel it will be sent with each question as context about you, which lets "
    "the assistant weigh answers against what you are trying to do."
)

PLACEHOLDER = "Ask about your network — e.g. who works in finance?"

# st.chat_input cannot be instantiated inside a column, and P2.8d puts the panel
# in the right-hand column. P2.10.4: the question box is a text area in a form,
# with an explicit Send.
#
# - It wraps, so a long question can be read back before it goes. Streamlit
#   1.41's text area has a fixed height and does not grow with its content:
#   four lines show a typical question whole, and a longer one scrolls inside
#   the box rather than sideways.
# - Enter is a new line, not a submit. Send (or Ctrl+Enter) submits. Without the
#   button the chat would inherit D-51's failure on the notes box, which kept a
#   note only on Ctrl+Enter or on leaving the box.
# - Leaving the box no longer sends a half-typed question. The old text input
#   submitted on blur, a trade-off accepted at P2.8f that the form removes.
# - clear_on_submit empties the box after Send. That replaces the callback and
#   pending key the text input needed, because a widget key cannot be written
#   from the script body once its widget exists.
INPUT_KEY = "chat_question_input"
FORM_KEY = "chat_question_form"
SEND_LABEL = "Send"
INPUT_HEIGHT = 110   # about four lines; Streamlit's minimum is 68 (two lines)


# --- pure helpers ------------------------------------------------------------


def table_fingerprint(df: pd.DataFrame) -> str:
    """Cheap identity for the current table.

    person_index plus role plus display_state: catches a reload, an upload, and
    a correction. A correction SHOULD move it — the previous answer was computed
    against different groupings, so keeping its highlight would be stale.
    """
    cols = [c for c in ("person_index", "role", "display_state") if c in df.columns]
    if not cols:
        return f"len:{len(df)}"
    blob = df[cols].astype(str).to_csv(index=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def format_answer(answer: ChatAnswer) -> str:
    """Render one answer to the markdown string that goes into history.

    Called ONCE, at answer time, against the table the answer was computed from.
    Nothing here is re-resolved later.
    """
    if answer.status != STATUS_OK:
        return answer.note

    lines: list[str] = []
    if answer.text:
        lines.append(answer.text)

    for person in answer.people:
        bits = [f"**{person.name}**", person.role or "no title"]
        if person.unreviewed:
            bits.append("needs review")
        elif person.not_classified:
            # Distinct wording, not a second kind of "needs review": the
            # classifier never answered for them.
            bits.append("not classified yet")
        else:
            bits.append(person.group or "—")
        line = " · ".join(b for b in bits if b)
        if person.why:
            line += f" — {person.why}"
        lines.append(f"- {line}")

    if answer.insufficient and not answer.people and not answer.text:
        lines.append("_No one in the table matches this well enough to name._")

    if answer.dropped:
        lines.append(
            f"_{answer.dropped} reference"
            f"{'s' if answer.dropped != 1 else ''} could not be matched to "
            "anyone in your network and were dropped._"
        )

    return "\n\n".join(lines)


def highlight_from(answer: ChatAnswer) -> set[int] | None:
    """Indices to light on the canvas, or None for 'no chat highlight'.

    None rather than an empty set, matching the P2.4b sentinel: an empty set
    means "match nothing, fade everything", which is wrong for an answer that
    named nobody.
    """
    if answer.status != STATUS_OK or not answer.people:
        return None
    return {p.person_index for p in answer.people}


# --- streamlit glue ----------------------------------------------------------


def init_chat_state(df: pd.DataFrame) -> None:
    """Ensure history exists; drop a stale highlight when the table has moved."""
    import streamlit as st

    st.session_state.setdefault(HISTORY_KEY, [])

    fingerprint = table_fingerprint(df)
    if st.session_state.get(FINGERPRINT_KEY) != fingerprint:
        st.session_state[FINGERPRINT_KEY] = fingerprint
        st.session_state[HIGHLIGHT_KEY] = None  # rule 2


def get_chat_highlight() -> set[int] | None:
    import streamlit as st

    return st.session_state.get(HIGHLIGHT_KEY)


def clear_chat() -> None:
    import streamlit as st

    st.session_state[HISTORY_KEY] = []
    st.session_state[HIGHLIGHT_KEY] = None


def newest_first(history: list[dict]) -> list[list[dict]]:
    """The history as exchanges, most recent first (P2.10.3).

    An exchange is a question and the turns that answer it, kept in their own
    order: the question above its answer. Only the exchanges are reversed. In a
    panel of fixed height, the newest answer is then in view without scrolling,
    which is the reason for the order.
    """
    exchanges: list[list[dict]] = []
    for turn in history:
        if turn.get("role") == "user" or not exchanges:
            exchanges.append([turn])
        else:
            exchanges[-1].append(turn)
    return exchanges[::-1]


def _ask(st) -> str:
    """The question sent this run, or "" (P2.10.4).

    A form: typing changes nothing until Send, and clear_on_submit empties the
    box once it has been sent.
    """
    with st.form(FORM_KEY, clear_on_submit=True, border=False):
        text = st.text_area(
            PLACEHOLDER, key=INPUT_KEY, label_visibility="collapsed",
            placeholder=PLACEHOLDER, height=INPUT_HEIGHT,
        )
        sent = st.form_submit_button(SEND_LABEL)
    return (text or "").strip() if sent else ""


def render_chat_panel(df: pd.DataFrame, client=None, *, history_height: int | None = None):
    """Render the panel, and return the region the history is drawn in.

    Top to bottom (P2.10.3): the heading and coverage line, then a region
    holding the allowance, the question box, the panel's own controls ("What is
    sent", "Clear conversation") and the history, newest exchange first. With
    `history_height` the region scrolls at that height, the box included. The
    region is returned so the caller can add to its foot (app.py puts the review
    queue there).

    `df` MUST be state.get_display_table() output — the live table including
    session corrections — or answers silently ignore the user's review work.

    Safe inside a column: the question box is a text area in a form, not
    st.chat_input, which Streamlit forbids in a column.
    """
    import streamlit as st
    from src.assistant import STATUS_UNAVAILABLE, _default_client as chat_client
    from src.dashboard.chat_allowance import current, record_question
    from src.dashboard.enrich import KEY_ABOUT   # widget key, same read as session_io
    from src.dashboard.keys import key_source
    from src.dashboard.metering import BUDGET_SPENT_NOTE, budget_spent, metered_client

    init_chat_state(df)
    user_about = str(st.session_state.get(KEY_ABOUT, "") or "").strip()

    st.subheader("Ask about your network")
    st.caption(coverage_sentence(df))

    # P2.10.3: everything from here scrolls together in one region: the box,
    # the panel's controls, then the history, newest first. A browser verdict
    # put the box at the top of the region rather than above it, outside the
    # scroll. With the box outside, a question asked while the history was
    # scrolled down was answered out of view: the region is reused across
    # reruns, so it keeps its scroll position, and scroll anchoring holds the
    # view while the new exchange is inserted above it. With the box inside,
    # typing means being at the top, so the new answer lands under the box, in
    # view by construction.
    region = (st.container(height=history_height, border=False)
              if history_height else st.container())
    with region:
        # D-80: the ten-question allowance (design §6.6) and the daily ledger,
        # both on the project key only. Either one spent stops the chat and
        # says why, pointing at the key field; the network and everything else
        # stay usable. With the allowance spent the form is not drawn, so
        # nothing can be sent.
        source = key_source()
        allowance = current(st.session_state, source)
        if allowance.spent or budget_spent(source):
            st.caption(allowance.caption() if allowance.spent else BUDGET_SPENT_NOTE)
            question = ""
        else:
            question = _ask(st)
            if allowance.caption():
                st.caption(allowance.caption())

        history = st.session_state[HISTORY_KEY]

        # The panel's controls sit under the box they serve, above the
        # history. They are panel-level, not per exchange. At the foot of a
        # newest-first history, clearing the conversation would mean scrolling
        # past all of it.
        with st.expander("What is sent when you ask a question"):
            st.caption(PRIVACY_NOTE)
            st.caption(ABOUT_NOTE_ACTIVE if user_about else ABOUT_NOTE_IDLE)
        if history:
            st.button("Clear conversation", on_click=clear_chat)

        _render_history(st, df, question, history, user_about, source, client,
                        chat_client, record_question, STATUS_UNAVAILABLE)
    return region


def _render_history(st, df, question, history, user_about, source, client,
                    chat_client, record_question, status_unavailable) -> None:
    """The history, newest exchange first, with a new question answered at the
    top. Storage stays chronological: newest_first() reverses a copy."""
    from src.dashboard.metering import metered_client

    # P2.10.3: a new question is answered here, at the top of the history, so the
    # newest exchange is first on this run as well as after the rerun.
    if question:
        history.append({"role": "user", "text": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Reading your network…"):
                answer = answer_question(
                    df, question, user_about,
                    client=metered_client(source, client, chat_client),
                )
            if answer.status != status_unavailable:
                # After, not before (chat_allowance.record_question): a
                # question that got no answer does not use one up.
                record_question(st.session_state, source)
            rendered = format_answer(answer)   # rule 1: resolve now, store text
            st.markdown(rendered)
            st.caption(coverage_sentence(df))

        history.append({"role": "assistant", "text": rendered})
        st.session_state[HIGHLIGHT_KEY] = highlight_from(answer)
        # The canvas read HIGHLIGHT_KEY above build_figure, before this panel
        # ran, so the figure for THIS pass was drawn without the new answer.
        # One rerun lets it re-read. Terminating: a form's submit button reads
        # False on the next run, so `question` is empty and this branch cannot
        # run again.
        st.rerun()

    for exchange in newest_first(history):
        for turn in exchange:
            with st.chat_message(turn["role"]):
                st.markdown(turn["text"])