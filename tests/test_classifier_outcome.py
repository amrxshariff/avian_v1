"""
tests/test_classifier_outcome.py — P2.9b commit 1: classify_claude_outcome.

classify_claude raises on the first title it cannot answer, which is right for
the command-line chain and wrong for a build serving three consumers: one dead
call would throw away 400 good classifications and the layout with them.

This is the non-raising face. What it must get right:

  * an API error stops the run, and everyone unanswered carries its reason;
  * a single unanswerable title is marked alone, and the rest continues;
  * nothing that failed is ever cached or returned as an abstention (D-42);
  * an exception that is not a service failure propagates, because a bug must
    crash rather than be reported as a busy service.

Run from the repo root:
    python -m pytest tests/test_classifier_outcome.py -v
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from src import claude_classifier as cc
from src.failure_reasons import (
    REASON_KEY_FAILED,
    REASON_SERVICE_BUSY,
    REASON_UNANSWERABLE,
)


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Resp:
    content: list
    stop_reason: str = "end_turn"


class RateLimitError(RuntimeError):
    """Named as the SDK names it; _reason_for matches on the name."""
    status_code = 429


class AuthenticationError(RuntimeError):
    status_code = 401


class _LowCredit(RuntimeError):
    """The SDK reports an empty balance as a 400 with this wording."""
    status_code = 400

    def __str__(self) -> str:
        return "Your credit balance is too low to access the Anthropic API"


@dataclass
class _Client:
    """Answers batches, optionally failing at a chosen call.

    `max_ok` mirrors the real budget ceiling: a batch larger than this comes
    back truncated, which the splitter handles. `fail_at` raises `error` on
    that call (1-based), `unanswerable` never answers those titles at all.
    """

    max_ok: int = 20
    calls: list = field(default_factory=list)
    titles_sent: list = field(default_factory=list)
    fail_at: int | None = None
    error: Exception | None = None
    unanswerable: frozenset = frozenset()

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, system, messages):
        content = messages[0]["content"]
        titles = [line.split("title: ", 1)[1].split(" | ")[0].strip()
                  for line in content.splitlines() if "title: " in line]
        self.calls.append(len(titles))
        self.titles_sent.append(titles)

        if self.fail_at is not None and len(self.calls) == self.fail_at:
            raise self.error or RateLimitError("slow down")

        if len(titles) > self.max_ok:
            return _Resp([_Block("")], stop_reason="max_tokens")
        if any(t in self.unanswerable for t in titles):
            return _Resp([_Block("")], stop_reason="max_tokens")

        objs = [{"i": i, "soc": "13", "confidence": "high", "why": "ok"}
                for i in range(len(titles))]
        return _Resp([_Block(json.dumps(objs))])


def items(n, start=0):
    return [(f"Title {i}", "") for i in range(start, start + n)]


def _run(client, n, tmp_path, **kw):
    return cc.classify_claude_outcome(
        items(n), client=client, cache_path=tmp_path / "c.json", **kw
    )


# --- the happy path ----------------------------------------------------------


def test_a_clean_run_is_complete(tmp_path):
    out = _run(_Client(), 40, tmp_path, batch_size=20)
    assert out.complete
    assert out.failures == {}
    assert all(c is not None and c.tier == "claude" for c in out.answers)


def test_cached_titles_are_not_sent_again(tmp_path):
    path = tmp_path / "c.json"
    first = _Client()
    cc.classify_claude_outcome(items(5), client=first, cache_path=path)
    second = _Client()
    out = cc.classify_claude_outcome(items(5), client=second, cache_path=path)
    assert out.complete and second.calls == []


# --- an API error stops the run ---------------------------------------------


def test_a_rate_limit_stops_the_run_and_accounts_for_everyone(tmp_path):
    client = _Client(fail_at=2, error=RateLimitError("slow down"))
    out = _run(client, 60, tmp_path, batch_size=20)

    assert not out.complete
    assert client.calls == [20, 20]               # no third batch was attempted
    assert sorted(out.failures) == list(range(20, 60))
    assert set(out.reasons) == {REASON_SERVICE_BUSY}
    # The first batch survives: a partial run keeps what it paid for.
    assert all(out.answers[i] is not None for i in range(20))
    assert all(out.answers[i] is None for i in range(20, 60))


def test_a_dead_key_is_its_own_reason(tmp_path):
    out = _run(_Client(fail_at=1, error=AuthenticationError("bad key")), 10, tmp_path)
    assert set(out.reasons) == {REASON_KEY_FAILED}


def test_an_empty_balance_reads_as_a_key_failure_not_a_busy_service(tmp_path):
    """The SDK reports it as a 400, which would otherwise look like nothing."""
    out = _run(_Client(fail_at=1, error=_LowCredit()), 10, tmp_path)
    assert set(out.reasons) == {REASON_KEY_FAILED}


def test_a_bug_crashes_rather_than_becoming_a_reason(tmp_path):
    """Reporting a TypeError as 'the service was busy' would hide a defect."""
    with pytest.raises(TypeError):
        _run(_Client(fail_at=1, error=TypeError("bad argument")), 10, tmp_path)


# --- one unanswerable title --------------------------------------------------


def test_one_unanswerable_title_does_not_stop_the_batch(tmp_path):
    client = _Client(unanswerable=frozenset({"Title 3"}))
    out = _run(client, 8, tmp_path)

    assert out.failures == {3: REASON_UNANSWERABLE}
    assert out.answers[3] is None
    assert all(out.answers[i] is not None for i in (0, 1, 2, 4, 5, 6, 7))


def test_a_failed_title_is_never_cached_or_abstained(tmp_path):
    """D-42: an abstention is an answer; this is the absence of one."""
    path = tmp_path / "c.json"
    cc.classify_claude_outcome(
        items(4), client=_Client(unanswerable=frozenset({"Title 1"})),
        cache_path=path,
    )
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert "title 1||" not in cache
    assert len(cache) == 3
    assert not [k for k, v in cache.items() if v.get("why") == "unparsed"]


def test_successes_before_a_failure_are_still_cached(tmp_path):
    path = tmp_path / "c.json"
    cc.classify_claude_outcome(
        items(40), client=_Client(fail_at=2, error=RateLimitError("slow")),
        cache_path=path, batch_size=20,
    )
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 20


# --- the two faces agree -----------------------------------------------------


def test_the_raising_path_still_raises(tmp_path):
    """classify_claude is unchanged for the command-line chain."""
    with pytest.raises(cc.ClassificationFailed):
        cc.classify_claude(
            items(4), client=_Client(unanswerable=frozenset({"Title 2"})),
            cache_path=tmp_path / "c.json",
        )


def test_both_paths_answer_identically_when_nothing_fails(tmp_path):
    raising = cc.classify_claude(
        items(6), client=_Client(), cache_path=tmp_path / "a.json"
    )
    reporting = cc.classify_claude_outcome(
        items(6), client=_Client(), cache_path=tmp_path / "b.json"
    )
    assert [c.soc_major for c in raising] == [
        c.soc_major for c in reporting.answers
    ]
