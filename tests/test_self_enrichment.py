"""
tests/test_self_enrichment.py — P2.2 pure-function tests.

Runs under plain pytest: no Streamlit runtime, no ANTHROPIC_API_KEY, no network.
Everything exercised here is pure, which is the point of having split the module
that way — the parts that need a live model are covered separately by
tools/test_injection_rule7.py.

The comparison's wording (describe_comparison, its caveats, Comparison.agree)
is withdrawn with the comparison itself (D-84), and its tests with it. The
confidence gate survives: the panel's reading_lines() words a confident
abstention ("names no current occupation") differently from "could not tell",
through enrich._is_confident, and that distinction still ships.
"""

from __future__ import annotations

import types

import pytest

from src.claude_classifier import CONFIDENCE_SCORES, MIN_CONFIDENCE, ClassificationFailed
from src.onet import Classification
from src.dashboard.enrich import _is_confident
from src.self_enrichment import (
    MIN_ABOUT_CHARS,
    TIER_SELF_ENRICHED,
    _build_user_message,
    classify_from_about,
)

GATE = CONFIDENCE_SCORES[MIN_CONFIDENCE]


def make(soc_major: str | None, score: float, tier: str | None = None) -> Classification:
    """A Classification with only the fields these functions read.

    soc_code stays None throughout: config E returns 2-digit major groups only,
    so a detailed code here would misrepresent what this path produces.
    """
    if tier is None:
        tier = TIER_SELF_ENRICHED if soc_major else "abstain"
    return Classification(
        query="analyst",
        soc_code=None,
        soc_major=soc_major,
        occupation=None,
        tier=tier,
        score=score,
        n_candidates=1 if soc_major else 0,
        major_agreement=1.0 if soc_major else 0.0,
    )


CONFIDENT_NULL = make(None, CONFIDENCE_SCORES["high"])
UNSURE_NULL = make(None, CONFIDENCE_SCORES["low"])
GROUP_13 = make("13", CONFIDENCE_SCORES["high"])
GROUP_15 = make("15", CONFIDENCE_SCORES["high"])


# --- _is_confident: the gate boundary ----------------------------------------

def test_is_confident_at_the_gate_exactly():
    """The gate is >=, so a score landing exactly on it counts as confident.

    Pinned because an off-by-one here silently changes which answers reach the
    user, and the boundary is the value MIN_CONFIDENCE names.
    """
    assert _is_confident(make(None, GATE))


def test_is_confident_just_below_the_gate():
    assert not _is_confident(make(None, GATE - 0.01))


def test_is_confident_just_above_the_gate():
    assert _is_confident(make(None, GATE + 0.01))


# --- input guard -------------------------------------------------------------

def test_short_about_raises_before_any_client_is_built():
    """No API key is set in the test environment, so this passing at all proves
    the length guard runs BEFORE _default_client() is reached.

    That ordering is the assertion. If a refactor moved client construction
    above the guard, this test would fail with RuntimeError rather than
    ValueError — which is exactly the signal wanted.
    """
    with pytest.raises(ValueError, match="characters"):
        classify_from_about("Analyst", "too short")


def test_whitespace_only_about_raises():
    with pytest.raises(ValueError):
        classify_from_about("Analyst", "   \n\t  ")


def test_about_at_the_minimum_length_passes_the_guard():
    """One character under the minimum is rejected; the guard is on length, not
    on content, so a string of the right size must clear it and fail later at
    the client instead."""
    with pytest.raises(ValueError):
        classify_from_about("Analyst", "x" * (MIN_ABOUT_CHARS - 1))


# --- failed calls are failures, not abstentions (D-46) -----------------------

ABOUT = "I audit client accounts at a Big 4 firm and run fieldwork teams."


def _client(text: str, stop: str = "end_turn"):
    content = [types.SimpleNamespace(type="text", text=text)] if text else []
    response = types.SimpleNamespace(stop_reason=stop, content=content)
    return types.SimpleNamespace(messages=types.SimpleNamespace(create=lambda **kw: response))


def test_truncated_reply_raises_rather_than_abstaining():
    """D-46: a reply cut off at max_tokens used to become tier='abstain', and
    describe_comparison then told the user their description left the
    classifier unsure."""
    cut = _client('[{"i": 0, "soc": "13", "confid', stop="max_tokens")
    with pytest.raises(ClassificationFailed):
        classify_from_about("Auditor", ABOUT, client=cut)


def test_unparseable_reply_raises_rather_than_abstaining():
    with pytest.raises(ClassificationFailed):
        classify_from_about("Auditor", ABOUT, client=_client("I think this is audit."))


def test_empty_reply_raises_rather_than_abstaining():
    with pytest.raises(ClassificationFailed):
        classify_from_about("Auditor", ABOUT, client=_client(""))


def test_a_confident_null_is_still_an_answer():
    """The distinction D-46 protects runs both ways: a well-formed null is the
    model declining, and must stay an abstain, not become a failure."""
    reply = '[{"i": 0, "soc": null, "confidence": "high", "why": "student, no job"}]'
    c = classify_from_about("Student", ABOUT, client=_client(reply))
    assert c.soc_major is None and c.tier == "abstain"
    assert _is_confident(c)


# --- prompt construction: rule 7's mechanism ---------------------------------

def test_user_message_delimits_both_fields():
    """The <<<>>> boundaries are what make 'this text is data' enforceable.

    tools/test_injection_rule7.py proves they work against a live model, but
    only when someone remembers to run it. This fails immediately in CI if a
    refactor drops them.
    """
    message = _build_user_message("Financial Analyst", "I build valuation models.")
    assert message.count("<<<") == 2
    assert message.count(">>>") == 2
    assert "<<<Financial Analyst>>>" in message


def test_user_message_marks_a_missing_title():
    """An empty title must be labelled, not silently blank: an empty pair of
    delimiters would leave the model guessing whether the field was omitted or
    the person genuinely has no title."""
    message = _build_user_message("", "I build valuation models.")
    assert "(not given)" in message