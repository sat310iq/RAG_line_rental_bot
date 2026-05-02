# GCP PoC の停止・再開・課金確認

LINE Webhook / Worker（Cloud Run）と Pub/Sub を使う本 PoC向けの**運用手順**です。**誤削除防止**・**冪等性**・**ローカル状態ファイル**（`.state/gcp_poc_state.json`）で再実行安全性を高めています。

**課金の主因がイメージストレージのとき**は、Run を消さずに **GCR/AR を最新 N 件だけ残して整理**する **[GCP_SUSPEND_AND_IMAGE_TRIM.md](GCP_SUSPEND_AND_IMAGE_TRIM.md)**（`deploy/suspend_and_trim_images.sh`）も参照してください。

**Billing Reports の記録・判定用**は **[GCP_BILLING_CHECK_TEMPLATE.md](GCP_BILLING_CHECK_TEMPLATE.md)**（コピペ用チェックシートと判定ルール）。

## 対象リソース（代表）

| 種別 | 名前（デフォルト） |
|------|-------------------|
| Cloud Run | `line-webhook`, `line-worker` |
| Pub/Sub | topic `rag-line-events`, subscription `rag-line-events-sub`（`deploy/.env.gcp` で変更可） |
| コンテナ | `gcr.io/<PROJECT_ID>/line-webhook`, `line-worker` |
| Artifact Registry | 同一リージョン内の各リポジトリに `line-webhook` / `line-worker` パッケージがある場合 |

追加で**確認のみ**推奨: Cloud Build 成果物、GCS、Logging、他サービス（Vertex AI 等）。

## 環境変数（`deploy/.env.gcp`）

- `GCP_PROJECT_ID`（必須）
- `GCP_REGION`（省略時 `asia-northeast1`）
- `PUBSUB_TOPIC_NAME`（省略時 `rag-line-events`）
- `PUBSUB_SUBSCRIPTION_NAME`（省略時 `rag-line-events-sub`）

Cloud Run 実行時の `OPENAI_API_KEY` 等は**コンソールまたは** `gcloud run services update` で設定（従来どおり）。

## 誤操作防止（必読）

- **`deploy/.env.gcp` の `GCP_PROJECT_ID` と `gcloud config get-value project` が一致しない場合、スクリプトは即終了**します。
- プロジェクト ID に `prod` / `production` が含まれる場合は**追加警告**し、`--yes` なしでは**プロジェクト ID の手入力確認**が必要です。
- `stop_poc.sh` / `resume_poc.sh` は **`.state/gcp_poc.lock` ディレクトリによる簡易ロック**で同時実行を避けます。
- **請求アカウントのリンク解除・プロジェクト削除**は破壊的なため**スクリプトでは自動化していません**。手順は本書末を参照。

## 停止レベル A（suspend・再開しやすい）

- Cloud Run: **min-instances=0** に更新（サービスは残る）。
- Pub/Sub: **subscription → topic** の順で削除（**存在しなければ skip**）。
- イメージ: 既定では**削除しない**。`--delete-images` で GCR（と AR パッケージ）も削除可能。

**推奨順序（手動でも同じ）**

1. プロジェクト一致確認（`deploy/check_gcp_resources.sh`）
2. `deploy/stop_poc.sh --mode=suspend`
3. LINE Developers で Webhook を無効化（任意だが推奨）
4. 残存リソース・請求レポート確認

## 停止レベル B（delete・ほぼ完全撤去）

- Pub/Sub: subscription → topic（冪等）。
- Cloud Run: `line-webhook` / `line-worker` 削除（冪等）。
- GCR: `--delete-images` で PoC イメージを削除。
- Artifact Registry: **`--delete-artifacts`** のときのみ、`line-webhook` / `line-worker` パッケージを各リポジトリから削除。

その後、コンソールで Cloud Build / GCS / ログを確認してください。

## ローカル状態ファイル（Decision OS 向け）

`rental_rag_poc/.state/gcp_poc_state.json`（Git 対象外）に、直近の観測と意思決定メタデータを格納します。

例（イメージ）:

```json
{
  "version": 1,
  "status": "suspended",
  "cloud_run_webhook": "min0",
  "cloud_run_worker": "min0",
  "pubsub": "deleted",
  "images_gcr": "exists",
  "images_artifact": "unknown",
  "worker_url": "https://line-worker-....a.run.app",
  "last_updated": "2026-03-31T12:00:00+00:00",
  "last_operation": {
    "decision": "stop_gcp_poc",
    "reason": "unexpected billing",
    "mode": "suspend",
    "expected_outcome": "Cloud Run min-instances=0; Pub/Sub removed; ...",
    "timestamp": "2026-03-31T12:00:00+00:00"
  }
}
```

