---
name: eval_review_skill
description: >
  RAG・ルーティングの評価設計、メトリクス、レポート解釈、実装レビュー時の品質ゲート。
  PoC の eval ドキュメントとテスト階層に沿って確認する。
triggers:
  - eval
  - 評価
  - KPI
  - routing
  - OPIK
  - 品質ゲート
---

# Eval & review

## When to use

- `eval/datasets` やレポートを読む・追加する前
- 「routing-first」「contract QA の evidence」の変更が品質に与える影響をレビューするとき

## Procedure

1. [`docs/QUALITY_GATE.md`](../../../../docs/QUALITY_GATE.md) と [`docs/eval.md`](../../../../docs/eval.md) を確認。
2. 変更種別に応じて pytest 範囲を [`docs/TESTING_LAYERS.md`](../../../../docs/TESTING_LAYERS.md) で決める。
3. 運用ログ・OPIK は [`docs/OPIK_COMET_OPERATION.md`](../../../../docs/OPIK_COMET_OPERATION.md) を参照。
4. `eval/runs/` の最新結果を読み、`docs/QUALITY_GATE.md` の閾値を下回るケースを以下の4種に分類する。
   - **検索精度問題**: 関連チャンクが取得できていない → `resources/tuning_guide.md#retrieval`
   - **キャッシュ問題**: キャッシュ再利用判定がずれている → `resources/tuning_guide.md#cache`
   - **ルーティング問題**: FAQ/契約QA/エスカレーションの振り分けが誤っている → `resources/tuning_guide.md#routing`
   - **回答生成問題**: チャンクは正しいが回答品質が低い → `resources/tuning_guide.md#generation`
5. 分類結果に応じてチューニング対象を特定する。
   - 検索精度問題 → `src/config.py` の retrieval 系パラメータ（詳細は `resources/tuning_guide.md#retrieval`）
   - キャッシュ問題 → `src/config.py` の `cache_semantic_threshold`
   - ルーティング問題 → `src/config.py` の routing 系パラメータ / `src/contract_query_router.py`
   - 回答生成問題 → `src/rag_answerer.py` のプロンプトテンプレート
6. 変更内容を `implementation_plan_skill` で実装計画に落とす。
7. eval実行後は `forecast_review_skill` を呼び出して予測採点を実施する
8. 採点結果を `docs/eval/forecast_log.md` に記録し、次回予測タスクを更新する

## Output format

- 評価観点 / 現状メトリクス / リスク / 推奨テスト追加 / フォローアップ
- チューニング対象分類（検索精度 / キャッシュ / ルーティング / 回答生成）/ 変更候補ファイル
- 予測採点結果（Brier Score）/ 次回予測タスクの確率
