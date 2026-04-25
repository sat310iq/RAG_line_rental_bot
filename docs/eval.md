# 評価方針（Phase 1・軽量）

## 目的

回答品質・安全性・運用安定性の**推移を追跡**し、変更のたびに同じ形式で比較できるようにする。

## 既存評価との役割分担

- **Metrics v2 / スモーク**: `data/eval/eval_questions.csv` と `scripts/run_simple_eval.py`（既存・不変更）
- **本ドキュメント**: `scripts/run_eval.py` による**カテゴリ付き・レビュー前提**の記録。既定データセットは **`eval/datasets/line_rag_eval_router_abcd_v1.csv`**（A/B/C/D・`expected_route` 付き）。レガシー比較は `eval/datasets/line_rag_eval_v1.csv`。設計の正本は [RAG_ROUTING_AND_AB_REDESIGN.md](eval/RAG_ROUTING_AND_AB_REDESIGN.md)。

## コア指標（参考）

- 忠実性・関連性・コンテキスト再現率  
- フォールバック率・エスカレーション妥当性  
- レイテンシ p50 / p95  
- LINE 返信成功率（本スクリプト外で観測可能なら）

## データセットカテゴリ

`line_rag_eval_router_abcd_v1.csv` では `ab_group`（A/B/C/D）と `expected_route`（fast_path / rule / rag / clarification / escalation）を付与する。`line_rag_eval_v1.csv` の `category` 例（レガシー）:

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

`run_eval.py` 先頭付近のコメント参照。本リポジトリでは **Ragas・Amplifier CLI は Phase 1 では導入しない**。
