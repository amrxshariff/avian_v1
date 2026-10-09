"""
tests/test_app_smoke.py — D-66: app.py boots, under Streamlit's own rules.

Every other test of the dashboard hands a module a fake `st`. The fakes are
right to exist, but they enforce none of Streamlit's layout rules: a fake
expander is a null context manager, so an expander inside an expander passed
621 tests while the real dashboard raised on every run past the welcome
screen. The thing asserting correctness was not the thing that runs.

These run app.py itself through AppTest — the real element tree, the real
StreamlitAPIException — once for each screen a visitor can reach, and assert
that nothing raised. Not a behaviour test; the guard under the others. The
key-paste runs (D-67) also assert that no warning reached the page, because
some of Streamlit's rules are enforced with a warning rather than an error.

Run from the repo root:
    python -m pytest tests/test_app_smoke.py -v
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

import src.dashboard.keys as keys
from src.build import build_network
from src.dashboard.key_field import FIELD_SLOT
from src.dashboard.keys import KEY_VALID, USER_KEY_SLOT
from src.dashboard.session_build import BUILT_KEY
from src.dashboard.welcome import DEMO_KEY
from tests.test_build import _embed, _people, _project

# The first run imports the whole dashboard, sentence-transformers included.
TIMEOUT = 120


@pytest.fixture(autouse=True)
def _no_key(monkeypatch):
    """D-62: a smoke run must not depend on the developer's shell, and must
    never reach the API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _boot(**state) -> AppTest:
    at = AppTest.from_file("app.py", default_timeout=TIMEOUT)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def _raised(at: AppTest) -> list[str]:
    return [e.value for e in at.exception]


def test_the_welcome_screen_renders():
    at = _boot()
    assert _raised(at) == []


def test_the_demo_dashboard_renders():
    at = _boot(**{DEMO_KEY: True})
    assert _raised(at) == []


def test_a_built_network_renders():
    built = build_network(people=_people(30), classify=False,
                          embed=_embed, project=_project)
    at = _boot(**{BUILT_KEY: built})
    assert _raised(at) == []


# --- D-67: pasting a key -----------------------------------------------------
#
# The key field validates inside an on_change callback. A callback already
# causes a rerun; st.rerun() called inside one is a no-op that renders
# "Calling st.rerun() within a callback is a no-op." as a warning on the page.
# A fake st cannot reproduce that — it is runtime behaviour — so only these
# runs guard it.


@pytest.fixture
def _key_accepted(monkeypatch):
    """The real check_key and handler, with only the API call replaced."""
    monkeypatch.setattr(keys, "validate_key", lambda key, client=None: KEY_VALID)


def _paste(at: AppTest) -> AppTest:
    at.text_input(key=FIELD_SLOT).input("sk-ant-api03-test").run()
    return at


def test_pasting_a_valid_key_on_the_welcome_screen_leaves_no_warning(_key_accepted):
    """The path a first-time visitor takes, and the one with no other cover."""
    at = _paste(_boot())
    assert _raised(at) == []
    assert [w.value for w in at.warning] == []
    assert at.session_state[USER_KEY_SLOT] == "sk-ant-api03-test"


def test_pasting_a_valid_key_in_the_sidebar_leaves_no_warning(_key_accepted):
    built = build_network(people=_people(30), classify=False,
                          embed=_embed, project=_project)
    at = _paste(_boot(**{BUILT_KEY: built}))
    assert _raised(at) == []
    assert [w.value for w in at.sidebar.warning] == []
    assert [w.value for w in at.warning] == []
