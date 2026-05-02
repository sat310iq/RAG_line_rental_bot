# RAG PoC 精度・運用改善（実装サマリ）

## 変更概要

1. **評価 ID（strict / normalized）**  
   - [`data/eval/expected_id_aliases.yaml`](../../data/eval/expected_id_aliases.yaml) でレガシー slug → canonical intent を定義。  
   - [`EvalIDMapper`](../../src/eval_id_mapper.py): `map_expected_id`（エイリアスあり）と `map_expected_id_strict`（エイリアスなし）。  
   - 評価結果に `recall_at_*_strict`、`match_tier`（`strict_hit` / `normalized_only` / `miss` / `unknown`）を追加。

2. **キャッシュ**  
   - [`QueryCache`](../../src/query_cache.py) のバージョンキーに `manifest.json` の `kb_sha256` 先頭を連結（mtime に加え再現性向上）。

3. **Chroma / 運用**  
   - [`VectorStoreManager`](../../src/vector_store_manager.py): 初期化失敗をログに残す、`healthcheck_collections()`、起動時 INFO に manifest `kb_sha256` 短縮表示。  
   - [`scripts/preflight_check.py`](../../scripts/preflight_check.py): `kb_deal_csv` / `kb_master_pdf` コレクション存在チェック。

4. **誤マッチガード**  
   - [`faq_kb.csv`](../../data/faq_kb.csv) に任意列 `negative_keywords`, `negative_penalty`（例: `生活_水道請求` 行で水漏れ系クエリに -0.35）。  
   - [`rag_answerer`](../../src/rag_answerer.py): 閾値前にスコア減点。

5. **PII**  
   - [`analyze_pii`](../../src/metrics.py): `pii_policy_allowed_contact`, `pii_true_leak_suspected`, `pii_false_positive_prone`, `pii_reasons`。

6. **OPIK / 集計**  
   - `fact_error_rate`, `unsupported_content_rate`（unsourced と overreach の max）、PII 系レート。Comet 集計のレガシー `avg_hallucination` は `avg_hallucination_deprecated` として併記。

7. **ID 正規化成功率**  
   - エイリアス導入後も意味が崩れないよう、`id_mapper` 経由で「各 raw expected が非空マップに解決した割合」で計算。

## strict vs normalized の読み方

- **normalized**（従来の `recall_at_5` 等）: エイリアス適用後の期待 ID 集合。  
- **strict**: CSV の raw ID を PDF/FAQ マッピングのみ適用（YAML エイリアスなし）。  
- **`match_tier`**: top-5 で期待集合が全て含まれるかで `strict_hit` → だめなら normalized で `normalized_only` → それもだめなら `miss`。

## 再評価コマンド

```bash
cd rental_rag_poc
export OPENAI_API_KEY=...
python scripts/run_simple_eval.py --mode smoke
python scripts/run_simple_eval.py --mode full
```

## インデックス再生成

`faq_kb.csv` に列を追加したため、**BM25 / Chroma の再インデックス**を推奨します。

```bash
python scripts/reindex_vector_db.py
```

（プロジェクトの既定スクリプト名に合わせて実行してください。）

## 残課題（第2週以降）

- [`data/eval/semantic_neighbor_classes.yaml`](../../data/eval/semantic_neighbor_classes.yaml) に基づく `semantic_hit_but_id_mismatch` 層。  
- `negative_keywords` の本番調整（減点幅・衝突限定の除外ルール）。
