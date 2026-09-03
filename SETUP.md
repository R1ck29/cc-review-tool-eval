# 再現するための準備

このリポジトリのベンチマーク用フィクスチャ（`bench/repo` など）は、
`code-review-graph` が**ファイル列挙に git を使う**ため、git リポジトリである必要があります。
クローン直後は git 履歴を持たないので、最初に一度だけ初期化してください。

```bash
bash setup_fixtures.sh
```

これをやらずに `code-review-graph build --repo bench/repo` を実行すると
`Full build: 0 files` となり、ベンチマークが全戦略 33% に潰れます（実際に踏みました）。

その後の再現手順は [`README.md`](README.md) の「再現手順」を参照してください。
