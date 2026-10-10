"""D-42: a failed call must never be cached or returned as an abstention."""

import json
from dataclasses import dataclass, field

import pytest

from src import claude_classifier as cc


@dataclass
class _Block:
    text: str
    type: str = "text"


@dataclass
class _Resp:
    content: list
    stop_reason: str = "end_turn"


@dataclass
class _Client:
    """Answers batches of at most `max_ok` items; truncates anything larger."""
    max_ok: int = 10
    answered: int = 0
    calls: list = field(default_factory=list)
    partial_once: bool = False

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, system, messages):
        n = messages[0]["content"].count("\n. title: ") or messages[0]["content"].count(". title: ")
        self.calls.append(n)
        if n > self.max_ok:
            return _Resp([_Block("")], stop_reason="max_tokens")
        objs = [{"i": i, "soc": "13", "confidence": "high", "why": "ok"} for i in range(n)]
        if self.partial_once and n > 1:
            self.partial_once = False
            objs = objs[:-1]                      # one record short: parser pads it
        self.answered += n
        return _Resp([_Block(json.dumps(objs))])


def items(n):
    return [(f"Title {i}", "") for i in range(n)]


def test_truncated_batch_is_split_and_answered(tmp_path):
    client = _Client(max_ok=10)
    out = cc.classify_claude(items(20), client=client, cache_path=tmp_path / "c.json")
    assert len(out) == 20 and all(c.tier == "claude" for c in out)
    assert client.calls[0] == 20 and max(client.calls[1:]) <= 10


def test_nothing_unparsed_reaches_the_cache(tmp_path):
    path = tmp_path / "c.json"
    cc.classify_claude(items(20), client=_Client(max_ok=10), cache_path=path)
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert len(cache) == 20
    assert not [k for k, v in cache.items() if v.get("why") == "unparsed"]


def test_a_padded_record_is_retried_not_cached(tmp_path):
    path = tmp_path / "c.json"
    client = _Client(max_ok=20, partial_once=True)
    out = cc.classify_claude(items(5), client=client, cache_path=path)
    assert len(client.calls) > 1                  # the padded record was asked again
    assert all(c.tier == "claude" for c in out)
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert not [k for k, v in cache.items() if v.get("why") == "unparsed"]


def test_unanswerable_title_raises_rather_than_abstaining(tmp_path):
    path = tmp_path / "c.json"
    with pytest.raises(cc.ClassificationFailed):
        cc.classify_claude(items(4), client=_Client(max_ok=0), cache_path=path)
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_successes_survive_a_later_failure(tmp_path):
    path = tmp_path / "c.json"

    class _Flaky(_Client):
        def create(self, *, model, max_tokens, system, messages):
            if "Title 3" in messages[0]["content"]:
                return _Resp([_Block("")], stop_reason="max_tokens")
            return super().create(model=model, max_tokens=max_tokens, system=system, messages=messages)

    with pytest.raises(cc.ClassificationFailed):
        cc.classify_claude(items(4), client=_Flaky(max_ok=20), cache_path=path, batch_size=1)
    cache = json.loads(path.read_text(encoding="utf-8"))
    assert len(cache) == 3 and not [v for v in cache.values() if v.get("why") == "unparsed"]


def test_cached_titles_are_never_re_requested(tmp_path):
    path = tmp_path / "c.json"
    first = _Client(max_ok=20)
    cc.classify_claude(items(5), client=first, cache_path=path)
    second = _Client(max_ok=20)
    cc.classify_claude(items(5), client=second, cache_path=path)
    assert second.calls == []
