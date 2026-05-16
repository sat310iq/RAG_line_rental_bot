# Forecast Log

RAG精度改善施策の予測精度を記録する。
Brier Scoreで採点し、予測バイアスを特定・修正する。

採点タイミング: eval再実行のたびに実施する。
参照Skill: `skills/rental_rag/forecast_review_skill/SKILL.md`

---

## PT-001: 次回evalでrecall@5が0.95以上になるか

**登録日**: 2026-05-02
**採点予定**: 次回eval実行後

### 予測

| 項目 | 内容 |
|---|---|
| 問い | 次回evalでrecall@5が0.95以上になるか |
| 予測確率 | 50% |
| 対象指標 | `data/eval/eval_metrics.json` の `avg_recall_at_5` |
| 閾値 | avg_recall_at_5 ≥ 0.95 |

### Base Rate

初回のため主観確率。現在値0.941。過去のeval実行履歴が1件のみのため基準率算出不可。

### Inside View

- explanationタイプの1件（recall@5=0.0）はPDF非使用でクローズ済み
- 他タイプは全件recall@5=1.0で安定
- 大きな改善施策は未実施のため現状維持の可能性が高い

### 反証条件

explanationタイプ以外でrecall@5が低下する新ケースが発見された場合

---

## PT-002: 次回evalでroute_match率が60%以上になるか

**登録日**: 2026-05-02
**採点予定**: 次回eval実行後

### 予測

| 項目 | 内容 |
|---|---|
| 問い | 次回evalでroute_match率が60%以上になるか |
| 予測確率 | 50% |
| 対象指標 | `eval/runs/` 最新ファイルの `route_match` フィールド（`expected_route`設定済み行のみ） |
| 閾値 | route_match率（expected_route設定済み行） ≥ 60% |

### Base Rate

初回のため主観確率。修正前: 0/5=0%。修正後（run_20260501）: 3/5=60%確認済み。

### Inside View

- KB hit早期return追加（`src/rag_answerer.py`）
- `生活_水道請求` needs_clarification_when_short修正
- `生活_喫煙` primaryキーワード追加
- `敷金ってどう返ってくる？` expected_routeをfallbackに修正
- rule問題3件のうち2件（水道は定額？・喫煙したら請求される？）は未解決

### 反証条件

expected_route設定済み行のうち、KB未登録クエリが多数存在する場合

---

## 採点履歴

| 採点日 | PT-ID | 予測確率 | 実測値 | 結果 | Brier Score |
|---|---|---|---|---|---|
| 2026-05-12 | PT-001 | 50% | recall@5 = 1.0（≥ 0.95） | ✅ YES | 0.25 |
