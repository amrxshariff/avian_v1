"""
src/dashboard/metering.py — which calls are metered, and against what.

spend.py's meters were built and tested on 27 September and never constructed
by anything that runs (D-81): every build and retry on the project key went
uncapped, and the daily ledger file was never written. This is where the app
constructs them.

Only the project key is metered. A visitor's own key costs the project nothing,
and a keyless build calls nothing at all.
"""

from __future__ import annotations

from typing import Optional

from src.dashboard.keys import KEY_PROJECT
from src.spend import DailyLedger, GenerationMeter, Meters


def meters_for(source: Optional[str]) -> Optional[Meters]:
    """The meters for one build or retry, or None when nothing should be metered.

    A fresh GenerationMeter every time — the $5 cap is per generation — over
    the one shared DailyLedger, which is a file and so the same ledger for
    every session on the container (design §6.5).
    """
    if source != KEY_PROJECT:
        return None
    return Meters(generation=GenerationMeter(), daily=DailyLedger())


# --- D-80: the calls a visitor makes after the build ------------------------
#
# Chat, summaries and self-enrichment charge the daily ledger on the project
# key and nothing else: not the generation meter, and not the ten-question
# allowance, which counts chat questions only (design record, 7 October
# amendment). One ledger, three sources; one question count, one source.

BUDGET_SPENT_NOTE = (
    "Today's free budget is spent. Add your own key to keep going."
)


def ledger_for(source: Optional[str]) -> Optional[DailyLedger]:
    """The daily ledger on the project key, or None when nothing is metered."""
    return DailyLedger() if source == KEY_PROJECT else None


def budget_spent(source: Optional[str]) -> bool:
    """True when the project key's day is used up. Never true on another key."""
    ledger = ledger_for(source)
    return ledger is not None and ledger.remaining <= 0


class LedgerClient:
    """An Anthropic client whose every call is checked against, and charged
    to, the daily ledger.

    Every spending path uses client.messages.create and nothing else, and
    every one already accepts an injected client, so wrapping the client
    meters all three without threading usage through three modules. It wraps
    whatever the path would have used: its own default (so the chat keeps its
    timeout and retries), or a test's fake.
    """

    def __init__(self, ledger: DailyLedger, client=None, factory=None) -> None:
        self._ledger = ledger
        self._client = client
        self._factory = factory

    @property
    def messages(self):
        return self

    def create(self, **kwargs):
        from src.claude_classifier import Usage
        from src.spend import BudgetExceeded

        # The same test as budget_spent(), not ledger.check(): check() with no
        # estimate refuses only once spend EXCEEDS the cap, so a day spent to
        # exactly $30 would still let a call through.
        if self._ledger.remaining <= 0:
            raise BudgetExceeded("day", self._ledger.spent, self._ledger.cap)
        if self._client is None:
            self._client = self._factory()
        response = self._client.messages.create(**kwargs)
        usage = Usage()
        usage.add(response)
        self._ledger.record(usage)
        return response


def metered_client(source: Optional[str], client, factory):
    """The client a call should use: charged to the ledger on the project key,
    unchanged on any other."""
    ledger = ledger_for(source)
    if ledger is None:
        return client
    return LedgerClient(ledger, client=client, factory=factory)
