"""
tests/test_timing.py — P2.11: the build's stage timings.

The lines are a measuring instrument, so the tests check what each one claims:
every stage reported, in the order it runs; a batch line for every batch sent
and none for a cached title; a split batch reports all its calls; a failed or
stopped run still ends with a summary. And none of it prints unless asked.

Elapsed times are not asserted. They are what the instrument is for, and a
test that pinned one would be pinning the machine.

Run from the repo root:
    python -m pytest tests/test_timing.py -v
"""

from __future__ import annotations

import re
import threading

import pytest

from src import timing
from src.build import InvalidExport, MIN_PEOPLE, retry_unclassified
from tests.test_build import RateLimitError, _Client, _build, _meters, _people

STAGES = ["parse", "embed", "umap", "graph", "classify", "metrics"]


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv(timing.ENV_VAR, "1")


def _lines(capsys) -> list[str]:
    return [l for l in capsys.readouterr().out.splitlines()
            if l.startswith(timing.PREFIX)]


def _field(line: str, name: str) -> str:
    match = re.search(rf"\b{name}=(\S+)", line)
    assert match, f"{name}= missing from {line!r}"
    return match.group(1)


def _distinct(n: int) -> list:
    return _people(n, titles=[f"Role {i}" for i in range(n)])


# --- off unless asked ---------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "0", "false", "No", "off"])
def test_nothing_prints_unless_the_variable_says_so(monkeypatch, capsys,
                                                    tmp_path, value):
    if value is None:
        monkeypatch.delenv(timing.ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(timing.ENV_VAR, value)
    _build(_distinct(25), tmp_path=tmp_path)
    assert _lines(capsys) == []


# --- a clean build --------------------------------------------------------------


def test_every_stage_is_reported_once_in_the_order_it_runs(on, capsys, tmp_path):
    _build(_distinct(25), tmp_path=tmp_path)
    lines = _lines(capsys)
    assert lines[0] == "[timing] build start"
    stages = [re.match(r"\[timing\] build stage (\w+) ", l).group(1)
              for l in lines if " stage " in l]
    assert stages == STAGES
    assert lines[-1].startswith("[timing] build summary ")


def test_one_line_per_batch_with_its_titles_and_stop_reason(on, capsys, tmp_path):
    _build(_distinct(45), tmp_path=tmp_path)   # 45 distinct titles: 20 + 20 + 5
    lines = _lines(capsys)

    cache = [l for l in lines if " classify cache " in l]
    assert len(cache) == 1
    assert (_field(cache[0], "titles"), _field(cache[0], "hits"),
            _field(cache[0], "api"), _field(cache[0], "batches")) == ("45", "0", "45", "3")

    batches = [l for l in lines if " classify batch " in l]
    assert [re.search(r"batch (\d+/\d+)", l).group(1) for l in batches] == ["1/3", "2/3", "3/3"]
    assert [_field(l, "titles") for l in batches] == ["20", "20", "5"]
    assert {_field(l, "source") for l in batches} == {"api"}
    assert {_field(l, "stop_reason") for l in batches} == {"end_turn"}
    assert {_field(l, "calls") for l in batches} == {"1"}
    # Batch lines sit inside the classify stage: before its line, after graph's.
    graph_at = next(i for i, l in enumerate(lines) if " stage graph " in l)
    classify_at = next(i for i, l in enumerate(lines) if " stage classify " in l)
    assert all(graph_at < lines.index(l) < classify_at for l in batches)


def test_the_summary_totals_what_the_lines_reported(on, capsys, tmp_path):
    _build(_distinct(45), client=_Client(tokens_per_call=1500), tmp_path=tmp_path)
    lines = _lines(capsys)
    summary = lines[-1]

    assert (_field(summary, "batches"), _field(summary, "cache_hits"),
            _field(summary, "api_calls")) == ("3", "0", "3")
    batch_secs = [float(_field(l, "elapsed").rstrip("s"))
                  for l in lines if " classify batch " in l]
    assert float(_field(summary, "mean_batch").rstrip("s")) == pytest.approx(
        sum(batch_secs) / 3, abs=0.01)
    assert {_field(l, "out_tokens") for l in lines if " classify batch " in l} == {"1500"}

    # Every named stage plus `other` adds back up to the total, so time spent
    # between the boundaries can't go missing from the sum.
    parts = [float(_field(summary, s).rstrip("s")) for s in STAGES + ["other"]]
    assert sum(parts) == pytest.approx(float(_field(summary, "total").rstrip("s")),
                                       abs=0.05)
    assert float(_field(summary, "other").rstrip("s")) >= -0.01


# --- the cache --------------------------------------------------------------------


def test_cached_titles_are_counted_and_never_reported_as_a_batch(on, capsys, tmp_path):
    people = _distinct(25)
    _build(people, tmp_path=tmp_path)            # warms the cache
    capsys.readouterr()

    client = _Client()
    _build(people, client=client, tmp_path=tmp_path)
    lines = _lines(capsys)
    assert client.calls == []
    assert not [l for l in lines if " classify batch " in l]
    cache = next(l for l in lines if " classify cache " in l)
    assert (_field(cache, "hits"), _field(cache, "api"), _field(cache, "batches")) == ("25", "0", "0")
    assert (_field(lines[-1], "cache_hits"), _field(lines[-1], "batches")) == ("25", "0")


# --- what a batch can be besides one clean call -----------------------------------


def test_a_split_batch_reports_every_call_and_its_stop_reason(on, capsys, tmp_path):
    """A truncated batch is halved and resent, so one batch is several calls.
    Reporting only the first would hide where the batch's time went."""
    people = _distinct(20)
    client = _Client(unanswerable=frozenset({"Role 3"}))
    _build(people, client=client, tmp_path=tmp_path)
    batch = next(l for l in _lines(capsys) if " classify batch " in l)

    reasons = _field(batch, "stop_reason").split(",")
    assert int(_field(batch, "calls")) == len(client.calls) == len(reasons)
    assert reasons[0] == "max_tokens" and "end_turn" in reasons


def test_an_api_error_ends_the_batch_line_and_the_run_with_a_summary(on, capsys, tmp_path):
    _build(_distinct(45), client=_Client(fail_at=2, error=RateLimitError("slow")),
           tmp_path=tmp_path)
    lines = _lines(capsys)
    batches = [l for l in lines if " classify batch " in l]
    assert len(batches) == 2
    assert _field(batches[1], "stop_reason") == "error:RateLimitError"
    stop = next(l for l in lines if " classify stopped " in l)
    assert "batch 2/3" in stop and _field(stop, "reason") == "service_busy"
    assert lines[-1].startswith("[timing] build summary ")


def test_a_budget_stop_says_which_batch_it_refused(on, capsys, tmp_path):
    _build(_distinct(60), client=_Client(tokens_per_call=20_000),
           meters=_meters(tmp_path, generation_cap=0.22), tmp_path=tmp_path)
    lines = _lines(capsys)
    assert len([l for l in lines if " classify batch " in l]) == 1
    stop = next(l for l in lines if " classify stopped " in l)
    assert "batch 2/3" in stop and _field(stop, "reason") == "budget_reached"


def test_a_rejected_export_still_closes_its_run(on, capsys, tmp_path):
    with pytest.raises(InvalidExport):
        _build(_people(MIN_PEOPLE - 1), tmp_path=tmp_path)
    lines = _lines(capsys)
    parse = next(l for l in lines if " stage parse " in l)
    assert _field(parse, "status") == "error:InvalidExport"
    assert lines[-1].startswith("[timing] build summary ")
    assert _field(lines[-1], "status") == "error"


# --- the retry path ---------------------------------------------------------------


def test_a_retry_is_its_own_run(on, capsys, tmp_path):
    first = _build(_distinct(45), client=_Client(fail_at=2, error=RateLimitError("x")),
                   tmp_path=tmp_path)
    capsys.readouterr()
    retry_unclassified(first, client=_Client(), cache_path=tmp_path / "cache.json")
    lines = _lines(capsys)
    assert lines[0] == "[timing] retry start"
    assert any(l.startswith("[timing] retry stage classify ") for l in lines)
    assert lines[-1].startswith("[timing] retry summary ")
    assert _field(lines[-1], "batches") == "2"   # 25 titles left: 20 + 5


# --- isolation ----------------------------------------------------------------------


def test_a_run_in_one_thread_is_invisible_to_another(on, capsys):
    """Streamlit runs each session's script in its own thread. Two builds at
    once must not total into each other's summary."""
    seen = []
    with timing.run("build"):
        t = threading.Thread(target=lambda: seen.append(timing._current.get()))
        t.start()
        t.join()
    assert seen == [None]
