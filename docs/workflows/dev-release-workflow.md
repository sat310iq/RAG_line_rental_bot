# Dev Release Workflow Reference

`rental_rag_poc` の開発作業を、ローカル品質ゲートとGCP品質ゲートの両方で安定運用するための手順。

## 1) 実装とローカル検証

```bash
cd "/Users/skoyama/Project/RAG_20260116/Assignment 3 - Solutions/rental_rag_poc"
python3 -m pytest -q tests
```

- まずローカルで全体テストを通す。
- 失敗時は修正後に再実行し、成功するまで次へ進まない。

## 2) 変更確認とコミット

```bash
git status
git diff --stat
git add <必要なファイルのみ>
git commit -m "fix: <意図がわかる要約>"
```

- 生成物や機密情報（`.env` など）はコミットしない。
- コミットは小さく、変更意図を分ける。

## 3) GCPテスト（デプロイ前ゲート）

```bash
gcloud builds submit . --config=deploy/cloudbuild_test.yaml
```

- 成功条件: Cloud Build が `SUCCESS`、`python3 -m pytest -q tests` が完走。
- 失敗時: Cloud Buildログの failing test を修正し、再実行。

## 4) 必要時のみデプロイ

テスト成功後にのみデプロイ実施。デプロイ用途は既存の定義を使う。

- `deploy/cloudbuild_webhook.yaml`（Docker build）
- 既存の deploy スクリプト群（`deploy/` 配下）

## 5) GCP受け入れ確認

最低限の確認ポイント:

- Cloud Buildの最終ステータス
- Cloud Runの `/health` と `/ready`
- `docs/testing/LINE_TEST_CHECKLIST.md` のブロッカー項目（D / F-04 / E-03）

## 6) 記録・エスカレーション

- 結果は `docs/eval_log.md` に反映する。
- 法的断定や運用ブロッカーは `LINE_TEST_CHECKLIST.md` のEscalationトリガーを優先する。
