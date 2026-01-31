# チューニング結果記録

このディレクトリには、各改善ステップの評価結果を記録します。

## ファイル構成

- `baseline_metrics.json`: ベースライン評価結果
- `phase2_baseline.json`: Phase 2開始時の評価結果
- `step1.1_results.json`: Step 1.1（IDマッピング改善）の評価結果
- `step1.2_results.json`: Step 1.2（検索クエリ改善）の評価結果
- `step1.3_results.json`: Step 1.3（再インデックス）の評価結果
- `step1.4_results.json`: Step 1.4（重み調整）の評価結果
- `step2.1_results.json`: Step 2.1（プロンプト強化）の評価結果
- `step2.2_results.json`: Step 2.2（フォールバック改善）の評価結果
- `step3.1_results.json`: Step 3.1（LLM reranking）の評価結果

## 記録形式

各JSONファイルには以下の情報を含めます:

```json
{
  "step": "1.1",
  "description": "IDマッピングの検証と改善",
  "date": "2026-01-31",
  "opik_experiment": "eval_20260131_120000",
  "metrics": {
    "before": {
      "avg_recall_at_5": 0.25,
      "avg_hallucination": 0.53,
      "search_failure_rate": 0.70
    },
    "after": {
      "avg_recall_at_5": 0.35,
      "avg_hallucination": 0.50,
      "search_failure_rate": 0.50
    },
    "improvement": {
      "avg_recall_at_5": 0.10,
      "avg_hallucination": -0.03,
      "search_failure_rate": -0.20
    }
  },
  "notes": "IDマッピングの修正により、検索失敗率が20%改善"
}
```

## 使用方法

1. 各ステップの改善前に、現在のメトリクスを記録
2. 改善を実装
3. 評価スクリプトを実行: `python scripts/run_simple_eval.py`
4. OPIKで結果を確認
5. 改善前後のメトリクスを比較して記録
