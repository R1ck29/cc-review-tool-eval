#!/usr/bin/env python3
"""Measure real detection rate with a blind reviewer, via the Claude CLI.

Context recall (run_bench.py) is only an upper bound: it says the evidence was
present, not that the model reported the defect. This closes that gap.

Blinding rules, all enforced here:
  - the reviewer never sees bench/defects.json, this repo, or any harness file
  - it runs in an empty temp directory outside the project, so there is nothing
    to wander into, and no CLAUDE.md is inherited
  - file tools are disallowed; the context is exactly the file set the strategy
    assembled, pasted into the prompt. That makes the run a clean test of the
    context, with no tool-use variance
  - --strict-mcp-config with no --mcp-config: the code-review-graph MCP server
    is not attached, so it cannot fetch anything the strategy did not give it

Scoring is keyword-based and deliberately generous (see MATCH): a finding counts
if it names the right symbol/file AND some signal of the right failure. Raw
reviews are written to results/blind/ so the scoring can be audited.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from run_bench import caller_context, graph_context, repo_files  # noqa: E402

# Each entry: list of groups; a finding matches when every group has >=1
# alternative present *within that one finding*.
#
# Cross-file defects (X and H) carry a third "anchor" group naming the other
# side of the inconsistency. Without it the scorer credits any unrelated remark
# about the changed file - auditing the first pass showed exactly that:
# "get_order has no Optional[Order] type hint" and "discount_percent has
# ambiguous units" were both scored as detections. A cross-file defect is only
# found when the reviewer connects both sides, so the anchor is the test.
MATCH = {
    # L - single file; no anchor needed
    "D01": [["bulk", "discount", "threshold"],
            ["off-by-one", "off by one", ">=", "greater than or equal",
             "boundary", "equal to", "exactly", "reaches"]],
    "D02": [["parse_money"],
            ["valueerror", "exception", "malformed", "invalid", "crash",
             "unhandled", "not caught"]],
    "D04": [["connect", "connection", "conn"],
            ["leak", "close", "finally", "context manager", "with statement"]],
    # X / H - the anchor group names the other side
    "D05": [["compute_total"],
            ["argument", "parameter", "typeerror", "missing", "signature", "arity"],
            ["orders.py", "create_order"]],
    "D06": [["get_order"],
            ["none", "null", "attributeerror"],
            ["orders.py", "get_order_summary"]],
    "D07": [["discount"],
            ["attributeerror", "does not exist", "no such", "renamed", "mismatch",
             "not match", "does not match"],
            ["serializ", "order_to_dict"]],
    "D08": [["discount_pct"],
            ["column", "no such", "does not exist", "mismatch", "not match"],
            ["schema", "discount_percent", "ddl"]],
    "D09": [["order.created"],
            ["mismatch", "never", "not match", "no subscriber", "silently"],
            ["handlers", "order_created\"", "'order_created'", "`order_created`",
             "subscribes to \"order_created", "subscribes to 'order_created"]],
    "D10": [["customerid"],
            ["mismatch", "keyerror", "camel", "snake", "not match", "does not match"],
            ["customer_id", "serializ", "order_to_dict"]],
    "D11": [["on_order_created", "run_task"],
            ["dynamic", "getattr", "rename", "static"],
            ["tasks.py", "handlers"]],
    "D12": [["max_retries"],
            ["retry", "disable", "no attempt", "single attempt", "only once"],
            ["0", "zero"]],
}

PROMPT = """You are reviewing a change to a Python service before it is merged.

Below is the full content of every file you have been given as context. The file
under review is `{changed}`; the others are provided as surrounding context.

Report every bug, defect, or correctness problem you can find. Include issues you
are uncertain about or consider low severity — coverage matters more than
precision here, and a separate step will filter your findings.

For each finding, write one line in exactly this form:
FINDING: <file path> | <one sentence describing the problem>

If you find nothing, write: FINDING: none

