"""
src/failure_reasons.py — P2.9b: why a person has no classification.

One vocabulary, shared by the producer and every consumer. It lives here, at
core level, because both ends need it and neither should import the other: the
classifier must not depend on a dashboard module, and the dashboard must not
depend on the classifier to know what words exist.

The four reasons come from the build contract in
docs/p2_9b_partial_failure.md section 4. Wording lives in
src/dashboard/unclassified.py, which is a display concern; what a reason MEANS
lives here:

  service_busy     the call kept failing after the SDK's own retries
  key_failed       the key was rejected, or had no credit left
  budget_reached   the free tier's session limit or daily budget ran out
  unanswerable     the model returned nothing usable for this one title, alone
                   in its own call

`unanswerable` is the only per-person reason. The other three describe the run,
so they apply to everyone the run never got to.

None of these is an abstention. An abstention is an answer — the model looked
at the title and declined. These are the absence of an answer, which is the
distinction D-42 was about.
"""

from __future__ import annotations

REASON_SERVICE_BUSY = "service_busy"
REASON_KEY_FAILED = "key_failed"
REASON_BUDGET_REACHED = "budget_reached"
REASON_UNANSWERABLE = "unanswerable"
# P2.9b: a build ran with no classifier at all. Not a failure of anything —
# the network is drawn, the question has simply not been asked yet. It is a
# reason rather than a fifth display state because what the user sees is the
# same: a person with no group, and a way to get one.
REASON_NO_KEY = "no_key"

ALL_REASONS: tuple[str, ...] = (
    REASON_SERVICE_BUSY,
    REASON_KEY_FAILED,
    REASON_BUDGET_REACHED,
    REASON_UNANSWERABLE,
    REASON_NO_KEY,
)

# The reasons that describe the run rather than one person. A build that hits
# one of these stops, and everyone it never reached carries that reason.
RUN_LEVEL_REASONS: frozenset[str] = frozenset({
    REASON_SERVICE_BUSY,
    REASON_KEY_FAILED,
    REASON_BUDGET_REACHED,
    REASON_NO_KEY,
})
