#!/usr/bin/env python3
"""検出力のある X クラス・ベンチマークを生成する。

前回の比較 (agent_review.py, n=9) は McNemar p=1.000・検出力 0% だった。
原因は設計側にある:
  - 9件中8件を両アームが当てる天井効果
  - L クラス(単一ファイル=道具不要)と H クラス(グラフに原理的に映らない)が
    半分以上を占め、差がつきうるのは X クラス3件だけだった
  - 15ファイルのリポでは grep が一発で終わる

ここでは差がつきうる X クラス(ファイル跨ぎ・静的エッジあり)だけを 30 件生成する。
30 ペアあれば 20pt の差を 80% で検出できる (harness/compare_arms.py の検出力計算)。

設計上の要点:

  層別      symbol 名が衝突するか否かで 15 件ずつに分ける。grep はユニーク名なら
            一発で当たり、衝突名では数百ヒットを返す。グラフの主張が効くのは後者
            だけのはずなので、層別しないと効果が薄まって見えなくなる。
  機構      signature / attribute / return_shape の3種を回す。1種類だと
            「その機構が得意なだけ」の結果を全体の結論に読み違える。
  import    style B (`from pkg import mod`) は 3/30 = 10%。実コードの実測は
            0〜3.7% なので、これでもまだ impact のバグに甘い設定。
  変更規模  1 PR = 2〜3 ファイル変更 (欠陥ファイル + 無害な隣接ファイル)。
            実PRに近づけると同時に blast radius の価値が出やすい側に倒している。
  規模      make_scaled_repo.py と同じ 60 個の合成サービスで包み、grep にノイズを与える。

    python harness/make_xbench.py /tmp/xbench --defects 30
"""
import argparse
import json
import random
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FEATURES = ["billing", "ledger", "settlement", "invoice", "payout", "refund",
            "tax", "fx", "dunning", "wallet", "escrow", "receipt", "quote",
            "subscription", "coupon"]
CONSUMERS = ["api", "worker", "cli", "batch", "webhook", "report", "sync",
             "admin", "export", "scheduler"]
COLLIDING = ["compute", "resolve", "handle", "build", "render"]

# ---- producer templates -------------------------------------------------
PROD_SIGNATURE = '''"""{feat} core."""

BASE_RATE = {rate}


def {sym}(amount_cents, quantity, rate_bps):
    """Return the {feat} total.

    rate_bps was added because {feat} now varies by contract.
    """
    return int(amount_cents * quantity * (1 + rate_bps / 10000))
'''

PROD_ATTRIBUTE = '''"""{feat} core."""


class {cls}:
    """A {feat} record."""

    def __init__(self, ident, amount_cents):
        self.ident = ident
        self.amount_minor_units = amount_cents


def {sym}(ident, amount_cents):
    return {cls}(ident, amount_cents)
'''

PROD_RETURN = '''"""{feat} core."""


def {sym}(ident, amount_cents):
    """Return the {feat} summary.

    Now returns a mapping so new fields can be added without breaking arity.
    """
    return {{"ident": ident, "amount_cents": amount_cents, "currency": "JPY"}}
'''

# ---- consumer templates -------------------------------------------------
CONS_SIGNATURE = '''"""{cons} entry point for {feat}."""
{importline}


def {entry}(amount_cents, quantity):
    """Charge one {feat} line."""
    total = {call}(amount_cents, quantity)
    return {{"total_cents": total}}
'''

CONS_ATTRIBUTE = '''"""{cons} entry point for {feat}."""
{importline}


def {entry}(ident, amount_cents):
    """Render one {feat} record."""
    record = {call}(ident, amount_cents)
    return f"{{record.ident}}: {{record.amount_cents}}"
'''

CONS_RETURN = '''"""{cons} entry point for {feat}."""
{importline}


def {entry}(ident, amount_cents):
    """Summarise one {feat} record."""
    ident_out, amount_out = {call}(ident, amount_cents)
    return f"{{ident_out}}/{{amount_out}}"
'''

NEIGHBOUR = '''"""{feat} {kind} helpers (unchanged behaviour)."""


def describe_{kind}(value):
    return f"{kind}={{value}}"


def normalise_{kind}(value):
    return str(value).strip().lower()
'''

FILLER = '''"""{pkg} {mod} (synthetic filler)."""


def compute(amount_cents, quantity):
    return amount_cents * quantity


def resolve(key, table):
    return table.get(key)


def handle(payload):
    return {{"ok": True, "id": payload.get("id")}}


def build(rows):
    return [dict(r) for r in rows]


def render(record):
    return f"{{record}}"
'''

