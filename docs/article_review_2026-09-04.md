# Zenn記事「ナレッジグラフ戦略」の検証 — 2026-09-04

対象: https://zenn.dev/helloworld/articles/bcaea69f58eae5
（code-review-graph / better-code-review-graph / Graphify / Serena の4ツール併用で
レビュー用コンテキストを「14万トークン→70」に削減、という主張）

制約: ソースを外部に出さない・ローカル完結。

> ⚠️ **本書は時系列の記録です。「追記」節が前の節を訂正しています。**
> 数値を引用する場合は**最後に出てくる値**を使ってください。特に：
> - §2〜§7 のトークン数は JSON-RPC 外殻込みで、**追記3 で約2倍過大と訂正**（モデルが見る量は約半分）
> - §7 の月額は **追記4 で再計算**（$381/$318/$147 → $345/$282/$69）
> - 「最大の削減つまみ」は **追記4 で `--max-results` から `impact` を呼ばないことに訂正**
>
> 結論だけ必要なら [`GETTING_STARTED.md`](GETTING_STARTED.md) を読んでください。

本書の数値はすべて本日このマシンで実測した。既存の
[`verification_2026-08-22.md`](verification_2026-08-22.md) の続きであり、
そこで確立した「ペイロードを数えろ」「実害欠陥で採点しろ」という基準を引き継ぐ。

---

## 結論

**記事の構成は採らない。code-review-graph 単体を CLI+skill で、`impact` を絞って使う。**

記事の4ツール併用は、この環境では**コストを下げず（$318→$381/月）、社外送信リスクを1つ増やす**。
一方で記事が正しく指摘している点（意味検索・LSPによる参照解決）は限定的に取り込む価値がある。

| # | 判定 | 記事の主張 | 実測 |
|---|------|-----------|------|
| 1 | ✅ 正しい | 4ツールは実在・OSS | Star数はむしろ記事より多い（後述） |
| 2 | ❌ 不成立 | 14万→70トークン | 分子と分母が別物。実測は114,529トークン |
| 3 | ❌ 逆効果 | 4ツール併用を推奨 | MCP固定費 16,957トークン/リクエスト |
| 4 | ⚠️ 要統制 | 全ツール「ローカル完結」 | bcrgは環境変数だけでソース本文を外部送信しうる |

---

## 1. ツールの実在性 — 記事は正しい（むしろ過小）

当初 Star 数（Graphify 94k 等）を誇張と疑ったが、GitHub API で確認したところ**記事の数値が古いだけで実際はさらに多い**。

| リポジトリ | 記事 | 実測(2026-09-04) | ライセンス |
|---|---|---|---|
| tirth8205/code-review-graph | 26k | **31,146** | MIT |
| Graphify-Labs/graphify | 94k | **114,233** | Apache-2.0 |
| oraios/serena | 26.8k | **28,780** | MIT |
| n24q02m/better-code-review-graph | 66 | （PyPIにURL記載なし・GitHubに実在） | Apache-2.0 |

4つとも PyPI に存在し、記事のバージョンから進んでいる
（crg 2.3.7→**2.3.8**、bcrg 3.21.0→**3.24.0**、graphifyy 0.9.28→**0.9.53**、serena 1.6.0→**1.7.0**）。

**この点で記事を疑ったのは誤りだった。ツール選定そのものは妥当。**

---

## 2. 「14万→70トークン」は成立しない

記事の「70トークン」を再現した。`detect-changes` の出力である。

```json
{ "summary": "Analyzed 5 changed file(s):\n  - 0 changed function(s)/class(es)\n
             - 0 affected flow(s)\n  - 0 test gap(s)\n  - Overall risk score: 0.00",
  "risk_score": 0.0, "changed_functions": [], "affected_flows": [],
  "context_savings": { "saved_tokens": 3079, "saved_percent": 98 } }
```

**実測 102トークン。だが中身は「変更関数0件・リスク0.00」のサマリだけで、コードを1行も含まない。**
ツール自身が `saved_percent: 98` と自己申告するが、これは「ファイルを読み直さなかった」ことの申告にすぎない。

レビューに必要な文脈は `impact` が返す。実リポ（`repos/code-review-graph`・192ファイル・975,419トークン）で
15ファイルをサンプルし、depth 2 既定で測った：

| 変更ファイル | 選ばれたファイル | 文脈トークン | **ペイロード** |
|---|---|---|---|
| parser.py | 40 | 400,142 | **630,636** |
| embeddings.py | 10 | 89,284 | 109,834 |
| communities.py | 12 | 104,163 | 58,750 |
| **平均** | **5.5 (リポの3%)** | **48,843** | **65,686** |

**平均 114,529トークン／1回。最悪 630,636トークン（どのコンテキストウィンドウにも入らない）。**

