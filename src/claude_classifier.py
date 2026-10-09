"""
src/claude_classifier.py — Phase 1.5: the LLM tier.

Replaces the embedding tier, which measured 40% accurate on the eval set and
cost 8 points of precision for 10 of coverage. Its five outputs all scored
0.5517-0.5974 — good and bad indistinguishable — so no threshold could separate
them. MiniLM on a two-word title has no world knowledge to contribute; it is a
string matcher with extra steps.

This tier targets the 56% that the deterministic tiers abstain on, which share
one shape: compound titles and UK early-career conventions.

    Finance Intern · Trading Analyst Intern · Deals Intern
    Banking and Capital Markets Assurance Associate · Actuarial Graduate
    Senior Data Science Product Leader · Co-Founder · IT Technician

Every one is trivial for a human and impossible for a lexicon lookup. It does
NOT replace the exact (85.7%) and fuzzy (75.0%) tiers — those stay in front,
are free, and cite a lexicon row.

Company as context
------------------
Optional and load-bearing where present. "President" is undecidable alone and
trivial as "President @ Barclays" (11) vs "President @ UCL Debating Society"
(null). The deterministic tiers cannot use it; this one can.

Scope: MAJOR GROUP only
-----------------------
Returns a 2-digit SOC major group, not a detailed O*NET-SOC code. Asking for a
detailed code invites invented codes — the model has no reliable index of the
1,016 valid ones. Major group is what the dashboard groups by and what the eval
measures. Detailed codes (needed for the O*NET skills join) are a Phase 2
two-stage problem: major group here, then match within the group.

Caching
-------
Keyed by (normalised title, normalised company). ~372 distinct titles over 19
batched calls; a cache hit costs nothing, and titles recur across users' networks
so the cache warms. Cached under data/cache/ (gitignored — derived from real
people).

Requires ANTHROPIC_API_KEY in the environment or a gitignored .env.

Run from the repo root:
    python -m src.claude_classifier
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Protocol

from src.failure_reasons import (
    REASON_BUDGET_REACHED,
    REASON_KEY_FAILED,
    REASON_SERVICE_BUSY,
    REASON_UNANSWERABLE,
)
from src.onet import Classification, MAJOR_GROUP_NAMES, normalise

MODEL = "claude-sonnet-5"
BATCH_SIZE = 20
# D-42: Sonnet 5's adaptive thinking draws on this same budget. At 2000 a
# batch of 20 spent the lot on thinking, the JSON never arrived, and the
# padded abstains were cached as though the model had declined. A full
# batch of 20 measured 1925 output tokens, so this leaves real headroom.
MAX_TOKENS = 8000
CACHE_PATH = Path("data/cache/claude_classification.json")

# Confidence -> a score comparable to the other tiers, and a gate. "low" is
# treated as an abstain: the whole point of this tier is that a blank card is
# honest and a confident wrong one is not.
CONFIDENCE_SCORES = {"high": 0.95, "medium": 0.75, "low": 0.40}
MIN_CONFIDENCE = "medium"


class _Client(Protocol):
    """Minimal shape of anthropic.Anthropic, so tests can inject a fake."""

    @property
    def messages(self): ...


def _default_client():
    """The classifier's client. One resolver since D-55; see dashboard/keys.py."""
    from src.dashboard.keys import resolve_client

    return resolve_client()


# --- prompt ------------------------------------------------------------------

_GROUPS_BLOCK = "\n".join(f"{k} {v}" for k, v in sorted(MAJOR_GROUP_NAMES.items()))

