#!/usr/bin/env python3
"""Independent cost/quality benchmark for graph-based review-context tools.

Measures two things per seeded defect, deterministically (no LLM in the loop):

  context recall - is every file needed to *see* the defect present in the
                   context the strategy assembles? If it is not, no model can
                   find the defect, so this is a hard ceiling on review quality.
  context cost   - estimated tokens the strategy puts in the prompt.

Strategies compared:
  full-repo  every source file (the "read everything" baseline vendors quote)
  diff-only  only the changed files (the cheapest possible agent)
  graph      changed files + the tool's blast radius
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SRC_EXT = {".py", ".sql", ".ts", ".js", ".go", ".rs", ".java"}


def est_tokens(text: str) -> int:
    """~4 chars/token. An estimate, but it cancels in the ratios we report."""
    return (len(text) + 3) // 4


def repo_files(root: Path):
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix in SRC_EXT and ".git" not in p.parts \
                and ".code-review-graph" not in p.parts:
            out.append(str(p.relative_to(root)))
    return out


def tokens_for(root: Path, rel_files):
    total = 0
    for rel in rel_files:
        fp = root / rel
        if fp.exists():
            total += est_tokens(fp.read_text(errors="ignore"))
    return total


def graph_context(cli: str, root: Path, changed, depth: int):
    """Files code-review-graph says are in the blast radius of `changed`."""
    proc = subprocess.run(
        [cli, "impact", "--repo", str(root), "--files", *changed, "--depth", str(depth)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-500:])
    data = json.loads(proc.stdout)
    files = set(changed)
    for key in ("changed_nodes", "impacted_nodes", "affected_files", "impacted_files"):
        for item in data.get(key, []) or []:
            fp = item.get("file_path") if isinstance(item, dict) else item
            if not fp:
                continue
            try:
                files.add(str(Path(fp).resolve().relative_to(root.resolve())))
            except ValueError:
                pass
    return sorted(files), est_tokens(proc.stdout)


def caller_context(cli: str, root: Path, changed, base_files):
    """`impact` + every file containing a *caller* of a symbol defined in the
    changed files, found via the symbol-level `query callers_of`.

    This exists because the two disagree: the CALLS edges are complete, but the
    blast radius is derived from file-level IMPORTS edges and silently drops
    callers that used `from package import module`.
    """
    import ast
    files = set(base_files)
    extra_tokens = 0
    for rel in changed:
        src = (root / rel)
        if src.suffix != ".py":
            continue
        try:
            tree = ast.parse(src.read_text(errors="ignore"))
        except SyntaxError:
            continue
        names = [n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        for name in names:
            proc = subprocess.run([cli, "query", "--repo", str(root), "callers_of", name],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                continue
            extra_tokens += est_tokens(proc.stdout)
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                continue
            results = data.get("results", [])
            if data.get("status") == "ambiguous":
                results = data.get("candidates", [])
            for n in results if isinstance(results, list) else []:
                fp = n.get("file_path") if isinstance(n, dict) else None
                if not fp:
                    continue
                try:
                    files.add(str(Path(fp).resolve().relative_to(root.resolve())))
                except ValueError:
                    pass
    return sorted(files), extra_tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--defects", required=True)
    ap.add_argument("--cli", required=True)
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    defects = json.loads(Path(args.defects).read_text())["defects"]
    all_files = repo_files(root)
    full_tokens = tokens_for(root, all_files)

    rows = []
    for d in defects:
        # `changed` is a single path in the original manifest and a list in the
        # multi-file X-class benchmark (make_xbench.py).
        changed = d["changed"] if isinstance(d["changed"], list) else [d["changed"]]
        gfiles, payload_tokens = graph_context(args.cli, root, changed, args.depth)
        cfiles, _ = caller_context(args.cli, root, changed, gfiles)
        need = set(d["evidence"])
        strategies = {
            "full-repo": (all_files, full_tokens),
            "diff-only": (changed, tokens_for(root, changed)),
            "graph": (gfiles, tokens_for(root, gfiles)),
            "graph+callers": (cfiles, tokens_for(root, cfiles)),
        }
        row = {"id": d["id"], "class": d["class"], "changed": changed,
               "evidence": d["evidence"], "static_edge": d["static_edge"],
               "graph_payload_tokens": payload_tokens, "graph_files": gfiles}
        for name, (files, toks) in strategies.items():
            row[f"{name}_hit"] = need.issubset(set(files))
            row[f"{name}_tokens"] = toks
            row[f"{name}_missing"] = sorted(need - set(files))
        rows.append(row)

    Path(args.out).write_text(json.dumps({"repo": str(root), "depth": args.depth,
                                          "repo_files": len(all_files),
                                          "full_repo_tokens": full_tokens,
                                          "rows": rows}, indent=2))

    # ---- report -------------------------------------------------------
    w = sys.stdout.write
    w(f"\nrepo: {len(all_files)} source files, {full_tokens} est. tokens, depth={args.depth}\n\n")
    w(f"{'id':4} {'cls':4} {'changed':22} {'full':>5} {'diff':>5} {'graph':>5} {'g+call':>7}  {'graph tok':>9}  missing from graph ctx\n")
    w("-" * 104 + "\n")
    for r in rows:
        m = lambda k: "HIT " if r[f"{k}_hit"] else "MISS"
        w(f"{r['id']:4} {r['class']:4} {str(r['changed'][0])[:22]:22} {m('full-repo'):>5} "
          f"{m('diff-only'):>5} {m('graph'):>5} {m('graph+callers'):>7}  {r['graph_tokens']:>9}  "
          f"{','.join(r['graph_missing']) or '-'}\n")

    w("\nrecall by defect class and strategy\n")
    w(f"{'class':6} {'n':>3} {'full-repo':>10} {'diff-only':>10} {'graph':>10} {'graph+callers':>14}\n")
    for cls in ("L", "X", "H", "*"):
        sub = rows if cls == "*" else [r for r in rows if r["class"] == cls]
        if not sub:
            continue
        cells = "".join(
            f"{sum(r[f'{s}_hit'] for r in sub) / len(sub):>10.0%}"
            for s in ("full-repo", "diff-only", "graph", "graph+callers"))
        w(f"{cls:6} {len(sub):>3}{cells}\n")

    w("\nmean context tokens per review\n")
    for s in ("full-repo", "diff-only", "graph", "graph+callers"):
        avg = sum(r[f"{s}_tokens"] for r in rows) / len(rows)
        w(f"  {s:10} {avg:8.0f}  ({full_tokens / avg:.2f}x cheaper than full-repo)\n")
    w(f"\nwrote {args.out}\n")


if __name__ == "__main__":
    main()
