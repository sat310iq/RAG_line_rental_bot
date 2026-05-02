# 評価方針（Phase 1・軽量）

## 目的

回答品質・安全性・運用安定性の**推移を追跡**し、変更のたびに同じ形式で比較できるようにする。

## 既存評価との役割分担

- **Metrics v2 / スモーク・Opik ダッシュボード・詳細レポート**（[eval/OPIK_*.md](eval/) 等）: 運用・可視化向け。これらは**本ファイルと競合させず**、スクリプトとダッシュの一次情報を残す。
- **Metrics v2 スモーク用 CSV**: `data/eval/eval_questions.csv` と `scripts/run_simple_eval.py`（既存・RAG 主路は変更しない）
- **本ドキュメント（Phase 1 軽量枠）**: `scripts/run_eval.py` による**カテゴリ付き・人間レビュー前提**の JSONL 記録。
  - ルーティング A/B 実験: 既定 **`eval/datasets/line_rag_eval_router_abcd_v1.csv`**（`expected_route` 付き）。ルート設計の正本は [RAG_ROUTING_AND_AB_REDESIGN.md](eval/RAG_ROUTING_AND_AB_REDESIGN.md)。
  - **カテゴリ網羅のベースライン**（`expected_behavior` / `expected_source` 付き）: **`eval/datasets/line_rag_eval_v1.csv`**。実行例:  
    `python3 scripts/run_eval.py --dataset eval/datasets/line_rag_eval_v1.csv`

## Evaluation Sources of Truth

- Router KPI dataset: `eval/datasets/line_rag_eval_router_abcd_v1.csv`
- Legacy/general QA dataset: `eval/datasets/line_rag_eval_v1.csv`
- Runner: `scripts/run_eval.py`
- Summary output: `data/eval/ab_summary.json`（`note_forced_leg_scoping` と `route_metrics.forced_leg_scoping` で **D 群の強制 leg と auto KPI** の切り分けを明記。各 JSONL 行に `eval_scoping`）
- Failure analysis: `scripts/analyze_failure_patterns.py`
- **Failure backlog（上位 N 件・改善メモ）**: `scripts/failure_backlog.py` — `run_eval.py` の JSONL を入力に、`data/eval/failure_backlog_top10.jsonl` と `data/eval/failure_backlog_summary.md` を生成。`infer_failure_tags` の `failure_tags` を正としつつ、`wrong_intent_match` の拡張ヒューリスティックを合算する。
  - 実行例: `python3 scripts/failure_backlog.py --input eval/runs/ab_compare_<timestamp>.jsonl`（`--input` 省略時は `eval/runs/ab_compare_*.jsonl` の最新 mtime）
  - **D 群と `auto` 追加実行 vs 強制 leg**: D 群は `auto` で管理会社誘導・ルーティングを見る一方、同一質問の **`kb_only` / `rag` 強制**は通常パイプラインであり、Router KPI（`auto`）と**別の誤意図・品質リスク**を持つ。バックログの `should_escalate_but_answered`×`kb_only`/`rag` は「強制 leg が `auto` のエスカレーション判定をバイパスする」件として `evaluation_scope` に分類される。詳細は生成される `failure_backlog_summary.md` の注意節を参照。
- Router/RAG design: `docs/eval/RAG_ROUTING_AND_AB_REDESIGN.md`

## コア指標（参考）

- 忠実性・関連性・コンテキスト再現率  
- フォールバック率・エスカレーション妥当性  
- レイテンシ p50 / p95  
- LINE 返信成功率（本スクリプト外で観測可能なら）

## `expected_source` マッピング（`line_rag_eval_v1.csv`）

| CSV の値 | 意味（PoC ルーター表現） |
|----------|-------------------------|
| `deal_only` | 個別契約 / FAQ KB 優先で足りる想定 |
| `master_only` | 基本契約 PDF（マスタ）中心の想定 |
| `multi` | 複数ソース統合の想定 |
| `none` | 法判断等・根拠を断定しない想定（`should_escalate` と併用しうる） |

`run_eval.py` 出力の `retrieved_sources` から**観測**されるソース種は `debug_trace` / source_type の組み合わせで [scripts/run_eval.py](../scripts/run_eval.py) 内 `infer_observed_source` により `deal_only` / `master_only` / `multi` / `unknown` / `none` へ正規化される。厳密一致の自動採点は**参考**（`match_tier`）であり、**本採用は人間レビュー前提**（`pass_fail` は既定 `needs_review`）。

## データセットカテゴリ

`line_rag_eval_router_abcd_v1.csv` では `ab_group`（A/B/C/D）と `expected_route`（fast_path / rule / rag / clarification / escalation）を付与する。`line_rag_eval_v1.csv` の `category` 例:

- `csv_only` … FAQ/KB のみで足りる想定  
- `pdf_only` … 基本契約 PDF 中心の想定  
- `conflict` … ソース優先順位が効く想定  
- `should_escalate` … 断定・法判断・根拠不足で誘導すべき想定  
- `ambiguous` … 曖昧な質問  
- `leading` … 誘導・思い込みを促す質問  
- `ops` … 連絡先・手続き・運用系

## レビュー観点

- 取得根拠は回答を支持しているか  
- 正しいソース優先が適用されたか  
- エスカレーションが妥当か  
- LINE 向けに長すぎないか  

## Failure taxonomy（分類ラベル）

失敗分析・`review_failures.py` レビュー時に用いる:

| ラベル | 意味の例 |
|--------|-----------|
| `retrieval_miss` | 必要な文書が取れていない |
| `source_conflict` | CSV と PDF 等の矛盾の扱いが不適切 |
| `answer_hallucination` | 根拠にない断定・事実 |
| `escalation_missing` | エスカレーションすべきだったが通常回答 |
| `escalation_overused` | 不要なエスカレーション |
| `timeout_fallback` | 時間切れ・簡略応答に偏った |
| `line_reply_failure` | LINE API・配信経路の失敗（本スクリプト外観測含む） |
| `ops_memory_risk` | OOM・重いモデル・キャッシュ等の運用リスク |

## ラン出力

`eval/runs/run_<timestamp>.jsonl` に 1 行 1 レコード。`pass_fail` は既定 `needs_review` とし、自動採点は行わない。

## 将来拡張（Ragas / Amplifier）

`run_eval.py` 先頭付近のコメント参照。`eval/runs/*.jsonl` を後段で **Ragas や外部 Amplifier 系**に渡す場合の入力としても使える。本リポジトリでは **Ragas・Amplifier CLI は Phase 1 では導入しない**。

## Phase 2（スコープ外のまとめ）

- **本格** `docs/recipes/*`、Failure taxonomy の運用固定、**リリースゲート**の自動化は Phase 1 完了後。入口として [release_checklist.md](release_checklist.md)（スケルトン）を置く。