記事は「変更内容で9,272〜142,188トークン」を分子に、`detect-changes` のサマリを分母に置いている。
比べているものが違う。**2,000分の1は、測り方が作った数字。**

### better-code-review-graph でも解決しない

同じリポ・同じサンプルで bcrg の `query impact` を測った：

```
mean payload: 104,558 tokens   max: 141,537
返すファイル数: 137〜164（リポ192ファイルの71〜85%）
```

bcrg には `--max-payload-bytes` という上限がある。**既定値は 500,000バイト ≒ 125,000トークン**
（`tools.py:559 _DEFAULT_IMPACT_PAYLOAD_BYTES`）。
節約のための既定ではなく、プロセスを守るためのガードである。

---

## 3. MCP固定費 — 記事構成は 16,957トークン/リクエスト

各サーバを stdio で起動し `tools/list` を実測（`harness/mcp_overhead.py`）：

| サーバ | ツール数 | フルスキーマ | 遅延ロード時(名前のみ) |
|---|---|---|---|
| code-review-graph 2.3.8 | 30 | **8,895** | 348 |
| better-code-review-graph 3.24.0 | 7 | **2,005** | 70 |
| serena 1.7.0 | 23 | **6,057** | 178 |
| **記事構成 合計** | **60** | **16,957** | **596** |
| Graphify（skill方式） | — | frontmatter 97 ＋ **本体 10,304**（呼出時） | 同左 |

**bcrg の設計は優秀** — 7ツールに集約（`query` に `action=search/impact/...` を畳む）しており、
crg の30ツールに対し固定費が 4.4分の1。crg 側が学ぶべき設計。

### 決定的な分岐: 遅延ロード

Claude Code は 2026年1月から Tool Search（遅延ロード）が既定で有効。
本セッションでも実際にスキーマ未ロード状態で動作している。これにより固定費は
**16,957 → 596トークン（28分の1）** になる。

