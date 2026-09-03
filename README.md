# Claude Code コスト/品質ツール評価

予算上限があり、社外へのコード持ち出しが禁止された環境で、
`tirth8205/code-review-graph` と `ix-infrastructure/Ix`、および代替候補を実測比較した。

> ### 🚀 まず何をすればいいか知りたい人へ
> **[`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md) を読んでください。**
> 前提知識ゼロ・15分・コピペで終わります。本 README は評価の根拠であって手順書ではない。
>
> 効果を自分のリポで測る: `python harness/measure_savings.py /path/to/your/repo`

検証日 2026-08-11 / code-review-graph v2.3.7 / Ix `1292375` (2026-08-10)

> **2026-09-04 追記 — Zenn記事の4ツール構成を検証。[`docs/article_review_2026-09-04.md`](docs/article_review_2026-09-04.md)。**
> 結論は不採用（月$282→$345 に上がるだけで文脈は減らない）。本評価に影響する発見:
> ①`uvx` が最新を取るため**本番は未評価の 2.3.8**（graph単体 56%→44%に退行。`callers_of` 併用なら78%維持）
> ②`harness/string_contracts.py` に無言の欠落バグ2件（Python3.8 で1規則が消える／落ちたファイルが**偽陽性を生む**）— **修正済み**
> ③最大の削減は `get_impact_radius` を既定で呼ばないこと（1回 80,353 トークン・**上限を掛ける手段が存在しない**）。
>   `--max-results` は2番目
> ④独立エージェント2体でレビュー済み（数値5項目CONFIRMED／コード指摘3件修正）
>
> ⚠️ 旧版の数値（月$318→$381・114,529→42,358 等）は JSON-RPC 外殻を含み**約2倍過大**だった。
> 現行の数値はすべて `content[].text`（モデルが実際に見る量）ベース。
>
> **2026-08-22 再検証済み — 先に [`docs/verification_2026-08-22.md`](docs/verification_2026-08-22.md) を読むこと。**
> 全数値は完全に再現したが、結論を変える穴が3つ見つかった:
> ①`impact` のツール出力自体（実リポ depth 2 で1回23万トークン）がコスト計算から抜けている
> ②import 偏りを補正すると `callers_of` 併用の上乗せが消える（graph 単体で 56%→78%）
> ③`string_contracts.py` は実リポで偽陽性のみ（月$15,318 の試算はこの行に依存）

---

## 結論

**code-review-graph を採用。ただし単体では使わない。**

社外秘要件を満たすのは code-review-graph だけで、Ix は失格。
ただし code-review-graph の `impact`（レビュー範囲を決めるコマンド）には
**再現可能な取りこぼしバグがある** — 社内テストで観測された「指摘漏れ」の実体はこれ。
回避策は判明しており、下記の3段構成で**文脈再現率 67% → 100%** になる。

| # | 構成 | 追加コスト | 文脈再現率 |
|---|------|-----------|-----------|
| 1 | `impact` のみ（現状） | — | 67%（実害欠陥のみでは **56%**） |
| 2 | ＋ `query callers_of` を併用 | +13% トークン | 83%（同 **78%**） |
| 3 | ＋ 文字列契約プリパス（LLM不使用） | 0 トークン | **100%**（同 **100%**） |

※「実害欠陥のみ」＝仕込んだ12件のうち実行時に再現する9件だけで再集計した値。
graph 単体は**実害のある文字列結合欠陥を1件も検出できない（0/3）**。

**費用対効果**：レビュー時のトークン代は約2倍になるが、見逃しの手戻りを計上すると
推奨構成は**月 $15,318 の節約**（手戻り4h・欠陥0.5件/PR・200PR/月）。
損益分岐は「見逃し1件の対処が11分以上」— まず下回らない。

---

## Ix を外した理由（技術評価以前の問題）

Ix はコードを取り込む本体 **memory-layer が非公開リポジトリのクローズドソース**。
公開されている Apache-2.0 は CLI と tree-sitter 部分だけ。

```
CONTRIBUTING.md:110
  The Scala backend (memory-layer) lives in a separate private repo.

docker image inspect ghcr.io/ix-infrastructure/ix-memory-layer:latest
  Cmd: ["java","-jar","app.jar"]      ← 410MB の JVM バイナリ
```

localhost:8090 にバインドされるので設計上は外部送信しない。
だが**全社のソースを投入する部品を監査できない**。
社外秘規程がある環境では、検証不能なバイナリは許可要件を満たさない。

補足: 683 stars / early alpha / CLI 起動ごとに `api.github.com` へ更新確認。
コード本体は送らないが、オフライン環境では毎回失敗する。

**技術的には Ix の方が優れている点もある。** 実際に起動して同じベンチを当てたところ、
下記の `impact` バグ（D05）を Ix は正しく処理した（`Callers: create_order` を正答）。
シンボル単位の影響解析は Ix に分がある。それでも監査不能なバイナリという一点で外している。
詳細は `docs/limitations.md`。

一方 code-review-graph の外部通信は `embeddings.py` の3箇所のみ、
すべて **opt-in のクラウド埋め込みプロバイダ**。`build` の既定は埋め込み無効・完全ローカル。
CLI ヘルプ自身が `Cloud providers may transmit source-derived text` と警告する。
DNS リバインディング対策 (`http_origin_guard.py`) まで入っており、設計は堅い。

---

## 見つけたバグ — 「指摘漏れ」の正体

**根本原因は Python の import 解決 1 箇所**。グラフ探索やスコアリングの問題ではない。

最小再現 (`bench/probe_importstyle/`)：同じ関数を3通りの import で呼ぶ。

| 呼び出し側の書き方 | `callers_of` | `impact` |
|---|---|---|
| `from pkg.target import do_work` | ✅ | ✅ |
| `from pkg import target` → `target.do_work()` | ✅ | ❌ **消える** |
| `import pkg.target` → `pkg.target.do_work()` | ✅ | ✅ |

**この形式の呼び出し元は、depth をいくら上げてもレビュー範囲に入らない。**

### どれくらい踏むのか（実測・4コードベース）

当初「最も一般的な書き方のひとつ」と書いたが、**実測したら誤りだった**。
実在プロジェクトの import 文を数えた結果：

`harness/import_style.py` で実在プロジェクトの import 文を数えた：

| コードベース | .py | import文 | うち B（消える形） |
|---|---|---|---|
| code-review-graph 本体 | 156 | 1,612 | 59 (**3.7%**) |
| Megatron-LM-ABEJA | 347 | 2,973 | 40 (**1.3%**) |
| megekit_MoE | 46 | 498 | 0 (0.0%) |
| **本評価のベンチマーク** | 14 | 16 | 7 (**43.8%**) |

**バグは実在し再現もするが、実コードで踏む頻度は import 文の 0〜3.7%。**
「頻発する重大バグ」ではなく「低頻度だが確実に取りこぼす穴」が正しい評価。

**そして本ベンチマークは 43.8% と、実コードの10倍以上この形に偏っていた。**
つまり本評価の X クラス再現率（graph 67%）は**実リポジトリより悲観側**。
実際にはもっと当たる可能性が高いが、**それは未測定**。

自社リポでの頻度：`python harness/import_style.py <path>`
（該当箇所のファイル名・行番号も出る）

### 因果の連鎖（DB を直接見て確認）

```
1. from pkg import target
   → IMPORTS_FROM が pkg/__init__.py を指す（正しくは pkg/target.py）
        python_resolver.py:33-47  モジュール表を「from の対象」だけで引くため、
        import された名前 target 自体が submodule である場合を見ていない

2. bare CALLS 解決器（graph.py:734）は
   「呼び出し元ファイルが import している唯一のファイル」を証拠に使う
   → 証拠が pkg/__init__.py なので do_work が見つからず、解決できない

3. CALLS エッジのターゲットが bare 名のまま残る
        style_a: CALLS -> pkg/target.py::do_work   ✅ 解決済み
        style_b: CALLS -> do_work                  ❌ bare のまま
        style_c: CALLS -> pkg/target.py::do_work   ✅ 解決済み

4. impact は qualified_name の一致で JOIN するため bare 名に到達できない
   一方 callers_of は「名前」で引くので bare でも当たる  ← 回避策が効く理由
```

### 1本のエッジを直すと全部直ることを実証した

probe の DB で IMPORTS_FROM を `pkg/target.py` に向け直し、`postprocess` を再実行：

```
INFO: Resolved 1 evidence-backed bare CALLS targets
CALLS  style_b_from_package.py::b -> pkg/target.py::do_work    ← 解決した
impact --files pkg/target.py → ['style_a', 'style_b', 'style_c']  ← 全部入った
```

**探索器もスコアリングも正しい。壊れているのは import 解決の1点だけ。**
（`bench/probe_importstyle/` はバグ再現状態に戻してある）

ベンチマークでの実害（D05）：`pricing.compute_total` の引数を変えたのに、
唯一の呼び出し元 `orders.py` が文脈に入らない。depth 1〜6 すべてで欠落。

→ **`impact` の結果を `query callers_of` で補完すれば埋まる。**

---

## コスト実測 — 「なし vs あり」で**どちらも高くなる**

公称「中央値 65倍削減」。**実測は 2.3倍**（`results/crg_depth2.json`）。

| 戦略 | 平均トークン/レビュー | 全読み比 |
|---|---|---|
| full-repo（全ファイル読み込み） | 1,100 | 1.0x |
| **graph** | 489 | 2.3x |
| graph + callers | 551 | 2.0x |
| diff-only（差分だけ） | 94 | 11.8x |

> 訂正（2026-08-22）: 旧版はここに 1,556 / 681 / 769 / 132 を載せていた。
> 破棄した注釈付きベンチ（`bench/repo_annotated_backup`）の値で、比率は同じだが絶対値が違う。
>
> **さらに重要: この表は `impact` が返す JSON 自体を数えていない。**
> ベンチで平均 3,198トークン（選んだファイルの6.6倍）、実リポ192ファイルの depth 2 では
> 1回278,349トークン。payload を数えると**ベンチ上でも全読みより3倍高い**。
> `harness/payload_cost.py` と `docs/verification_2026-08-22.md` §2A を参照。

差の理由は**比較対象**。65倍は「リポジトリ全体を読む」との比較で、
まともなエージェントはそんな読み方をしない。

### MCP のツール定義は毎リクエストの固定費

`harness/mcp_overhead.py` で実測：**code-review-graph は 30ツール = 7,615トークン**。
グラフが節約する文脈（681トークン）の 11倍。
一方 **Ix は MCP を持たず Skill + CLI 方式**で、常時ロードは frontmatter のみ（約60トークン）。
ただし code-review-graph も CLI + skill で運用でき、その場合この固定費はゼロになる。

### 月額での実額（Opus 5 / $5・$25 per MTok / 1PR=12リクエスト / 200PR/月）

`harness/cost_model.py`。プロンプトキャッシュ込みの実効値：

| 構成 | $/レビュー | $/月 | 予算上限比 |
|---|---|---|---|
| なし・リポジトリ全読み | 43.40 | 8,680 | **579%** |
| **code-review-graph (MCP)** | 1.17 | 235 | 16% |
| **code-review-graph (CLI+skill)** | 1.08 | 217 | 14% |
| Ix (CLI+skill) | 1.08 | 217 | 15% |
| **なし・差分+grep** | **0.58** | **116** | **8%** |

**レビュー時のトークン代だけ見れば、ツールを入れると約2倍になる。**
「65倍削減」が成立するのは全読み（$8,680/月）と比べた場合だけで、
それは誰もやらない上に、そもそも上限を5.8倍超過している。

### ただしこの表は不完全だった — 見逃しの手戻りを数えていない

上はレビュー時のトークン代のみ。**見逃した欠陥はタダにならず、手戻りになる。**
`harness/cost_rework.py` で3項目すべてを計上した：

```
PRあたり総費用 = トークン代 + トリアージ時間 + 見逃し欠陥の手戻り
```

トリアージ時間も実測した。文脈が増えると指摘件数も増える（＝読む時間が増える）：

| 戦略 | 指摘件数/レビュー（実測・中央値） |
|---|---|
| 差分のみ | 12 |
| graph | 15 |
| graph+callers | 16 |
| 全読み | **23** |

**総費用（手戻り4h・欠陥0.5件/PR・$60/h・200PR/月）:**

| 戦略 | 検出率 | トークン | トリアージ | 手戻り | 合計/PR | 合計/月 |
|---|---|---|---|---|---|---|
| なし・差分のみ | 33% | 0.58 | 12.40 | 80.40 | 93.38 | 18,676 |
| graph のみ | 56% | 1.08 | 16.00 | 52.80 | 69.88 | 13,976 |
| graph+callers | 78% | 1.09 | 15.70 | 26.40 | 43.19 | 8,638 |
| **＋文字列プリパス** | **100%** | 1.09 | 15.70 | **0** | **16.79** | **3,358** |
| なし・全読み | 89% | 43.40 | 23.60 | 13.20 | 80.20 | 16,040 |

**推奨構成は月 $15,318 の節約**になる。トークン代で $100 多く払って、手戻りで $15,400 返ってくる。

### 損益分岐（自社の数字で判断するために）

「見逃し1件がいくら以上なら、そのツールが元を取るか」：

| 戦略 | 必要な手戻り単価 | エンジニア時間換算 |
|---|---|---|
| graph のみ | $35.65 | **36分** |
| graph+callers | $16.93 | **17分** |
| ＋文字列プリパス | $11.37 | **11分** |
| なし・全読み | $192.93 | 3.2時間 |

**見逃したバグ1件の対処に11分以上かかるなら、推奨構成は元を取る。**
現実的にこれを下回ることはまずない。

### 本当に効いているのはトークンではなくエンジニアの時間

上表で一番大きい項目はトークン代（$1.09）ではなく**トリアージ（$15.70）— 14倍**。

- だから**全読みは検出率89%でも負ける**。指摘が23件に膨らみ、読む時間がトークン代より重い
- だから**文字列プリパスが最強**。トークン0・指摘3件（しかも全部真）で検出率を100%に押し上げる
- 最適化すべきは「文脈を増やすこと」ではなく**「少なく正確な指摘」**

※ 前提の感度：手戻りが30分未満かつ欠陥が0.1件/PR未満という条件では、
トリアージ費用が上回りツールなしが勝つ。`--rework-hours` 等で自社の数字を入れて確認のこと。

**予算上限に対しては、最も高い構成でもトークン代は16%。**
コストは制約になっていない。**判断軸は品質であり、その品質が費用対効果でも勝つ。**

MCP のツール定義税だけを取り出すと、キャッシュ有効時 $17.9/月・無効時 $91.4/月。
`tools` はプレフィックス先頭なのでキャッシュが効く。
ただし**セッション途中で MCP を接続/切断するとプレフィックスが無効化される**ので、
接続するなら固定にすること。

---

## 品質実測 — 欠陥クラス別の文脈再現率

`bench/repo`（15ファイル）に12個の欠陥を仕込み、
「その欠陥を見るのに必要なファイルが文脈に入るか」を LLM 抜きで判定した。
入っていなければ、どのモデルでも検出は不可能 — 品質の上限を決定論的に測れる。

| クラス | n | full-repo | diff-only | graph | graph+callers | ＋文字列プリパス |
|---|---|---|---|---|---|---|
| L 単一ファイル内 | 4 | 100% | 100% | 100% | 100% | 100% |
| X ファイル跨ぎ・静的エッジあり | 3 | 100% | 0% | **67%** | 100% | 100% |
| H 文字列/動的結合のみ | 5 | 100% | 0% | **40%** | 60% | 100% |
| **合計** | 12 | 100% | 33% | **67%** | **83%** | **100%** |

### この表は graph を過大評価していた（`harness/verify_defects.py` で判明）

12個の欠陥を実際に実行して分類したところ、等価ではなかった：
**実行時に壊れる (FIRES) 9件 / 将来の編集で壊れる潜在結合 (LATENT) 2件 / 可読性 (STATIC) 1件**。

**実際に壊れる9件だけで再集計すると：**

| クラス | n | full-repo | diff-only | graph | graph+callers | ＋文字列プリパス |
|---|---|---|---|---|---|---|
| L | 3 | 100% | 100% | 100% | 100% | 100% |
| X | 3 | 100% | 0% | 67% | 100% | 100% |
| H | 3 | 100% | 0% | **0%** | 33% | 100% |
| **合計** | 9 | 100% | 33% | **56%** | **78%** | **100%** |

**H クラスの 40% は全部まやかしだった：**

```
graph が当てた H クラス欠陥（LATENT・今は壊れない） : 2/2
graph が当てた H クラス欠陥（FIRES・実際に壊れる）  : 0/3   ← ゼロ
```

- **X の取りこぼし**は上記の `impact` バグ。`callers_of` 併用で解消。
- **H の取りこぼし**は原理的限界で、**実害のある欠陥に限れば graph の検出はゼロ**。
  SQL カラム名、イベントトピック、dict のキーなど「文字列でしか繋がっていない」結合は
  どんなコードグラフにも映らない。→ **別種のツールが必須**（オプションではない）。
  Ix でも同じ欠陥が取りこぼされることを確認済み（独立2実装で再現）。

### 精度（precision）— 「当たり」の中身

再現率だけ見ると `impact` は健闘して見えるが、**返しているファイルの 87% は無関係**：

| | 値 |
|---|---|
| blast radius が返すファイル（リポジトリ比） | **平均 40%** |
| precision（必要ファイル / 返したファイル） | **平均 13%** |
| 最悪ケース D06 | 15ファイル中 **12ファイル** を返して HIT（実質ほぼ全読み） |

つまり **HIT の一部は「絞り込めた」からではなく「ほぼ全部返した」から**。
これが公称65倍と実測2.3倍の乖離の正体でもある。
そして precision 8% の文脈は、LLM がノイズの山から欠陥を見つけることを意味するので、
**文脈再現率は実検出率の上限としても楽観側に寄る**。

---

## 実検出率の盲検実測（Claude CLI・36ラン・$8.68）

文脈再現率は上限でしかないので、**実際に LLM が指摘するか**を測った。
`harness/blind_review.py`。盲検の担保：

- `--strict-mcp-config`（MCP 未接続）／プロジェクト外の空 temp ディレクトリで実行
- ファイル系ツールを全禁止 → 文脈は戦略が組んだファイル集合そのもの
- `bench/defects.json` は非開示。生の指摘は `results/blind/` に全36件保存

実害欠陥9件 × 4戦略：

| クラス | n | diff-only | graph | graph+callers | full-repo |
|---|---|---|---|---|---|
| L | 3 | 100% | 100% | 100% | 100% |
| X | 3 | 0% | 67% | **100%** | 100% |
| H | 3 | 0% | **0%** | 33% | 67% |
| **合計** | 9 | 33% | **56%** | **78%** | 89% |

### 最重要の結果：文脈再現率が検出率を完全に予測した

| クラス | | diff-only | graph | graph+callers |
|---|---|---|---|---|
| L | 文脈再現率 / 実検出率 | 100% / 100% | 100% / 100% | 100% / 100% |
| X | 文脈再現率 / 実検出率 | 0% / 0% | 67% / 67% | 100% / 100% |
| H | 文脈再現率 / 実検出率 | 0% / 0% | 0% / 0% | 33% / 33% |
| **合計** | 文脈再現率 / 実検出率 | **33% / 33%** | **56% / 56%** | **78% / 78%** |

**9セルすべてが完全一致**した。

これは社内 A/B の問題に直接効く：**高価でブレる LLM 実測の代わりに、
`harness/run_bench.py` の決定論的な文脈再現率を使えばよい。**
分散ゼロなので有意差検定が不要になり、必要サンプル数の問題自体が消える。

唯一の乖離は full-repo（再現率100% → 検出89%）。
これが「再現率は上限」の実例で、文脈にあっても見落とすことがある。

該当の D10 は境界事例：レビュアーは
「`payload["customerId"]` は camelCase で他は snake_case、キー名が不整合」
と指摘したが、**producer 側（`serializers` が `customer_id` を出す）と繋げなかった**。
ファイル跨ぎ契約の破れは両側を繋いで初めて検出、という基準で MISS とした。

### 採点で踏んだ罠（自社で再現する場合の注意）

3回とも**採点側のバグで結果が反転した**。生データを保存していなければ全部誤った結論になっていた。

| 症状 | 原因 | 影響 |
|---|---|---|
| diff-only が 88% を記録 | レビュー**全文**を横断照合していた。別々の指摘に散った単語で誤ヒット | 偽陽性 |
| 無関係な指摘が HIT 判定 | ファイル跨ぎ欠陥に「相手側を名指ししたか」の要件が無かった | 偽陽性4件 |
| 正しい指摘が MISS 判定 | `**FINDING:**` のマークダウン装飾行をパーサが落としていた | 偽陰性 |
| X/H が全戦略 0% | レート制限の失敗を MISS として計上（`result: null`・$0.000） | 26セル無効 |

対処：1指摘内での照合／相手側名指しの必須化／装飾に強いパーサ／
**失敗は必ずエラー扱いで再試行し、決して MISS に計上しない**。

---

`harness/string_contracts.py`（依存なし・約120行）で残り3件すべてを検出：

```
app/db.py:       SQL identifier 'discount_pct' is not a declared column; did you mean 'discount_percent'?
app/api.py:      reads key 'customerId' but the only producer writes 'customer_id'
app/handlers.py: subscribes to 'order_created' but publisher emits 'order.created'

3 findings, 0 tokens spent.
```

LLM を一切使わないので、トークンコストもレビュー時間も増えない。

---

## 社内 A/B テストについて

「統計的有意差なし」は**まだ何も言えていない**状態。有意差がないことは安全の証拠ではない。

検出率 70% を基準に、必要サンプル数（α=0.05, 検出力 80%）:

| 真の低下幅 | 非対応2群 (各群) | 対応あり McNemar (総PR数) |
|---|---|---|
| 5pt (70→65%) | 1,377 | 194 |
| 10pt (70→60%) | 356 | 60 |
| 20pt (70→50%) | 93 | 20 |

**推奨:**
1. **同一PRを両方式でレビューする対応ありデザイン**に変える → 必要数が約1/7
2. **そもそも A/B が不要**。上の盲検実測で、決定論的な文脈再現率が
   実検出率を12セル中12セルで正確に予測した。分散ゼロなので検定自体が要らない。
   `harness/run_bench.py` を自社リポに向けるのが最短。

`harness/power.py` で再計算できる。

---

## 他の候補

| ツール | ★ | ライセンス | ローカル完結 | 位置づけ |
|---|---|---|---|---|
| **code-review-graph** | 29.8k | MIT | ✅ 既定で完全ローカル | 採用。構造グラフ |
| **semgrep** (OSS) | 16.2k | LGPL-2.1 | ✅ | H クラス欠陥の決定論的検出。併用推奨 |
| **ast-grep** | 15.5k | MIT | ✅ | 構文パターン検索。軽量、semgrep の代替 |
| oraios/serena | 27.8k | MIT | ✅ (LSP) | LSP 経由なので import 形式に依存しない参照解決。`impact` バグの根治候補 |
| yamadashy/repomix | 27.8k | MIT | ✅ | リポジトリ圧縮。小規模リポ向け |
| zilliztech/claude-context | 12.4k | MIT | △ Milvus 必要 | ベクタDB前提。社内では構成負担が大きい |
| ix-infrastructure/Ix | 683 | Apache-2.0 (CLI のみ) | ❌ バックエンド非公開 | **失格** |

Serena は LSP（実際の型解決）を使うため、今回見つけた
`from pkg import module` 問題が原理的に起きない。
`impact` バグが upstream で直らない場合の代替として評価する価値がある。

---

## 推奨構成

```
1. 文字列契約プリパス   harness/string_contracts.py 相当 or semgrep    0トークン
2. 構造文脈             code-review-graph impact + query callers_of    ~770トークン
3. LLM レビュー         Claude Code                                    上記文脈のみ
```

導入手順:
- `impact` 単体を信用しない。`callers_of` 併用を review skill / CLAUDE.md に明記する
- 埋め込みは既定（ローカル）のまま。`--embedding-provider` のクラウド指定を組織ポリシーで禁止
- 上流に import 解決バグを報告（最小再現は `bench/probe_importstyle/`）

**上流修正を待つ必要はない。** 回避策で X クラスは実測 100% に戻る。
バグの本質は「エッジのターゲットが bare 名のまま残る」ことで、
`callers_of` は名前で引くため bare でも当たるから。
情報はグラフに存在していて、`impact` が拾えていないだけ。

修正を出す場合の想定パッチ位置（小さい）:
- `python_resolver.py` — `from X import Y` で `X.Y` がモジュールとして存在するなら
  `X/__init__.py` ではなく `X/Y.py` を IMPORTS_FROM のターゲットにする
- または `graph.py:734` の bare 解決器 — import 証拠がパッケージの `__init__.py` の場合、
  そのパッケージ内の兄弟モジュールも候補に含める（パーサ変更が不要な分こちらが安全）

なお `jedi_resolver.py` に意味解決器が入っているが、v2.3.7 では
**どこからも呼ばれていない**（`jedi` も依存に入っていない）。
手動で実行しても対象が `receiver.method()` 形式のみで、今回のケースは解決しない（resolved=0）。

---

## 再現手順

**クローン直後は先に `bash setup_fixtures.sh` を実行すること**（[`SETUP.md`](SETUP.md)）。
`bench/` のフィクスチャが git リポジトリでないと `build` が 0 files になり、
ベンチマークが全戦略 33% に潰れる。

```bash
bash setup_fixtures.sh

uv venv .venv --python 3.12
uv pip install --python .venv/bin/python code-review-graph

.venv/bin/code-review-graph build --repo bench/repo
.venv/bin/python harness/run_bench.py \
    --repo bench/repo --defects bench/defects.json \
    --cli .venv/bin/code-review-graph --depth 2 --out results/crg_depth2.json

.venv/bin/python harness/verify_defects.py
.venv/bin/python harness/blind_review.py --reps 1 --pace 12   # 要 Claude CLI・約$9
.venv/bin/python harness/rescore.py
.venv/bin/python harness/quality_report.py
.venv/bin/python harness/string_contracts.py bench/repo
```

> ⚠️ `.venv/` (428MB) と `repos/` (759MB, ix-cli の node_modules 含む) で計 1.2GB。
> Dropbox 配下なので同期対象。再生成可能なので不要なら削除してよい。
> 評価成果物は `bench/` `harness/` `docs/` `results/` の 0.9MB のみ。

## ファイル

| パス | 内容 |
|---|---|
| `bench/repo/` | 12個の欠陥を仕込んだ評価用リポジトリ |
| `bench/defects.json` | 欠陥マニフェスト（クラス・必要文脈ファイル） |
| `bench/probe_importstyle/` | `impact` バグの最小再現 |
| `harness/run_bench.py` | 文脈再現率＋トークンコスト測定 |
| `harness/string_contracts.py` | 文字列結合欠陥の検出（LLM不使用） |
| `harness/blind_review.py` | Claude CLI による盲検レビュー（実検出率） |
| `harness/rescore.py` | 保存済みレビューの再採点＋ヒット根拠の監査出力 |
| `results/blind/` | 生のレビュー全36件（採点は監査可能） |
| `harness/verify_defects.py` | 仕込み欠陥が実際に壊れるかを実行検証 |
| `harness/quality_report.py` | 実害欠陥のみでの再集計＋精度分析 |
| `harness/mcp_overhead.py` | MCP ツール定義の固定費を実測 |
| `harness/cost_model.py` | レビュー時トークン代の月額試算 |
| `harness/cost_rework.py` | 手戻り込みの総保有コスト＋損益分岐 |
| `harness/import_style.py` | 自社リポで `impact` バグを踏む頻度を測る |
| `harness/power.py` | A/B 必要サンプル数の計算 |
| `harness/measure_savings.py` | **自社リポでの削減効果を実測**（推奨パラメータの before/after） |
| `docs/GETTING_STARTED.md` | **導入手順（前提知識ゼロ向け）** |
| `docs/article_review_2026-09-04.md` | Zenn記事の4ツール構成の検証・全実測データ |
| `results/crg_depth2.json` | 実測生データ |
| `docs/limitations.md` | 本評価の限界 |
