#!/usr/bin/env python3
"""How many reviewed PRs does the internal A/B actually need?

The in-house test compares "findings reported" between two context strategies
and has not reached significance. That is the expected outcome, not a surprise:
detecting a small drop in a rate needs far more paired observations than a few
weeks of PRs provide.

Two designs are costed:

  unpaired  two independent arms (arm A reviews some PRs, arm B reviews others).
            Needs the most samples; this is usually what teams accidentally run.
  paired    every PR is reviewed *both* ways (McNemar). Only the PRs where the
            two strategies disagree carry information, so it needs far fewer
            PRs. This is the design to switch to.

No SciPy: the normal-approximation formulas are closed-form.
"""
from math import ceil, sqrt

Z = {0.80: 0.8416, 0.90: 1.2816}          # one-sided z for power
Z_ALPHA_2 = {0.05: 1.9600, 0.10: 1.6449}  # two-sided z for alpha


def n_unpaired(p1, p2, alpha=0.05, power=0.80):
    """Per-arm n for two independent proportions."""
    za, zb = Z_ALPHA_2[alpha], Z[power]
    pbar = (p1 + p2) / 2
    num = (za * sqrt(2 * pbar * (1 - pbar)) + zb * sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return ceil(num / (p1 - p2) ** 2)


def n_paired(p1, p2, discordance, alpha=0.05, power=0.80):
    """Total pairs for McNemar. `discordance` = P(the two strategies disagree)."""
    za, zb = Z_ALPHA_2[alpha], Z[power]
    d = abs(p1 - p2)
    if d >= discordance:
        discordance = d                       # cannot disagree less than they differ
    psi = d / discordance                     # directional imbalance among discordant pairs
    n_disc = ceil(((za / 2 + zb * sqrt(1 - psi ** 2)) / psi) ** 2)
    return ceil(n_disc / discordance), n_disc


def main():
    base = 0.70   # findings a full-context review reports (assumed detection rate)
    print(f"assumed baseline detection rate: {base:.0%}\n")
    print(f"{'true drop':>10} {'graph rate':>11} {'unpaired n/arm':>15} {'paired PRs':>11} "
          f"{'(discordant)':>13}")
    print("-" * 64)
    for drop in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30):
        p2 = base - drop
        nu = n_unpaired(base, p2)
        # discordant pairs: at least the drop, plus noise from model run-to-run
        # variance. 0.15 is a deliberately optimistic-but-plausible value.
        np_, nd = n_paired(base, p2, discordance=max(drop + 0.10, 0.15))
        print(f"{drop:>10.0%} {p2:>11.0%} {nu:>15,} {np_:>11,} {nd:>13,}")

    print("\nReading: to prove a 5-point drop (70%->65%) at 80% power / alpha 0.05,")
    print("an unpaired A/B needs ~1,380 reviewed PRs per arm. The paired design")
    print("needs ~194 PRs total. Anything smaller cannot resolve the effect, so")
    print("'not significant' at n<200 is uninformative, not reassuring.")
    print("\nCheaper still: context recall (this repo's benchmark) is a *deterministic*")
    print("measurement with zero run-to-run variance, so a single pass over N seeded")
    print("defects bounds review quality without any significance testing at all.")


if __name__ == "__main__":
    main()