**ただし Codex は非対応**（[調査](https://ismaelramos.dev/blog/lazy-loading-mcp-tools/)）。
Codex でも使うなら、MCP ではなく **CLI+skill 方式**にすれば固定費はゼロになる
（crg は `--no-instructions --no-skills` を外せば skill を生成できる）。

**→ Codex を含めるなら CLI+skill 一択。** これは前回評価の結論と一致する。

---

## 4. 社外送信の監査 — 1つだけ統制が要る

全4ツールのソースを取得して egress を読んだ。

| ツール | 判定 | 根拠 |
|---|---|---|
| **code-review-graph** | ◎ | 既定 `local`。クラウドは `CRG_OPENAI_API_KEY`+`CRG_OPENAI_BASE_URL` など**専用名前空間**の変数が必要。使用前に stderr へ egress 警告。基本依存にクラウドSDKなし（`google-genai` は extras のみ） |
| **Serena** | ◎ | コード送信なし。`analytics` は localhost ダッシュボード用のローカル集計。ただし**言語サーバのバイナリを外部から自動DL**（storage.googleapis.com / releases.hashicorp.com / nuget.org） |
| **Graphify** | ○ | 既定は Claude Code サブエージェント（新たな送信先は増えない）。ただし `graphify extract` の `detect_backend()` は **汎用キー（GEMINI/KIMI/CLAUDE/OPENAI/DEEPSEEK）を検出すると自動でクラウドを選ぶ**（ollama より優先） |
| **better-code-review-graph** | ⚠️ | 埋め込みは既定ローカルONNXで安全。**だが `summarize` は明示opt-inなしに有効化される** |

### bcrg `summarize` の具体的な穴

`summarizer.py:88 resolve_summary_chain()`：

```python
# Key-gated default: keep only models whose provider key is set
for m in _DEFAULT_SUMMARY_CHAIN:                     # gemini → openai
    env_var = key_env_for_model(m)
    if config_value_for_current_request(env_var) or (
        env_var == "GEMINI_API_KEY"
        and config_value_for_current_request("GOOGLE_API_KEY")
    ):
        keyed.append(m)
```

そして送るものは加工された要約ではなく**ソース本文そのもの**（`summarizer.py`）：

```python
prompt = _PROMPT_PREFIX + node.source_text
```

**`GEMINI_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` が環境にあるだけで、
フラグも確認もなくソースが Gemini / OpenAI に流れる。**

crg の「専用名前空間の変数＋警告」という設計と対照的で、
これは前回 Ix を失格にしたのと同じ判断軸（統制不能な送信経路）に触れる。

**本マシンでは6種のキーすべて未設定を確認済み — 現時点で実害はない。**
だが社内展開では各開発者の環境に依存するため、導入するなら以下が必須：

```json
{ "env": { "SUMMARY_MODELS": "", "EMBEDDING_MODELS": "", "DISABLE_LOCAL_EMBED": "" } }
```

`SUMMARY_MODELS=""` を明示すれば `explicit` が空文字で分岐せず…**ではない**点に注意。
コードは `if explicit:` で空文字を偽と扱い、キーゲート既定にフォールバックする。
**空文字では止まらない。** 環境からキー自体を除去するか、`summarize` を運用で禁止すること。

---

## 5. 新規発見 — 本番が未固定で、しかも退行している

### 5.1 稼働中のバージョンは評価済みのものと違う

`.mcp.json` は `uvx code-review-graph serve`。**uvx は最新を取りに行く。**
評価・承認したのは 2.3.7、いま動いているのは **2.3.8**。

### 5.2 2.3.8 は文脈再現率が下がっている

ベンチ（`bench/repo`・12欠陥）を 2.3.8 で再実行し、2.3.7 の保存結果と突き合わせた：

| 欠陥 | クラス | graph 2.3.7→2.3.8 | graph+callers 2.3.7→2.3.8 |
|---|---|---|---|
| D06 | X (FIRES) | HIT → **MISS** | HIT → HIT |
| D11 | H (LATENT) | HIT → **MISS** | HIT → **MISS** |

全12欠陥では graph 67%→**50%**、graph+callers 83%→**75%**。

**実害のある9欠陥（FIRES）だけで再集計すると：**

| 戦略 | 2.3.7 | 2.3.8 |
|---|---|---|
| diff-only | 33% | 33% |
| graph 単体 | 56% | **44%** |
| **graph + callers_of** | **78%** | **78%** ← 維持 |
| full-repo | 100% | 100% |

**`callers_of` 併用という前回の結論が、2.3.8 でより重要になった。**
graph 単体は 44% まで落ちたが、併用すれば 78% を維持する。
（D11 は LATENT ＝ 実行時には壊れない欠陥なので、実害集計には影響しない）

そして**コストは改善している**：平均ペイロード 3,940 → **1,450**トークン（2.7分の1）。
2.3.8 は「絞り込みを強めた」バージョンで、単体では取りこぼすが併用前提なら純粋な改善。

### 5.3 対応

```jsonc
// .mcp.json — バージョンを固定する
"args": ["--from", "code-review-graph==2.3.8", "code-review-graph", "serve"]
```

更新時は `harness/run_bench.py` を回してから上げる。分散ゼロなので1回で判定できる。

---

## 6. 自前プリパスの無言のバグ（修正済み）

`harness/string_contracts.py` が **Python 3.8 では dictキー規則を丸ごと落としていた**。

```
$ python3 harness/string_contracts.py bench/repo      # 3.8.5
2 string-contract finding(s)          ← app/api.py の customerId が出ない
$ .venv/bin/python harness/string_contracts.py bench/repo   # 3.12
3 string-contract finding(s)
```

原因は Python 3.8 が `Subscript.slice` を `ast.Index` で包むこと。
`isinstance(n.slice, ast.Constant)` が常に偽になり、**エラーを出さずに検出0件**になる。
「指摘が少ない＝きれいなコード」に見えるので気付けない。

このマシンの `python3` は 3.8.5 で、README の再現手順は `.venv/bin/python`（3.12）を使う。
**手順どおりなら踏まないが、社内で素の `python3` を使えば踏む。**

`subscript_key()` を追加して修正済み。両インタプリタで 3/3 検出を確認：

```
python3 (3.8.5) → 3 findings   ✅
.venv   (3.12)  → 3 findings   ✅
```

これで `graph+callers 78%`（D08・D10 が残る）＋プリパスが両方を拾い、
**実害欠陥 9/9 = 100%** が 2.3.8 でも再現する。

---

## 7. 費用比較（Opus 5・12リクエスト/PR・200PR/月・キャッシュ有効）

文脈は初回に一度入り以後はキャッシュ読み、という実態に合わせて計算した
（`cost_model.py` の既定は文脈を毎ターン再送する保守側の仮定）。

| 構成 | 固定tok | 文脈tok | $/review | $/月 | 予算上限比 |
|---|---|---|---|---|---|
| A 記事の4ツール（MCP全開・非遅延=Codex） | 27,261 | 114,529 | 1.90 | **381** | 25% |
| A' 同左・Claude Code 遅延ロード | 10,900 | 114,529 | 1.71 | 342 | 23% |
| B 現状: crg のみ・既定設定 | 348 | 114,529 | 1.59 | 318 | 21% |
| **C 推奨: CLI+skill・d1/max25・callers併用** | **0** | **42,358** | **0.74** | **147** | **10%** |
| D ツールなし: 差分+grep | 0 | 5,500 | 0.30 | 61 | 4% |

**記事の構成（A）は現状（B）より月$63高い。** 固定費を足して文脈は1トークンも減らないため。

**効くつまみは MCP の数ではなく `impact` の絞り込み**だった。同じ実リポで：

| 設定 | 選ばれたファイル | 文脈+ペイロード |
|---|---|---|
| depth 2 / max 500（既定） | 5.5 | **114,529** |
| depth 1 / max 500 | 4.7 | 74,711 |
| **depth 1 / max 25** | **2.0** | **42,358** |
| depth 2 / max 25 | 2.3 | 44,810 |

**depth を下げるより `max-results` を絞るほうが効く（2.7分の1）。**

---

## 推奨構成

```
0. バージョン固定        code-review-graph==2.3.8 を .mcp.json に明記    —
1. 文字列契約プリパス    harness/string_contracts.py（修正済み）        0トークン
2. 構造文脈              crg impact --depth 1 --max-results 25
                         ＋ query callers_of を必ず併用                  ~42k
3. LLMレビュー           Claude Code / Codex（上記文脈のみ）
```

- **Codex も使うなら MCP をやめて CLI+skill**。固定費が 8,895→0 になり、遅延ロード非対応の影響が消える
- **`impact` 単体を信用しない**。`callers_of` 併用を CLAUDE.md / skill に明記（2.3.8 で単体44%）
- **埋め込みは既定（ローカル）のまま**。`--embedding-provider` のクラウド指定を組織ポリシーで禁止

### 記事から取り込む価値があるもの

| 取り込む | 理由 |
|---|---|
| **Serena（限定導入）** | LSPなので `from pkg import module` の import解決バグが原理的に起きない。ただし**シンボル名が既知の質問専用**。固定費6,057トークンを払う価値があるかは自社リポで `harness/import_style.py` を回して判断（本評価のベンチは実コードの10倍この形に偏っていた） |
| **bcrg のツール集約設計** | 7ツール2,005トークン。crg（30ツール8,895）へのフィードバック候補。ツールとして採用する意味ではない |

### 採らないもの

| 採らない | 理由 |
|---|---|
| **better-code-review-graph** | `summarize` が環境変数だけでソース本文を外部送信。crg と機能が重複し、`impact` のペイロード問題も解決しない |
| **Graphify** | 既定パイプラインが Claude Code サブエージェントでグラフを構築する＝**構築コストがトークン建て**。記事はこれを一切計上していない。skill本体だけで10,304トークン |
| **4ツール併用そのもの** | 固定費が増えるだけで文脈は減らない（$318→$381/月） |

---

## 再現手順

```bash
SP=/tmp/crg_verify && mkdir -p $SP

# MCP固定費
python3 harness/mcp_overhead.py uvx code-review-graph serve
MCP_TRANSPORT=stdio python3 harness/mcp_overhead.py \
    uvx --python 3.13 --from better-code-review-graph==3.24.0 better-code-review-graph
python3 harness/mcp_overhead.py \
    uvx --from serena-agent==1.7.0 serena start-mcp-server --context ide-assistant

# 2.3.8 でのベンチ再実行
uv venv $SP/v238 --python 3.12
uv pip install --python $SP/v238/bin/python code-review-graph==2.3.8
$SP/v238/bin/code-review-graph build --repo bench/repo
$SP/v238/bin/python harness/run_bench.py --repo bench/repo \
    --defects bench/defects.json --cli $SP/v238/bin/code-review-graph \
    --depth 2 --out $SP/crg238_depth2.json

# 実リポでのペイロード（つまみ比較）
$SP/v238/bin/code-review-graph build --repo repos/code-review-graph
$SP/v238/bin/python harness/payload_cost.py repos/code-review-graph --depth 1 --max-results 25

# プリパス（両インタプリタで3件出ることを確認）
python3 harness/string_contracts.py bench/repo
.venv/bin/python harness/string_contracts.py bench/repo
```

## 限界

- 実リポのペイロード計測は `repos/code-review-graph`（Python 192ファイル）1本のみ。
  記事のベンチは TypeScript であり、**言語による差は未測定**
- bcrg / Graphify / Serena は**欠陥検出品質を測っていない**（egress監査と固定費のみ）。
  bcrg を不採用にしたのは送信リスクと重複であって、品質で劣ると示したわけではない
- 費用表の「文脈は初回一度」という仮定は、レビュー中に `impact` を複数回呼べば崩れる。
  呼ぶ回数だけ 42k〜114k が加算される
- Codex の遅延ロード非対応は二次情報。**Codex を本番採用する前に自環境で実測すること**

---

## 追記（同日）— 設定を適用して分かったこと

`.mcp.json` の 2.3.8 固定と「max-results 25」を適用する作業で、
**CLI と MCP でパラメータが違う**ことが判明した。§7の CLI 実測（`--max-results 25 --depth 1`）は
そのままでは MCP 経路に適用できない。

### 適用した設定

| 対象 | 変更 |
|---|---|
| `~/.mcp.json` | `uvx code-review-graph serve` → `uvx --from code-review-graph==2.3.8 code-review-graph serve` |
| PATH バイナリ（PostToolUse hook が使用） | `uv tool install code-review-graph==2.3.8 --force`（2.3.7 → 2.3.8） |
| `~/CLAUDE.md` | 呼び出しパラメータの規約を追記 |

**書き手と読み手のバージョンがずれていた。** hook は PATH の **2.3.7** でグラフを更新し、
MCP は uvx の **2.3.8** で読んでいた。固定するなら両方揃える必要がある。

### 環境変数は効かない（実測）

```
baseline                                        92,000 tok
CRG_MAX_IMPACT_NODES=25 CRG_MAX_IMPACT_DEPTH=1  92,000 tok   ← バイト単位で同一
--max-results 25 --depth 1                      37,004 tok
```

`tools/query.py:112 get_impact_radius()` が自前の既定（500 / 2）を
`store.get_impact_radius(max_nodes=...)` に必ず渡すため、`constants.py` の
env 由来の既定は上書きされる。**`.mcp.json` の `env` で絞ることはできない。**

### MCP経路の実測（同一の変更ファイル1件）

| ツール | 設定 | トークン |
|---|---|---|
| `get_impact_radius_tool` | 既定 | **167,395** |
| 〃 | `max_depth=1` | 165,507（**1%しか減らない**） |
| 〃 | `detail_level="minimal"` | **472** |
| `get_review_context_tool` | 既定 | 78,300 |
| 〃 | **`max_results=25, max_depth=1`** | **25,420** |
| 〃 | ＋`max_lines_per_file=80` | 22,655 |

**訂正が2点ある。**

1. **`get_impact_radius_tool` に `max_results` は存在しない。**
   渡すと `1 validation error ... unexpected_keyword_argument` で**ハードエラー**になる
   （黙って無視されるのではない）。`max_results` を持つのは `get_review_context_tool` と
   `detect_changes_tool` の方。CLI の `impact --max-results` とは別物。

2. **`detail_level="minimal"` は 355分の1になるがレビューには使えない。**
   返るのは件数・リスクラベル・`key_entities` だけで、**影響ファイル名を列挙しない**：

   ```json
   { "summary": "... 126 nodes impacted (within 2 hops)\n  - 5 additional files affected",
     "risk": "high", "impacted_file_count": 5,
     "key_entities": ["test_non_string_legacy_metadata_is_ignored", ...] }
   ```

   `detect_changes` と同じ「トリアージ信号」であり、文脈供給源ではない。

### したがって MCP 経路での推奨は

```
トリアージ    get_impact_radius_tool  detail_level="minimal"        472 tok
レビュー文脈  get_review_context_tool max_results=25, max_depth=1  25,420 tok
取りこぼし補完 query_graph_tool       pattern="callers_of"          （必須）
```

§7 の CLI 表（`--max-results 25 --depth 1` → 42,358）は CLI+skill 運用では有効なまま。
MCP 運用ではこの追記の数値を使うこと。

### 未検証

`get_review_context_tool` の `max_results=25` が**欠陥再現率を落とさないことは測っていない**。
本評価のベンチ（`harness/run_bench.py`）は `impact` のファイル選択を測る作りで、
`get_review_context` 経路を通っていない。トークンが3.1分の1になることは実測済みだが、
**品質への影響は未測定**。`callers_of` 併用（78%）はこの設定と独立に効く。

---

## 追記2（同日）— 残っていた未検証項目を全て潰した

前節までで「未検証」と書いた項目を実測した。**2つの記述が誤りだったので訂正する。**

### V1. `max_results=25` は再現率を落とさない（検証済み・当初は未測定）

`get_review_context_tool` を12欠陥ベンチに通し、既定と絞り込みで文脈再現率を比較した
（判定基準は `run_bench.py` と同一 — 欠陥を見るのに必要なファイルが文脈に入るか）。

| リポジトリ | 設定 | 全12件 | 実害9件 | 平均トークン |
|---|---|---|---|---|
| bench/repo（15ファイル） | 既定 | 50% | 44% | 3,043 |
| 〃 | max_results=25, max_depth=1 | **50%** | **44%** | 2,806 |
| scaled60（315ファイル） | 既定 | 50% | 44% | 3,938 |
| 〃 | max_results=25, max_depth=1 | **50%** | **44%** | 3,602 |

**12欠陥すべてで判定が一致。上限を掛けても再現率は1件も落ちない。**
（`get_review_context` の再現率が `impact` 単体と同値の44%なのは、内部の選択ロジックが同じため）

### V2. 削減率は 2.5倍。3.1倍は n=1 の外れ値だった（訂正）

前節で「78,300→25,420＝3.1倍」と書いたが、**これは1ファイルだけの測定**だった。
8ファイルのサンプルで測り直した：

| コードベース | 既定 | 絞り込み | 比 |
|---|---|---|---|
| repos/code-review-graph（Python・192ファイル） | 39,782 | 15,932 | **2.5x** |
| ix-cli/src（TypeScript・131ファイル） | 46,549 | 21,027 | **2.2x** |

**効果はファイル数ではなくファイルサイズに連動する**：小さいファイルでは 1.0x（上限が効かない）、
大きいファイルでは 2.1〜3.3x。**落とすものが無いので、常に付けてよい。**

### V3. 言語差はなかった（当初は未測定）

TypeScript（131ファイル・290,589トークン）でも Python と同じ 2.2x。
記事のベンチが TypeScript であることは結論に影響しない。

なお TS リポは全体で 290,589 トークンしかないのに、
**`get_review_context` 既定の1回が 46,549 トークン＝リポジトリ全体の16%** を消費する。

### V4. import解決バグは 2.3.8 でも健在（`bench/probe_importstyle`）

| 呼び出し形式 | `impact` 2.3.8 | `callers_of` 2.3.8 |
|---|---|---|
| `from pkg.target import do_work` | ✅ | ✅ |
| `from pkg import target` → `target.do_work()` | ❌ **消える** | ✅ |
| `import pkg.target` → `pkg.target.do_work()` | ✅ | ✅ |

前回 2.3.7 で報告した挙動と完全に同一。**回避策（`callers_of` 併用）は 2.3.8 でも有効。**

### V5. Serena は確かにこのバグを起こさない — が `callers_of` で足りる

Serena の `find_referencing_symbols` を同じ probe に当てた：

```
pkg/style_a_from_module.py  →  a()   "return do_work(1)"
pkg/style_b_from_package.py →  b()   "return target.do_work(2)"   ← impact が落とすもの
pkg/style_c_plain_import.py →  c()   "return pkg.target.do_work(3)"
```

**3形式すべて解決。README の仮説（LSPなら原理的に起きない）は正しかった。**

ただし同じ質問のコストを比べると：

| 手段 | 1クエリ | 固定費 | 追加情報 |
|---|---|---|---|
| crg `callers_of` | 904 tok | 0（導入済み） | ファイルパス＋修飾名 |
| Serena `find_referencing_symbols` | **249 tok** | 6,057（遅延ロード時 178） | ＋行番号・前後のコード |

Serena は1クエリあたり 655 トークン安く、情報も richer。
だが**固定費6,057を回収するには1セッションで約9クエリ必要**（遅延ロードなら1クエリで回収）。

**そして肝心の穴は `callers_of` が既に無料で塞いでいる。**
Serena の限界効用は「バグの修正」ではなく「クエリ単価と行番号」であり、
`impact` バグを理由に Serena を入れる必要はない。

### V6. 自前プリパスに2つ目の無言バグ（修正済み）

修正後も 3.8 と 3.12 で結果が1件ずれた。原因は `ast.Index` ではなく別物だった：

```
python 3.8:  7 / 156 files fail to parse   ← 無言でスキップされていた
python 3.12: 0 / 156 files fail to parse
```

`except SyntaxError: continue` が、新しい構文を含むファイルを**警告なしに走査対象から外す**。
指摘が減るだけなので「きれいなコード」に見える。`ast.Index` と同じ失敗様式。

未走査ファイルを警告する処理を追加した：

```
13 string-contract finding(s), 0 tokens spent.

WARNING: 7 file(s) could not be parsed by python 3.8 and were NOT scanned
         - coverage is incomplete. Re-run on a newer interpreter.
  unscanned: tests/test_registry.py
  ...
```

`bench/repo` は 3/3 のまま（回帰なし）。

### V7. プリパスの精度は実リポで低い（README の記述を確認）

実リポ（156ファイル）に当てると 14件出るが、**確認した範囲では全て偽陽性**：

```
'Other' vs 'other' / 'Content-type' vs 'Content-Type' / 'host' vs 'Host'
'mcp_servers' vs 'mcpServers'
```

HTTPヘッダの大小文字など、正当な差を拾っている。
**ベンチでは 3/3 正解だが、実リポでは精度が出ない。**
README の「実リポで偽陽性のみ」は正しい。
月$15,318 の試算がこの行に依存する以上、**自社リポで当ててから信じること。**

### V8. Codex の遅延ロードは検証できなかった（未解決）

`codex debug prompt-input` はメッセージ列だけを描画し、**`tools` 配列を含まない**
（MCP有無で出力がバイト単位で同一：56,249文字）。
バイナリには `code-mode`（ツールをコードAPI化する仕組み）の文字列があるが、
MCPに適用されるかは判別できなかった。

**確定させるには実APIコールが必要なので行っていない。**
ただし推奨構成（CLI+skill）ではMCP固定費が0になるため、**この問いは意思決定に影響しない。**
MCP方式をCodexで採る場合のみ、自社で実測すること。

---

## 追記3（同日）— 独立レビュー2件の結果と、それによる訂正

自分で測った数値を自分で検証しても意味が薄いので、独立エージェント2体に
(a) コードレビュー (b) 数値の再測定 を、こちらの数値を明示した上で「反証してみろ」という形で投げた。

### 数値検証：5項目すべて CONFIRMED（最大誤差 0.008%）

MCP固定費（30/8,895・7/2,005・23/6,057）、`max_results` の拒否、`get_review_context` の
2.5倍、環境変数の無効性、import解決バグ — すべて独立に再現。多くはトークン単位で一致。

根本原因の特定が2つ追加された：

- **環境変数が効かない理由**：`constants.py:43-44` は env を読んでいるが、`cli.py:1153-1154` が
  argparse の default に同じ値をハードコードしており、argparse は常に値を渡すため
  `graph.py` の env 由来 default が無条件に上書きされる。**構造的に死んでいる。**
- **style_b が消える理由**：CALLS エッジのターゲットが bare 名 `do_work` のまま保存されている。
  `impact` は修飾名からBFSするので辿れず、`callers_of` は名前照合なので当たる
  （結果に `"target_resolution": "unresolved"` が付く）。depth 2/3/5/10 いずれでも欠落するので
  深さ打ち切りではない。

### 訂正：トークン数はモデルが見る量の約2倍を報告していた

指摘：私の計測は **JSON-RPC の result 全体**を数えており、モデルが実際に受け取る
`content[].text` は埋め込みソースがJSONエスケープされる分、およそ半分。

自分で測り直した（`repos/code-review-graph`・8ファイル・同一サンプル）：

| | envelope（前回報告） | **text（モデルが見る量）** |
|---|---|---|
| `get_review_context` 既定 | 39,786 | **19,037** |
| 〃 `max_results=25, max_depth=1` | 15,972 | **7,645** |
| 比 | 2.5x | **2.5x**（不変） |

**envelope / text = 2.09倍。比率と結論は変わらないが、絶対値はすべて約半分。**

主要ツールの実測値を訂正して再掲（`embeddings.py` 1ファイル変更時）：

| 呼び出し | envelope | **text** |
|---|---|---|
| `get_impact_radius` 既定 | 167,396 | **80,353** |
| 〃 `detail_level="minimal"` | 472 | **213** |
| `detect_changes` 既定 | 598 | **268** |
| `get_review_context` 既定 | 78,301 | **37,482** |
| 〃 絞り込み | 25,420 | **12,187** |

§7 の月額試算は envelope ベースの値で計算しているため、**MCP経路については最大2倍の保守側
（過大）に振れている**。構成間の順位は変わらない。

### 追加で判明：MCP の impact には有効な上限が存在しない

C2（`max_results` は拒否）＋ C4（env は MCP経路でも無効・`max_depth=1` は1%）を合わせると、
**MCP の `get_impact_radius_tool` は出力量を制御する手段が一つも無い。**
`--max-results` は CLI にしか存在しない。
→ `detail_level="minimal"` でトリアージに限定するか、CLI経路を使うかの二択。

### コードレビュー：`string_contracts.py` に3件（すべて修正済み）

**① 落ちたファイルは「見逃し」だけでなく「偽陽性」を生む（重要）**

ルール2は「このキーを書くファイルが無い」という**不在**を根拠に発火する。
パース不能なファイルは producer を1つも登録しないので、**そのファイルが唯一の生産者だった場合、
存在しない不整合を報告する。** 最小再現を作って確認した：

```
3.8  → 1 finding（偽陽性）
3.12 → 0 findings
```

私の警告文は「coverage is incomplete」＝見逃しがあるかも、としか言っておらず、**逆方向を伝えていなかった。**

修正：`unparsed` が空でない場合、**ルール2を実行せずスキップし**、その旨を明示するようにした。
決定論を売りにする以上、インタプリタ依存の偽陽性を出すくらいなら出さない方がよい。

```
0 string-contract finding(s), 0 tokens spent.

WARNING: 1 file(s) could not be parsed by python 3.8. Their dict keys and string
literals were not indexed, so results below are BOTH incomplete (missed findings)
and unreliable (a missing producer can invent a finding).
  SKIPPED dict-key mismatch (rule 2): needs every producer parsed, 1 file(s) were not
```

**② `ValueError` がハンドラを素通りして実行全体を落とす（重要）**

3.8 では NUL バイトを含むソースが `SyntaxError` ではなく
`ValueError: source code string cannot contain null bytes` を投げる。実測：

```
py3.8 : ValueError  -> ESCAPES current handler
py3.12: SyntaxError -> caught
```

無言スキップより悪く、**1件も出力しないまま traceback で終わる**。
`string_literals()` 側（ルール3）にも同じ穴があり、そちらも塞いだ。
併せて壊れたシンボリックリンク由来の `OSError` も捕捉。

なお私が疑っていた `UnicodeDecodeError` は **`read_text(errors="ignore")` により到達不能**
（既存のハンドラは死んだコード）。疑う先を間違えていた。

**③ 出力文言の自己矛盾**

`the only producer (app/orders.py, app/serializers.py)` — 生産者が2つあるのに「唯一の」。
このまま README と本書が引用していた。複数形を出し分けるよう修正：

```
app/api.py: reads key 'customerId' but all 2 producers
            (app/orders.py, app/serializers.py) write 'customer_id'
```

### 回帰確認

| 対象 | 3.8.5 | 3.12 |
|---|---|---|
| `bench/repo` | **3件** | **3件** |
| `repos/code-review-graph` | ルール2スキップ＋警告 | 14件（変化なし） |
| NULバイトを含むリポ | クラッシュせず0件＋警告 | — |

---

## 追記4（同日）— 月額試算の再計算と、優先順位の訂正

追記3でトークン計測を text ベースに訂正した結果、**§7 の月額試算が古い前提のまま残っていた**ので
再計算した。同時に、**どの操作が効いているかの順位が変わった**。

すべて `content[].text` の実測値（`get_review_context` は8ファイル平均、`impact` は1ファイル）：
`RC既定 19,037 / RC絞込 7,645 / impact既定 80,353 / detect_changes 268 / callers_of 900`

| 構成 | 固定 | 文脈 | $/review | **$/月** | 予算上限比 |
|---|---|---|---|---|---|
| A 記事の4ツール（非遅延=Codex） | 27,261 | 99,390 | 1.73 | 345 | 23% |
| A' 同左・Claude Code 遅延ロード | 10,900 | 99,390 | 1.53 | 307 | 20% |
| B 現状: パラメータ指定なし | 348 | 99,390 | 1.41 | **282** | 19% |
| B' 現状・**`impact` を呼ばないだけ** | 348 | 19,037 | 0.47 | **93** | 6% |
| **C 推奨: 絞り込み+callers+プリパス** | 348 | 8,813 | 0.35 | **69** | **5%** |
| C' 推奨・CLI+skill（Codex向け） | 0 | 8,813 | 0.34 | 68 | 5% |
| D ツールなし: 差分+grep | 0 | 5,500 | 0.30 | 61 | 4% |

（旧 §7 の 381/318/147 は envelope ベース。順位は同じだが絶対値が約2倍過大だった）

### 優先順位の訂正 — 主役は `max_results` ではなかった

削減の内訳を分解すると：

| 施策 | 文脈の削減 | 全削減に占める割合 |
|---|---|---|
| **`impact` を既定で呼ばない** | 99,390 → 19,037（−80,353） | **89%** |
| `max_results=25, max_depth=1` | 19,037 → 7,645（−11,392） | 13% |
| `callers_of` + `detect_changes` を足す | 7,645 → 8,813（+1,168） | −1%（品質のための追加） |

**これまで「`max_results` の絞り込みが最大の効き目」と書いてきたが、誤り。**
実際は **`get_impact_radius_tool` を既定設定で呼ばないことが削減の89%** を占める。
`max_results` は2番目で、しかも `impact` を避けていれば効果は13%にとどまる。

理由は単純で、`impact` 1回（80,353）が `get_review_context` 既定（19,037）の4.2倍あるため。
そして追記3のとおり **`impact` には MCP 経路で有効な上限が一つも存在しない**ので、
「絞って使う」ができない。避けるしかない。

CLAUDE.md の記述順もこれに合わせてある（`impact` を既定で呼ばない → `max_results` を渡す）。

### 私が加えた環境変更の安全性（検証済み）

PATH バイナリを 2.3.7 → 2.3.8 に上げたが、PostToolUse hook は編集のたびに
`update` を走らせるため、2.3.7 が作った既存DBを壊さないかを確認した。

- **スキーマ完全一致** — テーブル15個・`nodes`/`edges` の全カラム・`user_version` すべて同一
  （2.3.7製 `everything-claude-code` の実DBと2.3.8製DBを読み取り専用で比較）
- **前方互換を実地確認** — 2.3.7 でビルドしたDBを 2.3.8 で `update --skip-flows`：
  `1 files updated, 5 nodes, 8 edges` / `integrity_check: ok` / 新関数ノードも取り込まれた
- **リポジトリルートが違う場合は破壊せず拒否する**（「Rebuild it, or retry with the root it was
  built with, instead of reconciling every file away」）＝安全側の設計

既存3プロジェクト（`agent-harness` / `claude-code-codegraph-harness` /
`everything-claude-code`）のDBは**一切変更していない**。検証はすべてコピーまたは新規リポで行った。