SYSTEM_PROMPT = f"""You classify job titles from LinkedIn connection exports into US SOC (Standard Occupational Classification) major groups.

SOC major groups:
{_GROUPS_BLOCK}

Rules, in priority order:

1. Classify the occupational FUNCTION the title names. Not seniority, not the employer's industry.

2. Return null when the title names no occupational function. Apply this TEST: strip away every word that is only seniority ("senior", "lead", "trainee", "graduate"), tenure ("intern", "placement", "student", "year out"), or organisational membership ("member", "ambassador", "volunteer", "representative", "committee"). If NO occupational noun remains, return null.
   - "Student Ambassador", "Campus Ambassador", "Lead Student Ambassador" -> null (only membership words remain)
   - "Member", "Volunteer", "Senior", "Intern", "Student", "Part-time Placement" -> null
   - "Empowered Females in STEM Programme", "Customer Experience Team Member" -> null (a programme or team membership, not a job)
   - CONTRAST: "Finance Intern" -> 13, "Mechanical Engineering Intern" -> 17 (an occupational noun survives the strip)
   "Ambassador" and "Representative" name an occupation ONLY with a commercial qualifier: "Brand Ambassador", "Sales Representative" -> 41. A student/campus/university ambassador is not an occupation -> null.
   Returning null is a correct answer, not a failure.

3. An entry-level title that DOES name a function is that function:
   "Finance Intern" -> 13. "Actuarial Graduate" -> 15. "Graduate Quantity Surveyor" -> 13.
   The seniority word does not change the group.

4. Use the company to disambiguate when it helps:
   "President" at a bank -> 11. "President" of a student society -> null.
   "Engineer" at an airline -> 17. "Maintenance Engineer" at a property firm -> 49.
   Ignore the company when the title is already clear.

5. UK conventions matter — these titles are mostly UK:
   - "Quantity Surveyor" is cost estimation -> 13, NOT land surveying (17).
   - "Maintenance Engineer" in buildings is a repair trade -> 49, not chartered engineering.
   - "Chartered Accountant", "ACA", "ACCA" -> 13.
   - "Solicitor", "Barrister", "Trainee Solicitor", "SQE" -> 23.
   - "Registrar", "Foundation Doctor", "SHO" -> 29.
   - Big-4 "Deals" / "Assurance" / "Audit" service lines -> 13.
   - "Supervisor" is a first-line supervisor in its own group (a "Security Supervisor" -> 33), NOT management (11). Reserve 11 for genuine managers and directors.

6. Prefer null over a guess. A wrong classification is worse than no classification: it appears on a profile card citing an authoritative taxonomy, and the user cannot tell it is wrong.


Set confidence "low" if you are unsure — low-confidence answers are discarded, so guessing gains nothing.

Return ONLY a JSON array, one object per input, same order, no prose:
[{{"i": 0, "soc": "13", "confidence": "high", "why": "audit is a finance function"}}, {{"i": 1, "soc": null, "confidence": "high", "why": "society role, no occupation"}}]

"why" must be under 10 words."""


def _build_user_message(items: list[tuple[str, str]]) -> str:
    lines = []
    for i, (title, company) in enumerate(items):
        c = f" | company: {company}" if company else ""
        lines.append(f'{i}. title: {title}{c}')
    return "Classify these:\n\n" + "\n".join(lines)


# --- response parsing --------------------------------------------------------

def _parse_response(text: str, n: int) -> list[dict]:
    """Extract the JSON array, tolerating markdown fences and stray prose.

    Returns a list of n dicts, padded with abstains if the model returned fewer
    or the payload is unusable — a malformed response must degrade to "no claim",
    never to a wrong claim or an exception mid-batch.
    """
    blank = [{"soc": None, "confidence": "low", "why": "unparsed"} for _ in range(n)]

    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return blank
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return blank
    if not isinstance(parsed, list):
        return blank

    out = list(blank)
    for obj in parsed:
        if not isinstance(obj, dict):
            continue
        i = obj.get("i")
        if not isinstance(i, int) or not (0 <= i < n):
            continue
        soc = obj.get("soc")
        # Guard against an invented group: only the 23 real ones are accepted.
        if soc is not None:
            soc = str(soc).strip()
            if soc not in MAJOR_GROUP_NAMES:
                soc = None
        out[i] = {
            "soc": soc,
            "confidence": str(obj.get("confidence", "low")).lower(),
            "why": str(obj.get("why", ""))[:80],
        }
    return out


# --- cache -------------------------------------------------------------------

def _cache_key(title: str, company: str) -> str:
    return f"{normalise(title)}||{normalise(company or '')}"


def _resolve_cache(cache_path: Path | str | dict | None) -> Path | dict:
    """The cache file to use, with CACHE_PATH looked up NOW, not at import.

    A `cache_path: Path = CACHE_PATH` default is fixed when the module loads,
    so patching the module attribute afterwards reaches nothing — which is
    what left the D-64 guard unable to guard. One call-time lookup here means
    there is exactly one name to redirect.

    A dict is returned unchanged and is used as the cache itself (D-71). A
    session build classifies real people's job titles, and those do not
    belong in a file the app keeps between sessions — on a deployment,
    between strangers. The caller holds the mapping, so it lives and dies with
    whatever scope the caller gave it.
    """
    if isinstance(cache_path, dict):
        return cache_path
    return CACHE_PATH if cache_path is None else Path(cache_path)


