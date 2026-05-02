# OPIK / Comet ダッシュボード Runbook

運用で指標名・解釈・閾値を暗黙にしないための一行定義と UI 手順です。`feedback_scores` には**数値のみ**、`match_tier` 文字列は **metadata** に載せます（`opik_integration.py`）。

## KPI（一行・固定）

**成功** = **normalized recall（`avg_recall_at_5`）が意図した方向に上昇** かつ **`fact_error_rate` を 0 に維持**（悪化させない）。

補助ゲート（単純版・閾値はバージョン管理）:

| ゲート | 条件 |
|--------|------|
| Recall | `avg_recall_at_5` > 0.4 |
| Fact | `fact_error_rate` == 0 |
| Match tier | `match_tier_miss_rate` < 0.5（集計に存在する場合） |

`rag_health_score`（0〜1 目安）:

```text
0.5 * avg_recall_at_5 + 0.3 * (1 - fact_error_rate) + 0.2 * (1 - match_tier_miss_rate)
```

`rag_health_pass` は上記ゲートをすべて満たすと 1、それ以外 0。

## `match_tier_code` 対応表（OPIK feedback_scores）

| Code | 意味（metadata の `match_tier` と対応） |
|------|----------------------------------------|
| 0 | `strict_hit` |
| 1 | `normalized_only` |
| 2 | `miss` |
| 3 | `unknown` |

## 4 パネル（保存ビュー名の目安）

Comet / OPIK の保存ビュー名の例として **RAG_POC_Main / Retrieval / Safety / PII** を使います。

### 1. RAG_POC_Main（ヘルス）

- `rag_health_score`, `rag_health_pass`
- Comet `summary_text`（aggregate）: KPI 一行 + Health 一行
- タグ例: `rag_health:pass` / `rag_health:fail`

### 2. Retrieval

- `avg_recall_at_5`, `avg_recall_at_5_strict`
- `match_tier_strict_hit_rate`, `match_tier_normalized_only_rate`, `match_tier_miss_rate`
- 行単位: `recall_at_5`, `recall_at_5_strict`, `match_tier_code`（数値）

### 3. Safety

- `fact_error_rate`, `avg_hallucination_fact_error`
- `unsupported_content_rate`, `avg_relevance`

### 4. PII

- `pii_true_leak_suspected_rate`, `pii_policy_allowed_contact_rate`, `pii_false_positive_prone_rate`
- 行単位: `pii_true_leak_suspected`, `pii_policy_allowed_contact`, `pii_false_positive_prone`（0/1）

### Semantic（第2週・任意）

- `semantic_neighbor_hit_rate` / `match_tier_semantic_rate`（YAML `semantic_neighbor_classes.yaml` の `pairs` が空なら 0）
- 評価を甘くしうるため、**normalized 指標が安定してから**見る。

## トレース Runbook（オフライン評価）

1. `python scripts/run_simple_eval.py` を実行（`data/eval/eval_results.jsonl` 更新）。
2. Comet で同一 experiment の per-step メトリクスと aggregate（step=-1）を確認。
3. OPIK で experiment / dataset を開き、`experiment_item.metadata.match_tier` と `feedback_scores.match_tier_code` を突合。
4. 失敗分析: `python scripts/analyze_failure_patterns.py` → `data/eval/failure_patterns.csv`（`hit_at_1` / `hit_at_3` / `hit_at_5`）
5. デプロイ前: `python scripts/preflight_check.py`（Chroma collection 件数 > 0、`RAG_VECTOR_STORE_PATH`、manifest サブセット表示）

## FAQ / KB チューニング（誤マッチ）

- `data/faq_kb.csv` は**除外禁止・減点のみ**（`rag_answerer` の設計）。
- ベースライン CSV 保存 → 改善後 diff で「Top5 誤マッチ」傾向を比較する。
