# Failure → intent 修正表（top10・設計メモ）

**目的**: 実装前のトリアージ。`data/faq_kb.csv` には**この表の結論に基づく 1 テーマだけ**を反映する。  
**根拠 run**: `eval/runs/ab_compare_20260425T064154Z.jsonl`（`failure_backlog_summary.md` 生成元と同一 run_id）

**必読フィールド**（`answer_preview` のみに依存しない）:

- `retrieved_sources[].source_id`
- `decision_path`
- `actual_route` / 評価上の `expected_route`

| rank | question | current_wrong_intent_or_source | expected_intent_or_route | failure_tag | root_cause | fix_type | add_negative_to | add_positive_to | escalation_clar | reason |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 家賃減額を請求できますか？ | **生活_ガス料金**（`evidence`）· `decision_path=rule` · `mode=kb_only` | `escalation`（D） | `should_escalate_but_answered`, `wrong_intent_match` | `forced_leg_bypasses_auto_escalation` | **`evaluation_scope`** | **—**（原則 CSV 禁止） | **—** | **管理会社エスカ**が正。`management_escalation` は auto/LINE 再現時に | D 群は forced leg 評価の偽陽性と混在。`source_id` はガスで正しくトレースされている（本文が「請求」全般向けのため一見イレギュラー）。**KB negative で塞がない。**同質問が **auto / 本番**でもガス案内になる時だけ `生活_ガス料金` への negative を再検討。 |
| 2 | 家賃減額を請求できますか？ | 同上 · `decision_path=rag` · `mode=rag` | 同上 | 同上 | 同上 | **`evaluation_scope`** | **—** | **—** | 同上 | 同上。RAG でも evidence は **生活_ガス料金**。 |
| 3 | 清掃費って払うの？ | **契約_退去清掃費**· `decision_path=clarification` | データセットは `expected_route=rule`、実測 `clarification` | `wrong_intent_match` | `category_mismatch_answer` | **`dataset_label` / `add_ambiguous_pattern` の三択** | ゴミ系: 既に対応済みなら**増やさない**（同一テーマ外） | 清掃費行: 既に拡充済なら**増やさない** | 既存 clar（退去清掃 vs ゴミ置き） | **`source_id` はゴミ系ではない。**失敗の主因は **「rule 期待 vs clar 実測」** または backlog の**拡張 `wrong_intent` タグ**。`answer_preview` だけ見ると清掃 vs 共用部で紛らわしい。次アクション: 評価上「clar 許容」にするか、**短くないのに clar** になる条件を [kb_fast_path] で見直すか。 |
| 4 | 清掃費って払うの？ | 同上（`mode=rag`） | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上。 |
| 5 | 騒音のことで相談です | **生活_騒音**· `decision_path=rule` | `clarification` | `needs_clarification` | `offline_harness_cannot_reproduce_line_state` | **`add_ambiguous_pattern`** / 評価切り出し | — | 騒音は既に当たり：不足は「曖昧扱い」 | C 群は**状況確認**期待 | カテゴリ `ambiguous` なのに **騒音で即 rule**。**answer は騒音向け**で一貫。ハーネスと「clar 期待」のズレ。LINE 実機再現ログがないと `kb_fast_path` 改修は先送り可。 |
| 6 | 騒音のことで相談です | 同上（`decision_path=rag`） | 同上 | 同上 | 同上 | 同上 | — | 同上 | 同上 | RAG でも同 evidence **生活_騒音**。 |
| 7 | この物件は浸水リスクある？ | `retrieved_sources=[]` 寄り· `decision_path=fallback` | `rag` | `overbroad_rule` | `template_subject_mismatch` | **`code_guard` / RAG 取得** + 必要なら KB | 誤った rule 行があれば `exclude` | **N/A**（期待は master 根拠） | フォールバックで管理案内 | **主語＝特定物件＋災害リスク**。PDF/RAG ヒットゼロでテンプレ案内。CSV negative より **検索・閾値・フォールバック分類**が主戦場。 |
| 8 | 原状回復費用はどこまで借主負担ですか？ | **契約_原状回復**· `decision_path=rule` | データ `expected_route=rag` | `overbroad_rule` | `template_subject_mismatch` | **`dataset_label` または** exclude 見直し | 他 intent からの**食い違い**がログに出た行のみ | `契約_原状回復` | — | 内容は原状回復の一般説明で妥当。**B 群は RAG 期待**のため、KB 命中有りでも「rule ＝ 広い」とタグ付く。`master_only` 期待との整合要確認。 |
| 9 | 契約書のどこに書いてありますか？ | `master`（`グランマーレ大分空港契約書.txt` 複数）· `decision_path=fallback` | `rag` | `overbroad_rule` | `template_subject_mismatch` | **`code_guard` / 検索品質** | 同上 | 同上 | エスカ or RAG 改善 | 根拠低でフォールバック。**`source_id` は PDF だが**回答は「確認できず」。キーワード以前に **RAG/チャンク**課題。 |
| 10 | 抵当権実行されたらどうなる？ | `retrieved_sources=[]`· `decision_path=fallback` | `rag` | `overbroad_rule` | `template_subject_mismatch` | **`code_guard` / ドメイン外扱い** | — | — | 管理会社・専門家 | 法的ライスクエリ。**KB 本文追加は慎重**（テンプレ窓口でよいなら方針固定）。 |

## 診断軸: positive 不足 / negative 不足

| 状況 | 典型アクション（同一テーマ内のみ） |
| --- | --- |
| 誤 intent（`source_id` 確定）が**強すぎる** | `add_negative_to_wrong_intent` |
| 正しい `source_id` だが**スコアで負けた** / 他に流れた | `add_positive_to` / `add_primary_to` |
| 両方 | 小さく両方。ただし **evaluation_scope 行は原則 CSV 禁止**のまま。 |

## 次の 1 テーマ候補（合意事項）

1. **cleaning vs garbage 残差**: 再評価の JSONL で **ゴミ意図**の `source_id` が再発しないか**確認のみ**（残なしなら完了）。
2. **gas vs rent/legal**: **evaluation_scope と escalation 切り分け後**、auto/LINE でも家賃減額→ガスが再現するなら限定的に KB/escalation へ。
3. **overbroad_rule**（B）: 浸水・抵当権・契約条項は **RAG/フォールバック/データセット**が主。CSV negative 単独に依存しない。
