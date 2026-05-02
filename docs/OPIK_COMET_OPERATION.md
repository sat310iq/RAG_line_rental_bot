# OPIK / Comet 運用の分離

## 方針

- **オフライン eval**（`run_simple_eval.py`）と **本番チャット**のトレースを混在させない。
- 比較しやすいよう **タグと metadata** に `trace_kind` / `eval_mode` / `run_id` / `git_commit` を載せる。

## 環境変数

| 変数 | 説明 |
|------|------|
| `ENABLE_COMET_LOGGING` | eval 実行時の Comet/OPIK 送信（既定 false） |
| `ENABLE_CHAT_OPIK_LOGGING` | チャット経路のログ（既定 true の場合あり） |
| `OPIK_TRACE_KIND` | 任意。`offline_eval` / `production_chat` など手動ラベル |

## 自動タグ

- eval 結果に `_eval_meta` がある場合、`eval_mode`（`full` / `smoke`）が **`trace:<mode>`** 相当の区分に使われる。
- Comet の `log_text` metadata に `trace_kind` を含める。

## プロジェクト分離（推奨）

- **eval 専用**: `COMET_PROJECT_NAME` にサフィックス（例: `rental-rag-poc-eval`）を付けた別プロジェクト。
- **本番監視**: 別プロジェクトまたは同一プロジェクト内で **タグフィルタ**（`trace:production_chat` のみ表示）。
- コスト・ノイズが増える場合は、本番のサンプリング率や eval の頻度を下げる。