def _load_cache(path: Path | dict) -> dict:
    # A mapping is returned AS IS, not copied: the caller's dict is the cache,
    # so entries written during the run accumulate in it and _save_cache has
    # nothing left to do.
    if isinstance(path, dict):
        return path
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_cache(cache: dict, path: Path | dict) -> None:
    if isinstance(path, dict):
        return          # already written: `cache` IS `path` (see _load_cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=1, sort_keys=True), encoding="utf-8")


def count_uncached_titles(people, cache_path: Path | str | None = None) -> int:
    """Distinct (title, company) pairs among `people` not already cached.

    What the pre-flight estimate should price: a cached title costs nothing,
    so counting it against the budget would refuse builds that are actually
    free. Same dedup and same (title, "") key as classify_people — company is
    never used here (config E).
    """
    cache = _load_cache(_resolve_cache(cache_path))
    distinct = {p.role.strip() for p in people if p.role.strip()}
    return sum(1 for title in distinct if _cache_key(title, "") not in cache)


# --- public API --------------------------------------------------------------

def _to_classification(title: str, rec: dict) -> Classification:
    soc = rec.get("soc")
    conf = rec.get("confidence", "low")
    score = CONFIDENCE_SCORES.get(conf, 0.4)

    # Low confidence is an abstain by design, not a weak answer.
    if soc is None or CONFIDENCE_SCORES.get(conf, 0.0) < CONFIDENCE_SCORES[MIN_CONFIDENCE]:
        return Classification(
            query=title, soc_code=None, soc_major=None, occupation=None,
            tier="abstain", score=score, n_candidates=0, major_agreement=0.0,
        )
    return Classification(
        query=title, soc_code=None, soc_major=soc,
        occupation=MAJOR_GROUP_NAMES.get(soc), tier="claude", score=score,
        n_candidates=1, major_agreement=1.0,
    )


class ClassificationFailed(RuntimeError):
    """A title could not be answered, even alone in its own call.

    Raised rather than abstaining: an abstention means the model declined to
    classify, and a truncated or unparseable call is not that. Whatever did
    succeed is already cached, so a rerun only costs the failures.
    """


def _batch_outcome(
    client, model: str, items: list[tuple[str, str]], usage: Usage | None = None
) -> tuple[list[Optional[dict]], list[Optional[str]]]:
    """Per-item records and per-item failure reasons, both aligned to `items`.

    A truncated response, or a record `_parse_response` had to pad, is a failed
    call rather than an answer, so it is never returned and never cached. The
    same titles that overflow the budget in a batch of 20 parse cleanly in
    smaller batches, so splitting is the retry.

    A title that still has no usable answer ALONE in its own call is marked
    unanswerable and the rest of the batch continues. That is the only failure
    decided here; an API error (a rate limit, a dead key) is about the run, not
    about a title, so it propagates to the caller untouched.

    One implementation, two callers: classify_claude raises on the first
    failure, classify_claude_outcome reports them. Keeping the splitting logic
    in one place is deliberate — two copies would agree until the day they did
    not, which is what D-53 was.
    """
    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(items)}],
    )
    if usage is not None:
        usage.add(resp)
    stop = getattr(resp, "stop_reason", None)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    truncated = stop == "max_tokens"
    recs = [] if truncated else _parse_response(text, len(items))
    missing = [i for i, r in enumerate(recs) if r.get("why") == "unparsed"]

    if truncated or len(missing) == len(items):
        if len(items) == 1:
            return [None], [REASON_UNANSWERABLE]
        half = len(items) // 2
        left_recs, left_fails = _batch_outcome(client, model, items[:half], usage)
        right_recs, right_fails = _batch_outcome(client, model, items[half:], usage)
        return left_recs + right_recs, left_fails + right_fails

    out: list[Optional[dict]] = list(recs)
    fails: list[Optional[str]] = [None] * len(items)
    if missing:
        sub_recs, sub_fails = _batch_outcome(
            client, model, [items[i] for i in missing], usage
        )
        for i, rec, fail in zip(missing, sub_recs, sub_fails):
            out[i] = rec
            fails[i] = fail
    return out, fails


def _classify_batch(client, model: str, items: list[tuple[str, str]]) -> list[dict]:
    """Records for `items`, raising ClassificationFailed if any has none.

    The raising face of _batch_outcome, kept for the command-line chain: there,
    a title nobody can answer is a fault to fix, not a state to render.
    """
    recs, fails = _batch_outcome(client, model, items)
    for (title, company), rec, fail in zip(items, recs, fails):
        if fail is not None or rec is None:
            raise ClassificationFailed(
                f"no usable answer for {title!r} even alone in its own call "
                f"({fail}). Nothing was cached for it."
            )
    return [rec for rec in recs if rec is not None]