---
{files}
"""


def build_context(repo: Path, files):
    out = []
    for rel in files:
        p = repo / rel
        if p.exists():
            out.append(f"===== FILE: {rel} =====\n{p.read_text(errors='ignore')}")
    return "\n\n".join(out)


def _invoke(prompt: str, model: str):
    with tempfile.TemporaryDirectory(prefix="blind-") as tmp:
        proc = subprocess.run(
            ["claude", "-p", prompt,
             "--strict-mcp-config",
             "--model", model,
             "--output-format", "json",
             "--disallowedTools", "Read", "Write", "Edit", "Bash", "Glob",
             "Grep", "WebSearch", "WebFetch", "Task", "NotebookEdit"],
            capture_output=True, text=True, cwd=tmp, timeout=900,
        )
    if proc.returncode != 0:
        return None, 0.0, f"exit {proc.returncode}: {proc.stderr[-200:]}"
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, 0.0, f"unparseable: {proc.stdout[-200:]}"
    # A rate-limited or refused call comes back as valid JSON with result=null
    # and zero cost. Scoring that as a MISS silently invents a quality result,
    # so it has to be an error the caller retries - never a data point.
    if d.get("result") is None or d.get("is_error"):
        return None, d.get("total_cost_usd", 0.0), (
            f"no result (subtype={d.get('subtype')}, "
            f"stop={d.get('stop_reason')}, term={d.get('terminal_reason')})")
    return d["result"], d.get("total_cost_usd", 0.0), None


def run_review(prompt: str, model: str, retries: int = 4, pause: float = 5.0):
    """Run one blind review, retrying transient failures with backoff."""
    last = None
    for attempt in range(retries):
        text, cost, err = _invoke(prompt, model)
        if err is None:
            return text, cost, None
        last = err
        time.sleep(pause * (2 ** attempt))
    return None, 0.0, last


def findings(text: str):
    """Split a review into individual FINDING lines.

    Matching must happen inside one finding, not across the whole review. A
    reviewer that mentions the right symbol in one finding and the right
    failure mode in an unrelated one has not identified the defect - scoring
    across the full text credits it anyway, which is how the first pass
    produced a false 88% for diff-only.
    """
    out = []
    for line in (text or "").splitlines():
        # Reviewers decorate the label: "**FINDING:**", "- FINDING:", "1. FINDING:".
        # Anchoring on a bare "FINDING:" prefix silently drops those lines and
        # turns a real detection into a scored miss, so strip decoration first.
        m = re.match(r"^[\s>*_\-#\d.)\[]*finding\s*:?\s*\**\s*(.*)$", line.strip(),
                     re.IGNORECASE)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out


def scored(defect_id: str, text: str) -> bool:
    for finding in findings(text):
        low = finding.lower()
        if all(any(re.search(re.escape(alt.lower()), low) for alt in group)
               for group in MATCH[defect_id]):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default=str(ROOT / ".venv/bin/code-review-graph"))
    ap.add_argument("--model", default="opus")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--only", nargs="*", default=None, help="defect ids")
    ap.add_argument("--strategies", nargs="*",
                    default=["diff-only", "graph", "graph+callers", "full-repo"])
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--pace", type=float, default=3.0, help="seconds between calls")
    ap.add_argument("--resume", action="store_true", help="skip cells already recorded")
    args = ap.parse_args()

    repo = ROOT / "bench" / "repo"
    defects = json.loads((ROOT / "bench" / "defects.json").read_text())["defects"]
    verdict = json.loads((ROOT / "results" / "verdicts.json").read_text())
    defects = [d for d in defects if verdict.get(d["id"]) == "FIRES"]
    if args.only:
        defects = [d for d in defects if d["id"] in args.only]

    all_files = repo_files(repo)
    outdir = ROOT / "results" / "blind"
    outdir.mkdir(parents=True, exist_ok=True)

    resume_path = ROOT / "results" / "blind_review.json"
    records = json.loads(resume_path.read_text()) if (args.resume and resume_path.exists()) else []
    done = {(r["id"], r["strategy"], r["rep"]) for r in records if not r.get("error")}
    total_cost = sum(r.get("cost_usd", 0.0) for r in records)
    for d in defects:
        changed = [d["changed"]]
        gfiles, _ = graph_context(args.cli, repo, changed, args.depth)
        cfiles, _ = caller_context(args.cli, repo, changed, gfiles)
        sets = {"diff-only": changed, "graph": gfiles,
                "graph+callers": cfiles, "full-repo": all_files}
        for strat in args.strategies:
            for rep in range(args.reps):
                if (d["id"], strat, rep) in done:
                    continue
                prompt = PROMPT.format(changed=d["changed"],
                                       files=build_context(repo, sets[strat]))
                text, cost, err = run_review(prompt, args.model)
                total_cost += cost
                hit = bool(text) and scored(d["id"], text)
                records = [r for r in records
                           if (r["id"], r["strategy"], r["rep"]) != (d["id"], strat, rep)]
                records.append({"id": d["id"], "class": d["class"], "strategy": strat,
                                "rep": rep, "hit": hit, "cost_usd": cost,
                                "error": err, "review": text})
                tag = "ERR " if err else ("HIT " if hit else "MISS")
                print(f"  {d['id']} {strat:14} rep{rep} {tag} ${cost:.3f}"
                      + (f"  {err[:70]}" if err else ""), flush=True)
                (outdir / f"{d['id']}_{strat.replace('+', '-')}_{rep}.txt").write_text(
                    text or f"ERROR: {err}")
                resume_path.write_text(json.dumps(records, indent=2))
                time.sleep(args.pace)

    # ---- report ---------------------------------------------------------
    ok = [r for r in records if not r.get("error")]
    bad = [r for r in records if r.get("error")]
    print(f"\n{len(ok)} scored reviews, {len(bad)} errored, ${total_cost:.2f} total")
    if bad:
        print("  ERRORED CELLS ARE EXCLUDED, NOT COUNTED AS MISSES:")
        for r in bad:
            print(f"    {r['id']} {r['strategy']}: {r['error'][:80]}")
    print()
    print(f"{'class':6} {'n':>3}" + "".join(f"{s:>16}" for s in args.strategies))
    print("-" * (9 + 16 * len(args.strategies)))
    for cls in ("L", "X", "H", "*"):
        sub = [r for r in ok if cls in (r["class"], "*")]
        ids = {r["id"] for r in sub}
        if not ids:
            continue
        cells = ""
        for s in args.strategies:
            rs = [r for r in sub if r["strategy"] == s]
            cells += f"{sum(r['hit'] for r in rs) / len(rs):>16.0%}" if rs else f"{'-':>16}"
        print(f"{cls:6} {len(ids):>3}{cells}")
    print(f"\nraw reviews: {outdir}")


if __name__ == "__main__":
    main()
