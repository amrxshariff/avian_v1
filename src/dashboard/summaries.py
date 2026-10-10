"""
src/dashboard/summaries.py — Phase 2, P2.7: cached cluster summaries.

DoD: each SOC group has an auto-generated 2-3 sentence summary of its
composition, generated once and cached; summaries are accurate to the members
actually in the group and regenerate if membership changes via P2.1 corrections.

Two layers, matching the discipline in state.py / card.py / search.py:

  * PURE CORE (no streamlit) — membership_key(), group_members(),
    coverage_counts(), coverage_sentence(), build_prompt(), generate_summary(),
    summarise_group(). The cache dict and the Anthropic client are passed IN
    (dependency injection, same pattern as the encoder in onet.py and the client
    in claude_classifier.py), so every branch unit-tests under plain pytest with
    no Streamlit runtime and no network.

  * STREAMLIT GLUE — init_summaries(), get_group_summary(),
    render_summaries_panel(). Pull the cache from st.session_state and delegate.
    streamlit is imported lazily inside these functions.

Design decisions (settled 23 Aug 2026, before any code was written)
-------------------------------------------------------------------
1. CACHE KEY IS A MEMBERSHIP SIGNATURE, not a group code. "Generated once and
   cached" and "regenerates if membership changes" only reconcile if the key is
   a function of who is actually in the group. Key = f"{soc_major}:{hash of the
   sorted person_index set}". A P2.1 correction therefore produces a natural
   cache MISS and orphans the old entry; there is no invalidation logic to get
   wrong. The group prefix is not needed for uniqueness (membership sets are
   disjoint) — it is there so a session-state dump is readable when something
   goes wrong.

   Rejected: keying on the title multiset. It would avoid a redundant call when
   two members swap and the titles are unchanged, but it would then NOT
   regenerate on a membership change that preserved the multiset — a DoD
   criterion failing quietly, which is precisely the failure mode this project
   is designed against. One redundant call in a rare case is the cheaper error.

2. THIS IS A SESSION MEMO, NOT @st.cache_data. Decision log 7.4: anything that
   changes within a session must not be Streamlit-cached (a stale @st.cache_data
   entry once outlived the empty CSV it captured). The cache lives in
   st.session_state, is keyed by membership, and dies with the session — which
   also keeps the Version A promise: nothing is written server-side.

3. LAZY GENERATION ON GROUP SELECTION. 18 classified groups generated eagerly at
   boot would be 18 calls, most never read. The P2.6a multi-select is the
   trigger. Consequence accepted knowingly: selecting five uncached groups at
   once runs five sequential calls behind one spinner, so the first multi-select
   of a session feels slow. A "generate" button would fix the latency and lose
   "auto-generated" from the DoD.

4. FLOOR OF 5 MEMBERS. A 2-3 sentence summary of the "composition" of a group of
   one is a description of a named individual derived from their title. That is
   the Amendment 2 boundary, not a nicety. Below the floor, render the member
   count and the verbatim titles instead — both are already visible on cards and
   in search, so nothing is inferred about anyone.

5. TITLES ONLY LEAVE THE BROWSER. No names (identities are not needed for the
   task, and the ephemerality promise is easier to keep if they never go out) and
   no companies (company encodes industry rather than occupation — measured as a
   distractor for the classifier in four runs, and the same distractor here).
   Titles are de-duplicated with counts so twelve identical roles do not spend
   twelve slots against the cap. Over the cap, the true member count goes in the
   prompt and the summary says it describes a sample.

6. FAILURE FALLS BACK TO THE FLOOR RENDERING. No key, a raised exception, an
   unusable response — all degrade to count-plus-verbatim-titles with a one-line
   note, never to fabricated prose. Useful side effect: the P2.9a demo deploy
   renders a truthful panel with no key configured rather than an error card.

The membership predicate is display_state == "classified", NOT
soc_major == code. Unreviewed abstains carry "99" and resolved ones carry the
NOT_OCCUPATION sentinel, and both are values in the soc_major column; filtering
on the code alone would eventually render a summary of "group 99", which is not
a group. Filtering on display_state makes that unreachable.

Nothing here attributes a skill, tool, or capability to a named individual. A
summary describes an occupational group, in aggregate, from job titles the user
already holds.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional, Sequence

import pandas as pd

from src.dashboard.state import (
    STATE_CLASSIFIED,
    STATE_NEEDS_REVIEW,
    STATE_NOT_CLASSIFIED,
    STATE_NOT_OCCUPATION,
    require_known_state,
)
from src.onet import MAJOR_GROUP_NAMES

# --- constants ---------------------------------------------------------------

MODEL = "claude-sonnet-5"
# D-45: adaptive thinking shares this budget with the answer (D-16, D-42).
# tools/probe_summaries on 10 real groups (21 Sep 2026): no call thought,
# peak output 207 tokens. 400 fitted only because the model chose not to
# think; a single thinking block would have used all of it. max_tokens is
# a ceiling, billed only on use, so 8000 (as in assistant.py and
# claude_classifier.py) costs nothing when it is not needed.
MAX_TOKENS = 8000

# NOTE: no `temperature`. The API rejects it for this model — `temperature` is
# deprecated for claude-sonnet-5 and sending it returns a 400, which the caller
# then degrades to "unavailable". claude_classifier.py has never sent it either.
# Wording stability comes from the membership cache, not from a sampling
# parameter, so nothing is lost. Do not reintroduce it; a test guards this.

# Below this, no prose is generated — see design decision 4.
MIN_GROUP_SIZE = 5

# Cap on DISTINCT titles sent in one prompt. 430-node networks never approach it;
# a much larger uploaded network degrades honestly rather than truncating in
# silence (the prompt states the true count and the summary says it is a sample).
MAX_TITLES = 150

# Session-state key for the memo. Distinct from state.CORRECTIONS_KEY.
SUMMARIES_KEY = "cluster_summaries"

# The three outcomes render() branches on.
STATUS_SUMMARY = "summary"
STATUS_TOO_SMALL = "too_small"
STATUS_UNAVAILABLE = "unavailable"

NOTE_TOO_SMALL = (
    f"Fewer than {MIN_GROUP_SIZE} people in this group — showing the titles "
    "rather than a generated summary."
)
NOTE_UNAVAILABLE = (
    "Summaries are unavailable right now — showing the titles instead."
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write short, factual descriptions of occupational groups within a person's professional network.

You are given the name of a SOC major group and the job titles of the people in that group, with counts. Write 2-3 sentences describing what this group is composed of.

Rules:
1. Describe ONLY the titles you are given. Do not add occupations, sectors, skills, tools, or seniority patterns that are not evident in the list.
2. Never name or refer to an individual. Describe the group in aggregate.
3. Do not restate what the SOC group means in general. The reader can see the group name; they want to know who is in THEIR group.
4. Note genuine concentrations or spreads if the list shows them (e.g. mostly analyst-level, or split between two distinct functions). Do not invent one if the list is flat.
5. Plain British English. No bullet points, no headings, no preamble. Output the 2-3 sentences and nothing else.
6. If the titles are too sparse or generic to say anything specific, say so plainly in one sentence rather than padding."""


