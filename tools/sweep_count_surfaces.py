"""
tools/sweep_count_surfaces.py - Gate D surface enumeration.

Source-level, offline, no API. Answers two questions the gate cannot answer by
screenshot:

  1. WHERE does the app render a population count? Every f-string or literal
     passed to a Streamlit text call whose literal portion carries count
     vocabulary is a surface.

  2. WHERE do those counts COME FROM? Two surfaces agreeing is not two surfaces
     sharing a derivation. Every call to a count-producing function is reported
     per file, so a surface that computes its own figure is visible as a call
     site outside the single owner.

AST, not grep: check_single_loader.py learned this when a docstring mention of
get_display_table() produced a false positive. Docstrings are never JoinedStr
nodes, and literal constants are only considered when they are call arguments,
so prose cannot reach this report.

Exemptions live AT THE SITE, not in a table here
------------------------------------------------
    st.sidebar.caption(...)   # count-exempt: guarded by `filtering` above

check_single_loader.py keeps its exemptions in a dict, and D-33 was invisible
for exactly that reason - state.py was exempt as "owns NODES_CSV as the base
read", and that exemption WAS the defect. A table in the checker also goes
stale the moment a line moves. Every exemption is printed with its reason, so
they appear in the gate record rather than hiding in it.

Note what an exemption means here. This tool detects the CONSTRUCTION, not
whether a guard exists, so a correctly guarded site still matches. Reasons
therefore carry three distinct meanings and the prose has to say which:
equality is intended (the restore report), equality is unreachable by
construction (the pager), or a guard exists at a named line (the D-32/D-34/
sidebar fixes).

Run from the repo root:

    python -m tools.sweep_count_surfaces                # full inventory
    python -m tools.sweep_count_surfaces --ui-only      # screen surfaces only
    python -m tools.sweep_count_surfaces --ui-only --strict   # exit 1 on any
                                                              # unexempt stutter
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

from tools._markers import comment_markers

# Streamlit calls that put text on screen. st.caption is where every known
# surface lives, but a count can reach the user through any of these.
TEXT_CALLS = frozenset(
    {"caption", "markdown", "write", "info", "success", "warning", "error",
     "text", "subheader", "header", "title", "metric", "label"}
)

COUNT_WORDS = re.compile(
    r"\b(?:of|need\s+review|still\s+need|shown|classified|connections|people|"
    r"remaining|left|total|not\s+an\s+occupation|summaries)\b",
    re.IGNORECASE,
)

# The stutter risk: literal "of" sitting between two substituted values.
#
# The bare version of this matched prose - state.py's "Expected one of the 23
# SOC major-group codes or {NOT_OCCUPATION}" and both classifier system
# prompts. Two constraints drop those: the "of" must sit within ~40 characters
# of BOTH slots, and no sentence boundary may fall between them. Verified to
# still catch assistant.py's "all {classified} classified connections of
# {total}", where 23 characters of literal separate the slot from the "of".
OF_BETWEEN_SLOTS = re.compile(
    r"\{[^{}]*\}[^{}.!?]{0,40}\bof\b[^{}.!?]{0,40}\{[^{}]*\}", re.IGNORECASE
)

COUNT_SOURCES = frozenset(
    {"get_review_counts", "review_counts", "get_coverage", "coverage_counts",
     "get_summary_counts", "count_needing_review", "load_base_table"}
)

SCANNED_DIRS = ("src/dashboard", "src", "tools")

# Files whose strings can reach a user's screen. Everything else in the
# inventory is CLI output, checker output or model prompt text - worth seeing
# in the full report, never worth failing a UI gate over.
UI_PATHS = ("app.py", "src/dashboard/", "src/assistant.py")


def _is_ui(rel: Path) -> bool:
    text = rel.as_posix()
    return any(text == p or text.startswith(p) for p in UI_PATHS)


def _exemptions(text: str) -> dict[int, str]:
    """Line number -> reason, for every `# count-exempt: <reason>` comment.

    Where a marker applies is decided by _exempt_reason below; the parsing
    is shared with check_single_loader via tools/_markers.py (D-39). Parse
    failures are reported by the AST pass, not here.
    """
    return comment_markers(text, "count-exempt")


def _exempt_reason(node: ast.AST, markers: dict[int, str]) -> str | None:
    """A marker on the line above the node, or on any line the node spans.

    The span matters: an f-string broken across lines carries its marker on
    whichever line the author found readable, not necessarily the first.
    """
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start) or start
    for line in range(start - 1, end + 1):
        if line in markers:
            return markers[line]
    return None


def _template(node: ast.JoinedStr) -> tuple[str, str]:
    """Return (rendered template, literal-only text) for an f-string."""
    shown: list[str] = []
    literal: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            shown.append(str(value.value))
            literal.append(str(value.value))
        else:
            try:
                expr = ast.unparse(value.value)
            except Exception:  # pragma: no cover - unparse is best effort
                expr = "..."
            shown.append("{" + expr + "}")
    return "".join(shown), "".join(literal)


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _scan(path: Path) -> tuple[list[dict], list[dict]]:
    """Return (surfaces, count_source_calls) found in one file."""
    text = path.read_text(encoding="utf-8-sig")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [{"line": 0, "template": f"<unparseable: {exc}>", "in_call": False,
                 "stutter": False, "exempt": None}], []

    markers = _exemptions(text)
    surfaces: list[dict] = []
    sources: list[dict] = []
    text_call_args: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in COUNT_SOURCES:
            sources.append({"line": node.lineno, "name": name})
        if name in TEXT_CALLS:
            for arg in list(node.args) + [kw.value for kw in node.keywords]:
                text_call_args.add(id(arg))

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            shown, literal = _template(node)
            if not COUNT_WORDS.search(literal):
                continue
            surfaces.append({
                "line": node.lineno,
                "template": shown,
                "in_call": id(node) in text_call_args,
                "stutter": bool(OF_BETWEEN_SLOTS.search(shown)),
                "exempt": _exempt_reason(node, markers),
            })
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in text_call_args and COUNT_WORDS.search(node.value):
                surfaces.append({
                    "line": node.lineno,
                    "template": node.value,
                    "in_call": True,
                    "stutter": False,
                    "exempt": _exempt_reason(node, markers),
                })
    return surfaces, sources


def _python_files(root: Path, ui_only: bool) -> list[Path]:
    seen: dict[Path, None] = {}
    app = root / "app.py"
    if app.exists():
        seen[app] = None
    for directory in SCANNED_DIRS:
        base = root / directory
        if not base.exists():
            continue
        for candidate in sorted(base.glob("*.py")):
            if candidate.name != "__init__.py":
                seen[candidate] = None
    if not seen:  # flat layout fallback, for scanning a copied-out snapshot
        for candidate in sorted(root.glob("*.py")):
            if candidate.name != "__init__.py":
                seen[candidate] = None
    files = list(seen)
    if ui_only:
        files = [f for f in files if _is_ui(f.relative_to(root))]
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate D count-surface sweep")
    parser.add_argument("--root", default=".", help="repo root to scan")
    parser.add_argument("--ui-only", action="store_true",
                        help="app.py, src/dashboard/, src/assistant.py only")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 on any unexempt 'N of M' construction")
    args = parser.parse_args()
    root = Path(args.root)

    files = _python_files(root, args.ui_only)
    scope = "UI surfaces" if args.ui_only else "all modules"
    print(f"Scanning {len(files)} files under {root.resolve()}  [{scope}]\n")

    total_surfaces = 0
    unexempt: list[str] = []
    exempted: list[str] = []
    source_calls: list[str] = []

    for path in files:
        surfaces, sources = _scan(path)
        if not surfaces and not sources:
            continue
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"{rel}")
        for surface in surfaces:
            total_surfaces += 1
            marks = []
            if not surface["in_call"]:
                marks.append("not-in-text-call")
            if surface["stutter"]:
                if surface["exempt"]:
                    marks.append(f"exempt: {surface['exempt']}")
                    exempted.append(f"{rel}:{surface['line']}  {surface['exempt']}")
                else:
                    marks.append("STUTTER-RISK")
                    unexempt.append(f"{rel}:{surface['line']}")
            suffix = f"   [{', '.join(marks)}]" if marks else ""
            print(f"  L{surface['line']:>4}  {surface['template']}{suffix}")
        for source in sources:
            source_calls.append(f"{rel}:{source['line']} {source['name']}()")
            print(f"  L{source['line']:>4}  <count source> {source['name']}()")
        print()

    print("-" * 72)
    print(f"{total_surfaces} count-bearing strings across {len(files)} files")

    print(f"\n{len(exempted)} exempt 'N of M' construction(s), with reason:")
    for entry in exempted:
        print(f"    {entry}")

    print(f"\n{len(unexempt)} UNEXEMPT 'N of M' construction(s):")
    for entry in unexempt:
        print(f"    {entry}")

    print(f"\n{len(source_calls)} call(s) to a count-producing function:")
    for entry in source_calls:
        print(f"    {entry}")
    print(
        "\nOne count source per figure is the target. More than one means a\n"
        "surface derives its own, which is the D-15 shape: agreement today,\n"
        "divergence the first time one route changes."
    )

    if args.strict and unexempt:
        print(f"\nFAIL  {len(unexempt)} construction(s) with neither a guard "
              "nor a `# count-exempt: <reason>` marker.")
        return 1
    if args.strict:
        print("\nPASS  every 'N of M' construction in scope is exempt with a reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
