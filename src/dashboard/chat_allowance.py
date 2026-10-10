"""
How many free questions are left, and who is paying for them.

A count, not a spend figure. Ten questions cost about $0.20, so this cap can
never bind for money — it exists so one visitor cannot ask forty questions on
Amr's key, and so the limit is something a person can see and predict. A
dollar figure would need explaining and would move under them mid-session.

Unlimited on the visitor's own key: there is nothing to protect.
"""

from __future__ import annotations

from dataclasses import dataclass

from src import config
from src.dashboard.keys import KEY_PROJECT

SESSION_KEY = "chat_questions_asked"


@dataclass(frozen=True)
class Allowance:
    """What the chat box should show and whether it should accept.

    metered is False on the visitor's own key, and then asked/remaining carry
    no meaning — callers branch on metered first.
    """

    metered: bool
    asked: int = 0
    cap: int = config.FREE_CHAT_QUESTIONS

    @property
    def remaining(self) -> int:
        return max(0, self.cap - self.asked) if self.metered else 0

    @property
    def spent(self) -> bool:
        return self.metered and self.remaining == 0

    def caption(self) -> str:
        """The line beside the box. Empty when nothing needs saying."""
        if not self.metered:
            return ""
        if self.spent:
            return "Free questions used up — add your own key to keep asking."
        n = self.remaining
        return f"{n} free question{'' if n == 1 else 's'} left"


def current(session, key_source: str) -> Allowance:
    """Read the allowance without changing it."""
    if key_source != KEY_PROJECT:
        return Allowance(metered=False)
    return Allowance(metered=True, asked=int(session.get(SESSION_KEY, 0)))


def record_question(session, key_source: str) -> Allowance:
    """Count one question. Call after a question is answered, not before.

    After, deliberately: a question that failed to answer should not consume
    an allowance the visitor never got the benefit of.
    """
    if key_source != KEY_PROJECT:
        return Allowance(metered=False)
    session[SESSION_KEY] = int(session.get(SESSION_KEY, 0)) + 1
    return current(session, key_source)