# --- results -----------------------------------------------------------------

@dataclass(frozen=True)
class Coverage:
    """How much of the network the summaries collectively describe.

    `classified` and `summarised` differ, and the difference is the point: a
    person in a group below the size floor HAS a group but gets no prose. Before
    the floor existed these were the same number, and reporting `classified` as
    coverage silently counted those people as summarised when they were not.
    """

    total: int
    classified: int
    summarised: int
    below_floor: int
    needs_review: int
    not_occupation: int
    # P2.9b. Its own field, never added to needs_review: the four state counts
    # partition the total, and a caption that folded these into the review
    # backlog would ask the user to review people nobody has judged.
    not_classified: int = 0


@dataclass(frozen=True)
class GroupSummary:
    """One group's panel content. `status` selects the renderer branch."""

    soc_major: str
    group_name: str
    status: str
    n_members: int
    titles: tuple[str, ...] = ()
    text: Optional[str] = None
    cache_key: Optional[str] = None
    from_cache: bool = False


# --- pure core: membership and keys ------------------------------------------

def membership_key(person_indices: Iterable[int]) -> str:
    """Stable, order-independent signature of a set of person_index values.

    Sorted and de-duplicated before hashing, so the key depends on WHO is in the
    group and nothing else — not row order, not how many times a caller passed
    the same index.
    """
    unique_sorted = sorted({int(i) for i in person_indices})
    payload = ",".join(str(i) for i in unique_sorted).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def cache_key(soc_major: str, person_indices: Iterable[int]) -> str:
    """The memo key: group code plus membership signature."""
    return f"{soc_major}:{membership_key(person_indices)}"


