"""
src/dashboard/welcome.py — P2.9: what a new visitor sees first.

The dashboard opens on a network, which is right for someone who already has
one and wrong for everyone else: a stranger's connections, a review queue, and
a chat box, with nothing saying what any of it is. This is the screen before
that one.

It asks for one decision and offers two answers: build from your own export, or
look at the example first. Both lead to the same dashboard.

The example network is shown as an EXAMPLE, never as "yours". P2.9 replaces the
file behind it with synthetic data before the public deploy; until then the
wording here is the only thing stopping a visitor reading someone else's
connections as their own.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.dashboard.session import session_store
from src.dashboard.provenance import load_demo_provenance

# Session key, not a build: choosing the example means "show me the dashboard",
# and the dashboard falls back to the demo table whenever no build exists.
DEMO_KEY = "using_demo"

HEADLINE = "See who is actually in your LinkedIn network"

WHAT_IT_DOES = """
Your connections export is a list of names and job titles. This turns it into a
map:

- **Grouped by what people do**, using the US Bureau of Labor Statistics'
  occupation groups, not by job title wording.
- **Placed by similarity**, so people doing related work sit near each other.
- **Ask questions about it** in plain English, answered only from your own data.
- **Correct anything that is wrong.** The classifier abstains rather than
  guessing, and you get the final say on every person.
"""

PRIVACY = (
    "Your export is read in memory and never saved. It is gone when you close "
    "the tab, and dropped after an hour of inactivity. Nothing is sent "
    "anywhere unless you add an API key and ask for classification."
)

# Shown once, above the headline, after lifetime.expire_if_stale dropped the
# session. Not a silent return to the start: someone who left a network open
# and came back to this screen would otherwise think it had broken. "If": the
# app cannot know a download completed, so it does not assume one.
EXPIRED_NOTE = (
    "Your session ended after an hour of inactivity, and the network was "
    "dropped with your corrections, notes and API key. If you downloaded your "
    "work, upload your export again, then restore it from the sidebar."
)

NO_KEY_NOTE = (
    "No API key needed to start: your network is built and placed without one. "
    "Groups arrive later, when you add a key."
)


def using_demo(store: Optional[dict] = None) -> bool:
    """True once the visitor has chosen to look at the example."""
    return bool(session_store(store).get(DEMO_KEY))


def choose_demo(store: Optional[dict] = None) -> None:
    session_store(store)[DEMO_KEY] = True


def start_over(store: Optional[dict] = None) -> None:
    """Forget the current network and the demo choice, back to the welcome.

    Both must clear together. Clearing only the flag would send someone with a
    built network to a welcome screen they cannot leave except by uploading
    again; clearing only the build would drop them into the demo.
    """
    from src.dashboard.session_build import clear_built

    clear_built(store)
    session_store(store).pop(DEMO_KEY, None)


def should_welcome(built, store: Optional[dict] = None) -> bool:
    """Show the welcome screen only to someone who has done neither thing.

    A built network is the strongest possible signal that they are past this
    screen, so it is checked first and no flag can override it.
    """
    return built is None and not using_demo(store)


def demo_caption(provenance: Optional[dict] = None) -> str:
    """What the example network is, with its size read rather than asserted.

    D-58: this said "442 people" as a literal. Correct at the time, and
    carrying no provenance — regenerating the synthetic export at another
    size would have left the screen stating the old figure with nothing
    failing. 442 is also the real network's size, because the demo was
    generated to match it, so a reader could not tell which network the
    number described.

    The count is dropped rather than guessed when the file cannot be read.
    A network described without its size is honest; one described with the
    wrong size is the failure this whole module is written against.
    """
    if provenance is None:
        provenance = load_demo_provenance()
    people = provenance.get("people")

    # bool is an int subclass; `true` is not a headcount.
    counted = isinstance(people, int) and not isinstance(people, bool)
    size = f" of {people:,} people" if counted else ""
    return (
        f"A ready-made network{size}. Nothing in it is yours, and nothing "
        "you do to it is saved."
    )


def render_welcome(
    *,
    st=None,
    store: Optional[dict] = None,
    build_fn: Optional[Callable] = None,
    on_ready: Optional[Callable] = None,
) -> None:
    """Draw the first-run screen. Either route ends by calling `on_ready`.

    The uploader is the same component the sidebar uses, rather than a second
    one written for this page: two uploaders would be two sets of error
    messages, and they would drift.
    """
    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    from src.dashboard.upload import render_upload_panel

    from src.dashboard.lifetime import take_expired

    st.title("Network Visualiser")
    if take_expired(store):
        st.warning(EXPIRED_NOTE)
    st.subheader(HEADLINE)
    st.markdown(WHAT_IT_DOES)

    st.divider()
    st.markdown("#### Start with your own network")
    st.caption(NO_KEY_NOTE)
    # on_key is deliberately not passed: on_ready is st.rerun, and the key
    # field validates inside a callback, which reruns anyway (D-67). The
    # screen still redraws with the key held; it just does not ask twice.
    render_upload_panel(st=st, store=store, build_fn=build_fn,
                        on_built=on_ready)
    st.caption(PRIVACY)

    st.divider()
    st.markdown("#### Or look around an example first")
    st.caption(demo_caption())
    if st.button("Explore the example network", key="choose_demo"):
        choose_demo(store)
        if on_ready is not None:
            on_ready()
