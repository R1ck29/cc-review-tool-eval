# 変更履歴

[Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) の形式に従います。
従来はリポジトリ自身のバージョン定義がなかったため、今回から `VERSION` で管理します。

## [0.1.1] - 2026-11-17

### 追加

- push・プルリクエスト・手動実行に対応する GitHub Actions の `verify` を追加。
- `setup_fixtures.sh` と `bench/`・`harness/` 内のシェルスクリプトの ShellCheck、Python 構文チェック、既存の仕込み欠陥検証を実行。

### アップグレード方法

- 既存クローンで `git pull --ff-only` を実行するか、新版をダウンロードしてください。
- CLI・設定・データ形式・ワークスペース配置の変更はなく、追加の移行操作は不要です。
- 評価用フィクスチャのテストは意図的に失敗するため、CI では `python harness/verify_defects.py` で欠陥の再現を確認します。
