"""
src/timing.py — P2.11: where a build's seconds go.

A keyed build of 442 people takes about five minutes (D-72), and nothing says
which part of it. This prints one line per stage and one per classifier batch
to stdout, the same channel the loader's "Read 442 rows from ..." uses, so the
lines land in the terminal locally and in the log on Community Cloud.

Off unless NV_TIMING is set (to anything but 0/false/no). Read at call time,
not at import, so a test or a shell can turn it on without a reload.

Every line starts with [timing], so `grep "\\[timing\\]"` is the whole report:

    [timing] build start
    [timing] build stage parse elapsed=0.04s
    [timing] classify cache titles=384 hits=5 api=379 batches=19
    [timing] classify batch 7/19 titles=20 calls=1 elapsed=13.8s source=api stop_reason=end_turn out_tokens=1925
    [timing] build summary total=318.4s parse=0.04s ... other=0.6s batches=19 mean_batch=15.1s cache_hits=5 api_calls=19

`other` in the summary is total minus the named stages, so time spent between
the boundaries shows up as a number rather than vanishing from the sum.

The stage names here are the boundaries D-72's progress indicator will report
against. That's why they are named in one place and not printed ad hoc.
"""

from __future__ import annotations

import functools
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator, Optional

ENV_VAR = "NV_TIMING"
PREFIX = "[timing]"

# Stage names, in the order build_network runs them. Graph comes before
# classification and metrics after it: the layout doesn't need the classifier,
# but the centrality join is done once the groups are known.
PARSE = "parse"
EMBED = "embed"
UMAP = "umap"
GRAPH = "graph"
CLASSIFY = "classify"
METRICS = "metrics"
RENDER = "render"

_OFF = {"", "0", "false", "no", "off"}


def enabled() -> bool:
    return os.environ.get(ENV_VAR, "").strip().lower() not in _OFF


def emit(text: str) -> None:
    # flush: Streamlit's stdout is block-buffered when it isn't a terminal,
    # and a line that arrives after the build is no use for seeing a hang.
    print(f"{PREFIX} {text}", flush=True)


@dataclass
class Batch:
    index: int
    total: int
    titles: int
    stop_reasons: list[str] = field(default_factory=list)
    elapsed: float = 0.0


@dataclass
class Run:
    label: str
    started: float
    stages: dict[str, float] = field(default_factory=dict)
    batches: list[Batch] = field(default_factory=list)
    cache_hits: int = 0


# One build per Streamlit script thread, and a context variable is per
# thread, so two sessions building at once don't write into each other's run.
_current: ContextVar[Optional[Run]] = ContextVar("timing_run", default=None)
_batch: ContextVar[Optional[Batch]] = ContextVar("timing_batch", default=None)


def _prefix() -> str:
    run_ = _current.get()
    return run_.label if run_ is not None else "-"


@contextmanager
def run(label: str) -> Iterator[Optional[Run]]:
    """A build (or retry) from start to summary. A no-op when timing is off."""
    if not enabled():
        yield None
        return
    current = Run(label=label, started=time.perf_counter())
    token = _current.set(current)
    emit(f"{label} start")
    failed = False
    try:
        yield current
    except BaseException:
        failed = True
        raise
    finally:
        _current.reset(token)
        emit(summary(current, time.perf_counter() - current.started, failed))


def timed(label: str):
    """`run(label)` around every call of the decorated function."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with run(label):
                return fn(*args, **kwargs)
        return inner
    return wrap


def summary(run_: Run, total: float, failed: bool = False) -> str:
    parts = [f"{run_.label} summary total={total:.2f}s"]
    parts += [f"{name}={secs:.2f}s" for name, secs in run_.stages.items()]
    parts.append(f"other={total - sum(run_.stages.values()):.2f}s")
    n = len(run_.batches)
    mean = sum(b.elapsed for b in run_.batches) / n if n else 0.0
    parts.append(f"batches={n} mean_batch={mean:.2f}s")
    parts.append(f"cache_hits={run_.cache_hits}")
    parts.append(f"api_calls={sum(len(b.stop_reasons) for b in run_.batches)}")
    if failed:
        parts.append("status=error")
    return " ".join(parts)


@contextmanager
def stage(name: str, **fields) -> Iterator[None]:
    """One stage boundary: a line when it ends, and a total in the summary."""
    if not enabled():
        yield
        return
    started = time.perf_counter()
    status = ""
    try:
        yield
    except BaseException as exc:
        status = f" status=error:{type(exc).__name__}"
        raise
    finally:
        elapsed = time.perf_counter() - started
        run_ = _current.get()
        if run_ is not None:
            run_.stages[name] = run_.stages.get(name, 0.0) + elapsed
        extra = "".join(f" {k}={v}" for k, v in fields.items())
        emit(f"{_prefix()} stage {name} elapsed={elapsed:.2f}s{extra}{status}")


def cache(titles: int, hits: int, batches: int) -> None:
    """What the classifier's cache answered before any batch was sent.

    A cache hit never joins a batch: the cached titles are taken out before
    batching, so every batch line is an API batch, and the hits are counted here.
    """
    if not enabled():
        return
    run_ = _current.get()
    if run_ is not None:
        run_.cache_hits += hits
    emit(f"classify cache titles={titles} hits={hits} api={titles - hits} "
         f"batches={batches}")


@contextmanager
def batch(index: int, total: int, titles: int, usage=None) -> Iterator[None]:
    """One classifier batch, 1-based `index` of `total`.

    A batch can be more than one call: a truncated response is split and
    retried, so `calls` and every call's stop_reason are reported, not only
    the first. `usage` is read on the way out for output tokens, which
    include the adaptive thinking, the likeliest reason one batch is slower
    than another.
    """
    if not enabled():
        yield
        return
    current = Batch(index=index, total=total, titles=titles)
    token = _batch.set(current)
    started = time.perf_counter()
    try:
        yield
    except BaseException as exc:
        current.stop_reasons.append(f"error:{type(exc).__name__}")
        raise
    finally:
        _batch.reset(token)
        current.elapsed = time.perf_counter() - started
        run_ = _current.get()
        if run_ is not None:
            run_.batches.append(current)
        out = getattr(usage, "output_tokens", None)
        emit(
            f"classify batch {index}/{total} titles={titles} "
            f"calls={len(current.stop_reasons)} elapsed={current.elapsed:.2f}s "
            f"source=api stop_reason={','.join(current.stop_reasons) or 'none'}"
            + (f" out_tokens={out}" if out is not None else "")
        )


def call(stop_reason: Optional[str]) -> None:
    """One API response inside the current batch."""
    current = _batch.get()
    if current is not None:
        current.stop_reasons.append(str(stop_reason))


def stopped(index: int, total: int, reason: str) -> None:
    """The batch loop ended at batch `index`: refused before it was sent (a
    cap), or failed in it (an API error). No later batch was sent."""
    if enabled():
        emit(f"classify stopped at batch {index}/{total} reason={reason}")
