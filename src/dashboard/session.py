"""
src/dashboard/session.py — the session store, and the one guard on reaching it.

Three modules held a private copy of this (D-59). They agreed until the key
field needed a fourth, by which point one of them had to learn that the chain
modules also run from the command line, where there is no Streamlit runtime and
st.session_state does not behave.

An injected dict is the test path. A missing runtime returns an empty dict
rather than raising: a CLI run has no session key, which is a fact about the
run, not an error in it.
"""

from __future__ import annotations

from typing import Any, Optional


def session_store(store: Optional[dict] = None) -> Any:
    """The session store, an injected dict, or {} outside a Streamlit run."""
    if store is not None:
        return store

    try:
        import streamlit as st

        if st.runtime.exists():
            return st.session_state
    except Exception:  # noqa: BLE001 — no runtime is not an error here
        pass
    return {}
