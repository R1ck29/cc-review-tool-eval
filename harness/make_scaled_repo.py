#!/usr/bin/env python3
"""bench/repo at a size where `grep` stops being free.

bench/repo has 15 files. In a repo that small a plain agent finds a cross-file
caller by grepping once, so a with/without comparison there measures nothing
about scale - which is the graph's entire value proposition.

This wraps the same 15 files (same defects, same imports, same graph edges) in
N synthetic service packages that reuse the same function and topic names. The
defect files are untouched; what changes is that `grep compute_total` now
returns dozens of unrelated definitions and the reviewer has to decide which
call site is the real one.

Synthetic, and named as such: real repositories are not built from a template.
The one property it reproduces on purpose is name collision at scale, which is
what makes symbol-level lookup worth more than text search.

    python harness/make_scaled_repo.py /tmp/repo_scaled --packages 60
"""
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "bench" / "repo"

MODULE = '''"""{pkg} {mod} layer (synthetic filler)."""
from services.{pkg} import config

{topic_const} = "{topic}"


def compute_total(quantity, unit_cents):
    """Line total for {pkg}."""
    return quantity * unit_cents


def get_order(order_id):
    """Look up a {pkg} order."""
    return {{"id": order_id, "customer_id": None, "status": "open"}}


def order_to_dict(order):
    return {{"customer_id": order["customer_id"], "total_cents": order.get("total_cents", 0)}}


def subscribe(topic, handler):
    config.HANDLERS.setdefault(topic, []).append(handler)


def on_order_created(payload):
    return f"{pkg} handled {{payload.get('id')}}"


def create_order(customer_id, quantity, unit_cents):
    total = compute_total(quantity, unit_cents)
    return {{"customer_id": customer_id, "total_cents": total}}


subscribe({topic_const}, on_order_created)
'''

CONFIG = '''"""{pkg} configuration (synthetic filler)."""
HANDLERS = {{}}
MAX_RETRIES = {retries}
DEFAULT_TOPIC = "{topic}"


def get(key, default=None):
    return globals().get(key, default)
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--packages", type=int, default=60)
    ap.add_argument("--modules", type=int, default=3)
    a = ap.parse_args()

    dest = Path(a.dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns(
        "__pycache__", ".code-review-graph", ".git"))

    services = dest / "services"
    services.mkdir()
    (services / "__init__.py").write_text('"""Synthetic filler packages."""\n')
    names = ["billing", "shipping", "catalog", "accounts", "inventory", "notify",
             "search", "reports", "audit", "webhooks"]
    mods = ["orders", "pricing", "repository", "handlers", "serializers"][:a.modules]
    for i in range(a.packages):
        pkg = f"{names[i % len(names)]}_{i // len(names):02d}"
        pdir = services / pkg
        pdir.mkdir()
        (pdir / "__init__.py").write_text(f'"""{pkg} package."""\n')
        (pdir / "config.py").write_text(CONFIG.format(pkg=pkg, retries=i % 5 + 1,
                                                      topic=f"{pkg}.order_created"))
        for mod in mods:
            (pdir / f"{mod}.py").write_text(MODULE.format(
                pkg=pkg, mod=mod, topic_const="ORDER_TOPIC",
                topic=f"{pkg}.order_created"))

    n = len(list(dest.rglob("*.py")))
    print(f"wrote {dest}: {n} python files "
          f"({a.packages} filler packages x {len(mods) + 2} modules + the 14 benchmark files)")


if __name__ == "__main__":
    main()
