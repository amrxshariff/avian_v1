"""
app.py — Network Visualiser dashboard entry point.

Phase 2. The canvas (P2.3) renders the network; the sidebar carries search
(P2.4), the result list, and the profile card with its confirmation control
(P2.5 + P2.1 UI).

Selection is list-driven, not click-driven: Streamlit's on_select does not fire
reliably on Scatter3d, so the graph is a pure output surface and every selection
flows through the sidebar. See Phases 2-3 Amendment 1.

Run from the repo root:
    streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from st_keyup import st_keyup

from src.onet import MAJOR_GROUP_NAMES
from src.dashboard.state import get_corrections, review_counts
from src.dashboard.loader import DEMO_NODES_CSV, load_base_frame, load_display_table
from src.dashboard.canvas import build_figure
from src.dashboard.search import filter_caption, filter_nodes
from src.dashboard.card import render_profile_card
from src.dashboard.enrich import render_enrichment_panel
from src.dashboard.session_io import render_session_io
from src.dashboard.summaries import coverage_counts, render_summaries_panel
from src.dashboard.session_build import (
    classification_cache, get_built, set_built, touch,
)
from src.dashboard.lifetime import (
    expire_if_stale,
    render_lifetime_notices,
    watch_session,
)
from src.dashboard.welcome import render_welcome, should_welcome, start_over
from src.dashboard.upload import render_upload_panel
from src.dashboard.unclassified import pending_clause, render_notice
from src.dashboard.retry_offer import take_offer
from src.dashboard.provenance import provenance_line
from src.dashboard.keys import key_source, redact
from src.dashboard.metering import meters_for
from src.dashboard.chat import get_chat_highlight, init_chat_state, render_chat_panel
from src.dashboard.people_list import (
    MODE_RESULTS,
    get_selected,
    render_people_list,
    render_review_queue,
    select,
)

# 760 since P2.10: the chat now scrolls in its own region beside the canvas, so
# a taller canvas no longer pushes anything below the fold, and both columns
# fill more of the window. Sized for a 1080-pixel-tall screen; a smaller screen
# scrolls the page a little. (620 before, cut from 700 when the chat column
# still grew with its content.)
CANVAS_HEIGHT = 760
# P2.10: two thirds of the width to the canvas. The chat column keeps enough
# width for the review queue's controls.
CANVAS_RATIO = (2, 1)   # canvas : chat

# P2.10.1: scroll-to-zoom is back on. P2.8c (7923f88) turned it off because the
# plot swallowed the page scroll, so reaching anything below it meant fighting
# the canvas. P2.10.2 answers that reason: the chat column is now a panel with
# its own scroll, so the page no longer grows below the canvas, and the wheel
# over the canvas is free to zoom. Neither scrolls the other.
CANVAS_CONFIG = {"scrollZoom": True}

# P2.10.2: the chat history and the review queue scroll inside a region of
# fixed height, rather than extending the page. That is what keeps the canvas in
# place, with no positioning CSS: an earlier attempt pinned the canvas with
# sticky CSS in a keyed container, and a browser session found a stale canvas
# from an earlier run left on the page beneath it (D-85).
# P2.10.3: the box and the panel's controls scroll inside that region, at its
# top. Only the chat's heading and coverage line sit above it, so the region is
# the canvas's height less roughly what those two take. That figure is an
# estimate, to be set by a browser verdict.
CHAT_TOP_ESTIMATE = 90
CHAT_HISTORY_HEIGHT = CANVAS_HEIGHT - CHAT_TOP_ESTIMATE
NO_SELECTION = "—"


KEY_NONCE = "search_nonce"


def _render_sidebar(df: pd.DataFrame, built) -> tuple[int | None, set[int] | None, set[str]]:
    """Group filter, search box, result list, profile card.

    Returns (highlight, match set, selected group codes). The two filters
    INTERSECT: a node is prominent only if it satisfies both. Neither silently
    overrides the other, because a filter that ignores another filter makes the
    view unpredictable (P2.6a DoD-3).
    """
    with st.sidebar:
        with st.expander("Your network", expanded=built is None):
            # Already in an expander: the key field must not open another
            # inside it, which Streamlit refuses (D-66).
            # No on_key: validation runs inside an on_change callback, which
            # Streamlit already follows with a rerun. Calling st.rerun() from
            # within one is a no-op that prints a warning a visitor can read
            # (D-67).
            render_upload_panel(on_built=st.rerun, boxed=False)
            if st.button("Start over", key="start_over"):
                start_over()
                st.rerun()

    # MUST run before render_enrichment_panel(), which main() draws later in the
    # canvas column: enrich.py binds KEY_TITLE and
    # KEY_ABOUT to widget keys, and Streamlit forbids writing a widget key once
    # its widget exists. Restoring from below the panel raises.
    # render_enrichment_panel() is drawn later, in the canvas column (P2.10).
    render_session_io(df)

    st.sidebar.header("Groups")
    # Options come from the taxonomy, never from the data, so the control is
    # identical across every user's network (DoD-5) — same rule as the palette.
    name_to_code = {v: k for k, v in MAJOR_GROUP_NAMES.items()}
    chosen = st.sidebar.multiselect(
        "Occupation groups", sorted(name_to_code),
        label_visibility="collapsed", placeholder="all groups",
    )
    group_codes = {name_to_code[n] for n in chosen}
    render_summaries_panel(df, group_codes)

    st.sidebar.header("Search")
    # Columns are created first, then written into in either order — so the clear
    # is handled ABOVE the widget instantiation while still rendering to its right.
    search_box, clear_box = st.sidebar.columns([4, 1])

    with clear_box:
        cleared = st.button("✕", help="Clear search", key="clear_search_btn")

    if cleared:
        old = st.session_state.get(KEY_NONCE, 0)
        st.session_state.pop(f"search_query_{old}", None)
        st.session_state[KEY_NONCE] = old + 1
        select(None)
        # st_keyup is an iframe: a key change during a callback-driven rerun
        # registers the new component but loses its height message, so it renders
        # at zero height until the next pass. Force that pass here. Terminates
        # after exactly one iteration — `cleared` is False on the forced rerun,
        # so this branch cannot re-enter.
        st.rerun()

    with search_box:
        query = st_keyup(
            "Search",
            key=f"search_query_{st.session_state.get(KEY_NONCE, 0)}",
            debounce=250,
            placeholder="name, role, or occupation group",
            label_visibility="collapsed",
        ) or ""

    matches = filter_nodes(df, query)
    if group_codes:
        matches = matches[matches["soc_major"].astype(str).isin(group_codes)]

    filtering = bool(query.strip() or group_codes)
    match_indices = set(matches["person_index"].astype(int)) if filtering else None
    st.sidebar.caption(filter_caption(len(matches), len(df), filtering))

    if matches.empty:
        # Naming BOTH filters matters: an empty intersection is the one outcome
        # a user reads as a bug rather than as an answer.
        if query.strip() and group_codes:
            st.sidebar.info("No one matches that search inside the selected groups.")
        elif group_codes:
            st.sidebar.info("Nobody in this network holds the selected groups.")
        else:
            st.sidebar.info("No matches — try a different term.")
        return None, match_indices, group_codes

    # P2.8d: results render live as cards rather than hiding behind a dropdown.
    # Same component as the review queue, so the two behave identically.
    with st.sidebar:
        highlight = render_people_list(matches.sort_values("name"), mode=MODE_RESULTS)

    # A selection made before the filters changed may no longer be on screen.
    if highlight is not None and highlight not in set(matches["person_index"].astype(int)):
        highlight = None

    st.sidebar.divider()
    if highlight is None:
        st.sidebar.caption("Select a result to see their profile.")
    else:
        row = df.loc[df["person_index"] == highlight].iloc[0]
        with st.sidebar:
            render_profile_card(row, source=_build_source(built))

    return highlight, match_indices, group_codes


# How often an open tab checks its own clock. Under a minute of slack on a
# one-hour lifetime; browsers throttle background-tab timers to about this.
WATCH_EVERY = 60


def _build_source(built) -> str | None:
    """Whose key the BUILD used, from its own provenance — never the session's
    key now: someone can fail on the project key and then paste their own
    (D-63). None when the build recorded nothing, or for the demo, and the
    wording then declines to guess."""
    return built.provenance.get("source") if built is not None else None


def _retry_handler(built):
    """Re-classify the people this build could not, then redraw.

    Only the classification is redone: retry_unclassified carries the
    coordinates and centrality across, so nobody moves on the canvas while
    someone is mid-review. The titles that succeeded are cached, so a retry
    pays only for the people being retried.
    """
    def handler(person_indices: list[int]) -> None:
        from src.build import retry_unclassified

        try:
            with st.spinner(f"Classifying {len(person_indices)} more..."):
                set_built(retry_unclassified(
                    built,
                    person_indices,
                    # Without this, provenance keeps saying "project" after a
                    # retry the user paid for, and the notice then tells them
                    # the service was unavailable when their own key failed.
                    source=key_source(),
                    # The session's cache, the one its build used (D-71): a
                    # title already answered is not paid for twice, and none
                    # of them reaches the shared file.
                    cache_path=classification_cache(),
                    # The same caps as the build it retries (D-81).
                    meters=meters_for(key_source()),
                ))
        except Exception as exc:  # noqa: BLE001 — shown, not swallowed
            # redact before display: an SDK error can quote the request it
            # failed on, and a key in a traceback on a public deploy is the
            # failure this whole design exists to avoid. The build is left
            # intact — a failed retry must not cost someone their network.
            st.error(redact(str(exc)))
            return
        st.rerun()

    return handler


@st.fragment(run_every=WATCH_EVERY)
def _session_watch(df) -> None:
    """lifetime.watch_session on a timer: an idle tab does not rerun, and
    without this "dropped after an hour" would be false of one left open."""
    if watch_session(df):
        st.rerun()          # the whole app, to the welcome screen's note


def main() -> None:
    st.set_page_config(page_title="Network Visualiser", layout="wide")

    # P2.8b: the assembly (base -> sidecar merge -> corrections -> notes) lives
    # in the loader, which every checker imports too. It used to live here,
    # where nothing else could reach it, so each caller reimplemented a subset.
    #
    # D-33: base is read ONCE, here, and threaded through — not re-read from
    # disk by a second cached function. That second read (state.load_base_table,
    # now deleted) is what let the header report a different network's counts
    # from the one the rest of the page was showing, the moment a real upload's
    # frame diverged from the canonical CSV on the server.
    # P2.9b: a network built this session takes precedence over the demo
    # CSV. Both go through the SAME loader and the same overlays — a second
    # assembly path for uploads is exactly the drift D-33 was.
    #
    # Before the loader: composing a table from a network about to be dropped
    # is wasted work, and renders a screen that vanishes on the same pass.
    expire_if_stale()

    built = get_built()

    # P2.9: the dashboard opens on a network, which means nothing to someone
    # who has not supplied one. Returning here is what keeps the rest of
    # main() from rendering a stranger's connections behind it.
    if should_welcome(built):
        render_welcome(on_ready=st.rerun)
        return

    # This full rerun is someone doing something. The watch's fragment reruns
    # never reach this line, which is the point.
    touch()

    st.title("Network Visualiser")
    base = built.nodes if built is not None else load_base_frame(DEMO_NODES_CSV)
    df = load_display_table(frame=base)

    c = coverage_counts(df)                        # same source as the other three
    n = c.needs_review
    _, m = review_counts(base, get_corrections())  # baseline, from the loader's base
    # n = what is left of the backlog, m = what it was at session start. n
    # LEADS, always: D-18 was the header announcing m while both coverage
    # captions reported n, putting two different "need review" figures on one
    # screen. m is suppressed until the first correction, where "131 of 131"
    # would restate itself, and appears as "N of M" after it, so P2.1
    # criterion 5's phrasing survives. review_counts() is untouched.
    counter = f"{len(df)} people · **{n}** need review"
    if n != m:  # count-exempt: guarded, n != m
        counter = f"{len(df)} people · **{n}** of {m} still need review"
    if c.not_classified:
        # A SEPARATE figure beside the backlog, never added to it: these
        # people were never judged, so they are not part of what the user has
        # been asked to review. The reason and the retry sit below, in the
        # notice, so the header stays one line.
        counter += f" · **{pending_clause(c.not_classified, ())}**"
    st.caption(counter)

    # Its own line, not appended to the counter: that line carries every
    # figure on the screen and this is not a figure. Stated here rather than
    # in a tooltip, per the P2.9b record.
    provenance = provenance_line(built)
    if provenance:
        st.caption(provenance)

    # Above take_offer, which can return early: a run that never reaches the
    # fragment stops its timer, and a tab left idle on the offer would never
    # expire. The prompt is for the visitor's own network; the demo's
    # corrections are practice, and "nothing you do to it is saved" is
    # already on the welcome screen.
    if built is not None:
        _session_watch(df)
        render_lifetime_notices(df)

    # Before the notice: the offer supersedes it while it is pending, and a
    # retry started here reruns immediately.
    if built is not None and take_offer(df, built, _retry_handler(built)):
        return

    # Retry only exists for a network this session built. The demo's nodes
    # are all classified, and there is no client behind them to ask again.
    render_notice(
        df,
        on_retry=_retry_handler(built) if built else None,
        source=_build_source(built),
    )

    highlight, match_indices, label_groups = _render_sidebar(df, built)

    # init_chat_state also drops a stale highlight if the table has moved
    # (rule 2 in chat.py). Read BEFORE build_figure, not from the panel's
    # return: the panel is called below the canvas, and by then the figure
    # would already be drawn one pass behind the answer the user is reading.
    init_chat_state(df)
    chat_hits = get_chat_highlight()
    if chat_hits is not None:
        match_indices = chat_hits if match_indices is None else (match_indices & chat_hits)

    canvas_column, chat_column = st.columns(CANVAS_RATIO, gap="large")

    with canvas_column:
        fig = build_figure(df, highlight_index=highlight,
                           match_indices=match_indices, label_groups=label_groups)
        fig.update_layout(height=CANVAS_HEIGHT)  # height belongs in the layout,
        st.plotly_chart(                          # not as a plotly_chart kwarg
            fig, use_container_width=True, config=CANVAS_CONFIG,
        )
        # P2.10: within the canvas column, not across the full width above it.
        # Still after render_session_io, which _render_sidebar calls first: a
        # restore writes this panel's widget keys, and Streamlit forbids that
        # once the widget exists.
        render_enrichment_panel()

    with chat_column:
        # The box and controls render above; the history region comes back so
        # the review queue scrolls at its foot, inside the same region.
        history_region = render_chat_panel(df, history_height=CHAT_HISTORY_HEIGHT)
        with history_region:
            st.divider()
            render_review_queue(df, m)

    st.caption(
        "Occupation groups from the O*NET 30.3 Database (USDOL/ETA), CC BY 4.0. "
        "O*NET\u00ae is a trademark of USDOL/ETA."
    )


if __name__ == "__main__":
    main()


# Zombie-server reset (a recurring diagnostic trap — a stale process on 8501
# serves an old module while the new server runs on another port):
#   Get-Process python, streamlit -ErrorAction SilentlyContinue | Stop-Process -Force
#   streamlit cache clear
#   streamlit run app.py