# Runbook: ローカルと本番の挙動差・RAG 障害

## 1. 起動ログの config summary

- Cloud Run / ローカル Docker のログで `CONFIG_SUMMARY` 行を検索。
- **Python バージョン**、**retrieval K**、**threshold**、**モデル名**、**manifest** が同一か比較する。

## 2. 環境変数差分

- [LOCAL_VS_CLOUDRUN.md](LOCAL_VS_CLOUDRUN.md) の表に照らし、`CSV_SCORE_THRESHOLD`（0.40）、`RAG_RETRIEVAL_K`（16）等が本番で上書きされていないか確認。

## 3. manifest 差分

- `data/vector_store/manifest.json` の `kb_sha256`、`built_at`、`git_commit`。
- 本番イメージに焼いた KB と **再インデックス時点の KB** が一致しているか（`preflight_check.py` がローカルで検知）。

## 4. データの存在

- イメージ内の `vector_store` が空でないか。
- デプロイ直後ログで Chroma 件数や起動エラーがないか。

## 5. 外部 API

- OpenAI 429 / 5xx、レート制限、キー無効。

## 6. リソース

- Cloud Run のメモリ・CPU・リクエストタイムアウト、同時実行数。
- cold start による LINE reply token 失効（ログに関連メッセージが出る場合あり）。

## 7. スモーク

- `GET /health` / `GET /ready`。
- 許可される場合のみ `ENABLE_DEBUG_RAG_ENDPOINT=true` で `POST /debug/rag`（本番公開時は認証・ネットワーク制限とセットで検討）。
