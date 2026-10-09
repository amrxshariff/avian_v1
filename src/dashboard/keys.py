"""
src/dashboard/keys.py — the one place a key is resolved.

D-55: _default_client() existed four times — in claude_classifier, assistant,
summaries, and via the first of those in self_enrichment. Each read
ANTHROPIC_API_KEY from the environment, and they agreed because there was one
key from one place.

A session key breaks that silently. Paste a key, and the build would use it
while the chat and the summaries carried on with the project's, with nothing on
screen to say which answered what. That is D-53's shape: four copies that agree
until the day one of them learns something the others do not.

Slice 1: the session key itself. Held in the session store (D-59), never
written to disk, remembered only once validated — an invalid key is never the
thing key_source() means by "a key".
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional

from src.claude_classifier import MODEL
from src.dashboard.session import session_store

# Kept here rather than in assistant.py, which is where it used to live: a
# module that four others import should not be the one that happens to own the
# error. assistant.py re-exports it, so existing imports keep working.
class MissingKeyError(RuntimeError):
    """No usable API key for this request."""


MISSING_KEY_MESSAGE = (
    "ANTHROPIC_API_KEY not set. Generate one at console.anthropic.com and set "
    "it for this shell:\n"
    '    $env:ANTHROPIC_API_KEY = "sk-ant-..."'
)

USER_KEY_SLOT = "user_api_key"
KEY_CHECK_SLOT = "user_key_check"


def remember_key(key: str, store: Optional[dict] = None) -> None:
    """Hold a key for this session. Only ever called with a validated key.

    An invalid key is never stored, which is what lets key_source() mean
    "a key that works" rather than "a key is present". Callers validate
    through check_key() and store only on KEY_VALID.
    """
    session_store(store)[USER_KEY_SLOT] = key


def forget_key(store: Optional[dict] = None) -> None:
    """Drop the key and the memo of what was last checked."""
    s = session_store(store)
    s.pop(USER_KEY_SLOT, None)
    s.pop(KEY_CHECK_SLOT, None)


def session_key(store: Optional[dict] = None) -> Optional[str]:
    """The validated key pasted this session, or None."""
    return session_store(store).get(USER_KEY_SLOT)


def resolve_key(store: Optional[dict] = None) -> str:
    """The key to use, in precedence order, or raise.

    Order, as the P2.9b record sets it:
      1. a key the user pasted this session — their key, their credit;
      2. the project key from the environment, subject to the free tier;
      3. nothing, which is an error the caller must surface.
    """
    pasted = session_key(store)
    if pasted:
        return pasted

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise MissingKeyError(MISSING_KEY_MESSAGE)
    return key


# Whose key, not where it's stored — "session" described storage and left
# the question every caller actually asks ("whose credit is this?") to be
# inferred rather than named.
KEY_USER = "user"
KEY_PROJECT = "project"
KEY_NONE = "none"


def key_source(store: dict | None = None) -> str:
    """Whose key this build would use: KEY_USER, KEY_PROJECT or KEY_NONE.

    Always truthy, including KEY_NONE. Never test the result for truth —
    compare against a constant. D-57 was `bool(key_source(store))`, which
    reads as "is there a key" and is always True.
    """
    if session_key(store):
        return KEY_USER
    if os.environ.get("ANTHROPIC_API_KEY"):
        return KEY_PROJECT
    return KEY_NONE


def resolve_client(timeout: float | None = None, max_retries: int | None = None,
                   store: Optional[dict] = None):
    """An Anthropic client built from the resolved key.

    The key is resolved BEFORE the SDK is imported, which assistant.py did
    deliberately and D-55 nearly lost: on a deploy without anthropic installed,
    a missing key must report itself as a missing key, not as an ImportError
    that reads like a broken build. The import stays lazy either way, so the
    chain modules still load without the SDK.
    """
    key = resolve_key(store)

    import anthropic

    kwargs = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return anthropic.Anthropic(api_key=key, **kwargs)


# What a validation call found. Four outcomes, because "your key is broken" and
# "the service is busy" send a user to completely different actions.
KEY_VALID = "valid"
KEY_REJECTED = "rejected"
KEY_NO_CREDIT = "no_credit"
KEY_SERVICE_BUSY = "service_busy"

KEY_MESSAGES = {
    KEY_REJECTED: "That key was rejected. Check it was copied in full.",
    KEY_NO_CREDIT: "That key has no credit left.",
    # Must not read as a bad key: telling someone their key is broken when the
    # service is having a bad minute sends them to rotate a key that was fine.
    KEY_SERVICE_BUSY: (
        "The classification service is busy. Your key looks fine — try again "
        "in a moment."
    ),
}


def validate_key(key: str, client=None) -> str:
    """One cheap call, before a build spends anything on a key that cannot pay.

    Returns one of the four outcomes above. Never raises for an API failure:
    the caller shows a message, and a failure here is not the user's fault.
    """
    from src.claude_classifier import _reason_for
    from src.failure_reasons import REASON_KEY_FAILED, REASON_SERVICE_BUSY

    if client is None:
        # Not a duplicate of resolve_client (D-55): a validation call must
        # fail once rather than retry three times while someone watches a
        # spinner, so this path builds its own client at max_retries=0.
        import anthropic

        client = anthropic.Anthropic(api_key=key, max_retries=0)

    try:
        client.messages.create(
            model=MODEL,
            max_tokens=1,
            messages=[{"role": "user", "content": "ok"}],
        )
    except Exception as exc:                      # noqa: BLE001 — mapped below
        reason = _reason_for(exc)
        if reason == REASON_KEY_FAILED:
            return KEY_NO_CREDIT if "credit" in str(exc).lower() else KEY_REJECTED
        if reason == REASON_SERVICE_BUSY:
            return KEY_SERVICE_BUSY
        raise
    return KEY_VALID


def redact(text: str, store: Optional[dict] = None) -> str:
    """Remove the session key from anything about to be shown or logged.

    An SDK error can quote the request it failed on. Applied at the point of
    display rather than trusted not to be needed: a key in a traceback on a
    public deploy is the failure this whole design exists to avoid.
    """
    key = session_key(store)
    if not key:
        return text
    return text.replace(key, "sk-ant-...redacted")


def fingerprint(key: str) -> str:
    """Identify a key without holding it a second time."""
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def check_key(key: str, store: Optional[dict] = None, client=None) -> str:
    """validate_key(), memoised on the key's fingerprint.

    Streamlit reruns the script on every interaction. Without this, clicking
    anything after pasting spends another call — including on a typo, which
    would re-check on every rerun forever.

    A valid key is remembered here; an invalid one is not, only the verdict.
    KEY_SERVICE_BUSY is never memoised: the message tells the user to try
    again in a moment, and a memo would make "try again" do nothing.

    The memo is ONE slot, not a history: checking a second key overwrites it,
    and forget_key() clears it along with the held key. So pasting A, then B,
    then forgetting, then pasting A again re-validates A — it is not still
    cached from the first time. That is correct: forgetting is supposed to
    mean forgetting, not "until the next unrelated key is checked."
    """
    fp = fingerprint(key)
    s = session_store(store)

    cached = s.get(KEY_CHECK_SLOT)
    if cached and cached[0] == fp:
        return cached[1]

    outcome = validate_key(key, client=client)
    if outcome != KEY_SERVICE_BUSY:
        s[KEY_CHECK_SLOT] = (fp, outcome)
    if outcome == KEY_VALID:
        remember_key(key, store)
    return outcome
