---
name: forecast_review_skill
description: >
  eval再実行のたびに予測精度を採点し、バイアスを特定する。
  Brier Scoreで過去予測を評価し、次回予測を更新する。
  recall@5改善予測とroute_match率改善予測を対象とする。
triggers:
  - 予測採点
  - Brier Score
  - forecast review
  - 予測精度
  - eval採点
---

# Forecast Review Skill

## When to use
- eval再実行後（`python3 scripts/run_simple_eval.py --mode full` または `python3 scripts/run_eval.py` の直後）
- 施策を実施してeval結果が出たとき

## Procedure

1. `docs/eval/forecast_log.md` を開き、最新の未採点予測タスクを確認する
2. 今回のeval結果（`data/eval/eval_metrics.json` または `eval/runs/` 最新ファイル）から該当指標を取得する
3. 各予測タスクのBrier Scoreを計算する（`resources/brier_score_guide.md` を参照）
4. 結果を `docs/eval/forecast_log.md` に記録する
5. バイアスを特定する
   - 過去4回のスコアが上昇傾向 → アンカリングまたは過剰反応を疑う
   - 予測確率が常に50%付近 → 情報処理が不十分
6. 反証サーチ（5〜15分）: 現在の改善施策が間違っている証拠を探す
7. 次回予測タスクを設定し `docs/eval/forecast_log.md` に追記する
   - 確率は1%単位で記録する（「約50%」は禁止）
   - 調整幅の目安: 通常 ±5〜15%。±20%超は根拠を必ず記載する

## Output format

| タスクID | 予測確率 | 結果 | Brier Score | バイアス判定 |
|---|---|---|---|---|
| PT-001 | 50% | 未達 | 0.25 | 適切 |

今回特定したバイアス: 過剰反応 / アンカリング / 適切 のいずれか
次回予測タスク: （PT-NNNの形式で追記）
