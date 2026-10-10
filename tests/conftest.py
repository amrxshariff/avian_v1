"""
tests/conftest.py — suite-wide guards.
"""

from __future__ import annotations

import hashlib

import pytest

import src.claude_classifier as cc

# Captured at import, before any fixture can redirect it: this is the file the
# backstop below watches.
_REAL_CACHE = cc.CACHE_PATH


def _digest(path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


@pytest.fixture(autouse=True)
def _isolate_classification_cache(tmp_path, monkeypatch):
    """No test reaches the real classification cache (D-64).

    A test that classifies without an injected cache_path writes to
    data/cache/claude_classification.json. One did, in the P2.9b slice 3 batch,
    and left a fabricated answer for a title that does not exist — D-42's
    failure mode by a different route, with nothing failing and a dirty
    git status as the only signal.

    Autouse so the safe path is the default. A test that genuinely needs the
    real cache must undo this deliberately, rather than get it by forgetting.

    This works only because claude_classifier resolves CACHE_PATH at call
    time (_resolve_cache). A default argument bound at import would ignore
    the patch entirely.
    """
    monkeypatch.setattr(cc, "CACHE_PATH", tmp_path / "classification.json")


@pytest.fixture(autouse=True)
def _isolate_spend_ledger(tmp_path, monkeypatch):
    """No test writes the real daily ledger (D-81).

    The upload panel and the retry handler construct a DailyLedger on the
    project key. Before this fixture existed, the first suite run after that
    wiring created data/spend/daily.json and counted four networks in it. Same
    shape as the classification cache in D-64, and the same remedy: DailyLedger
    reads spend.LEDGER_PATH when it is constructed, so one patch redirects
    every ledger a test creates.
    """
    import src.spend as spend

    monkeypatch.setattr(spend, "LEDGER_PATH", tmp_path / "spend" / "daily.json")


@pytest.fixture(autouse=True, scope="session")
def _real_ledger_untouched():
    """Fail the run if the real ledger changed anyway."""
    import src.spend as spend

    real = spend.LEDGER_PATH
    before = _digest(real)
    yield
    if _digest(real) != before:
        pytest.fail(
            f"{real} changed during the test run (D-81). Some path wrote the "
            "real daily ledger without going through spend.LEDGER_PATH."
        )


class RealAPICallRefused(BaseException):
    """A test tried to send a request to the real Anthropic API (D-74).

    BaseException, not Exception: the chat (assistant.answer_question), the
    summaries and the retry handler all catch Exception around the call and
    show a degraded result. A refusal they could catch would read as a failed
    call, and the test would pass, which is exactly how D-74 hid.
    """


@pytest.fixture(autouse=True)
def _refuse_real_api(monkeypatch):
    """No test sends a request to the real Anthropic API (D-74).

    Four tests did, whenever ANTHROPIC_API_KEY was set in the shell, and
    passed either way: keyless with no key, fourth state with a fake one, a
    real spend with a real one. Nothing on disk, nothing in the output; the
    only trace was the bill.

    The guard is at the SDK's send, not at the key or at client construction.
    A missing key only reproduces the case that already passed silently.
    There are three _default_client()s plus validate_key's own client, and
    building a client is free (test_keys builds one on purpose). Sending is
    what costs. `request` is a method on the base class, so it is reached
    however the client was built or imported.

    Every attempt is recorded and the test fails at teardown, so a refusal
    swallowed by a broad handler still fails. Yields the record, so the one
    test that checks the guard can inspect and clear it.
    """
    from anthropic._base_client import AsyncAPIClient, SyncAPIClient

    attempts: list[str] = []

    def refuse(self, *args, **kwargs):
        attempts.append(type(self).__name__)
        raise RealAPICallRefused(
            "A test sent a request to the real Anthropic API (D-74). "
            "Inject a fake client, or build keyless."
        )

    monkeypatch.setattr(SyncAPIClient, "request", refuse)
    monkeypatch.setattr(AsyncAPIClient, "request", refuse)
    yield attempts
    if attempts:
        pytest.fail(
            f"{len(attempts)} request(s) to the real Anthropic API (D-74). "
            "Inject a fake client, or build keyless."
        )


@pytest.fixture(autouse=True, scope="session")
def _real_cache_untouched():
    """Fail the run if the real cache changed anyway.

    The fixture above is only as good as every path honouring CACHE_PATH. A
    new default argument, or a module importing the constant by value, would
    slip past it silently; this turns that into a failure.
    """
    before = _digest(_REAL_CACHE)
    yield
    if _digest(_REAL_CACHE) != before:
        pytest.fail(
            f"{_REAL_CACHE} changed during the test run (D-64). Some path "
            "reached the real classification cache without going through "
            "claude_classifier._resolve_cache."
        )