def group_members(df: pd.DataFrame, soc_major: str) -> pd.DataFrame:
    """Rows currently IN `soc_major`, per the corrected display table.

    Predicate is display_state == classified AND soc_major == code. The
    display_state half is load-bearing: "99" (unreviewed abstain) and the
    NOT_OCCUPATION sentinel are both values of the soc_major column, and neither
    names a group.
    """
    if "display_state" not in df.columns or "soc_major" not in df.columns:
        return df.iloc[0:0]
    mask = (df["display_state"] == STATE_CLASSIFIED) & (
        df["soc_major"].astype(str) == str(soc_major)
    )
    return df.loc[mask]


def member_titles(members: pd.DataFrame) -> tuple[str, ...]:
    """Verbatim `role` strings for the members, blanks and NaN dropped."""
    if "role" not in members.columns:
        return ()
    roles = members["role"].fillna("").astype(str).str.strip()
    return tuple(r for r in roles if r)


def title_counts(titles: Sequence[str], cap: int = MAX_TITLES) -> list[tuple[str, int]]:
    """De-duplicate titles into (title, count), commonest first, then A-Z.

    Capped at `cap` DISTINCT titles. Counting rather than repeating means a
    group of forty with six distinct roles costs six lines, not forty.
    """
    counts = Counter(t.strip() for t in titles if t and t.strip())
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return ordered[:cap]


# --- pure core: coverage ------------------------------------------------------

def coverage_counts(
    df: pd.DataFrame, min_group_size: int = MIN_GROUP_SIZE
) -> Coverage:
    """Live counts across the four display states, plus the size-floor split.

    Never cached (log 7.4): group sizes move as corrections land, so a node can
    cross the floor mid-session and the counts must follow.
    """
    if "display_state" not in df.columns:
        return Coverage(
            total=len(df), classified=0, summarised=0,
            below_floor=0, needs_review=0, not_occupation=0,
            not_classified=0,
        )

    states = df["display_state"]
    for value in states.unique():
        require_known_state(value)   # D-54: no state counted as "other"
    classified_mask = states == STATE_CLASSIFIED
    classified = int(classified_mask.sum())

    below_floor = 0
    if classified and "soc_major" in df.columns:
        sizes = df.loc[classified_mask, "soc_major"].astype(str).value_counts()
        below_floor = int(sizes[sizes < min_group_size].sum())

    return Coverage(
        total=int(len(df)),
        classified=classified,
        summarised=classified - below_floor,
        below_floor=below_floor,
        needs_review=int((states == STATE_NEEDS_REVIEW).sum()),
        not_occupation=int((states == STATE_NOT_OCCUPATION).sum()),
        not_classified=int((states == STATE_NOT_CLASSIFIED).sum()),
    )


