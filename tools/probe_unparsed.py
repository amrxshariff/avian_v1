"""tools/probe_unparsed.py - D-42: why do batches come back unparsed?

Replays real titles whose cached record is a padded abstain, using the same
model, prompt and parser as classify_claude, and reports what the API actually
returned. Three calls by default: current settings, a bigger token budget, and
a smaller batch.

No title text is printed. Nothing is written to the cache.

    python -m tools.probe_unparsed
"""

from __future__ import annotations

import json

from src import claude_classifier as cc
from src.dashboard.loader import load_base_frame


def affected_titles() -> list[str]:
    cache = json.loads(cc.CACHE_PATH.read_text(encoding="utf-8"))
    bad = {k for k, v in cache.items() if v.get("why") == "unparsed"}
    roles = load_base_frame()["role"].fillna("").str.strip()
    hit = [t for t in dict.fromkeys(roles) if t and cc._cache_key(t, "") in bad]
    return hit


def probe(client, titles: list[str], max_tokens: int, label: str) -> None:
    items = [(t, "") for t in titles]
    resp = client.messages.create(
        model=cc.MODEL,
        max_tokens=max_tokens,
        system=cc.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": cc._build_user_message(items)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    kinds = [getattr(b, "type", "?") for b in resp.content]
    recs = cc._parse_response(text, len(items))
    answered = sum(1 for r in recs if r["why"] != "unparsed")
    print(f"\n[{label}] batch={len(items)} max_tokens={max_tokens}")
    print(f"  stop_reason : {resp.stop_reason}")
    print(f"  output_tok  : {resp.usage.output_tokens}")
    print(f"  block types : {kinds}")
    print(f"  text chars  : {len(text)}   parsed: {answered}/{len(items)}")
    if text:
        print(f"  text tail   : ...{text[-120:]!r}")


def main() -> None:
    titles = affected_titles()
    print(f"{len(titles)} distinct titles in the node table carry a padded 'unparsed' record.")
    if not titles:
        return
    client = cc._default_client()
    probe(client, titles[:cc.BATCH_SIZE], cc.MAX_TOKENS, "as shipped")
    probe(client, titles[:cc.BATCH_SIZE], 8000, "bigger budget")
    probe(client, titles[:5], cc.MAX_TOKENS, "smaller batch")


if __name__ == "__main__":
    main()
