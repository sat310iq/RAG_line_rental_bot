# テスト層の整理（pytest / smoke eval / full eval）

## pytest

- **目的**: 高速・安定した回帰。分岐、閾値、フォールバック、CSV キーワード優先など、**LLM 出力に依存しにくい**挙動を担保する。
- **実行**: `pytest`（プロジェクトルート、venv 有効化後）。
- **推奨タイミング**: PR ごと、またはコミット前。

## smoke eval（固定少数）

- **目的**: エンドツーエンドで **毎回同じ**質問セットを通し、重大な退行を早く見つける。
- **入力**: `data/eval/smoke_eval_questions.csv`
- **実行**: `python scripts/run_simple_eval.py --mode smoke`
- **推奨タイミング**: PR 前、Docker ローカル起動後、軽量確認。

## full eval（全件）

- **目的**: リリース品質判断。`eval_questions.csv` 全件と Metrics v2 集計。
- **実行**: `python scripts/run_simple_eval.py` または `--mode full`
- **推奨タイミング**: リリース前、`data/faq_kb.csv` や RAG ロジックの変更直後。

## 併用ルール

1. **full と smoke を混同しない**（既定は full。短縮評価は必ず `--mode smoke`）。
2. オフライン評価結果は `_eval_meta` / `eval_run` で **manifest・git・mode** を追跡する。
3. Ship 判定は [QUALITY_GATE.md](QUALITY_GATE.md) を参照。
