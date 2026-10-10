"""
tests/test_summaries.py — P2.7 cluster summaries.

No Streamlit, no network, no API key. The cache dict and the Anthropic client
are injected, so every branch is reachable under plain pytest.

The four DoD criteria map onto tests as:
  generated                  -> test_generates_and_caches
  cached                     -> test_second_call_hits_cache_without_client
  accurate to actual members -> test_prompt_contains_only_member_titles,
                                test_prompt_carries_no_names_or_companies
  regenerates on change      -> test_correction_changes_key_and_regenerates
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.dashboard.state import (
    NOT_OCCUPATION,
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_OCCUPATION,
    apply_corrections,
)
from src.dashboard.summaries import (
    MAX_TOKENS,
    MIN_GROUP_SIZE,
    STATUS_SUMMARY,
    STATUS_TOO_SMALL,
    STATUS_UNAVAILABLE,
    build_prompt,
    cache_key,
    coverage_counts,
    coverage_sentence,
    group_members,
    membership_key,
    summarise_group,
    title_counts,
)


# --- fakes -------------------------------------------------------------------

class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Response:
    def __init__(self, text: str) -> None:
        self.content = [_Block(text)]


class FakeMessages:
    """Records every call so tests can assert on the payload, or on silence."""

    def __init__(self, reply: str = "A group of analysts.", raises: bool = False):
        self.calls: list[dict] = []
        self.reply = reply
        self.raises = raises

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise RuntimeError("simulated API failure")
        return _Response(self.reply)


class FakeClient:
    def __init__(self, reply: str = "A group of analysts.", raises: bool = False):
        self.messages = FakeMessages(reply=reply, raises=raises)

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls


class MalformedClient:
    """Returns a response whose blocks carry no usable text."""

    class _Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)

            class _Empty:
                content = []

            return _Empty()

    def __init__(self):
        self.messages = self._Messages()


# --- fixtures ----------------------------------------------------------------

def _row(person_index, name, role, soc_major, uncertain=False):
    return {
        "person_index": person_index,
        "name": name,
        "role": role,
        "company": f"Company{person_index}",
        "soc_major": soc_major,
        "soc_major_name": "Business and Financial Operations",
        "is_uncertain": uncertain,
    }


@pytest.fixture
def base_df() -> pd.DataFrame:
    """Six in group 13, one in group 15, two needing review."""
    rows = [
        _row(1, "Ada Kowalski", "Financial Analyst", "13"),
        _row(2, "Ben Osei", "Financial Analyst", "13"),
        _row(3, "Cara Lindqvist", "Risk Analyst", "13"),
        _row(4, "Dan Ferreira", "Management Consultant", "13"),
        _row(5, "Eve Nakamura", "Actuarial Graduate", "13"),
        _row(6, "Femi Adeyemi", "Compliance Officer", "13"),
        _row(7, "Gus Halvorsen", "Software Engineer", "15"),
        _row(8, "Hana Brzezinski", "Student Ambassador", "99", True),
        _row(9, "Ivo Petrov", "Member", "99", True),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def display_df(base_df) -> pd.DataFrame:
    return apply_corrections(base_df, {})


# --- membership key ----------------------------------------------------------

def test_membership_key_is_order_independent_and_deduplicated():
    assert membership_key([3, 1, 2]) == membership_key([1, 2, 3])
    assert membership_key([1, 2, 2, 3]) == membership_key([1, 2, 3])


def test_membership_key_changes_when_a_member_is_added_or_removed():
    base = membership_key([1, 2, 3])
    assert membership_key([1, 2, 3, 4]) != base
    assert membership_key([1, 2]) != base


def test_cache_key_is_prefixed_by_group():
    assert cache_key("13", [1, 2]).startswith("13:")


# --- membership predicate ----------------------------------------------------

def test_group_members_excludes_needs_review_and_not_occupation(base_df):
    corrected = apply_corrections(base_df, {8: NOT_OCCUPATION})

    # "99" is a column value, not a group: asking for it must return nothing.
    assert len(group_members(corrected, "99")) == 0
    assert len(group_members(corrected, NOT_OCCUPATION)) == 0
    assert len(group_members(corrected, "13")) == 6


# --- coverage ----------------------------------------------------------------

def test_coverage_counts_split_the_states_and_the_floor(base_df):
    corrected = apply_corrections(base_df, {8: NOT_OCCUPATION})
    c = coverage_counts(corrected)

    # 7 classified, but the lone member of group 15 is below the floor, so only
    # 6 are actually described in prose.
    assert (c.total, c.classified, c.needs_review, c.not_occupation) == (9, 7, 1, 1)
    assert (c.summarised, c.below_floor) == (6, 1)


def test_coverage_sentence_reports_all_three_gaps_separately(base_df):
    corrected = apply_corrections(base_df, {8: NOT_OCCUPATION})
    sentence = coverage_sentence(corrected)

    assert "6 of the 7 classified" in sentence  # summarised of CLASSIFIED, not total
    assert "1 are in groups too small to summarise" in sentence
    assert "1 still need review" in sentence
    assert "1 are marked not an occupation" in sentence


def test_coverage_never_counts_sub_floor_members_as_summarised(base_df):
    """The fault option A fixes: before the floor existed, `classified` was the
    coverage number, so a person in a 1-member group was counted as summarised
    while the panel showed them only a title."""
    df = apply_corrections(base_df, {})
    c = coverage_counts(df)
    assert c.classified == 7
    assert c.summarised == 6
    assert "6 of the 7 classified" in coverage_sentence(df)


def test_sub_floor_member_crossing_the_floor_moves_the_count(base_df):
    """Corrections can push a group over the floor mid-session; the line follows."""
    extras = pd.DataFrame(
        [_row(i, f"Person {i}", "Software Engineer", "15") for i in range(10, 14)]
    )
    wider = pd.concat([base_df, extras], ignore_index=True)

    c = coverage_counts(apply_corrections(wider, {}))
    assert (c.summarised, c.below_floor) == (11, 0)  # group 15 now has 5


def test_coverage_sentence_when_nothing_is_outstanding():
    df = pd.DataFrame(
        [
            {"display_state": STATE_CLASSIFIED, "soc_major": "13"}
            for _ in range(5)
        ]
    )
    assert coverage_sentence(df) == "Summaries cover all 5 connections."


def test_all_classified_but_below_the_floor_is_not_full_coverage():
    df = pd.DataFrame(
        [
            {"display_state": STATE_CLASSIFIED, "soc_major": "13"},
            {"display_state": STATE_CLASSIFIED, "soc_major": "15"},
        ]
    )
    sentence = coverage_sentence(df)
    assert "cover all" not in sentence  # "small" contains "all" — match the phrase
    assert "0 of the 2 classified" in sentence
    assert "2 are in groups too small to summarise" in sentence


# --- title counting ----------------------------------------------------------

def test_title_counts_dedupes_and_orders_by_frequency():
    counted = title_counts(["Analyst", "Analyst", "Zebra Keeper", "Baker"])
    assert counted[0] == ("Analyst", 2)
    assert counted[1:] == [("Baker", 1), ("Zebra Keeper", 1)]


def test_title_counts_respects_the_cap():
    assert len(title_counts([f"Role {i}" for i in range(300)], cap=150)) == 150


# --- the size floor ----------------------------------------------------------

def test_small_group_returns_titles_and_never_calls_the_client(display_df):
    client = FakeClient()
    result = summarise_group(display_df, "15", cache={}, client=client)

    assert result.status == STATUS_TOO_SMALL
    assert result.n_members == 1
    assert result.titles == ("Software Engineer",)
    assert result.text is None
    assert client.calls == []  # the floor is checked before the client


def test_floor_is_five(display_df):
    assert MIN_GROUP_SIZE == 5
    four = display_df[display_df["person_index"].isin([1, 2, 3, 4])]
    assert summarise_group(four, "13", cache={}, client=FakeClient()).status == (
        STATUS_TOO_SMALL
    )


# --- generation and caching --------------------------------------------------

def test_generates_and_caches(display_df):
    cache: dict[str, str] = {}
    client = FakeClient(reply="Mostly analyst-level finance roles.")

    result = summarise_group(display_df, "13", cache=cache, client=client)

    assert result.status == STATUS_SUMMARY
    assert result.text == "Mostly analyst-level finance roles."
    assert result.from_cache is False
    assert cache == {result.cache_key: "Mostly analyst-level finance roles."}
    assert len(client.calls) == 1


def test_second_call_hits_cache_without_client(display_df):
    cache: dict[str, str] = {}
    first_client = FakeClient()
    summarise_group(display_df, "13", cache=cache, client=first_client)

    second_client = FakeClient()
    result = summarise_group(display_df, "13", cache=cache, client=second_client)

    assert result.from_cache is True
    assert second_client.calls == []


def test_correction_changes_key_and_regenerates(base_df):
    """The DoD criterion with teeth: a P2.1 correction must produce a miss."""
    cache: dict[str, str] = {}
    before = apply_corrections(base_df, {})
    first = summarise_group(before, "13", cache=cache, client=FakeClient("Before."))

    # The user resolves a needs-review node INTO group 13.
    after = apply_corrections(base_df, {8: "13"})
    client = FakeClient("After.")
    second = summarise_group(after, "13", cache=cache, client=client)

    assert second.cache_key != first.cache_key
    assert second.from_cache is False
    assert second.text == "After."
    assert len(client.calls) == 1
    assert len(cache) == 2  # the old entry is orphaned, not mutated


def test_correction_into_another_group_leaves_this_group_cached(base_df):
    cache: dict[str, str] = {}
    before = apply_corrections(base_df, {})
    summarise_group(before, "13", cache=cache, client=FakeClient())

    after = apply_corrections(base_df, {8: "15"})  # nothing to do with 13
    client = FakeClient()
    result = summarise_group(after, "13", cache=cache, client=client)

    assert result.from_cache is True
    assert client.calls == []


# --- the prompt payload ------------------------------------------------------

def test_prompt_contains_only_member_titles(display_df):
    client = FakeClient()
    summarise_group(display_df, "13", cache={}, client=client)
    content = client.calls[0]["messages"][0]["content"]

    assert "Financial Analyst" in content
    assert "Software Engineer" not in content  # a member of group 15
    assert "Student Ambassador" not in content  # needs review, no group


def test_prompt_carries_no_names_or_companies(display_df):
    client = FakeClient()
    summarise_group(display_df, "13", cache={}, client=client)
    payload = str(client.calls[0])

    for surname in ["Kowalski", "Osei", "Lindqvist", "Ferreira", "Nakamura"]:
        assert surname not in payload
    assert "Company1" not in payload


def test_prompt_declares_a_sample_when_titles_are_capped():
    counted = [(f"Role {i}", 1) for i in range(150)]
    prompt = build_prompt("Business and Financial Operations", counted, n_members=400)
    assert "sample" in prompt.lower()
    assert "400" in prompt


def test_prompt_does_not_claim_a_sample_when_complete():
    counted = [("Financial Analyst", 4), ("Risk Analyst", 2)]
    prompt = build_prompt("Business and Financial Operations", counted, n_members=6)
    assert "sample" not in prompt.lower()


def test_no_temperature_is_sent(display_df):
    """Regression guard: `temperature` is deprecated for claude-sonnet-5 and
    sending it returns a 400, which then degrades to "unavailable" — a live
    failure that no amount of unit testing of the fallback would have caught."""
    client = FakeClient()
    summarise_group(display_df, "13", cache={}, client=client)
    assert "temperature" not in client.calls[0]


# --- failure degrades, never fabricates --------------------------------------

def test_api_failure_degrades_to_titles_and_is_not_cached(display_df):
    cache: dict[str, str] = {}
    result = summarise_group(display_df, "13", cache=cache, client=FakeClient(raises=True))

    assert result.status == STATUS_UNAVAILABLE
    assert result.text is None
    assert set(result.titles) >= {"Financial Analyst", "Risk Analyst"}
    assert cache == {}  # a retry on the next rerun must be possible


def test_malformed_response_degrades_rather_than_fabricating(display_df):
    result = summarise_group(display_df, "13", cache={}, client=MalformedClient())
    assert result.status == STATUS_UNAVAILABLE
    assert result.text is None


class _TruncatedClient:
    """Text that stops mid-sentence at the ceiling, as a real truncation does."""

    class _Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)

            class _Cut:
                stop_reason = "max_tokens"
                content = [_Block("This group is mostly made up of financial anal")]

            return _Cut()

    def __init__(self):
        self.messages = self._Messages()


def test_truncated_response_is_never_shown_or_cached(display_df):
    """D-45: a response cut off at max_tokens used to be returned as a finished
    summary, so the panel showed a half sentence as if it were complete."""
    cache: dict[str, str] = {}
    result = summarise_group(display_df, "13", cache=cache, client=_TruncatedClient())
    assert result.status == STATUS_UNAVAILABLE
    assert result.text is None
    assert cache == {}


def test_truncated_and_empty_responses_are_logged(display_df, caplog):
    """D-45: both used to return None silently, indistinguishable in the
    terminal from a missing key."""
    with caplog.at_level("WARNING", logger="src.dashboard.summaries"):
        summarise_group(display_df, "13", cache={}, client=_TruncatedClient())
        summarise_group(display_df, "13", cache={}, client=MalformedClient())
    messages = [r.getMessage() for r in caplog.records]
    assert any("cut off at max_tokens" in m for m in messages)
    assert any("had no text" in m for m in messages)


def test_budget_leaves_room_for_thinking(display_df):
    """D-45: D-16 measured 3800 thinking tokens on one call to this model. A
    budget below that can be spent entirely on thinking."""
    client = FakeClient()
    summarise_group(display_df, "13", cache={}, client=client)
    assert client.calls[0]["max_tokens"] == MAX_TOKENS >= 4000


def test_no_client_and_no_key_degrades(display_df, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = summarise_group(display_df, "13", cache={}, client=None)
    assert result.status == STATUS_UNAVAILABLE