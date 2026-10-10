"""
tests/test_api_guard.py — the conftest guard refuses a real send (D-74).

The guard is only as good as the route it covers, so this sends through a
route that hides failures: the chat, which catches Exception around the call
and returns "unavailable". A refusal it could catch would turn into a
degraded answer, and the test asking would pass.
"""

from __future__ import annotations

import pytest

from src.assistant import answer_question
from tests.conftest import RealAPICallRefused
from tests.test_assistant import make_df


def test_a_real_send_is_refused_even_inside_a_broad_handler(_refuse_real_api, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")

    with pytest.raises(RealAPICallRefused):
        answer_question(make_df(), "who works in finance?", client=None)

    assert _refuse_real_api == ["Anthropic"]
    _refuse_real_api.clear()          # recorded on purpose; not a failure
