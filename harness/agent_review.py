#!/usr/bin/env python3
"""With vs without the graph, measured as a whole agent - not as a file set.

blind_review.py answered a narrower question: given exactly these files, does
the model find the defect? Every arm there had file tools disabled, so its
"no tool" baseline is a diff pasted into a chat window - not Claude Code, which
would have grepped for the caller. Comparing a tool-using agent against that
baseline overstates what the graph adds.

This runs the real comparison. Both arms are the same agent in the same
repository with the same prompt; the only difference is whether the
code-review-graph MCP server is attached and the review is told to use it.

Measured per run: detection (blind_review.MATCH), dollars, turns, tokens.

    python harness/agent_review.py --arms agent agent+graph
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from blind_review import findings, scored  # noqa: E402


def scored_with(match, text) -> bool:
    """Score against a matcher carried by the manifest (make_xbench.py).

    Same rule as blind_review.scored: every group must be satisfied inside one
    finding, so a review that names the symbol in one line and the consumer in
    an unrelated line does not count.
    """
    import re
    for finding in findings(text or ""):
        low = finding.lower()
        if all(any(re.search(re.escape(alt.lower()), low) for alt in group)
               for group in match):
            return True
    return False

BASE_PROMPT = """You are reviewing a change to a Python service before it is merged.

The repository is your working directory. The files under review are: {changed}.
{extra}
Report every bug, defect, or correctness problem you can find in that change,
including problems it causes in other files. Include issues you are uncertain
about or consider low severity - coverage matters more than precision here, and
a separate step will filter your findings.

For each finding, write one line in exactly this form:
FINDING: <file path> | <one sentence describing the problem>

