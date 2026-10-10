"""
What has been spent today, and what is this build allowed to spend.

Two meters, in different units and with different lifetimes:

  GenerationMeter — one build, in memory, dies with it. A runaway guard.
  DailyLedger     — every build, on disk, resets at UTC midnight. The real cap.

The ledger is a file rather than a module global because a redeploy resets a
global to zero, and a redeploy is exactly when the counter matters most: a
crash loop could otherwise spend the daily budget several times over between
lunch and dinner. It is not a substitute for the Console spend limit (see
config.py) — two processes can still double-count, since there is no lock we
can rely on in a hosted environment. This closes the common hole cheaply; the
Console closes the rest.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from src import config
from src.claude_classifier import Usage

LEDGER_PATH = Path("data/spend/daily.json")


class BudgetExceeded(RuntimeError):
    """Raised when a call would breach a cap. Carries which one, for wording."""

    def __init__(self, scope: str, spent: float, cap: float) -> None:
        self.scope = scope          # "generation" or "day"
        self.spent = spent
        self.cap = cap
        super().__init__(f"{scope} budget spent: ${spent:.2f}, cap ${cap:.2f}")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


@dataclass
class GenerationMeter:
    """Spend for one build, including that session's chat.

    Holds a Usage rather than a running float so the token counts survive for
    provenance — how a build spent its money is worth showing, and a float
    cannot be broken back down.
    """

    cap: float = config.MAX_SPEND_PER_GENERATION
    usage: Usage = field(default_factory=Usage)

    @property
    def spent(self) -> float:
        return self.usage.cost()

    @property
    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent)

    def check(self, estimate: float = 0.0) -> None:
        """Raise if spending `estimate` more would breach the cap.

        Called before a batch, with the batch's estimated cost. An estimate of
        zero asks only whether the cap is already breached.
        """
        if self.spent + estimate > self.cap:
            raise BudgetExceeded("generation", self.spent, self.cap)

    def record(self, usage: Usage) -> None:
        self.usage.input_tokens += usage.input_tokens
        self.usage.output_tokens += usage.output_tokens
        self.usage.calls += usage.calls


class DailyLedger:
    """Spend across everyone, today, persisted.

    Holds only today's figures: a date that is not today reads as zero, so
    there is nothing to prune and no history to keep. History would be useful
    and is deliberately not kept — the file would then be a record of when
    strangers used the demo.
    """

    def __init__(self, path: Path | None = None,
                 cap: float | None = None) -> None:
        self.path = Path(path) if path else LEDGER_PATH
        self.cap = config.MAX_SPEND_PER_DAY if cap is None else cap

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict) or data.get("date") != _today():
            return {}
        return data

    def _write(self, data: dict) -> None:
        """Write atomically, and never let a failure stop a build.

        A ledger that cannot be written fails open: the build proceeds and the
        spend goes unrecorded. The alternative — refusing to classify because a
        disk is full — trades a small overspend for a dead app, and the Console
        limit is the backstop for exactly this.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(data, fh)
                os.replace(tmp, self.path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        except OSError:
            pass

    @property
    def spent(self) -> float:
        return float(self._read().get("spent", 0.0))

    @property
    def remaining(self) -> float:
        return max(0.0, self.cap - self.spent)

    def check(self, estimate: float = 0.0) -> None:
        spent = self.spent
        if spent + estimate > self.cap:
            raise BudgetExceeded("day", spent, self.cap)

    def record(self, usage: Usage) -> None:
        """Add a call's spend.

        Re-reads immediately before writing rather than holding the earlier
        read, which narrows the lost-update window to microseconds without
        pretending to close it. Under concurrent writers this under-counts; it
        never over-counts, so the app stays live and the Console limit holds.
        """
        data = self._read()
        self._write({
            "date": _today(),
            "spent": float(data.get("spent", 0.0)) + usage.cost(),
            "calls": int(data.get("calls", 0)) + usage.calls,
            "networks": int(data.get("networks", 0)),
        })

    def record_network(self) -> None:
        data = self._read()
        self._write({
            "date": _today(),
            "spent": float(data.get("spent", 0.0)),
            "calls": int(data.get("calls", 0)),
            "networks": int(data.get("networks", 0)) + 1,
        })


def estimate_titles(n: int) -> float:
    """What n uncached titles should cost, at the limiter's assumption.

    Any estimate shown to a visitor must come from here, over a count from
    count_uncached_titles — not from a fresh len(set(...)) or a separate cache
    read. The number displayed and the number checked have to be the same
    number, or the app refuses a build it told someone was affordable.
    """
    return n * config.ASSUMED_COST_PER_TITLE


@dataclass
class Meters:
    """The pair, checked and recorded together.

    Both or neither: a build that meters the generation but not the day would
    let the daily cap be breached one build at a time.
    """

    generation: GenerationMeter
    daily: DailyLedger

    def check(self, estimate: float = 0.0) -> None:
        self.daily.check(estimate)
        self.generation.check(estimate)

    def record(self, usage: Usage) -> None:
        self.generation.record(usage)
        self.daily.record(usage)
