#!/usr/bin/env bash
# ベンチマーク用フィクスチャを git リポジトリとして初期化する。
# code-review-graph はファイル列挙に git を使うため、これがないと 0 files になる。
set -euo pipefail
cd "$(dirname "$0")"

for d in bench/repo bench/probe_importstyle bench/repo_annotated_backup; do
    [ -d "$d" ] || { echo "skip (missing): $d"; continue; }
    if [ -d "$d/.git" ]; then
        echo "already a git repo: $d"
        continue
    fi
    git -C "$d" init -q
    git -C "$d" add -A
    git -C "$d" -c user.email=fixture@local -c user.name=fixture \
        commit -q -m "fixture seed"
    echo "initialised: $d"
done
echo
echo "done. verify with:"
echo "  code-review-graph build --repo bench/repo   # expect: 15 files"