def coverage_sentence(df: pd.DataFrame) -> str:
    """The panel's honesty line: what the summaries do NOT describe.

    Needs-review, not-an-occupation and not-classified are reported SEPARATELY.
    They are three different facts: an unanswered question, a resolved verdict,
    and a question never asked.
    Folding them together would overstate the gap. The sub-floor group is a
    third, separate case: those people ARE grouped and their titles ARE shown,
    they simply get no prose — so they are neither covered nor a gap in the
    classification.
    """
    c = coverage_counts(df)
    if c.total == 0:
        return "No connections loaded."

    if c.summarised == c.total:
        return f"Summaries cover all {c.total} connections."

    if c.summarised == c.classified:
        lead = f"Written summaries exist for all {c.classified} classified connections."
    else:
        lead = (  # count-exempt: guarded at L282/285
            f"Written summaries exist for {c.summarised} of the "
            f"{c.classified} classified connections."
        )
    clauses = []
    if c.below_floor:
        clauses.append(
            f"{c.below_floor} are in groups too small to summarise"
        )
    if c.needs_review:
        clauses.append(
            f"{c.needs_review} still need review and belong to no group yet"
        )
    if c.not_classified:
        # Its own clause, never added to the review figure: these people were
        # never judged, so asking the user to review them would be a lie about
        # what the classifier did (D-42).
        clauses.append(f"{c.not_classified} are not classified yet")
    if c.not_occupation:
        clauses.append(f"{c.not_occupation} are marked not an occupation")
    if not clauses:
        return lead
    return f"{lead} " + "; ".join(clauses) + "."


# --- pure core: prompt and generation ----------------------------------------

def build_prompt(
    group_name: str,
    counted_titles: Sequence[tuple[str, int]],
    n_members: int,
) -> str:
    """The user message. Titles only — no names, no companies (decision 5)."""
    lines = [
        f"{title} x{count}" if count > 1 else title
        for title, count in counted_titles
    ]
    shown = sum(count for _, count in counted_titles)

    header = f"SOC major group: {group_name}\nPeople in this group: {n_members}"
    if shown < n_members:
        header += (
            f"\nThe list below covers {shown} of them, a sample. Say that your "
            "description is based on a sample."
        )
    return f"{header}\n\nJob titles:\n" + "\n".join(lines)


def _extract_text(response) -> str:
    """Concatenate the text blocks of an Anthropic response."""
    return "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()


def generate_summary(
    group_name: str,
    counted_titles: Sequence[tuple[str, int]],
    n_members: int,
    client=None,
    model: str = MODEL,
) -> Optional[str]:
    """Return 2-3 sentences, or None if anything at all goes wrong.

    None is a first-class outcome, not an error path bolted on: a missing key, a
    network failure, a malformed response and an empty response all mean the same
    thing to the caller — no summary. Never raises, never returns invented prose.

    D-45: a response cut off at max_tokens is a failed call, not a short
    summary, and returns None rather than a half sentence. Truncated and
    empty responses are logged, so the terminal can tell them apart from a
    missing key.
    """
    if not counted_titles:
        return None
    try:
        if client is None:
            client = _default_client()
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_prompt(group_name, counted_titles, n_members),
                }
            ],
        )
        text = _extract_text(response)
    except Exception as exc:
        # Swallowed for the UI (decision 6), but never silently: without this the
        # terminal cannot distinguish "no key", "bad request" and "empty
        # response", which are three different fixes wearing the same face.
        logger.warning("summary generation failed: %s", exc, exc_info=True)
        return None
    stop = getattr(response, "stop_reason", None)
    blocks = [getattr(b, "type", "?") for b in getattr(response, "content", [])]
    if stop == "max_tokens":
        logger.warning(
            "summary cut off at max_tokens=%s; not shown, not cached (blocks: %s)",
            MAX_TOKENS, blocks,
        )
        return None
    if not text:
        logger.warning(
            "summary response had no text (stop_reason=%r, blocks: %s)", stop, blocks
        )
        return None
    return text


def _default_client():
    """D-55: one resolver. Raises MissingKeyError, not RuntimeError — a caller
    catching one used to miss the other."""
    from src.dashboard.keys import resolve_client

    return resolve_client()


# --- pure core: the one entry point ------------------------------------------

