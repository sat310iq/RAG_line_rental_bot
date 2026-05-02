# Failure Backlog Summary

Generated from: `ab_compare_20260425T064154Z.jsonl` (run_id=dce33165e3bf4a90bdd3b09678cbacc1)
Backlog size: 10 (cap=10).

Extended `wrong_intent_match` heuristics are applied in this script; tags may not match raw JSONL alone.

## Router KPI vs forced legs (important)

- **D-group** questions may show management-company guidance when evaluated with the **`auto`** path (including D-group extra runs in `run_eval.py`).
- The same question under **`kb_only` or `rag` forced** modes uses the standard pipeline; mismatches there are a **separate** quality issue from Router KPI and `should_escalate_but_answered` on `auto`.
- Treat **Router KPI** (auto) and **forced-leg quality** (kb_only/rag) on different scorecards, or tag forced-leg rows as `evaluation_scope` fixes.

## Top failure tags (merged, all rows)

- `should_escalate_but_answered`: 22
- `overbroad_rule`: 9
- `wrong_intent_match`: 4
- `needs_clarification`: 2

## Top backlog items

| rank | question | tag | root_cause | fix_type | suggested_change |
|---|---|---|---|---|---|
| 1 | 家賃減額を請求できますか？ | should_escalate_but_answered | forced_leg_bypasses_auto_escalation | evaluation_scope | Router KPI では `auto` 実行を正とし、`kb_only`/`rag` 強制 ... |
| 2 | 家賃減額を請求できますか？ | should_escalate_but_answered | forced_leg_bypasses_auto_escalation | evaluation_scope | Router KPI では `auto` 実行を正とし、`kb_only`/`rag` 強制 ... |
| 3 | 清掃費って払うの？ | wrong_intent_match | category_mismatch_answer | negative_keyword | faq_kb.csv: 意図ずれのある intent へ negative_keywords ... |
| 4 | 清掃費って払うの？ | wrong_intent_match | category_mismatch_answer | negative_keyword | faq_kb.csv: 意図ずれのある intent へ negative_keywords ... |
| 5 | 騒音のことで相談です | needs_clarification | offline_harness_cannot_reproduce_line... | clarification_pattern | 曖昧パターン（例: 水道の件/修繕/契約/更新）を CSV か別リストに登録。LINE 実機の... |
| 6 | 騒音のことで相談です | needs_clarification | offline_harness_cannot_reproduce_line... | clarification_pattern | 曖昧パターン（例: 水道の件/修繕/契約/更新）を CSV か別リストに登録。LINE 実機の... |
| 7 | この物件は浸水リスクある？ | overbroad_rule | template_subject_mismatch | negative_keyword | exclude_keywords / negative_keywords を厳格化し、主語違い... |
| 8 | 原状回復費用はどこまで借主負担ですか？ | overbroad_rule | template_subject_mismatch | negative_keyword | exclude_keywords / negative_keywords を厳格化し、主語違い... |
| 9 | 契約書のどこに書いてありますか？ | overbroad_rule | template_subject_mismatch | negative_keyword | exclude_keywords / negative_keywords を厳格化し、主語違い... |
| 10 | 抵当権実行されたらどうなる？ | overbroad_rule | template_subject_mismatch | negative_keyword | exclude_keywords / negative_keywords を厳格化し、主語違い... |

## Recommended next commit (max 3)

1. Tighten **negative / exclude keywords** (gas/water/garbage/repair intents) for wrong_intent and overbroad_rule.
2. Register **ambiguous phrasing** (水道口頭/修繕/契約/更新) for clarification or KB routing.
3. **Scope evaluation** for D-group: separate `auto` Router KPI from `kb_only`/`rag` forced-leg notes in reports.
