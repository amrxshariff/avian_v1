"""
tests/test_welcome.py — P2.9: the first screen, and who sees it.

The dashboard opens on a network. For a visitor who has not supplied one, that
is a stranger's connections with no explanation, so the gate matters as much as
the copy:

  * a new visitor sees the welcome screen;
  * anyone who has built or chosen the example does not, ever again;
  * both routes lead to the dashboard through the same signal.

The copy is tested where it makes a PROMISE — that no key is needed, that the
file is not saved, and that the example is an example rather than the
visitor's own network.

Run from the repo root:
    python -m pytest tests/test_welcome.py -v
"""

from __future__ import annotations

import pytest

from src.build import build_network
from src.dashboard.session_build import BUILT_KEY
from src.dashboard.welcome import (
    DEMO_KEY,
    choose_demo,
    demo_caption,
    render_welcome,
    should_welcome,
    using_demo,
)
from tests.test_build import _embed, _people, _project
from tests.test_upload import FakeStreamlit, _Upload, _csv


class WelcomeStreamlit(FakeStreamlit):
    """The upload panel's fake, plus the few things a page needs."""

    def __init__(self, upload=None, click=False):
        super().__init__(upload=upload, click=click)
        self.blocks: list[str] = []

    def title(self, text): self.blocks.append(text)
    def subheader(self, text): self.blocks.append(text)
    def markdown(self, text): self.blocks.append(text)
    def divider(self): pass

    @property
    def text(self) -> str:
        return " ".join(self.blocks + self.captions + self.successes).lower()


def _built():
    return build_network(people=_people(10), classify=False,
                         embed=_embed, project=_project)


# --- the gate ----------------------------------------------------------------


def test_a_new_visitor_sees_the_welcome():
    assert should_welcome(None, {})


def test_someone_with_a_network_never_sees_it():
    """A build is the strongest signal there is; no flag can override it."""
    assert not should_welcome(_built(), {})
    assert not should_welcome(_built(), {DEMO_KEY: False})


def test_choosing_the_example_dismisses_it():
    store: dict = {}
    assert not using_demo(store)
    choose_demo(store)
    assert using_demo(store)
    assert not should_welcome(None, store)


def test_the_example_button_records_the_choice_and_moves_on():
    store: dict = {}
    moved = []
    st = WelcomeStreamlit(click=True)

    render_welcome(st=st, store=store, on_ready=lambda: moved.append(1))
    assert store == {DEMO_KEY: True}
    assert moved == [1]


def test_uploading_from_the_welcome_screen_builds_and_moves_on(monkeypatch):
    """Keyless, as a first visit is: moving on does not depend on
    classification. With a key in the shell this reached the real API
    (D-74)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store: dict = {}
    moved = []
    st = WelcomeStreamlit(upload=_Upload(_csv(12)))

    render_welcome(
        st=st, store=store, on_ready=lambda: moved.append(1),
        build_fn=lambda src, **kw: build_network(
            src, embed=_embed, project=_project, **kw
        ),
    )
    assert store[BUILT_KEY].people == 12
    assert moved == [1]
    assert not should_welcome(store[BUILT_KEY], store)


def test_start_over_clears_both_the_build_and_the_choice():
    """Clearing one without the other strands the user on the wrong screen."""
    from src.dashboard.welcome import start_over

    store = {BUILT_KEY: _built(), DEMO_KEY: True}
    start_over(store)
    assert store == {}
    assert should_welcome(None, store)


# --- what the screen promises ------------------------------------------------


def test_it_says_no_key_is_needed_to_start():
    st = WelcomeStreamlit()
    render_welcome(st=st, store={})
    assert "no api key needed" in st.text


def test_it_says_the_file_is_not_saved():
    st = WelcomeStreamlit()
    render_welcome(st=st, store={})
    assert "never saved" in st.text


def test_the_example_is_offered_as_an_example_not_as_theirs():
    """Until P2.9 swaps in synthetic data, this wording is the only guard."""
    st = WelcomeStreamlit()
    render_welcome(st=st, store={})
    assert "nothing in it is yours" in st.text


def test_it_explains_what_the_tool_does_before_asking_for_anything():
    st = WelcomeStreamlit()
    render_welcome(st=st, store={})
    for promise in ("occupation", "similarity", "correct"):
        assert promise in st.text


# --- the example's size (D-58) -----------------------------------------------

def test_the_caption_takes_its_count_from_provenance():
    assert "a ready-made network of 1,234 people." in demo_caption(
        {"people": 1234}).lower()


def test_a_missing_count_drops_the_size_rather_than_guessing():
    for provenance in ({}, {"model": "claude-sonnet-5"}):
        caption = demo_caption(provenance)
        assert caption.startswith("A ready-made network. ")
        assert "people" not in caption


def test_a_non_integer_count_drops_the_size():
    for people in ("442", 442.0, None, True):
        caption = demo_caption({"people": people})
        assert caption.startswith("A ready-made network. "), people
