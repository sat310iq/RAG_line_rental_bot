# GCP デプロイ（Cloud Run / Cloud Build）

このディレクトリは、LINE Webhook および Worker を Google Cloud Run にデプロイするための設定とスクリプトを格納しています。

## スクリプトの役割

- **deploy_webhook.sh**: LINE Webhook のビルドと Cloud Run へのデプロイを一括実行（フルデプロイ）。
- **deploy_all.sh**: Webhook → Worker → Pub/Sub の順にビルド・デプロイ・購読設定まで実行。
- **deploy_worker.sh**: Worker のみビルド・デプロイ。
- **setup_pubsub.sh**: Pub/Sub トピックと購読の設定（Worker URL を引数に指定）。
- **check_gcp_resources.sh**: PoC 関連リソースの**一覧のみ**（削除なし）。
- **stop_poc.sh**: 停止レベル A（suspend）/ B（delete）。プロジェクト一致ガード・冪等・`--dry-run` 対応。詳細は **docs/GCP_SUSPEND_AND_RESUME.md**。
- **resume_poc.sh**: **Worker → Pub/Sub → Webhook** の順で再デプロイ（再開用）。`deploy_all.sh` より Pub/Sub プッシュ先確定が容易。
- **lib/gcp_poc_common.sh**: 上記で共有するヘルパー（状態ファイル・ロック・冪等 `gcloud`）。
- **suspend_and_trim_images.sh**: Option 1 — Cloud Run を min-only にし、PoC 由来 Pub/Sub（**`.env.gcp` の `PUBSUB_*` 優先＋既定フォールバック**）と **GCR/AR を `--keep-latest N` でトリム**。AR は **リポジトリ短名に `cloud-run-source` を含むもののみ**。**docs/GCP_SUSPEND_AND_IMAGE_TRIM.md** 参照。

## Cloud Build 設定（cloudbuild_webhook.yaml）

LINE Webhook 用の Docker イメージを Cloud Build でビルドするための設定です。

**実行例**（プロジェクトルートで）:

```bash
gcloud builds submit . --config=deploy/cloudbuild_webhook.yaml --project YOUR_PROJECT_ID
```

**設定内容のサンプル**:

```yaml
# Cloud Build config for line-webhook (uses deploy/Dockerfile.webhook).
# Run from project root: gcloud builds submit . --config=deploy/cloudbuild_webhook.yaml --project PROJECT_ID
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/line-webhook', '-f', 'deploy/Dockerfile.webhook', '.']
images:
  - 'gcr.io/$PROJECT_ID/line-webhook'
```

- ビルドコンテキストはプロジェクトルート（`.`）。`Dockerfile.webhook` で `data/` を COPY するため、**ビルド前に** ローカルで `python3 scripts/reindex_vector_db.py` を実行し、`data/vector_store` を用意してください。`deploy_webhook.sh` および `scripts/deploy_webhook_build_only.sh` は、`data/vector_store` が空の場合にビルド前にエラーで止まります。

## ビルドと反映の分割

Cloud Run へのデプロイは次の 2 段階です。

1. **ビルド**: `gcloud builds submit` でイメージをビルドし、Container Registry にプッシュする（**時間がかかるのはここ**）。
2. **反映**: `gcloud run deploy` でそのイメージを Cloud Run のサービスに反映する。

### ビルドだけ実行する

- **推奨**: プロジェクトルートで `scripts/deploy_webhook_build_only.sh` を実行する。  
  `data/vector_store` の事前チェックののち、`gcloud builds submit` のみ実行します。
- 手動で実行する場合:
  ```bash
  gcloud builds submit . --config=deploy/cloudbuild_webhook.yaml --project YOUR_PROJECT_ID
  ```

### 反映だけ実行する

すでに `gcr.io/YOUR_PROJECT_ID/line-webhook` がビルド済みの場合、次のコマンドで反映のみ行えます（オプションは `deploy_webhook.sh` のデプロイ部分と同一）。

```bash
gcloud run deploy line-webhook \
  --image gcr.io/YOUR_PROJECT_ID/line-webhook \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60 \
  --project YOUR_PROJECT_ID
```

### 環境変数のみ更新する場合

コードやイメージを変えず、Cloud Run の環境変数だけ変更する場合は、イメージの再ビルド・再デプロイは不要です。

```bash
gcloud run services update line-webhook --set-env-vars "KEY=VALUE" --region asia-northeast1 --project YOUR_PROJECT_ID
```

コンソールの「変数とシークレット」から編集しても同様です。
