#!/usr/bin/env python3
"""What the recommended call parameters save on YOUR repository.

The numbers in docs/ were measured on two repositories. Yours is not either of
them, and the saving depends on how large your files are - not how many you
have - so it is worth 60 seconds to measure instead of assuming.

This drives the real MCP server over stdio, exactly as an agent would, and
counts the text the model actually receives (``content[].text``), not the
JSON-RPC envelope. The envelope is ~2x larger because embedded source is
JSON-escaped; counting it overstates what reaches the model.

    python harness/measure_savings.py /path/to/your/repo

The graph must already exist for that repo:

    code-review-graph build --repo /path/to/your/repo
"""
# Modern annotations (dict[str, Any] etc.) are evaluated lazily so this file
# also runs on the 3.8 interpreter that is still first on PATH here - the same
# version trap that silently disabled a rule in string_contracts.py.
from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

CRG_PIN = "code-review-graph==2.3.8"
SOURCE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".php"}
# Test trees and fixtures are excluded by default: they skew the sample toward
# tiny files and are not what a PR usually changes. --include-tests turns them
# back on. This choice moves the headline ratio a lot (measured 1.0x vs 2.5x on
# the same repo), which is exactly why you should run this on your own code
# rather than trusting a number from someone else's.
SKIP_PARTS = {".code-review-graph", "node_modules", ".venv", "venv", "dist",
              "build", "__pycache__", ".git", "site-packages",
              "tests", "test", "__tests__", "fixtures", "spec", "__mocks__"}

def est_tokens(text: str) -> int:
    """Token estimate used across this harness: 1 token ~= 4 chars."""
    return (len(text) + 3) // 4


def call_tool(repo: str, tool: str, arguments: dict[str, Any],
              timeout_lines: int = 600) -> tuple[str, bool]:
    """One MCP tools/call over stdio. Returns the text the model would see."""
    cmd = ["uvx", "--from", CRG_PIN, "code-review-graph", "serve", "--repo", repo]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, bufsize=1)
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "measure_savings", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": tool, "arguments": arguments}},
    ]
    try:
        for m in msgs:
            proc.stdin.write(json.dumps(m) + "\n")
            proc.stdin.flush()
        for _ in range(timeout_lines):
            line = proc.stdout.readline()
            if not line:
                break
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("id") == 2:
                result = obj.get("result", {})
                text = "".join(c.get("text", "") for c in result.get("content", []))
                return text, result.get("isError", False)
    finally:
        proc.kill()
    return "", True


def pick_sample(root: Path, n: int, seed: int,
                include_tests: bool = False) -> list[Path]:
    skip = {s for s in SKIP_PARTS} if not include_tests else {
        ".code-review-graph", "node_modules", ".venv", "venv", "dist",
        "build", "__pycache__", ".git", "site-packages"}
    files = [p for p in sorted(root.rglob("*"))
             if p.is_file() and p.suffix in SOURCE_EXT
             and not any(s in p.parts for s in skip)
             and (include_tests or "test" not in p.name.lower())]
    if not files:
        return []
    random.seed(seed)
    return files if len(files) <= n else random.sample(files, n)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Measure what the recommended parameters save on your repo.")
    ap.add_argument("repo")
    ap.add_argument("--sample", type=int, default=8,
                    help="how many changed-file scenarios to measure (default 8)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--include-tests", action="store_true",
                    help="include test/fixture trees in the sample (default: excluded)")
    ap.add_argument("--skip-impact", action="store_true",
                    help="skip the get_impact_radius measurement (it is slow and large)")
    a = ap.parse_args()

    root = Path(a.repo).resolve()
    if not (root / ".code-review-graph").exists():
        sys.exit(f"No graph at {root}/.code-review-graph\n"
                 f"Build it first:  code-review-graph build --repo {root}")

    sample = pick_sample(root, a.sample, a.seed, a.include_tests)
    if not sample:
        sys.exit(f"No source files found under {root}")

    print(f"repo: {root}")
    print(f"sample: {len(sample)} changed-file scenarios "
          f"(seed {a.seed}); counting model-visible text\n")

    print(f"{'changed file':44} {'before':>10} {'after':>10} {'saved':>7}")
    print("-" * 74)
    before, after, impact_costs = [], [], []
    for path in sample:
        rel = str(path.relative_to(root))
        d_text, d_err = call_tool(str(root), "get_review_context_tool",
                                  {"changed_files": [rel]})
        n_text, n_err = call_tool(str(root), "get_review_context_tool",
                                  {"changed_files": [rel],
                                   "max_results": 25, "max_depth": 1})
        if d_err or n_err:
            print(f"{rel[-44:]:44} {'ERROR':>10}")
            continue
        d, n = est_tokens(d_text), est_tokens(n_text)
        before.append(d)
        after.append(n)
        print(f"{rel[-44:]:44} {d:>10,} {n:>10,} {d / max(n, 1):>6.1f}x")

        if not a.skip_impact:
            i_text, i_err = call_tool(str(root), "get_impact_radius_tool",
                                      {"changed_files": [rel]})
            if not i_err:
                impact_costs.append(est_tokens(i_text))

    if not before:
        sys.exit("every call failed - is the graph built and the repo path right?")

    mb, ma = statistics.mean(before), statistics.mean(after)
    print("-" * 74)
    print(f"{'MEAN get_review_context':44} {mb:>10,.0f} {ma:>10,.0f} "
          f"{mb / max(ma, 1):>6.1f}x")

    print("\n--- what this means per review ---")
    if impact_costs:
        mi = statistics.mean(impact_costs)
        print(f"  RULE 1  avoid get_impact_radius at default   saves {mi:>9,.0f} tokens/call")
        print(f"          (that one call is {mi / max(mb, 1):.1f}x your whole default review context)")
    else:
        print("  RULE 1  avoid get_impact_radius at default   (not measured: --skip-impact)")
    print(f"  RULE 2  max_results=25, max_depth=1          saves {mb - ma:>9,.0f} tokens/call")
    print(f"  RULE 3  add callers_of                       costs ~{900:>8,} tokens (recall 44%->78%)")
    print(f"  RULE 4  string_contracts.py pre-pass         costs {0:>9,} tokens")
    print(f"\n  recommended context per review: ~{ma + 900 + 268:,.0f} tokens")
    if impact_costs:
        naive = statistics.mean(impact_costs) + mb
        print(f"  unparameterised, calling both:  ~{naive:,.0f} tokens "
              f"({naive / max(ma + 900 + 268, 1):.0f}x more)")

    print("\nIf RULE 2 shows ~1.0x, your files are small and the cap never binds -"
          "\npass it anyway (it costs nothing) and rely on RULE 1, which is the"
          "\nlarger lever regardless of file size.")


if __name__ == "__main__":
    main()