# Exception -> reason. Matched by class name and HTTP status rather than by
# importing anthropic, so this module still imports without the SDK and so a
# fake client can exercise every branch.
_KEY_ERROR_NAMES = frozenset({"AuthenticationError", "PermissionDeniedError"})
_BUSY_ERROR_NAMES = frozenset({
    "RateLimitError", "APIConnectionError", "APITimeoutError",
    "InternalServerError", "APIStatusError", "OverloadedError",
})


def _reason_for(exc: BaseException) -> Optional[str]:
    """The reason this exception describes, or None if it is not ours.

    None means the exception is a BUG rather than a service failure, and bugs
    must crash. Reporting a TypeError to the user as \"the service was busy\"
    would hide a defect behind a reassuring sentence.
    """
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()

    if name in _KEY_ERROR_NAMES or status in (401, 403):
        return REASON_KEY_FAILED
    # Anthropic reports an empty balance as a 400, not a 402.
    if "credit balance" in text or "insufficient credit" in text:
        return REASON_KEY_FAILED
    if name in _BUSY_ERROR_NAMES or status == 429:
        return REASON_SERVICE_BUSY
    if isinstance(status, int) and status >= 500:
        return REASON_SERVICE_BUSY
    if type(exc).__module__.split(".")[0] == "anthropic":
        return REASON_SERVICE_BUSY      # an API error we have no name for
    return None


