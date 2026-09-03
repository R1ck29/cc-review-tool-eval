#!/usr/bin/env python3
"""あり/なし の差を、統計として扱えるかどうかまで含めて出す。

検出率が同じ数字だったことと、差がないことは別。このスクリプトは
(1) 対応あり McNemar 正確検定 (2) その設計の検出力 (3) 二次指標での符号検定
を出して、「今回の実験で何が言えて何が言えないか」を明示する。

    python harness/compare_arms.py --measured results/agent_review.json
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "harness"))
from blind_review import MATCH, findings  # noqa: E402


def exact_p(b, c):
    """McNemar 正確検定 (両側二項)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(sum(math.comb(n, j) for j in range(k + 1)) * 2 / 2 ** n, 1.0)


def power_mcnemar(n, p01, p10, alpha=0.05):
    """対応あり設計の検出力 (正確二項)."""
    pd = p01 + p10
    if pd == 0:
        return 0.0
    pi = p01 / pd
    total = 0.0
    for m in range(n + 1):
        pm = math.comb(n, m) * pd ** m * (1 - pd) ** (n - m)
        if not pm:
            continue
        rej = sum(math.comb(m, b) * pi ** b * (1 - pi) ** (m - b)
                  for b in range(m + 1) if exact_p(b, m - b) <= alpha)
        total += pm * rej
    return total


def all_seeded_hits(review):
    """このレビュー1本が報告した『仕込み欠陥』の集合（変更ファイル以外も含む）."""
    got = set()
    for f in findings(review or ""):
        low = f.lower()
        for did, groups in MATCH.items():
            if all(any(re.search(re.escape(a.lower()), low) for a in g) for g in groups):
                got.add(did)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", default=str(ROOT / "results" / "agent_review.json"))
    ap.add_argument("--base", default="agent")
    ap.add_argument("--test", default="agent+graph")
    ap.add_argument("--out")
    a = ap.parse_args()

    recs = [r for r in json.loads(Path(a.measured).read_text()) if not r.get("error")]
    by = {}
    for r in recs:
        by.setdefault(r["id"], {})[r["arm"]] = r
    pairs = {k: v for k, v in by.items() if a.base in v and a.test in v}

    b = sum(1 for v in pairs.values() if v[a.base]["hit"] and not v[a.test]["hit"])
    c = sum(1 for v in pairs.values() if v[a.test]["hit"] and not v[a.base]["hit"])
    n = len(pairs)
    p = exact_p(b, c)
    print(f"\n対応ペア n={n}  ({a.base} vs {a.test})")
    print(f"  {a.base} のみ正解 = {b} / {a.test} のみ正解 = {c} / 一致 = {n - b - c}")
    print(f"  McNemar 正確検定 p = {p:.3f}"
          + ("  → 有意差なし（ただし下の検出力を見ること）" if p > 0.05 else "  → 有意"))

    print(f"\nこの設計 (n={n}) の検出力")
    print(f"{'真の差':>8}{'検出力':>10}")
    rows = []
    for d in (0.05, 0.10, 0.20, 0.30, 0.40, 0.50):
        pw = power_mcnemar(n, d, 0.0)
        rows.append((d, pw))
        print(f"{d:>8.0%}{pw:>10.0%}")
    print("  ※ 「なし側だけが当てる」ケースを0と仮定した、ツールに最も有利な計算")

    print("\n検出力80%に必要なペア数 (同じ仮定)")
    need = {}
    for d in (0.05, 0.10, 0.20, 0.30):
        k = 1
        while k < 3000 and power_mcnemar(k, d, 0.0) < 0.8:
            k += 1
        need[d] = k
        print(f"  真の差 {d:>4.0%}: {k} ペア")

    # 二次指標: 1レビューが拾った仕込み欠陥の総数（天井効果を避けるため主指標より粒度が細かい）
    print("\n二次指標: 1レビューが報告した仕込み欠陥の総数（12件中）")
    diffs = []
    tb = tt = 0
    for did, v in sorted(pairs.items()):
        hb = all_seeded_hits(v[a.base]["review"])
        ht = all_seeded_hits(v[a.test]["review"])
        tb += len(hb)
        tt += len(ht)
        diffs.append(len(ht) - len(hb))
        print(f"  {did}: {a.base} {len(hb):>2}  {a.test} {len(ht):>2}  差 {len(ht)-len(hb):+d}")
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    print(f"  合計 {a.base} {tb} / {a.test} {tt} (差 {tt-tb:+d})")
    print(f"  符号検定: {a.test} 優位 {pos} / {a.base} 優位 {neg} / 同点 {n-pos-neg}"
          f"  p = {exact_p(pos, neg):.3f}")
    print(f"  run 内変動: 差の範囲 {min(diffs):+d} 〜 {max(diffs):+d}"
          f"  ← アーム間差 ({tt-tb:+d}) より大きい = 反復1回では読めない")

    if a.out:
        Path(a.out).write_text(json.dumps({
            "n_pairs": n, "base_only": b, "test_only": c, "mcnemar_p": p,
            "power": {f"{d:.2f}": pw for d, pw in rows},
            "n_needed_80pct": {f"{d:.2f}": k for d, k in need.items()},
            "secondary_totals": {a.base: tb, a.test: tt},
            "secondary_diffs": diffs, "sign_test_p": exact_p(pos, neg),
        }, indent=2))
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