- **`last_operation` は処理が最後まで成功した後に記録**されます（途中で `set -e` により失敗した場合はその時点で終了し、古いエントリのままになることがあります）。

## CLI 例

```bash
# 一覧（削除なし）
bash deploy/check_gcp_resources.sh

bash deploy/stop_poc.sh --mode=suspend --dry-run
bash deploy/stop_poc.sh --mode=suspend --yes
bash deploy/stop_poc.sh --mode=suspend --delete-images --yes \
  --reason="cost control until next sprint"

bash deploy/stop_poc.sh --mode=delete --delete-images --delete-artifacts --yes \
  --reason="tear down test project"
```

再開（**Worker → Pub/Sub → Webhook** の順。`deploy_all.sh` とは異なります）:

```bash
bash deploy/resume_poc.sh
```

## 再開手順（詳細）

1. `deploy/.env.gcp` と `gcloud config set project` を一致させる。
2. `data/vector_store` を用意（`python3 scripts/reindex_vector_db.py`）。
3. `bash deploy/resume_poc.sh`（内部で `deploy_worker.sh` → `setup_pubsub.sh <Worker URL>` → `deploy_webhook.sh`）。
4. Cloud Run の環境変数（OPENAI、LINE、`PUBSUB_TOPIC_NAME` 等）が揃っているか確認。
5. LINE Developers で Webhook URL を `https://<line-webhook-url>/webhook` に設定。
6. `curl` / 実メッセージで疎通確認。

**注意**: 既に Pub/Sub subscription だけが残っている場合、`setup_pubsub.sh` の `create` がスキップされることがあります。プッシュ先を変える場合は:

`gcloud pubsub subscriptions update rag-line-events-sub --push-endpoint="$WORKER_URL" --project="$GCP_PROJECT_ID"`

## 課金について

- **Cloud Run / Pub/Sub / イメージ**を止めると、主な課金は大きく減ります。
- **Logging、Cloud Build の成果物、GCS、Artifact Registry** などで微小な料金が残ることがあります。
- `gcloud billing projects describe $PROJECT_ID` は**請求アカウント紐付けの確認**に有用ですが、**コスト内訳の代替にはなりません**。必ず **コンソールの Billing → Reports** を確認してください。
- **完全に課金を止める**最終手段は、プロジェクト削除または請求アカウントのリンク解除です（[公式手順](https://cloud.google.com/billing/docs/how-to/modify-project)）。**本リポジトリのスクリプトは実行しません。**
- **予算アラート**の設定を推奨します（Console → Billing → Budgets）。

## スクリプト役割一覧

| スクリプト | 役割 |
|------------|------|
| `deploy/check_gcp_resources.sh` | Cloud Run / Pub/Sub / GCR / AR / GCS / API の簡易一覧。削除なし。 |
| `deploy/stop_poc.sh` | `--mode=suspend` または `delete`。冪等。`--dry-run` / `--yes` / `--delete-images` / `--delete-artifacts`。 |
| `deploy/resume_poc.sh` | Worker デプロイ → Pub/Sub → Webhook デプロイ。状態ファイルに `worker_url` を保存。 |
| `deploy/lib/gcp_poc_common.sh` | 共有関数（状態・ロック・冪等 gcloud）。 |

## suspend と delete の違い

| | suspend | delete |
|---|---------|--------|
| Cloud Run | 残す（min-instances=0） | サービス削除 |
| Pub/Sub | 削除 | 削除 |
| GCR イメージ | 既定は残す（`--delete-images` で削除） | 同上 + delete 後にイメージ掃除しやすい |
| 再開 | `resume_poc.sh` で短時間 | イメージが無い場合はフルビルドが必要 |

## トラブルシュート

- **`trap ERR`**: スクリプトは途中失敗時に行番号を表示します。
- **ロック残り**: 異常終了で `.state/gcp_poc.lock` が残った場合、`rmdir .state/gcp_poc.lock`（中身が空であることを確認）で解除できます。
- **権限**: `gcloud billing projects describe` が失敗しても、リソース削除は別権限で続けられることがあります。