MECHANISMS = ["signature", "attribute", "return_shape"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest")
    ap.add_argument("--defects", type=int, default=30)
    ap.add_argument("--filler-packages", type=int, default=60)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    dest = Path(a.dest)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "features").mkdir(parents=True)
    (dest / "consumers").mkdir()
    (dest / "services").mkdir()
    (dest / "features" / "__init__.py").write_text('"""Feature packages."""\n')
    (dest / "consumers" / "__init__.py").write_text('"""Consumer packages."""\n')
    (dest / "services" / "__init__.py").write_text('"""Synthetic filler."""\n')

    # grep noise: the colliding names appear in every filler module
    fill_names = ["orders", "pricing", "repository", "handlers", "serializers"]
    for i in range(a.filler_packages):
        pkg = f"svc_{i:02d}"
        d = dest / "services" / pkg
        d.mkdir()
        (d / "__init__.py").write_text(f'"""{pkg}."""\n')
        for mod in fill_names:
            (d / f"{mod}.py").write_text(FILLER.format(pkg=pkg, mod=mod))

    defects = []
    style_b_slots = set(rng.sample(range(a.defects), k=max(1, a.defects // 10)))
    for i in range(a.defects):
        did = f"X{i + 1:02d}"
        mech = MECHANISMS[i % len(MECHANISMS)]
        colliding = (i % 2 == 1)          # 15 / 15
        feat = f"{FEATURES[i % len(FEATURES)]}_{i // len(FEATURES):02d}"
        cons = f"{CONSUMERS[i % len(CONSUMERS)]}_{i // len(CONSUMERS):02d}"
        sym = (COLLIDING[i % len(COLLIDING)] if colliding
               else f"{feat.split('_')[0]}_total_{i:02d}")
        cls = f"{feat.split('_')[0].capitalize()}Record{i:02d}"
        entry = f"run_{i:02d}"

        fd = dest / "features" / feat
        fd.mkdir(exist_ok=True)
        (fd / "__init__.py").write_text(f'"""{feat}."""\n')
        prod = {"signature": PROD_SIGNATURE, "attribute": PROD_ATTRIBUTE,
                "return_shape": PROD_RETURN}[mech]
        (fd / "core.py").write_text(prod.format(feat=feat, sym=sym, cls=cls,
                                                rate=100 + i))
        for kind in ("format", "audit"):
            (fd / f"{kind}.py").write_text(NEIGHBOUR.format(feat=feat, kind=kind))

        cd = dest / "consumers" / cons
        cd.mkdir(exist_ok=True)
        (cd / "__init__.py").write_text(f'"""{cons}."""\n')
        if i in style_b_slots:
            importline = f"from features.{feat} import core"
            call = f"core.{sym}"
        else:
            importline = f"from features.{feat}.core import {sym}"
            call = sym
        cons_tpl = {"signature": CONS_SIGNATURE, "attribute": CONS_ATTRIBUTE,
                    "return_shape": CONS_RETURN}[mech]
        client = f"client_{i:02d}.py"
        (cd / client).write_text(cons_tpl.format(cons=cons, feat=feat, entry=entry,
                                                 importline=importline, call=call))

        failure = {"signature": ["typeerror", "missing", "argument", "parameter",
                                 "signature", "arity", "three", "rate_bps"],
                   "attribute": ["attributeerror", "renamed", "no attribute",
                                 "does not exist", "amount_minor_units", "mismatch",
                                 "not match"],
                   "return_shape": ["dict", "mapping", "unpack", "typeerror",
                                    "valueerror", "tuple", "return", "shape"]}[mech]
        defects.append({
            "id": did, "class": "X", "mechanism": mech,
            "stratum": "colliding" if colliding else "unique",
            "import_style": "B" if i in style_b_slots else "A",
            "symbol": sym, "entry": entry,
            "changed": [f"features/{feat}/core.py",
                        f"features/{feat}/format.py",
                        f"features/{feat}/audit.py"],
            "evidence": [f"consumers/{cons}/{client}"],
            "static_edge": True,
            "match": [[sym], failure, [client, entry, f"consumers/{cons}"]],
        })

    (dest / "xdefects.json").write_text(json.dumps({"defects": defects}, indent=2))
    n = len(list(dest.rglob("*.py")))
    print(f"{dest}: {n} python files, {len(defects)} X-class defects "
          f"({sum(d['stratum'] == 'colliding' for d in defects)} colliding / "
          f"{sum(d['import_style'] == 'B' for d in defects)} style-B)")
    print(f"manifest: {dest / 'xdefects.json'}")


if __name__ == "__main__":
    main()
