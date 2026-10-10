"""Report the third-party packages reached from one or more entry modules.

Walks internal imports (``src``, ``tools``, ``tests`` and repo-root modules
such as ``app``) transitively by AST, starting from the given entry modules, and records every other non-stdlib import it meets. Each is
marked ``eager`` (module level: loaded the moment the entry imports) or
``lazy`` (inside a function or class body: loaded only when that code runs).
A package reached eagerly anywhere is eager overall.

Used by D-31 to derive the runtime and build manifests from the code rather
than from memory. Run from the repo root inside the project venv, so import
names resolve to their pip distribution names:

    python -m tools.import_closure app
    python -m tools.import_closure app src.classify_pipeline --tree
    python -m tools.import_closure --all

``--all`` seeds the walk with every .py file at the repo root and under src/,
tools/ and tests/, which gives the development manifest's closure.

Exits 1 if any internal import cannot be resolved to a file, since an
unresolved module means the closure is incomplete.
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path.cwd()
STDLIB = set(sys.stdlib_module_names)
INTERNAL_ROOTS = {"src", "tools", "tests"}


def module_path(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def imports_in(path: Path) -> list[tuple[str, bool]]:
    """Return (absolute module name, eager) for every import in the file."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    found: list[tuple[str, bool]] = []

    def visit(node: ast.AST, eager: bool) -> None:
        for child in ast.iter_child_nodes(node):
            child_eager = eager and not isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            )
            # `if TYPE_CHECKING:` blocks never run.
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                continue
            if isinstance(child, ast.Import):
                found.extend((a.name, child_eager) for a in child.names)
            elif isinstance(child, ast.ImportFrom):
                if child.level:  # relative import: resolve against this package
                    pkg = path.relative_to(ROOT).with_suffix("").parts[: -child.level]
                    base = ".".join(pkg + ((child.module,) if child.module else ()))
                else:
                    base = child.module or ""
                if base == "__future__":
                    continue
                found.append((base, child_eager))
                # `from src.dashboard import loader` imports a submodule.
                for a in child.names:
                    if module_path(f"{base}.{a.name}"):
                        found.append((f"{base}.{a.name}", child_eager))
            visit(child, child_eager)

    visit(tree, True)
    return found


def closure(entries: list[str]):
    third_party: dict[str, dict[str, bool]] = defaultdict(dict)  # pkg -> {module: eager}
    unresolved: set[str] = set()
    seen: set[str] = set()
    stack = [(e, True) for e in entries]
    eager_reach: dict[str, bool] = {}
    while stack:
        mod, eager = stack.pop()
        # Re-visit a module if we now reach it eagerly but first reached it lazily.
        if mod in seen and (eager_reach[mod] or not eager):
            continue
        seen.add(mod)
        eager_reach[mod] = eager_reach.get(mod, False) or eager
        path = module_path(mod)
        if path is None:
            # A directory without __init__.py is a namespace package (tools/
            # is one): importable, and has no code of its own to walk.
            if not ROOT.joinpath(*mod.split(".")).is_dir():
                unresolved.add(mod)
            continue
        for name, imp_eager in imports_in(path):
            top = name.split(".")[0]
            reach_eager = eager and imp_eager
            if top in INTERNAL_ROOTS or module_path(top) is not None:
                stack.append((name, reach_eager))
            elif top not in STDLIB and top:
                prev = third_party[top].get(mod, False)
                third_party[top][mod] = prev or reach_eager
    return third_party, unresolved, seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("entries", nargs="*", help="dotted entry modules, e.g. app src.graph")
    ap.add_argument("--all", action="store_true", help="seed with every .py at the repo root and under src/, tools/, tests/")
    ap.add_argument("--tree", action="store_true", help="list the importing modules per package")
    args = ap.parse_args()
    if args.all:
        args.entries.extend(f.stem for f in sorted(ROOT.glob("*.py")))
        for top in sorted(INTERNAL_ROOTS):
            for f in sorted((ROOT / top).rglob("*.py")):
                args.entries.append(".".join(f.relative_to(ROOT).with_suffix("").parts))
    if not args.entries:
        ap.error("give entry modules or --all")

    third_party, unresolved, seen = closure(args.entries)
    dists = packages_distributions()

    shown = "--all" if args.all else ", ".join(args.entries)
    print(f"entries: {shown}")
    print(f"internal modules reached: {len(seen - unresolved)}\n")
    width = max((len(p) for p in third_party), default=0)
    for pkg in sorted(third_party, key=str.lower):
        importers = third_party[pkg]
        mode = "eager" if any(importers.values()) else "lazy "
        dist = ", ".join(dists.get(pkg, ["?? not installed"]))
        print(f"  {pkg:<{width}}  {mode}  {dist}")
        if args.tree:
            for m in sorted(importers):
                print(f"      {'E' if importers[m] else 'L'}  {m}")
    if unresolved:
        print("\nUNRESOLVED internal modules (closure incomplete):")
        for m in sorted(unresolved):
            print(f"  {m}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
