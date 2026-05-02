# Tuning Guide

## retrieval

### 基本パラメータ

| 変数名 | 用途 |
|---|---|
| `contract_source_master_top_k` | 契約書ソース検索（通常） |
| `contract_source_retry_top_k` | 契約書ソース検索（リトライ） |
| `pdf_score_threshold` | PDFスコア下限 |
| `csv_score_threshold` | CSVスコア下限 |

### 高度なパラメータ

| 変数名 | 用途 |
|---|---|
| `contract_source_pdf_retry_threshold` | master empty時リトライのPDF閾値 |
| `pdf_empty_retry_score_threshold` | KB-empty時のPDF再検索閾値 |
| `csv_keyword_override_min_hits` | CSVキーワードオーバーライド最小ヒット数 |
| `csv_keyword_override_min_fusion_score` | CSVキーワードオーバーライド最小fusionスコア |
| `csv_keyword_override_use_primary` | CSVキーワードオーバーライド一次利用フラグ |

確認手順: `eval/runs/` の recall@K を見て調整 → pytest で回帰確認

---

## cache

| 変数名 | 用途 |
|---|---|
| `cache_semantic_threshold` | キャッシュ再利用判定の類似度下限 |

確認手順: キャッシュヒット率とスコア分布を `eval/runs/` で確認

---

## routing

| 変数名 | 用途 |
|---|---|
| `kb_fast_path_enabled` | KB fast path 有効フラグ |
| `kb_fast_path_score_threshold` | KB fast path スコア下限 |
| `kb_fast_path_short_max_len` | KB fast path 短文判定上限 |
| `rag_contract_source_drop_kb_faq_entirely` | 契約ソース経路でKB FAQ完全除外フラグ |
| `enable_individual_contract_handoff` | 個別契約ハンドオフ有効フラグ |
| `rag_template_clause_scope_enabled` | テンプレート条項スコープ有効フラグ |

確認手順: `eval/runs/` のルーティング正解率を見て判定ロジックを修正 → pytest で回帰確認

---

## generation

| 変数名 | ファイル | 用途 |
|---|---|---|
| `self.answer_prompt` | `src/rag_answerer.py` | 通常回答プロンプト |
| `self.contract_answer_prompt` | `src/rag_answerer.py` | 契約回答プロンプト |
| `self.contract_source_qa_prompt` | `src/rag_answerer.py` | 契約出典付き回答プロンプト |

確認手順: `eval/runs/` の回答品質スコアを見てプロンプトを修正 → eval再実行
