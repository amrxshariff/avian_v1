"""
tests/test_session.py — D-59: one session store, not three private copies.

session_build.py and welcome.py each held their own `_store()`, agreeing with
each other only because neither had learned anything the other had not. The
guard here is the same shape as tools/check_single_loader.py: a module outside
the one sanctioned place should not be able to reach st.session_state at all,
so a fourth private copy cannot grow back quietly.

Run from the repo root:
    python -m pytest tests/test_session.py -v
"""

from __future__ import annotations

from pathlib import Path

from src.dashboard.session import session_store

SCANNED_DIR = Path("src/dashboard")
SESSION_MODULE = Path("src/dashboard/session.py")

# Each of these owns its OWN keyed overlay (a widget key, a per-session cache),
# read and written directly, never through an injectable store — a different,
# pre-existing pattern from the one D-59 collapses. Out of scope here; each is
# its own defect if it is ever worth centralising.
EXEMPT = {
    Path("src/dashboard/summaries.py"),
    Path("src/dashboard/chat.py"),
    Path("src/dashboard/state.py"),
    Path("src/dashboard/notes.py"),
    Path("src/dashboard/enrich.py"),
    Path("src/dashboard/people_list.py"),
    Path("src/dashboard/session_io.py"),
}


def test_no_module_outside_session_reaches_session_state_directly():
    offenders = []
    for path in sorted(SCANNED_DIR.glob("*.py")):
        if path in EXEMPT or path == SESSION_MODULE:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if "st.session_state" in text or ".session_state" in text:
            offenders.append(str(path))
    assert offenders == [], f"reaches session_state directly: {offenders}"


# --- session_store() itself ---------------------------------------------------


def test_an_injected_dict_is_returned_unchanged():
    store = {"x": 1}
    assert session_store(store) is store


def test_outside_a_runtime_returns_an_empty_dict():
    """Pytest has no Streamlit runtime, so this exercises the real fallback,
    not a mock of it."""
    assert session_store() == {}


def test_two_calls_with_no_store_do_not_share_state():
    """The {} fallback is a fresh dict each time — nothing here persists
    outside a runtime, which is the CLI's actual situation, not a workaround
    for one in tests."""
    a = session_store()
    a["mutated"] = True
    b = session_store()
    assert "mutated" not in b
