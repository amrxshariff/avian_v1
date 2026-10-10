"""
src/dashboard/key_field.py — where a visitor hands over their own API key.

Session-only, by decision: held in memory, never written to disk, never logged,
redacted from anything displayed, gone when the tab closes. The field says so
itself rather than burying it in a privacy note, and links to the source,
because a public page asking a stranger for an API key otherwise looks exactly
like phishing.

Validated on paste rather than at the next build. A key that cannot pay should
say so while the person is still looking at the field, not five seconds into a
build they thought had started. check_key() memoises on a fingerprint, so a
rerun costs nothing.

One component, two call sites: the welcome screen and the sidebar both reach it
through render_upload_panel.
"""

from __future__ import annotations

from typing import Callable, Optional

from src.dashboard.keys import (
    KEY_MESSAGES,
    KEY_VALID,
    check_key,
    forget_key,
    session_key,
)
from src.dashboard.session import session_store

FIELD_SLOT = "api_key_field"
NOTICE_SLOT = "api_key_notice"

CONSOLE_URL = "https://console.anthropic.com/settings/keys"
SOURCE_URL = "https://github.com/amrxshariff/network-visualiser"

LABEL = "Your Anthropic API key (optional)"

HELP = (
    "Used only to classify the network you just uploaded. Held in memory for "
    "this session, never saved, never logged, and gone when you close the tab. "
    f"[Read the code that handles it]({SOURCE_URL})."
)

HELD_NOTE = "Key held for this session. It is not saved anywhere."


def _paste_handler(store: Optional[dict], on_validated: Optional[Callable]) -> Callable:
    """Validate what was pasted, once, and record a notice for the rerun.

    A callback rather than a post-widget read: Streamlit forbids writing a
    widget key once its widget exists, and four bugs across P2.8c and P2.8d
    were variants of that rule.
    """

    def handler() -> None:
        s = session_store(store)
        typed = (s.get(FIELD_SLOT) or "").strip()

        if not typed:
            forget_key(store)
            s.pop(NOTICE_SLOT, None)
            return

        outcome = check_key(typed, store=store)
        s[NOTICE_SLOT] = outcome

        if outcome == KEY_VALID:
            # The field is cleared deliberately. The key is held in the store;
            # leaving it on screen means a visitor's key sits visible in a
            # password field they may not remember is there.
            s[FIELD_SLOT] = ""
            # Only when there is something to offer. A key pasted before an
            # upload has nothing to classify, and a prompt about a network
            # that does not exist is noise on the first screen.
            from src.dashboard.retry_offer import offer_retry
            from src.dashboard.session_build import get_built

            if get_built(store) is not None:
                offer_retry(store)
            if on_validated is not None:
                on_validated()

    return handler


def _forget_handler(store: Optional[dict]) -> Callable:
    def handler() -> None:
        forget_key(store)
        s = session_store(store)
        s[FIELD_SLOT] = ""
        s.pop(NOTICE_SLOT, None)

    return handler


def render_key_field(
    *,
    st=None,
    store: Optional[dict] = None,
    on_validated: Optional[Callable] = None,
) -> None:
    """Draw the key field, its verdict, and the way to take the key back.

    `on_validated` is passed by no production caller. It survives because a
    caller might legitimately need to act on a validated key — but it runs
    inside Streamlit's on_change callback, so it must not call st.rerun():
    a callback already triggers one, and rerunning from within it is a no-op
    that prints a warning on screen (D-67). Anything that does not touch
    control flow is fine.
    """
    if st is None:
        import streamlit as st  # noqa: PLC0415 — lazy, as everywhere in dashboard/

    held = session_key(store)

    if held:
        st.success(HELD_NOTE)
        st.button(
            "Forget my key",
            key="forget_key",
            on_click=_forget_handler(store),
        )
        return

    st.text_input(
        LABEL,
        key=FIELD_SLOT,
        type="password",
        help=HELP,
        placeholder="sk-ant-...",
        on_change=_paste_handler(store, on_validated),
    )

    notice = session_store(store).get(NOTICE_SLOT)
    if notice and notice != KEY_VALID:
        st.warning(KEY_MESSAGES[notice])

    st.caption(f"No key? [Create one at console.anthropic.com]({CONSOLE_URL}).")