def summarise_group(
    df: pd.DataFrame,
    soc_major: str,
    cache: dict[str, str],
    client=None,
    model: str = MODEL,
    min_group_size: int = MIN_GROUP_SIZE,
) -> GroupSummary:
    """Cache-first summary for one group. Mutates `cache` on a successful call.

    Order matters: the size floor is checked BEFORE the cache and before the
    client, so a small group can never trigger an API call regardless of state.
    A failed generation is NOT cached — the next rerun should retry, since the
    cause (no key, transient network) may have been fixed.
    """
    soc_major = str(soc_major)
    group_name = MAJOR_GROUP_NAMES.get(soc_major, soc_major)

    members = group_members(df, soc_major)
    titles = member_titles(members)
    n_members = int(len(members))

    if n_members < min_group_size:
        return GroupSummary(
            soc_major=soc_major,
            group_name=group_name,
            status=STATUS_TOO_SMALL,
            n_members=n_members,
            titles=titles,
        )

    key = cache_key(soc_major, members["person_index"])
    if key in cache:
        return GroupSummary(
            soc_major=soc_major,
            group_name=group_name,
            status=STATUS_SUMMARY,
            n_members=n_members,
            titles=titles,
            text=cache[key],
            cache_key=key,
            from_cache=True,
        )

    text = generate_summary(
        group_name, title_counts(titles), n_members, client=client, model=model
    )
    if text is None:
        return GroupSummary(
            soc_major=soc_major,
            group_name=group_name,
            status=STATUS_UNAVAILABLE,
            n_members=n_members,
            titles=titles,
            cache_key=key,
        )

    cache[key] = text
    return GroupSummary(
        soc_major=soc_major,
        group_name=group_name,
        status=STATUS_SUMMARY,
        n_members=n_members,
        titles=titles,
        text=text,
        cache_key=key,
        from_cache=False,
    )


# --- streamlit glue (lazy import) --------------------------------------------

def init_summaries() -> None:
    """Ensure the memo exists in session state. Idempotent."""
    import streamlit as st

    if SUMMARIES_KEY not in st.session_state:
        st.session_state[SUMMARIES_KEY] = {}


def get_summaries_cache() -> dict[str, str]:
    import streamlit as st

    init_summaries()
    return st.session_state[SUMMARIES_KEY]


def clear_summaries() -> None:
    """Drop every memoised summary (a session-reset control)."""
    get_summaries_cache().clear()


def get_group_summary(df: pd.DataFrame, soc_major: str, client=None) -> GroupSummary:
    """Session-cached summary for one group, read through the display table."""
    return summarise_group(df, soc_major, get_summaries_cache(), client=client)


def render_summaries_panel(
    df: pd.DataFrame,
    selected_groups: Sequence[str],
    client=None,
) -> None:
    """Render the coverage line and a summary block per selected group.

    `df` MUST be state.get_display_table() output, never the raw CSV, or
    corrections are invisible here and the regenerate-on-change DoD fails.
    """
    import streamlit as st

    st.caption(coverage_sentence(df))

    if not selected_groups:
        st.caption("Select a group to see a summary of who is in it.")
        return

    # D-80: charged to the daily ledger on the project key, and never to the
    # chat's question count. A visitor did not ask for these.
    from src.dashboard.keys import key_source
    from src.dashboard.metering import BUDGET_SPENT_NOTE, budget_spent, metered_client

    source = key_source()
    if budget_spent(source):
        st.caption(BUDGET_SPENT_NOTE)
    client = metered_client(source, client, _default_client)

    cache = get_summaries_cache()
    for soc_major in selected_groups:
        result = summarise_group(df, soc_major, cache, client=client)
        _render_one(st, result)


def _render_one(st, result: GroupSummary) -> None:
    """One group's block. too_small and unavailable share a renderer by design."""
    st.markdown(f"**{result.group_name}** — {result.n_members} people")

    if result.status == STATUS_SUMMARY:
        st.write(result.text)
        return

    st.caption(
        NOTE_TOO_SMALL if result.status == STATUS_TOO_SMALL else NOTE_UNAVAILABLE
    )
    for title, count in title_counts(result.titles):
        st.markdown(f"- {title}" + (f" ×{count}" if count > 1 else ""))