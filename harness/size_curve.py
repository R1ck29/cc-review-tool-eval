"""What determines the saving: the size of the CHANGED file, not the repo.

Sweeps files across the whole size range of a repository and measures, for each,
what RULE 2 saves and what RULE 1 avoids. Produces the bucket table in
docs/GETTING_STARTED.md. No LLM calls - drives the local MCP server only.

    python harness/size_curve.py <repo> <out.json>
"""
from __future__ import annotations
import json, subprocess, sys, statistics
from pathlib import Path
sys.path.insert(0,"harness")
from measure_savings import call_tool, est_tokens

if len(sys.argv) < 3:
    sys.exit(__doc__.strip().splitlines()[-1].strip())

root = Path(sys.argv[1]).resolve()
if not (root / ".code-review-graph").exists():
    sys.exit(f"No graph at {root}/.code-review-graph\n"
             f"Build it first:  code-review-graph build --repo {root}")
SKIP = {".code-review-graph","node_modules",".venv","dist","build","__pycache__",".git"}
files = [p for p in sorted(root.rglob("*.py"))
         if not any(s in p.parts for s in SKIP) and "test" not in p.name.lower()]
# サイズ順に並べて全域から均等に取る（大小の偏りを避ける）
files.sort(key=lambda p: len(p.read_text(errors="ignore")))
n = 15
picks = [files[round(i*(len(files)-1)/(n-1))] for i in range(n)]

print(f"{'changed file':38} {'file size':>9} {'before':>9} {'after':>9} {'saved':>6} {'impact':>9}")
print("-"*88)
rows=[]
for p in picks:
    rel=str(p.relative_to(root))
    fsz=est_tokens(p.read_text(errors="ignore"))
    d,_=call_tool(str(root),"get_review_context_tool",{"changed_files":[rel]})
    n2,_=call_tool(str(root),"get_review_context_tool",{"changed_files":[rel],"max_results":25,"max_depth":1})
    im,_=call_tool(str(root),"get_impact_radius_tool",{"changed_files":[rel]})
    b,a,i=est_tokens(d),est_tokens(n2),est_tokens(im)
    rows.append((rel,fsz,b,a,i))
    print(f"{rel[-38:]:38} {fsz:>9,} {b:>9,} {a:>9,} {b/max(a,1):>5.1f}x {i:>9,}")
json.dump([{"file":r[0],"size":r[1],"before":r[2],"after":r[3],"impact":r[4]} for r in rows],
          open(sys.argv[2],"w"), indent=1)
print("\n--- サイズ帯別 ---")
buckets=[("~1k",0,1000),("1k-3k",1000,3000),("3k-8k",3000,8000),("8k+",8000,10**9)]
for label,lo,hi in buckets:
    sel=[r for r in rows if lo<=r[1]<hi]
    if not sel: continue
    mb=statistics.mean(r[2] for r in sel); ma=statistics.mean(r[3] for r in sel)
    mi=statistics.mean(r[4] for r in sel)
    print(f"  {label:6} n={len(sel):<2} RULE2 {mb:>8,.0f}->{ma:>8,.0f} = {mb/max(ma,1):>4.1f}x   RULE1が回避する impact {mi:>9,.0f}")