If you find nothing, write: FINDING: none
"""

GRAPH_EXTRA = """
A code-review-graph MCP server is attached and its graph is already built for
this repository. Use it before reading files: `get_impact_radius_tool` on the
changed file for the blast radius, and `query_graph_tool` with
pattern="callers_of" for the callers of any symbol you changed.
"""

PLAIN_TOOLS = ["Read", "Grep", "Glob"]
GRAPH_TOOLS = PLAIN_TOOLS + [
    "mcp__code-review-graph__get_impact_radius_tool",
    "mcp__code-review-graph__query_graph_tool",
    "mcp__code-review-graph__get_review_context_tool",
    "mcp__code-review-graph__semantic_search_nodes_tool",
]


def mcp_config(cli: str) -> str:
    return json.dumps({"mcpServers": {"code-review-graph": {
        "command": cli, "args": ["serve"], "env": {}}}})


def run_once(repo: Path, changed, arm: str, model: str, cli: str, timeout: int):
    """One review in a throwaway copy of the repo. Returns (text, metrics, err)."""
    with tempfile.TemporaryDirectory(prefix="agentrev-") as tmp:
        work = Path(tmp) / "repo"
        ignore = shutil.ignore_patterns("__pycache__", ".git")
        if arm == "agent":       # no graph must also mean no graph database
            ignore = shutil.ignore_patterns("__pycache__", ".git", ".code-review-graph")
        shutil.copytree(repo, work, ignore=ignore)

        files = changed if isinstance(changed, list) else [changed]
        prompt = BASE_PROMPT.format(
            changed=", ".join(f"`{f}`" for f in files),
            extra=GRAPH_EXTRA if arm == "agent+graph" else "")
        cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
               "--strict-mcp-config", "--permission-mode", "bypassPermissions",
               "--disallowedTools", "Write", "Edit", "NotebookEdit", "Task",
               "WebSearch", "WebFetch", "Bash",
               "--allowedTools", *(GRAPH_TOOLS if arm == "agent+graph" else PLAIN_TOOLS)]
        if arm == "agent+graph":
            cmd[cmd.index("--strict-mcp-config"):cmd.index("--strict-mcp-config")] = [
                "--mcp-config", mcp_config(cli)]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=work,
                              timeout=timeout)
    if proc.returncode != 0:
        return None, {}, f"exit {proc.returncode}: {proc.stderr[-200:]}"
    try:
        d = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None, {}, f"unparseable: {proc.stdout[-200:]}"
    if d.get("result") is None or d.get("is_error"):
        return None, {"cost_usd": d.get("total_cost_usd", 0.0)}, (
            f"no result (subtype={d.get('subtype')})")
    u = d.get("usage", {}) or {}
    return d["result"], {
        "cost_usd": d.get("total_cost_usd", 0.0),
        "turns": d.get("num_turns"),
        "duration_ms": d.get("duration_ms"),
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
    }, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT / "bench" / "repo"))
    ap.add_argument("--defects", default=None,
                    help="manifest with per-defect matchers (make_xbench.py)")
    ap.add_argument("--cli", default=str(ROOT / ".venv/bin/code-review-graph"))
    ap.add_argument("--model", default="opus")
    ap.add_argument("--arms", nargs="*", default=["agent", "agent+graph"])
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--pace", type=float, default=5.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--out", default=str(ROOT / "results" / "agent_review.json"))
    ap.add_argument("--outdir", default=str(ROOT / "results" / "agent"))
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()

    repo = Path(a.repo).resolve()
    if a.defects:
        defects = json.loads(Path(a.defects).read_text())["defects"]
    else:
        defects = json.loads((ROOT / "bench" / "defects.json").read_text())["defects"]
        verdict = json.loads((ROOT / "results" / "verdicts.json").read_text())
        defects = [d for d in defects if verdict.get(d["id"]) == "FIRES"]
    if a.only:
        defects = [d for d in defects if d["id"] in a.only]

    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = Path(a.out)
    records = json.loads(out.read_text()) if (a.resume and out.exists()) else []
    done = {(r["id"], r["arm"], r["rep"]) for r in records if not r.get("error")}
    total = sum(r.get("cost_usd", 0.0) for r in records)

    for d in defects:
        for arm in a.arms:
            for rep in range(a.reps):
                if (d["id"], arm, rep) in done:
                    continue
                text, m, err = run_once(repo, d["changed"], arm, a.model, a.cli, a.timeout)
                total += m.get("cost_usd", 0.0)
                hit = bool(text) and (scored_with(d["match"], text) if d.get("match")
                                      else scored(d["id"], text))
                records = [r for r in records
                           if (r["id"], r["arm"], r["rep"]) != (d["id"], arm, rep)]
                records.append({"id": d["id"], "class": d["class"], "arm": arm,
                                "rep": rep, "hit": hit, "error": err,
                                "stratum": d.get("stratum"),
                                "mechanism": d.get("mechanism"),
                                "import_style": d.get("import_style"),
                                "repo": str(repo), "review": text, **m})
                tag = "ERR " if err else ("HIT " if hit else "MISS")
                print(f"  {d['id']} {arm:12} rep{rep} {tag} ${m.get('cost_usd', 0):.3f} "
                      f"turns={m.get('turns')} in={m.get('input_tokens')} "
                      f"cache_r={m.get('cache_read')}"
                      + (f"  {err[:70]}" if err else ""), flush=True)
                (outdir / f"{d['id']}_{arm.replace('+', '-')}_{rep}.txt").write_text(
                    text or f"ERROR: {err}")
                out.write_text(json.dumps(records, indent=2))
                time.sleep(a.pace)

    ok = [r for r in records if not r.get("error")]
    print(f"\n{len(ok)} reviews, {len(records) - len(ok)} errored, ${total:.2f}\n")
    print(f"{'class':6} {'n':>3}" + "".join(f"{s:>16}" for s in a.arms))
    for cls in ("L", "X", "H", "*"):
        sub = [r for r in ok if cls in (r["class"], "*")]
        if not sub:
            continue
        cells = ""
        for s in a.arms:
            rs = [r for r in sub if r["arm"] == s]
            cells += f"{sum(r['hit'] for r in rs)/len(rs):>16.0%}" if rs else f"{'-':>16}"
        print(f"{cls:6} {len({r['id'] for r in sub}):>3}{cells}")
    print()
    for s in a.arms:
        rs = [r for r in ok if r["arm"] == s]
        if rs:
            print(f"{s:14} ${sum(r['cost_usd'] for r in rs)/len(rs):.3f}/review  "
                  f"turns {sum(r['turns'] for r in rs)/len(rs):.1f}  "
                  f"cache_read {sum(r['cache_read'] for r in rs)/len(rs):,.0f}")


if __name__ == "__main__":
    main()
