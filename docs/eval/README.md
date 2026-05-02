# Eval ディレクトリ README

## 二系統の eval の役割

このプロジェクトでは eval を目的別に2系統で運用する。
**どちらを使うかは目的で決める。迷ったらこの表を参照する。**

| 系統 | スクリプト | データセット | 出力先 | 用途 |
|---|---|---|---|---|
| **品質ゲート** | `scripts/run_simple_eval.py --mode full` | `data/eval/eval_questions.csv` | `data/eval/eval_metrics.json` | リリース判定・QUALITY_GATE照合 |
| **ルーティング検証** | `scripts/run_eval.py` | `eval/datasets/line_rag_eval_router_abcd_v1.csv` | `eval/runs/run_<timestamp>.jsonl` | 開発中のルーティング動作確認 |

## 品質ゲート系統（run_simple_eval.py）

- **いつ使う**: リリース前・大きな変更後
- **判定基準**: `docs/QUALITY_GATE.md` の閾値と照合する
- **自動テスト**: `tests/test_eval_baseline.py` が `eval_metrics.json` を読んでQUALITY_GATE必須指標を検証する

## ルーティング検証系統（run_eval.py）

- **いつ使う**: KB変更・ルーティングロジック変更後
- **判定基準**: `route_match: true` の件数・割合で判断する
- **注意**: `faq_kb.csv` を変更した場合は **必ず先に `python3 scripts/reindex_vector_db.py` を実行する**

## ファイル一覧

| ファイル | 説明 |
|---|---|
| `eval_questions.csv` | 品質ゲート用の評価質問（17件） |
| `eval_results.jsonl` | run_simple_eval.py の問ごとの詳細結果 |
| `eval_metrics.json` | run_simple_eval.py の集計メトリクス（QUALITY_GATE照合用） |
| `forecast_log.md` | 精度改善施策の予測精度記録（Brier Score） |

## 関連ドキュメント

- `docs/QUALITY_GATE.md` — Ship/No Ship の閾値定義
- `docs/eval.md` — eval設計の詳細
- `skills/rental_rag/eval_review_skill/SKILL.md` — eval結果の解釈手順
- `skills/rental_rag/forecast_review_skill/SKILL.md` — 予測採点手順
