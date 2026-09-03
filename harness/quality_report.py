#!/usr/bin/env python3
"""Re-score context recall, weighted by whether each defect actually breaks.

run_bench.py treats all twelve seeded defects as equal. verify_defects.py shows
they are not: nine reproduce at runtime (FIRES), two are latent couplings that
only break on a future edit (LATENT), one is a readability issue (STATIC).

A strategy that catches the latent ones and misses the firing ones scores well
on the unweighted table while being useless in production. This re-scores on
the FIRES subset - the defects a reviewer would be blamed for missing - and
also reports context precision, because recall bought by returning most of the
repository is not a context reduction at all.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ["full-repo", "diff-only", "graph", "graph+callers"]

# From harness/verify_defects.py
VERDICT = {
    "D01": "FIRES", "D02": "FIRES", "D03": "STATIC", "D04": "FIRES",
    "D05": "FIRES", "D06": "FIRES", "D07": "FIRES", "D08": "FIRES",
    "D09": "FIRES", "D10": "FIRES", "D11": "LATENT", "D12": "LATENT",
}
# Caught by harness/string_contracts.py at zero token cost.
STRING_PREPASS = {"D08", "D09", "D10"}


def main():
    data = json.loads((ROOT / "results" / "crg_depth2.json").read_text())
    rows = data["rows"]
    n_repo = data["repo_files"]

    w = print
    w("\n=== 1. Recall on the defects that actually break (FIRES only) ===\n")
    fires = [r for r in rows if VERDICT[r["id"]] == "FIRES"]
    w(f"{'class':6} {'n':>3}" + "".join(f"{s:>15}" for s in STRATEGIES) + f"{'+string':>10}")
    w("-" * 76)
    for cls in ("L", "X", "H", "*"):
        sub = fires if cls == "*" else [r for r in fires if r["class"] == cls]
        if not sub:
            continue
        cells = "".join(
            f"{sum(r[f'{s}_hit'] for r in sub) / len(sub):>15.0%}" for s in STRATEGIES)
        with_str = sum(r["graph+callers_hit"] or r["id"] in STRING_PREPASS for r in sub)
        w(f"{cls:6} {len(sub):>3}{cells}{with_str / len(sub):>10.0%}")

    w("\n=== 2. What the unweighted table was crediting ===\n")
    w(f"{'id':5} {'cls':4} {'verdict':8} {'graph':>6} {'g+call':>7}")
    w("-" * 40)
    for r in sorted(rows, key=lambda r: r["id"]):
        if r["class"] != "H":
            continue
        m = lambda k: "HIT" if r[f"{k}_hit"] else "MISS"
        w(f"{r['id']:5} {r['class']:4} {VERDICT[r['id']]:8} "
          f"{m('graph'):>6} {m('graph+callers'):>7}")
    h_fires = [r for r in rows if r["class"] == "H" and VERDICT[r["id"]] == "FIRES"]
    h_latent = [r for r in rows if r["class"] == "H" and VERDICT[r["id"]] == "LATENT"]
    w(f"\n  graph on H-class that FIRES  : "
      f"{sum(r['graph_hit'] for r in h_fires)}/{len(h_fires)}")
    w(f"  graph on H-class that is LATENT: "
      f"{sum(r['graph_hit'] for r in h_latent)}/{len(h_latent)}")

    w("\n=== 3. Context precision - is the recall real, or just over-inclusion? ===\n")
    w(f"{'id':5} {'needed':>7} {'graph ret':>10} {'% of repo':>10} {'precision':>10}")
    w("-" * 48)
    tot_p, tot_share = 0.0, 0.0
    for r in sorted(rows, key=lambda r: r["id"]):
        need, ret = set(r["evidence"]), set(r["graph_files"])
        prec = len(need & ret) / len(ret) if ret else 0.0
        share = len(ret) / n_repo
        tot_p += prec
        tot_share += share
        w(f"{r['id']:5} {len(need):>7} {len(ret):>10} {share:>9.0%} {prec:>10.0%}")
    w(f"\n  mean: blast radius returns {tot_share / len(rows):.0%} of the repository, "
      f"precision {tot_p / len(rows):.0%}")
    worst = max(rows, key=lambda r: len(r["graph_files"]))
    w(f"  worst: {worst['id']} returns {len(worst['graph_files'])}/{n_repo} files "
      f"({len(worst['graph_files']) / n_repo:.0%}) - a HIT bought by reading almost everything")


if __name__ == "__main__":
    main()
