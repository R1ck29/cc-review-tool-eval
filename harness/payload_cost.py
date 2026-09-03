#!/usr/bin/env python3
"""What `impact` puts in the context window - including its own output.

run_bench.py priced the *files* the blast radius selects and ignored the JSON
the tool returns to say so. That JSON is context too: it is a tool result in
the conversation. On the 15-file benchmark it is 3.2k tokens - 6.6x the files it
selects, and run_bench.py records it in `graph_payload_tokens` without ever
adding it to a cost - so the omission is invisible there. On a real repository
it dominates everything else.

    python harness/payload_cost.py <repo> [--depth 2] [--sample 15]

Reports, per changed file, the files the blast radius names, the tokens of
those files, and the tokens of the impact payload itself.
"""
import argparse
import json
import random
import statistics
from pathlib import Path

from code_review_graph.tools import get_impact_radius

EXT = {".py", ".sql", ".ts", ".js", ".go", ".rs", ".java"}
est = lambda t: (len(t) + 3) // 4  # noqa: E731


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--max-results", type=int, default=500)
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out")
    a = ap.parse_args()

    root = Path(a.repo).resolve()
    files = [p for p in sorted(root.rglob("*"))
             if p.is_file() and p.suffix in EXT and ".code-review-graph" not in p.parts]
    full = sum(est(p.read_text(errors="ignore")) for p in files)
    cand = [p for p in files if p.suffix == ".py" and "tests" not in p.parts]
    random.seed(a.seed)
    sample = cand if len(cand) <= a.sample else random.sample(cand, a.sample)

    rows = []
    for p in sample:
        rel = str(p.relative_to(root))
        r = get_impact_radius(changed_files=[rel], max_depth=a.depth,
                              max_results=a.max_results, repo_root=str(root))
        payload = est(json.dumps(r))
        sel = {rel}
        for f in r.get("impacted_files") or []:
            try:
                sel.add(str(Path(f).resolve().relative_to(root)))
            except ValueError:
                pass
        ctx = sum(est((root / f).read_text(errors="ignore")) for f in sel if (root / f).exists())
        rows.append({"changed": rel, "files": len(sel), "ctx_tokens": ctx,
                     "payload_tokens": payload, "truncated": bool(r.get("truncated"))})

    mc = statistics.mean(r["ctx_tokens"] for r in rows)
    mp = statistics.mean(r["payload_tokens"] for r in rows)
    mf = statistics.mean(r["files"] for r in rows)
    print(f"\nrepo: {len(files)} source files, {full:,} tokens, depth={a.depth}, "
          f"max_results={a.max_results}, n={len(rows)}\n")
    print(f"{'changed':52} {'files':>5} {'ctx tok':>9} {'payload tok':>12} {'trunc':>6}")
    for r in rows:
        print(f"{r['changed']:52} {r['files']:>5} {r['ctx_tokens']:>9,} "
              f"{r['payload_tokens']:>12,} {str(r['truncated']):>6}")
    print(f"\nmean: {mf:.1f} files ({mf/len(files):.0%} of repo), "
          f"ctx {mc:,.0f} + payload {mp:,.0f} = {mc+mp:,.0f} tokens")
    print(f"vs reading the whole repo ({full:,}): "
          f"{full/(mc+mp):.1f}x with the payload counted, {full/mc:.1f}x without")
    if a.out:
        Path(a.out).write_text(json.dumps(
            {"repo": str(root), "depth": a.depth, "max_results": a.max_results,
             "repo_files": len(files), "full_repo_tokens": full,
             "mean_ctx_tokens": mc, "mean_payload_tokens": mp, "rows": rows}, indent=2))
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
