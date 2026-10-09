"""Verify the D-31 dependency manifests from scratch.

Builds two throwaway virtual environments with uv and checks each one:

  runtime  requirements.txt only (what Community Cloud installs)
           - every build-chain and dashboard module imports
           - no dev-only package is installed or loaded
           - app.py runs headlessly via streamlit.testing (AppTest), with
             ANTHROPIC_API_KEY removed so no paid call can happen
  dev      requirements.txt + requirements-dev.txt
           - the full test suite passes
           - tools.check_single_loader passes

It also checks that each lock is current: recompiling its .in file must not
change it, so an edited .in with a forgotten recompile fails here.

Run from the repo root with uv on PATH (python -m pip install uv):
    python -m tools.verify_manifests

Needs network access (PyPI). Uses uv's cache, so reruns are fast.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PY = "3.11"
ROOT = Path.cwd()

RUNTIME_MODULES = [
    # build chain (keep in step with tests/test_runtime_imports.py)
    "src.linkedin", "src.ingestion", "src.classify_pipeline", "src.embeddings",
    "src.projection_3d", "src.graph", "src.centrality",
    # dashboard and its third-party imports
    "src.assistant", "src.dashboard.loader", "src.dashboard.canvas",
    "src.dashboard.summaries", "src.dashboard.chat", "src.dashboard.session_io",
    "src.dashboard.people_list", "streamlit", "st_keyup",
]
DEV_ONLY = ["matplotlib", "faker", "dotenv", "pytest"]

RUNTIME_CHECK = f"""
import importlib, importlib.util, sys
for m in {RUNTIME_MODULES!r}:
    importlib.import_module(m)
loaded = [p for p in {DEV_ONLY!r} if p in sys.modules]
installed = [p for p in {DEV_ONLY!r} if importlib.util.find_spec(p) is not None]
assert not loaded, f"dev-only packages loaded: {{loaded}}"
assert not installed, f"dev-only packages installed: {{installed}}"
print(f"imported {{len({RUNTIME_MODULES!r})}} modules; no dev-only package installed or loaded")
"""

APPTEST_CHECK = """
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=300).run()
if at.exception:
    for e in at.exception:
        print("APP EXCEPTION:", e.message)
        print(e.stack_trace if hasattr(e, "stack_trace") else "")
    raise SystemExit(1)
print("app.py ran headlessly with no exception")
"""

results: list[tuple[str, bool]] = []


def run(label: str, cmd: list[str], env: dict | None = None) -> bool:
    print(f"\n--- {label}\n$ {' '.join(cmd)}", flush=True)
    ok = subprocess.run(cmd, cwd=ROOT, env=env).returncode == 0
    results.append((label, ok))
    print(f"--- {label}: {'PASS' if ok else 'FAIL'}", flush=True)
    return ok


def venv_python(venv: Path) -> str:
    return str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def make_env(tmp: Path, name: str, locks: list[str]) -> str | None:
    venv = tmp / name
    if not run(f"{name}: create venv", ["uv", "venv", "--python", PY, "--quiet", str(venv)]):
        return None
    py = venv_python(venv)
    if not run(f"{name}: sync {' + '.join(locks)}", ["uv", "pip", "sync", "--python", py, *locks]):
        return None
    return py


def check_fresh(tmp: Path, src: str, lock: str) -> None:
    # Recompile into a copy of the lock: uv prefers the copy's pins, so the
    # output is identical unless the .in and the lock disagree.
    copy = tmp / Path(lock).name
    shutil.copy(lock, copy)
    ok = run(f"lock current: {lock}", ["uv", "pip", "compile", src, "--universal",
             "--python-version", PY, "--quiet", "-o", str(copy)])
    body = lambda p: [l for l in Path(p).read_text().splitlines() if not l.startswith("#")]
    if ok and body(copy) != body(lock):
        results[-1] = (results[-1][0], False)
        print(f"--- {lock} is stale: recompile it from {src}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runtime-lock", default="requirements.txt")
    ap.add_argument("--dev-lock", default="requirements-dev.txt")
    ap.add_argument("--skip-freshness", action="store_true", help="skip the lock recompile check")
    ap.add_argument("--skip-apptest", action="store_true", help="skip the headless app run")
    args = ap.parse_args()

    if shutil.which("uv") is None:
        print("uv not found on PATH: python -m pip install uv")
        return 2

    with tempfile.TemporaryDirectory(prefix="nv_verify_") as t:
        tmp = Path(t)
        if not args.skip_freshness:
            check_fresh(tmp, "requirements.in", args.runtime_lock)
            check_fresh(tmp, "requirements-dev.in", args.dev_lock)

        py = make_env(tmp, "runtime", [args.runtime_lock])
        if py:
            run("runtime: imports and dev-only absence", [py, "-c", RUNTIME_CHECK])
            if not args.skip_apptest:
                env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
                run("runtime: app.py headless (no API key)", [py, "-c", APPTEST_CHECK], env=env)

        py = make_env(tmp, "dev", [args.runtime_lock, args.dev_lock])
        if py:
            run("dev: test suite", [py, "-m", "pytest", "tests", "-q"])
            run("dev: check_single_loader", [py, "-m", "tools.check_single_loader"])

    print("\n=== summary")
    for label, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = sum(not ok for _, ok in results)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