@dataclass
class Usage:
    """Tokens a run spent, and what they cost.

    Totalled here rather than estimated from the prompt: Sonnet 5's adaptive
    thinking bills as output and is invisible from the input side, so the only
    honest figure is the one the API reports back.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    def add(self, response) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        self.input_tokens += int(getattr(usage, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(usage, "output_tokens", 0) or 0)
        self.calls += 1

    def cost(self, input_per_mtok: float | None = None,
             output_per_mtok: float | None = None) -> float:
        """Spend in dollars.

        Rates default to config's, which carry their checked date and source.
        The arguments exist for tests and for costing a hypothetical at a
        different rate; nothing in the app should pass them.
        """
        from src import config

        if input_per_mtok is None:
            input_per_mtok = config.INPUT_PER_MTOK
        if output_per_mtok is None:
            output_per_mtok = config.OUTPUT_PER_MTOK
        return (self.input_tokens * input_per_mtok
                + self.output_tokens * output_per_mtok) / 1_000_000


@dataclass(frozen=True)
class ClassifyOutcome:
    """What a run produced, including what it did not.

    `answers` is aligned to the items passed in, with None where there is no
    answer. `failures` maps those positions to a reason. The two never overlap,
    and every position is in exactly one of them — a person is answered or
    accounted for, never silently absent.
    """

    answers: list[Optional[Classification]]
    failures: dict[int, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)

    @property
    def complete(self) -> bool:
        return not self.failures

    @property
    def reasons(self) -> set[str]:
        return set(self.failures.values())


def _partition_cached(
    items: list[tuple[str, str]], cache: dict, use_cache: bool
) -> tuple[dict[int, Classification], list[int]]:
    """Split items into what the cache already answers and what must be asked."""
    results: dict[int, Classification] = {}
    todo: list[int] = []
    for i, (title, company) in enumerate(items):
        k = _cache_key(title, company)
        if use_cache and k in cache:
            results[i] = _to_classification(title, cache[k])
        else:
            todo.append(i)
    return results, todo


def classify_claude_outcome(
    items: list[tuple[str, str]],
    client=None,
    model: str = MODEL,
    batch_size: int = BATCH_SIZE,
    cache_path: Path | str | None = None,
    use_cache: bool = True,
    meters: "Meters | None" = None,
) -> ClassifyOutcome:
    """Classify `items`, reporting what failed instead of raising on it.

    The build function's entry point (P2.9b). Same cache, same batching and the
    same splitting as classify_claude; the difference is what happens when a
    call fails.

    An API error STOPS the run, and everyone not yet answered carries its
    reason. Once the SDK's own retries are spent, the next batch is very likely
    to fail the same way: continuing costs the user time and their budget for
    an outcome a retry gives them anyway. A single unanswerable title is
    different — it says nothing about the run — so it is marked and the rest
    continues.

    An exception that is not a service failure propagates. A bug must crash.

    `meters`, injected, checks the free-tier caps before each batch and
    records what it actually spent after. None (the command-line chain, and
    a build on the visitor's own key) means unmetered — nothing to check,
    nothing to record.
    """
    from src.spend import BudgetExceeded, estimate_titles          # lazy: spend imports Usage from here

    cache_path = _resolve_cache(cache_path)
    cache = _load_cache(cache_path) if use_cache else {}
    results, todo = _partition_cached(items, cache, use_cache)
    failures: dict[int, str] = {}
    stopped: Optional[str] = None
    usage = Usage()

    if todo:
        if client is None:
            client = _default_client()

        try:
            for start in range(0, len(todo), batch_size):
                idxs = todo[start:start + batch_size]

                if meters is not None:
                    try:
                        meters.check(estimate_titles(len(idxs)))
                    except BudgetExceeded:
                        # Stop cleanly. Everything classified so far stands;
                        # the rest get REASON_BUDGET_REACHED. Enforced here
                        # rather than inside the batch because a call already
                        # made is already paid for.
                        for i in todo[start:]:
                            failures[i] = REASON_BUDGET_REACHED
                        break

                batch_usage = Usage()
                try:
                    recs, fails = _batch_outcome(
                        client, model, [items[i] for i in idxs], batch_usage
                    )
                except Exception as exc:          # noqa: BLE001 — re-raised below
                    stopped = _reason_for(exc)
                    if stopped is None:
                        raise
                    break

                usage.input_tokens += batch_usage.input_tokens
                usage.output_tokens += batch_usage.output_tokens
                usage.calls += batch_usage.calls
                if meters is not None:
                    meters.record(batch_usage)

                for i, rec, fail in zip(idxs, recs, fails):
                    if fail is not None or rec is None:
                        failures[i] = fail or REASON_UNANSWERABLE
                        continue                  # never cached, never an answer
                    title, company = items[i]
                    cache[_cache_key(title, company)] = rec
                    results[i] = _to_classification(title, rec)
        finally:
            if use_cache:
                _save_cache(cache, cache_path)    # keep whatever did succeed

    if stopped is not None:
        for i in range(len(items)):
            if i not in results and i not in failures:
                failures[i] = stopped

    return ClassifyOutcome(
        answers=[results.get(i) for i in range(len(items))],
        failures=failures,
        usage=usage,
    )


def classify_claude(
    items: list[tuple[str, str]],
    client=None,
    model: str = MODEL,
    batch_size: int = BATCH_SIZE,
    cache_path: Path | str | None = None,
    use_cache: bool = True,
) -> list[Classification]:
    """Classify (title, company) pairs via Claude. Returns one Classification each.

    Cache-first, then batched calls for the misses. `client` is injectable for
    tests; None builds the real Anthropic client (and requires a key).
    """
    cache_path = _resolve_cache(cache_path)
    cache = _load_cache(cache_path) if use_cache else {}
    results, todo = _partition_cached(items, cache, use_cache)

    if todo:
        if client is None:
            client = _default_client()

        try:
            for start in range(0, len(todo), batch_size):
                idxs = todo[start:start + batch_size]
                batch = [items[i] for i in idxs]
                recs = _classify_batch(client, model, batch)   # raises instead of padding
                for i, rec in zip(idxs, recs):
                    title, company = items[i]
                    cache[_cache_key(title, company)] = rec
                    results[i] = _to_classification(title, rec)
        finally:
            if use_cache:
                _save_cache(cache, cache_path)   # keep whatever did succeed

    return [results[i] for i in range(len(items))]


def main() -> None:
    """Classify every distinct (title, company) in the configured source."""
    from src.ingestion import load_profiles

    people = load_profiles()
    seen, items = set(), []
    for p in people:
        k = _cache_key(p.role, p.company)
        if p.role.strip() and k not in seen:
            seen.add(k)
            items.append((p.role.strip(), p.company.strip()))

    print(f"{len(items)} distinct (title, company) pairs -> "
          f"{(len(items) + BATCH_SIZE - 1) // BATCH_SIZE} batched calls\n")

    results = classify_claude(items)
    n = sum(1 for c in results if c.tier == "claude")
    print(f"  classified {n}/{len(results)} ({100 * n / len(results):.1f}%)")
    print(f"  abstained  {len(results) - n}")
    print(f"\nCache: {CACHE_PATH}")


if __name__ == "__main__":
    main()