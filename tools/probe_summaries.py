"""tools/probe_summaries.py - D-45: do group summaries fit in their token budget?

summaries.py calls claude-sonnet-5 with MAX_TOKENS = 400. D-16 and D-42 showed
that adaptive thinking shares that budget with the answer. generate_summary()
never reads stop_reason, so two failures are possible and neither is visible:

  EMPTY      thinking used the budget, no text came back. generate_summary()
             returns None and the panel says "unavailable", the same thing it
             says when there is no API key.
  TRUNCATED  text came back but was cut off at the ceiling. It is returned as
             a finished summary and shown to the user mid-sentence.

This replays each eligible group through the same model, system prompt, prompt
builder and text extraction as the dashboard, at the shipped budget and at a
larger one, and reports what came back. No title or summary text is printed.
Nothing is cached.

Costs one call per eligible group per budget (about 30 calls by default).

    python -m tools.probe_summaries
    python -m tools.probe_summaries --budgets 400 1000 2000 8000 --limit 5

Exits 1 if any call at the shipped budget was EMPTY or TRUNCATED.
"""
from __future__ import annotations

import argparse
import re
import sys

from src.dashboard.loader import load_display_table
from src.dashboard.state import STATE_CLASSIFIED
from src.dashboard import summaries as sm

OK, EMPTY, TRUNCATED = "ok", "EMPTY", "TRUNCATED"


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+", text) if s.strip()])


def _call(client, prompt: str, max_tokens: int) -> dict:
    resp = client.messages.create(
        model=sm.MODEL,
        max_tokens=max_tokens,
        system=sm.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = sm._extract_text(resp)
    stop = getattr(resp, "stop_reason", None)
    if not text:
        verdict = EMPTY
    elif stop == "max_tokens":
        verdict = TRUNCATED
    else:
        verdict = OK
    return {
        "stop": stop,
        "out": getattr(getattr(resp, "usage", None), "output_tokens", None),
        "blocks": [getattr(b, "type", "?") for b in resp.content],
        "chars": len(text),
        "sentences": _sentences(text),
        "verdict": verdict,
    }


def eligible_groups(df) -> list[str]:
    codes = sorted(df.loc[df["display_state"] == STATE_CLASSIFIED, "soc_major"].astype(str).unique())
    return [c for c in codes if len(sm.group_members(df, c)) >= sm.MIN_GROUP_SIZE]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budgets", type=int, nargs="+", default=[sm.MAX_TOKENS, 8000])
    ap.add_argument("--limit", type=int, default=None, help="probe only the first N groups")
    args = ap.parse_args()

    try:  # tools/ reads the key from .env; the app reads it from the environment
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    df = load_display_table(with_coords=False, corrections={}, notes_overlay=None)
    groups = eligible_groups(df)[: args.limit]
    client = sm._default_client()
    print(f"model {sm.MODEL}; shipped MAX_TOKENS {sm.MAX_TOKENS}; {len(groups)} groups; "
          f"budgets {args.budgets}\n")
    print(f"{'group':>5} {'n':>4} {'titles':>6} | {'budget':>6} {'stop':>10} {'out':>5} "
          f"{'chars':>5} {'sent':>4}  verdict  blocks")

    tally: dict[int, dict[str, int]] = {b: {OK: 0, EMPTY: 0, TRUNCATED: 0} for b in args.budgets}
    for code in groups:
        members = sm.group_members(df, code)
        counted = sm.title_counts(sm.member_titles(members))
        prompt = sm.build_prompt(sm.MAJOR_GROUP_NAMES.get(code, code), counted, len(members))
        for b in args.budgets:
            r = _call(client, prompt, b)
            tally[b][r["verdict"]] += 1
            print(f"{code:>5} {len(members):>4} {len(counted):>6} | {b:>6} {str(r['stop']):>10} "
                  f"{str(r['out']):>5} {r['chars']:>5} {r['sentences']:>4}  {r['verdict']:<8} "
                  f"{r['blocks']}")

    print("\nper budget:")
    for b, t in tally.items():
        mark = "  <- shipped" if b == sm.MAX_TOKENS else ""
        print(f"  {b:>6}: {t[OK]} ok, {t[EMPTY]} empty, {t[TRUNCATED]} truncated{mark}")
    shipped = tally.get(sm.MAX_TOKENS)
    return 1 if shipped and (shipped[EMPTY] or shipped[TRUNCATED]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
