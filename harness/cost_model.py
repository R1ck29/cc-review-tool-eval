#!/usr/bin/env python3
"""Total cost per PR review: no tool vs each tool, with and without caching.

Per-query context measurements (run_bench.py) miss the two costs that decide
whether a tool actually saves money:

  1. An MCP server's tool definitions render into `tools`, at the very front of
     the prompt prefix, on every request for the whole session.
  2. Prompt caching. Because `tools` sits at position 0, those definitions are
     cacheable - so the fixed overhead is paid at ~1.25x once and ~0.1x
     thereafter, not at full price every time. Ignoring caching overstates the
     MCP tax by roughly 10x.

Claude Opus 5 pricing (verified 2026-08-11): $5.00 / MTok input,
$25.00 / MTok output. Cache read ~0.1x input, cache write ~1.25x input (5-min
TTL). Minimum cacheable prefix on Opus 5 is 512 tokens.
"""
import argparse

IN, OUT = 5.00 / 1e6, 25.00 / 1e6
CACHE_READ, CACHE_WRITE = 0.1 * IN, 1.25 * IN
MIN_CACHEABLE = 512

# Measured on this repo's benchmark (see results/crg_depth2.json, mcp_overhead.py).
MCP_TOOL_TOKENS = 7615      # code-review-graph: 30 MCP tools
SKILL_FRONTMATTER = 60      # Ix: SKILL.md frontmatter; body loads on demand
GRAPH_PAYLOAD = 680         # impact JSON returned per review
CALLERS_PAYLOAD = 90        # query callers_of, additive


def cost(fixed, per_turn_in, turns, out_per_turn, cached=True):
    """Cost of one review: `turns` requests, conversation grows each turn."""
    total = 0.0
    history = 0
    for t in range(turns):
        new = per_turn_in if t else per_turn_in + fixed
        if cached and (history + new) >= MIN_CACHEABLE:
            total += history * CACHE_READ + new * CACHE_WRITE
        else:
            total += (history + new) * IN
        total += out_per_turn * OUT
        history += new + out_per_turn
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-tokens", type=int, default=400_000,
                    help="whole-repo size; only the full-read baseline pays this")
    ap.add_argument("--diff-tokens", type=int, default=1_500)
    ap.add_argument("--graph-context", type=int, default=6_000,
                    help="files the blast radius surfaces, in tokens")
    ap.add_argument("--turns", type=int, default=12)
    ap.add_argument("--out-per-turn", type=int, default=600)
    ap.add_argument("--reviews-per-month", type=int, default=200)
    ap.add_argument("--budget-cap", type=float, default=1500.0,
                    help="monthly budget per engineer, for the %% column")
    a = ap.parse_args()

    d, g, t, o = a.diff_tokens, a.graph_context, a.turns, a.out_per_turn

    configs = [
        ("no tool - full repo read", 0, a.repo_tokens),
        ("no tool - diff + grep", 0, d + 2_000),
        ("code-review-graph via MCP", MCP_TOOL_TOKENS, d + g + GRAPH_PAYLOAD),
        ("code-review-graph via CLI+skill", 0, d + g + GRAPH_PAYLOAD),
        ("  + query callers_of", 0, d + g + GRAPH_PAYLOAD + CALLERS_PAYLOAD),
        ("Ix (CLI + skill)", SKILL_FRONTMATTER, d + g + GRAPH_PAYLOAD),
    ]

    for label, cached in (("WITH prompt caching (real)", True),
                          ("WITHOUT caching (worst case)", False)):
        print(f"\n{label} - {t} requests/review, {a.reviews_per_month} reviews/month\n")
        print(f"{'configuration':34} {'fixed':>7} {'ctx':>8} {'$/review':>10} "
              f"{'$/month':>9} {'% of cap':>11}")
        print("-" * 84)
        base = None
        for name, fixed, ctx in configs:
            c = cost(fixed, ctx, t, o, cached=cached)
            m = c * a.reviews_per_month
            if base is None:
                base = c
            print(f"{name:34} {fixed:>7,} {ctx:>8,} {c:>10.3f} {m:>9.0f} "
                  f"{m/a.budget_cap:>10.1%}")

    print(f"\nMCP tool definitions alone ({MCP_TOOL_TOKENS:,} tokens, {t} requests):")
    warm = MCP_TOOL_TOKENS * CACHE_WRITE + (t - 1) * MCP_TOOL_TOKENS * CACHE_READ
    cold = t * MCP_TOOL_TOKENS * IN
    print(f"  cached   ${warm:.4f}/review  ->  ${warm * a.reviews_per_month:.2f}/month")
    print(f"  uncached ${cold:.4f}/review  ->  ${cold * a.reviews_per_month:.2f}/month")
    print("  Caching makes the MCP tax small. It is only large if something")
    print("  invalidates the prefix - and changing the tool set does exactly that,")
    print("  so connecting/disconnecting MCP servers mid-session is the real risk.")


if __name__ == "__main__":
    main()
