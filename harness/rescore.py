#!/usr/bin/env python3
"""Re-score saved blind reviews without re-running them.

Scoring rules changed once already (whole-review matching produced false
positives). Because every raw review is on disk, re-scoring costs nothing and
keeps the expensive part - the reviews themselves - untouched.

Also prints, for each cell, the finding that matched, so the score can be
checked by eye rather than trusted.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from blind_review import MATCH, findings, scored  # noqa: E402

STRATS = ["diff-only", "graph", "graph+callers", "full-repo"]


def matched_finding(defect_id, text):
    import re
    for f in findings(text):
        low = f.lower()
        if all(any(re.search(re.escape(a.lower()), low) for a in g)
               for g in MATCH[defect_id]):
            return f
    return None


def main():
    recs = json.loads((ROOT / "results" / "blind_review.json").read_text())
    ok = [r for r in recs if r.get("review")]
    for r in ok:
        r["hit"] = scored(r["id"], r["review"])
    (ROOT / "results" / "blind_review.json").write_text(json.dumps(recs, indent=2))

    ids = sorted({r["id"] for r in ok})
    print(f"\n{len(ok)} scored reviews "
          f"({len(recs) - len(ok)} errored, excluded)\n")
    print(f"{'id':5} {'cls':4}" + "".join(f"{s:>16}" for s in STRATS))
    print("-" * 70)
    for did in ids:
        row = {r["strategy"]: r for r in ok if r["id"] == did}
        cls = next(iter(row.values()))["class"]
        cells = ""
        for s in STRATS:
            r = row.get(s)
            cells += f"{'-':>16}" if r is None else f"{('HIT' if r['hit'] else 'MISS'):>16}"
        print(f"{did:5} {cls:4}{cells}")

    print(f"\n{'class':6} {'n':>3}" + "".join(f"{s:>16}" for s in STRATS))
    print("-" * 70)
    for cls in ("L", "X", "H", "*"):
        sub = [r for r in ok if cls in (r["class"], "*")]
        if not sub:
            continue
        cells = ""
        for s in STRATS:
            rs = [r for r in sub if r["strategy"] == s]
            cells += f"{sum(r['hit'] for r in rs) / len(rs):>15.0%}" + " " if rs else f"{'-':>16}"
        print(f"{cls:6} {len({r['id'] for r in sub}):>3}{cells}")

    print("\n--- matched finding per HIT (audit) ---")
    for r in sorted(ok, key=lambda r: (r["id"], r["strategy"])):
        if r["hit"]:
            f = matched_finding(r["id"], r["review"])
            print(f"\n{r['id']} / {r['strategy']}:\n  {f[:230]}")


if __name__ == "__main__":
    main()
