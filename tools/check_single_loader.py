"""
tools/check_single_loader.py — P2.8b criterion 7.

Source-level, offline, no API. Asserts that src/dashboard/loader.py is the ONLY
place that assembles the display table.

A comment saying "always go through the loader" is a request. This is the
guarantee. It is the check that would have caught last session's drift on the
day it appeared, rather than three items later: check_chat_grounding.py composed
corrections but not notes, so it verified the payload against a frame the app
never actually sends.

Run from the repo root:

    python -m tools.check_single_loader
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from tools._markers import comment_markers

LOADER = Path("src/dashboard/loader.py")
APP = Path("app.py")

def _exempt_lines(text: str) -> dict[int, str]:
    """Line -> reason for every `# loader-exempt: <reason>` comment.

    A marker exempts ONLY its own line: this checker scans lines of text, so
    the offence is a line. tools/_markers.py explains why
    sweep_count_surfaces applies its markers differently (D-39). Parse
    failures are reported by criterion 2b, not here.
    """
    return comment_markers(text, "loader-exempt")


# Two files only. Everything else declares its exemption AT THE SITE with a
# `# loader-exempt: <reason>` comment, checked per line.
#
# D-33 is why. state.py sat here as "owns NODES_CSV as the base read", and that
# exemption WAS the defect - a second cached read of the node table, invisible
# to this checker for exactly as long as the entry stood. A file-level exemption
# also grants itself forward: a second read added later inherits the pass.
EXEMPT = {
    LOADER,                                  # the rule's subject
    Path("tools/check_single_loader.py"),    # names the paths as data
}

# Pipeline modules legitimately WRITE these files; the rule is about the
# dashboard reading them, so src/ outside dashboard/ is out of scope.
SCANNED_DIRS = (Path("src/dashboard"), Path("tools"))

DATA_PATHS = ("network_nodes.csv", "projected_3d.csv")

# Functions that, when CALLED outside the loader, mean the caller is assembling
# its own frame. Detected via the AST, not by substring: chat.py's docstring
# names get_display_table() to say where its argument must come from, and a
# checker that flags prose is a checker people learn to ignore.
ASSEMBLY_CALLS = frozenset(
    {"get_display_table", "apply_notes_from_session", "apply_corrections"}
)

# check_uncertainty_honesty.py calls apply_corrections inside C5 and C6, where a
# correction is the SUBJECT of the check rather than a way of assembling the
# frame — both operate on the frame the loader already returned. Verified by the
# "Loaded N rows through load_display_table()" line in its own output.
CALL_EXEMPT = {Path("tools/check_uncertainty_honesty.py"): {"apply_corrections()"}}


def _python_files() -> list[Path]:
    out = [APP] if APP.exists() else []
    for directory in SCANNED_DIRS:
        if directory.exists():
            out += sorted(p for p in directory.glob("*.py") if p.name != "__init__.py")
    return out


UNPARSEABLE = "unparseable"


def _assembly_calls(path: Path) -> set[str]:
    """Names from ASSEMBLY_CALLS actually invoked in `path`, plus any merge
    carrying validate="one_to_one" (the sidecar join, wherever it is written)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        return {UNPARSEABLE}

    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in ASSEMBLY_CALLS:
            found.add(f"{name}()")
        if name == "merge":
            for kw in node.keywords:
                if (
                    kw.arg == "validate"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "one_to_one"
                ):
                    found.add("sidecar merge")
    return found


def _report(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
    return ok


def main() -> int:
    files = _python_files()
    print(f"Scanning {len(files)} files\n")
    results: list[bool] = []

    offenders: list[str] = []
    for path in files:
        if path in EXEMPT:
            continue
        text = path.read_text(encoding="utf-8-sig")
        markers = _exempt_lines(text)
        for number, line in enumerate(text.splitlines(), start=1):
            for name in DATA_PATHS:
                if name in line and number not in markers:
                    offenders.append(f"{path}:{number} -> {name}")
    results.append(
        _report(
            "1 no module outside the loader names a data path",
            not offenders,
            "; ".join(offenders[:4]),
        )
    )

    assemblers: list[str] = []
    unreadable: list[str] = []
    for path in files:
        if path in EXEMPT:
            continue
        calls = _assembly_calls(path)
        if UNPARSEABLE in calls:
            unreadable.append(str(path))
            continue
        hits = sorted(calls - CALL_EXEMPT.get(path, set()))
        if hits:
            assemblers.append(f"{path} -> {hits}")
    results.append(
        _report(
            "2 no module outside the loader composes its own frame",
            not assemblers,
            "; ".join(assemblers[:4]),
        )
    )
    results.append(
        _report(
            "2b every scanned file parses",
            not unreadable,
            "; ".join(unreadable[:4]),
        )
    )

    app_text = APP.read_text(encoding="utf-8-sig") if APP.exists() else ""
    results.append(
        _report("3 app.py imports load_display_table", "load_display_table" in app_text)
    )
    results.append(
        _report(
            "4 app.py no longer defines its own assembly",
            "_display_with_3d" not in app_text,
        )
    )

    loader_text = LOADER.read_text(encoding="utf-8-sig") if LOADER.exists() else ""
    results.append(
        _report(
            "5 the loader guards the merge",
            "SidecarMismatch" in loader_text and "without coordinates" in loader_text,
        )
    )
    results.append(
        _report(
            "6 the composed frame is never cached",
            "@st.cache_data" not in loader_text.split("def load_display_table")[-1],
        )
    )

    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())