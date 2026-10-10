"""
tests/test_canvas_layout.py — P2.10.1 and P2.10.2, as far as Python can see them.

Scroll-to-zoom is back on, and the chat column is a panel with its own scroll,
so the page no longer grows below the canvas. Whether the wheel and the panel
actually behave is browser behaviour, and gets a written verdict from a browser
session (P2.10's risk note). What these pin is the structure a refactor could
silently undo: the chart's config, which column each panel sits in, and the
fixed-height panel the chat and the review queue scroll inside.
"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

import app
from src.dashboard.welcome import DEMO_KEY


@pytest.fixture
def demo(monkeypatch) -> AppTest:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file("app.py", default_timeout=60)
    at.session_state[DEMO_KEY] = True
    return at.run()


def _chains(at: AppTest) -> dict:
    """For each element of interest, the blocks enclosing it, outermost first."""
    found: dict = {}

    def walk(node, chain):
        kids = getattr(node, "children", None)
        if isinstance(kids, dict):
            for child in kids.values():
                kind, label = getattr(child, "type", None), getattr(child, "label", None)
                if kind == "plotly_chart":
                    found["chart"] = chain
                elif kind == "expander" and label == "Your profile":
                    found["profile"] = chain
                elif kind == "text_area" and str(label).startswith("Ask about your network"):
                    found["chat"] = chain
                elif kind == "expander" and str(label).startswith("What is sent"):
                    found["controls"] = chain
                elif kind == "subheader" and getattr(child, "value", "") == "Review queue":
                    found["queue"] = chain
                walk(child, chain + [child])

    walk(at._tree, [])
    return found


def _column(chain):
    return next(b for b in reversed(chain) if type(b).__name__ == "Column")


def test_the_wheel_zooms_the_canvas(demo):
    """P2.10.1: re-enabled, after P2.8c turned it off (7923f88)."""
    assert not demo.exception
    assert '"scrollZoom": true' in demo.get("plotly_chart")[0].proto.config


def _fixed_heights(chain) -> list[int]:
    return [b.proto.vertical.height for b in chain
            if type(b).__name__ == "Block" and b.proto.HasField("vertical")
            and b.proto.vertical.height]


def test_the_box_history_and_queue_scroll_together_in_one_region(demo):
    """P2.10.2 and .3: the review queue scrolls inside a fixed-height region
    instead of extending the page, which keeps the canvas in place. The question
    box and the panel's controls scroll in the same region, at its top: with the
    box outside it, an answer to a question asked while scrolled down landed out
    of view (verdict 8)."""
    chains = _chains(demo)
    for part in ("queue", "chat", "controls"):
        assert app.CHAT_HISTORY_HEIGHT in _fixed_heights(chains[part]), part
    assert _column(chains["queue"]) is _column(chains["chat"])


def test_the_profile_panel_sits_in_the_canvas_column(demo):
    """P2.10: no longer across the full width above the canvas."""
    chains = _chains(demo)
    assert _column(chains["profile"]) is _column(chains["chart"])
    assert _column(chains["chat"]) is not _column(chains["chart"])


def test_the_canvas_takes_two_thirds_and_nothing_pins_it_with_css(demo):
    """The sticky-CSS attempt left a stale canvas from an earlier run on the
    page. The panel layout needs no positioning CSS, and none should return."""
    assert app.CANVAS_RATIO == (2, 1)
    assert not [m for m in demo.markdown if "position: sticky" in m.value]
