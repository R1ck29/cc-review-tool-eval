#!/usr/bin/env python3
"""あり/なし の判断材料を、実測ファイルだけから組み立てる。

cost_rework.py は検出率・指摘件数・トークン単価をソースに直書きしていた。
その3つはすべて results/agent_review.json（エージェント実測）に入っているので、
ここでは読み取るだけにする。仮定は CLI 引数に出してあるものだけ。

    python harness/decide.py --rework-hours 4 --defects-per-pr 0.5
"""
import argparse
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDING = re.compile(r"^[\s>*_\-#\d.)\[]*finding\s*:?\s*\**\s*(.+)$", re.I)


def n_findings(review: str) -> int:
    return sum(1 for line in (review or "").splitlines()
               if FINDING.match(line.strip()) and "none" not in line.lower()[-12:])


def arms(records):
    out = {}
    for arm in dict.fromkeys(r["arm"] for r in records):
        rs = [r for r in records if r["arm"] == arm and not r.get("error")]
        if not rs:
            continue
        ids = sorted({r["id"] for r in rs})
        out[arm] = {
            "n": len(rs),
            "defects": len(ids),
            "detect": sum(r["hit"] for r in rs) / len(rs),
            "findings": statistics.median(n_findings(r["review"]) for r in rs),
            "cost": statistics.mean(r["cost_usd"] for r in rs),
            "turns": statistics.mean(r["turns"] for r in rs if r.get("turns")),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", default=str(ROOT / "results" / "agent_review.json"))
    ap.add_argument("--defects-per-pr", type=float, default=0.5)
    ap.add_argument("--triage-min", type=float, default=1.0)
    ap.add_argument("--rate", type=float, default=60.0)
    ap.add_argument("--rework-hours", type=float, default=4.0)
    ap.add_argument("--prs-per-month", type=int, default=200)
    ap.add_argument("--reviews-per-pr", type=float, default=1.0)
    a = ap.parse_args()

    data = arms(json.loads(Path(a.measured).read_text()))
    rework = a.rework_hours * a.rate
    print(f"\n実測: {Path(a.measured).name}")
    print(f"仮定: 見逃し1件 = {a.rework_hours}h x ${a.rate}/h = ${rework:,.0f} / "
          f"欠陥 {a.defects_per_pr}件/PR / 指摘1件 {a.triage_min}分 / {a.prs_per_month} PR月\n")
    print(f"{'arm':14} {'n':>3} {'検出率':>7} {'指摘/件':>8} {'$/レビュー':>11} "
          f"{'トリアージ':>10} {'手戻り':>9} {'合計/PR':>9} {'合計/月':>10}")
    print("-" * 96)
    rows = []
    for name, m in data.items():
        tok = m["cost"] * a.reviews_per_pr
        triage = m["findings"] * (a.triage_min / 60) * a.rate * a.reviews_per_pr
        escaped = a.defects_per_pr * (1 - m["detect"]) * rework
        total = tok + triage + escaped
        rows.append((name, m, total, tok, triage))
        print(f"{name:14} {m['n']:>3} {m['detect']:>7.0%} {m['findings']:>8.0f} "
              f"{tok:>11.2f} {triage:>10.2f} {escaped:>9.2f} {total:>9.2f} "
              f"{total * a.prs_per_month:>10,.0f}")

    base = next((r for r in rows if r[0] == "agent"), rows[0])
    print(f"\n基準 = {base[0]}（ツールなし）")
    for name, m, total, tok, triage in rows:
        if name == base[0]:
            continue
        d = total - base[2]
        print(f"  {name:14} {d:+8.2f}/PR  {d * a.prs_per_month:+10,.0f}/月  "
              f"({'安い' if d < 0 else '高い'})")
        gain = a.defects_per_pr * (m["detect"] - base[1]["detect"])
        extra = (tok + triage) - (base[3] + base[4])
        if gain > 0 and extra > 0:
            c = extra / gain
            print(f"{'':16}損益分岐: 見逃し1件が ${c:,.0f}（= {c / a.rate:.1f}h）以上なら元が取れる")
        elif gain <= 0 and extra > 0:
            print(f"{'':16}損益分岐: 検出率が上回らないので、追加費用を回収する条件がない")
        elif extra <= 0:
            print(f"{'':16}固定費でも安いので常に勝つ")


if __name__ == "__main__":
    main()
