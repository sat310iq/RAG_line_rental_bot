# 評価データセット拡張計画

現行の `data/eval/eval_questions.csv`（約 16 問）はスモーク〜中期回帰に有効。運用品質判断に耐えるには、次の軸で**段階的に追加**する。

## 追加の優先軸

1. **カテゴリ網羅**: ゴミ / 設備 / 契約 / 防犯 / 生活 / 規則 / 共用部ごとに最低 1〜2 問。
2. **エッジケース**: 該当なし、曖昧な相談、禁止事項の列挙、更新・解約・原状回復の境界。
3. **マルチソース**: `deal` + `master` が同時に必要な質問（既存を増やす）。
4. **override / fallback**: CSV キーワード優先、PDF フォールバックが効くケース。
5. **safety**: PII を含みうる質問、エスカレーション行が必要な質問。

## スキーマ

- 既存列（`expected_sources`, `relevant_doc_ids`, `question_type` 等）を維持する。
- `expected_evidence_ids` / `relevant_doc_ids` は **ID マッピング**と整合させ [eval_id_mapper](../src/eval_id_mapper.py) を更新する。

## スモークとの役割分担

- 回帰の速さが必要なケースは **smoke_eval_questions.csv** に新規追加を控え、件数を小さく保つ。
- 大規模な論点は **full** セットのみに追加する。
