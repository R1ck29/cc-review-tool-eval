#!/usr/bin/env python3
"""Rebuild bench/repo with realistic import styles.

bench/repo writes 43.8% of its imports as `from pkg import module` - the one
form `impact` drops (harness/import_style.py). Real projects sit at 0-3.7%, so
every graph recall number measured on bench/repo is pessimistic by an unknown
amount. This rewrites the call sites that can be rewritten (the module-object
import in tasks.py is load-bearing for the D11 dynamic-dispatch defect and
stays), giving a defect-equivalent copy at 6.2%.

    python harness/make_style_a.py /tmp/repo_styleA
    code-review-graph build --repo /tmp/repo_styleA
    python harness/run_bench.py --repo /tmp/repo_styleA --defects bench/defects.json ...

Verified defect-equivalent: verify_defects.py reports FIRES 9 / LATENT 2 /
STATIC 1 on both copies. (D12's check must patch repository.fetch_order_row
instead of db.fetch_order_row: a direct-name import cannot be monkeypatched
through the module object.)
"""
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "bench" / "repo"

REWRITES = {
    "app/orders.py": [
        ("from app import pricing, repository",
         "from app.pricing import compute_total\nfrom app.repository import get_order"),
        ("pricing.compute_total(", "compute_total("),
        ("repository.get_order(", "get_order("),
    ],
    "app/handlers.py": [
        ("from app import events", "from app.events import subscribe"),
        ("events.subscribe(", "subscribe("),
    ],
    "app/repository.py": [
        ("from app import db", "from app.db import fetch_order_row"),
        ("db.fetch_order_row(", "fetch_order_row("),
    ],
    "app/tasks.py": [
        ("from app import config, handlers",
         "from app.config import get\nfrom app import handlers"),
        ('config.get("TASK_HANDLER_PREFIX")', 'get("TASK_HANDLER_PREFIX")'),
    ],
    "app/api.py": [
        ("from app import orders", "from app.orders import create_order"),
        ("orders.create_order(", "create_order("),
    ],
}


def main(dest):
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SRC, dest, ignore=shutil.ignore_patterns(
        "__pycache__", ".code-review-graph", ".git"))
    for rel, pairs in REWRITES.items():
        p = dest / rel
        text = p.read_text()
        for old, new in pairs:
            if old not in text:
                raise SystemExit(f"{rel}: pattern not found: {old!r}")
            text = text.replace(old, new)
        p.write_text(text)
    print(f"wrote {dest} ({len(REWRITES)} files rewritten)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/repo_styleA"))
