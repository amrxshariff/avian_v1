"""
src/dashboard/people_list.py — Phase 2, P2.8d: the review queue and the shared
people list.

One component, two consumers:

  * MODE_RESULTS — search and group-filter results, rendered live. Replaces the
    sidebar selectbox: selecting a person is now one click on a visible card
    rather than opening a dropdown to find out who matched.

  * MODE_REVIEW  — the review queue. The 168 needs-review nodes are this
    product's honest headline, and until now there was no way to ACT on them:
    search, select, expand the card, one at a time, with no sense of progress.

Building both from one component is less work than building them separately and
means the two behave identically — the same list, the same selection, the same
correction path.

Why the queue belongs in Phase 2 rather than Phase 4
----------------------------------------------------
P2.8c made review work survive a refresh. Reviewing 168 people is only worth
starting if the work persists; before save/restore the queue would have been a
novelty. The two items compose: restored corrections shrink the queue on load,
because the queue is derived from display_state, which the corrections overlay
already sets.

No second correction path
-------------------------
Every assignment here goes through state.set_correction(), the same function the
profile card's picker uses. A queue with its own write path would be a second
place for the correction semantics to drift — and display_state, is_uncertain
and the canvas colour all derive from that one overlay.

Skips are session-scoped and non-destructive
--------------------------------------------
Skipping removes someone from the queue view. It does NOT record a verdict: they
stay needs_review everywhere else, stay grey on the canvas, and stay in the
"still need review" count. A skip that silently resolved a node would be exactly
the confident-wrongness this project refuses. Skips are deliberately NOT in the
P2.8c save file: a skip is a statement about this sitting ("not now"), not about
the person, and restoring it a week later would hide someone from the queue for
a reason the user no longer remembers.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.dashboard.state import (
    NOT_OCCUPATION,
    NOT_OCCUPATION_NAME,
    STATE_NEEDS_REVIEW,
    set_correction,
)
from src.dashboard.summaries import coverage_counts
from src.onet import MAJOR_GROUP_NAMES

MODE_RESULTS = "results"
MODE_REVIEW = "review"

PAGE_SIZE = 10

SKIPPED_KEY = "review_skipped"
PAGE_KEY = "people_list_page"
SELECTED_KEY = "people_list_selected"

PICKER_PLACEHOLDER = "assign a group…"

QUEUE_EMPTY = "Nothing left to review. Every connection has been looked at."
QUEUE_ALL_SKIPPED = (
    "Every remaining person has been skipped this session. Clear the skips to "
    "see them again — they are still unreviewed."
)
NO_RESULTS = "No matches — try a different term."

SKIP_NOTE = (
    "Skipping hides someone from this list for now. It records no verdict: they "
    "stay unreviewed everywhere else."
)


# --- pure core ---------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    """One page of a list, plus what the caller needs to render the pager."""

    rows: pd.DataFrame
    number: int          # 1-based
    total_pages: int
    total_rows: int

    @property
    def first(self) -> int:
        """1-based index of the first row shown, 0 when the page is empty."""
        return 0 if self.rows.empty else (self.number - 1) * PAGE_SIZE + 1

    @property
    def last(self) -> int:
        return 0 if self.rows.empty else self.first + len(self.rows) - 1


def paginate(df: pd.DataFrame, number: int = 1, size: int = PAGE_SIZE) -> Page:
    """Slice `df` into a page. 168 entries cannot render at once.

    The requested page is CLAMPED rather than allowed to run off the end: the
    list shrinks as people are reviewed, so a user on page 17 who resolves the
    last entry must land on a real page rather than an empty one.
    """
    total_rows = len(df)
    total_pages = max(1, (total_rows + size - 1) // size)
    number = max(1, min(int(number), total_pages))
    start = (number - 1) * size
    return Page(df.iloc[start : start + size], number, total_pages, total_rows)


def queue_frame(df: pd.DataFrame, skipped: set[int] | None = None) -> pd.DataFrame:
    """The people still needing review, minus anyone skipped this session.

    Derived from display_state, so a correction — typed here, made on the
    profile card, or restored from a save file — removes someone immediately
    with no separate bookkeeping.
    """
    unreviewed = df[df["display_state"].astype(str) == STATE_NEEDS_REVIEW]
    if skipped:
        unreviewed = unreviewed[~unreviewed["person_index"].astype(int).isin(skipped)]
    return unreviewed


def review_progress(df: pd.DataFrame, base_needing_review: int) -> str:
    """"168 need review." at rest; "165 of 168 still need review." after progress.

    Counts DOWN and reuses the header's vocabulary, so the two numbers on screen
    describe the same fact in the same direction. `base_needing_review` is the
    session's fixed starting backlog, exactly as state.get_review_counts()
    reports it.

    D-32: the equal case needs its own branch. "168 of 168" restates itself, and
    "still" claims progress that has not happened. app.py's counter suppresses M
    until the first correction for the same reason; this panel was written after
    that fix and never inherited it.
    """
    # D-35: one source for this figure. Counting display_state here was a third
    # implementation of the rule coverage_counts() already encodes, and D-33
    # showed what a second one costs.
    remaining = coverage_counts(df).needs_review
    if not base_needing_review:
        return "Nothing needed review in this network."
    if not remaining:
        return f"All {base_needing_review} reviewed."
    if remaining == base_needing_review:
        # D-32: the header's suppression branch. "183 of 183" restates itself,
        # and "still" claims progress that has not happened. Same rule as
        # app.py's counter — n leads, m appears only once it differs.
        return f"{remaining} need review."
    return f"{remaining} of {base_needing_review} still need review."  # count-exempt: guarded at L154 (D-32)


def picker_options() -> list[str]:
    """Group labels for the assignment control, plus 'not an occupation'.

    Options come from the TAXONOMY, never from the data, so the control is
    identical for every user's network — the same rule as the canvas palette and
    the sidebar group filter.
    """
    return [
        *(f"{code} · {name}" for code, name in sorted(MAJOR_GROUP_NAMES.items())),
        NOT_OCCUPATION_NAME,
    ]


def option_to_code(option: str | None) -> str | None:
    """Map a picker label back to a correction value, or None for no choice."""
    if not option or option == PICKER_PLACEHOLDER:
        return None
    if option == NOT_OCCUPATION_NAME:
        return NOT_OCCUPATION
    code = option.split("·")[0].strip()
    return code if code in MAJOR_GROUP_NAMES else None


def person_label(row) -> str:
    name = str(row.get("name", "")).strip() or "(unnamed)"
    role = str(row.get("role", "")).strip()
    return f"{name} · {role}" if role else name


# --- streamlit glue ----------------------------------------------------------


def get_skipped() -> set[int]:
    import streamlit as st

    if SKIPPED_KEY not in st.session_state:
        st.session_state[SKIPPED_KEY] = set()
    return st.session_state[SKIPPED_KEY]


def skip(person_index: int) -> None:
    get_skipped().add(int(person_index))


def clear_skips() -> None:
    import streamlit as st

    st.session_state[SKIPPED_KEY] = set()


def get_selected() -> int | None:
    import streamlit as st

    return st.session_state.get(SELECTED_KEY)


def select(person_index: int | None) -> None:
    import streamlit as st

    st.session_state[SELECTED_KEY] = None if person_index is None else int(person_index)


def _page_number(mode: str) -> int:
    import streamlit as st

    return int(st.session_state.get(f"{PAGE_KEY}_{mode}", 1))


def _set_page(mode: str, number: int) -> None:
    import streamlit as st

    st.session_state[f"{PAGE_KEY}_{mode}"] = int(number)


def _assign(person_index: int, widget_key: str, mode: str) -> None:
    """on_change callback: write the correction before the script reruns.

    Two guards, both load-bearing. The placeholder writes nothing — selecting
    "assign a group…" is not a verdict. And an unchanged value writes nothing
    either: restoring a session shrinks the queue, so page 1 holds different
    people and Streamlit sees widget keys appear and disappear. Without the
    second guard each of those fires a write, which reruns, which renders a
    different ten, which fires again — the page never settles.
    """
    import streamlit as st

    from src.dashboard.state import get_corrections

    code = option_to_code(st.session_state.get(widget_key))
    if code is None:
        return
    if get_corrections().get(int(person_index)) == code:
        return
    set_correction(person_index, code)


def _render_pager(page: Page, mode: str) -> None:
    import streamlit as st

    if page.total_pages <= 1:
        return
    previous, label, following = st.columns([1, 2, 1])
    with previous:
        if st.button("‹", key=f"prev_{mode}", disabled=page.number <= 1,
                     use_container_width=True):
            _set_page(mode, page.number - 1)
            st.rerun()
    with label:
        st.caption(f"{page.first}–{page.last} of {page.total_rows}")  # count-exempt: unreachable — _render_pager returns early when total_pages <= 1
    with following:
        if st.button("›", key=f"next_{mode}", disabled=page.number >= page.total_pages,
                     use_container_width=True):
            _set_page(mode, page.number + 1)
            st.rerun()


def render_people_list(df: pd.DataFrame, mode: str = MODE_RESULTS) -> int | None:
    """Render one page of people. Returns the selected person_index, or None.

    MODE_RESULTS renders name, title and group with a select button.
    MODE_REVIEW adds an inline group picker and a skip control.
    """
    import streamlit as st

    page = paginate(df, _page_number(mode))
    if page.rows.empty:
        return get_selected()

    for _, row in page.rows.iterrows():
        index = int(row["person_index"])
        with st.container(border=True):
            st.markdown(f"**{str(row.get('name', '')).strip() or '(unnamed)'}**")
            st.caption(str(row.get("role", "")).strip() or "no title given")

            if mode == MODE_REVIEW:
                widget_key = f"assign_{index}"
                st.selectbox(
                    "Assign a group",
                    [PICKER_PLACEHOLDER, *picker_options()],
                    key=widget_key,
                    label_visibility="collapsed",
                    on_change=_assign,
                    args=(index, widget_key, mode),
                )
                if st.button("Skip", key=f"skip_{index}", use_container_width=True):
                    skip(index)
                    st.rerun()
            else:
                st.caption(str(row.get("soc_major_name", "")).strip())
                if st.button("Show profile", key=f"pick_{index}",
                             use_container_width=True):
                    select(index)
                    st.rerun()

    _render_pager(page, mode)
    return get_selected()


def render_review_queue(df: pd.DataFrame, base_needing_review: int) -> None:
    """The queue panel: progress line, then one page of people to review."""
    import streamlit as st

    st.subheader("Review queue")
    st.caption(review_progress(df, base_needing_review))

    skipped = get_skipped()
    remaining = queue_frame(df, skipped)

    if remaining.empty:
        st.success(QUEUE_ALL_SKIPPED if skipped else QUEUE_EMPTY)
        if skipped:
            st.button(f"Clear {len(skipped)} skips", on_click=clear_skips)
        return

    render_people_list(remaining, mode=MODE_REVIEW)
    st.caption(SKIP_NOTE)
    if skipped:
        st.button(f"Clear {len(skipped)} skips", on_click=clear_skips)