#!/usr/bin/env python3
"""Total cost of ownership per PR: tokens + triage + escaped-defect rework.

cost_model.py only counted review-time tokens, and on that basis concluded the
graph does not save money. That framing is incomplete: a defect the review
misses does not become free, it becomes rework. Once escaped defects are
priced, a strategy with a higher token cost can still be the cheaper one.

Three cost terms, per PR:

  tokens   measured, cost_model.py
  triage   an engineer reads every finding the review emits, real or not.
           Findings scale with context (measured: 12 -> 16 -> 24 per review),
           so a bigger context is not free even when the tokens are cheap.
  rework   defects that escape review, priced at whatever it costs your team to
           find and fix one later.

Rework cost is the one number this evaluation cannot measure for you, so the
script solves for it instead: the break-even rework cost above which each
strategy pays for itself. Compare that threshold against your own experience.

Detection rates and findings-per-review are measured (blind_review.py,
36 reviews); everything else is a named assumption you can override.
"""
import argparse

# Measured: harness/blind_review.py, 9 runtime-reproducible defects x 4 strategies.
# "+string" adds harness/string_contracts.py, which catches the two defects
# graph+callers missed (D08, D10) at zero token cost.
STRATEGIES = [
    # name,                     detection, findings/review, token $/review
    ("no tool - diff + grep",       0.33,   12.4,  0.58),
    ("graph (impact only)",         0.56,   16.0,  1.08),
    ("graph + callers_of",          0.78,   15.7,  1.09),
    ("  + string pre-pass",         1.00,   15.7,  1.09),
    ("no tool - full repo read",    0.89,   23.6, 43.40),
]


def totals(detect, n_findings, tokens, defects, triage_min, rate, rework):
    triage = n_findings * (triage_min / 60) * rate
    escaped = defects * (1 - detect) * rework
    return tokens, triage, escaped, tokens + triage + escaped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--defects-per-pr", type=float, default=0.5,
                    help="review-catchable defects introduced per PR")
    ap.add_argument("--triage-min", type=float, default=1.0,
                    help="engineer-minutes to read and judge one finding")
    ap.add_argument("--rate", type=float, default=60.0,
                    help="fully-loaded engineer cost, $/hour")
    ap.add_argument("--rework-hours", type=float, default=4.0,
                    help="engineer-hours to find and fix one escaped defect")
    ap.add_argument("--prs-per-month", type=int, default=200)
    a = ap.parse_args()

    rework = a.rework_hours * a.rate
    print(f"\n1件の見逃しの手戻り = {a.rework_hours}h x ${a.rate}/h = ${rework:,.0f}")
    print(f"PRあたり欠陥 {a.defects_per_pr} 件 / 指摘1件の判断 {a.triage_min} 分 / "
          f"{a.prs_per_month} PR/月\n")

    print(f"{'戦略':26} {'検出率':>6} {'トークン':>8} {'トリアージ':>10} "
          f"{'手戻り':>9} {'合計/PR':>9} {'合計/月':>10}")
    print("-" * 88)
    rows = []
    for name, det, nf, tok in STRATEGIES:
        t, tr, esc, tot = totals(det, nf, tok, a.defects_per_pr,
                                 a.triage_min, a.rate, rework)
        rows.append((name, tot))
        print(f"{name:26} {det:>6.0%} {t:>8.2f} {tr:>10.2f} "
              f"{esc:>9.2f} {tot:>9.2f} {tot * a.prs_per_month:>10,.0f}")

    best = min(rows, key=lambda r: r[1])
    base = rows[0][1]
    print(f"\n最安: {best[0].strip()}  (${best[1]:.2f}/PR, "
          f"ツールなしとの差 ${base - best[1]:+.2f}/PR = "
          f"${(base - best[1]) * a.prs_per_month:+,.0f}/月)")

    # ---- break-even -----------------------------------------------------
    print("\n損益分岐: 1件の見逃しがいくら以上なら、その戦略が『ツールなし・差分のみ』に勝つか")
    print(f"{'戦略':26} {'必要な手戻り単価':>18} {'engineer-hours 換算':>22}")
    print("-" * 70)
    b_det, b_nf, b_tok = STRATEGIES[0][1:]
    b_fixed = b_tok + b_nf * (a.triage_min / 60) * a.rate
    for name, det, nf, tok in STRATEGIES[1:]:
        fixed = tok + nf * (a.triage_min / 60) * a.rate
        gain = a.defects_per_pr * (det - b_det)      # fewer escaped defects
        extra = fixed - b_fixed                       # extra tokens + triage
        if gain <= 0:
            print(f"{name:26} {'検出率で勝てない':>18}")
            continue
        if extra <= 0:
            print(f"{name:26} {'常に勝つ（固定費も安い）':>18}")
            continue
        c = extra / gain
        print(f"{name:26} {'$%.2f' % c:>18} {c / a.rate:>21.2f}h")

    print("\n※ この閾値を自社の実感と比べてください。閾値が実際の手戻り費用より"
          "\n  低ければ、そのツールは払った以上に回収しています。")


if __name__ == "__main__":
    main()
