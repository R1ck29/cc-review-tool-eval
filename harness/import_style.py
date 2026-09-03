#!/usr/bin/env python3
"""How often does this codebase use the import style `impact` drops?

The blast-radius bug only bites callers written as:

    from pkg import module
    module.func()

Measured across four real projects, that style is 0-1.3% of import statements
- low enough that "one of the most common patterns" (an earlier claim in this
evaluation) was wrong. Run this on your own repositories before deciding how
urgent the `callers_of` workaround is.

Usage:  python import_style.py <path> [<path> ...]
"""
import ast
import collections
import pathlib
import sys

SKIP = {".git", "node_modules", "site-packages", ".venv", "__pycache__", "build", "dist"}


def scan(root: pathlib.Path):
    styles = collections.Counter()
    vulnerable_sites = []
    files = 0
    for f in sorted(root.rglob("*.py")):
        if any(p in SKIP for p in f.parts):
            continue
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        files += 1
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for a in n.names:
                    # `from pkg import name` is the dropped style only when
                    # `name` is itself a module, i.e. pkg/name.py exists.
                    if root.joinpath(*n.module.split("."), a.name + ".py").exists():
                        styles["B"] += 1
                        vulnerable_sites.append(
                            f"{f.relative_to(root)}:{n.lineno}  from {n.module} import {a.name}")
                    else:
                        styles["A"] += 1
            elif isinstance(n, ast.Import):
                styles["C"] += len(n.names)
    return files, styles, vulnerable_sites


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    print(f"{'codebase':34} {'.py':>5} {'imports':>8} {'B (dropped)':>13}")
    print("-" * 64)
    all_sites = []
    for arg in sys.argv[1:]:
        root = pathlib.Path(arg).resolve()
        if not root.exists():
            print(f"{arg:34} not found")
            continue
        files, styles, sites = scan(root)
        total = sum(styles.values())
        if not total:
            print(f"{root.name:34} {files:>5} {0:>8}")
            continue
        b = styles["B"]
        print(f"{root.name:34} {files:>5} {total:>8} {b:>6} ({b / total:>5.1%})")
        all_sites += sites
    if all_sites:
        print(f"\ncall sites at risk ({len(all_sites)}):")
        for s in all_sites[:40]:
            print(f"  {s}")
        if len(all_sites) > 40:
            print(f"  ... and {len(all_sites) - 40} more")
    else:
        print("\nNo at-risk import sites found: the `impact` bug cannot bite this code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
