#!/usr/bin/env python3
"""生成した X クラス欠陥が本当に実行時に壊れるかを確認する。

壊れない「欠陥」を数えた再現率は何も測っていない。前回の評価では
12件のうち3件が実行時に再現しないものだった (verify_defects.py) ので、
今回は生成直後に全件を実行して確かめる。

    python harness/verify_xbench.py /tmp/xbench
"""
import importlib
import json
import sys
from pathlib import Path

ARGS = {"signature": (1000, 2), "attribute": ("id-1", 1000),
        "return_shape": ("id-1", 1000)}
EXPECT = {"signature": TypeError, "attribute": AttributeError,
          "return_shape": (ValueError, TypeError)}


def main(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root))
    defects = json.loads((root / "xdefects.json").read_text())["defects"]
    fires, dead = [], []
    for d in defects:
        mod_path = d["evidence"][0][:-3].replace("/", ".")
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, d["entry"])
        try:
            fn(*ARGS[d["mechanism"]])
        except EXPECT[d["mechanism"]] as e:
            fires.append((d["id"], type(e).__name__, str(e)[:60]))
        except Exception as e:                      # noqa: BLE001
            dead.append((d["id"], f"WRONG {type(e).__name__}: {e}"[:70]))
        else:
            dead.append((d["id"], "no exception - not a defect"))
    for did, kind, msg in fires:
        print(f"  {did} FIRES  {kind}: {msg}")
    for did, why in dead:
        print(f"  {did} DEAD   {why}")
    print(f"\n{len(fires)}/{len(defects)} FIRES")
    return 0 if not dead else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
