# GCP PoC Option 1: suspend + イメージ整理

LINE Webhook PoC の**課金をほぼゼロに近づけつつ、再開しやすさを残す**ためのスクリプトです。Cloud Run は**削除せず**（存在すれば `min-instances=0` のみ）、**Pub/Sub の整理**と **GCR / Artifact Registry の古いイメージ削除**をオプションで行います。

## 目的

- Cloud Run の**実行課金を抑える**（常時インスタンスがあれば 0 に）
- **Pub/Sub** の PoC 由来リソースを削減
- **コンテナイメージストレージ**（多くの場合、PoC の主な残課金要因）を **最新 N 件だけ残して整理**
- `deploy/.env.gcp` の `GCP_PROJECT_ID` と `gcloud config` の**一致必須**で**別プロジェクト誤操作を防止**

## 対象スクリプト

[`deploy/suspend_and_trim_images.sh`](../deploy/suspend_and_trim_images.sh)

## 実行前チェック

1. `cp deploy/.env.gcp.example deploy/.env.gcp`（未作成なら）し **`GCP_PROJECT_ID` を正しく設定**
2. `gcloud config set project <同上の PROJECT_ID>`
3. 必要なら `export CLOUDSDK_PYTHON=/usr/bin/python3`（gcloud が Python 3.12 を要求して失敗する環境向け）
4. **本番っぽい project id**（`prod` / `production` を含む）では追加警告と確認あり

## Pub/Sub の削除対象

`--delete-pubsub` 時、**まず** `deploy/.env.gcp` の **`PUBSUB_TOPIC_NAME`** / **`PUBSUB_SUBSCRIPTION_NAME`**（`setup_pubsub.sh` と同じキー）が設定されていればその短名を候補に含めます。続けて次の**既定フォールバック**をマージします（重複は除く）。

**トピック短名のフォールバック:** `rag-line-events`, `line-events`, `line-events-dlq`

**サブスクリプション短名のフォールバック:** `rag-line-events-sub`

**サブスクリプション**は、名前が候補に一致するか、**バインド先トピックの短名が候補トピックのいずれか**なら、**subscription → topic** の順で削除対象です。

上記以外の名前だけを確実に消したい場合は、`.env.gcp` で `PUBSUB_*` を合わせるか、スクリプト内のフォールバック一覧を編集してください。

## Artifact Registry の対象判定（1 行ルール）

**リージョン内の Artifact Registry リポジトリのうち、リソース短名に文字列 `cloud-run-source` を含むものだけ**をイメージ列挙・トリムの対象にします（例: `cloud-run-source-deploy`）。別名のリポジトリは触りません。

## keep-latest の意味

- **GCR**（`gcr.io/$PROJECT/line-webhook` と `line-worker`）: `gcloud container images list-tags` の **timestamp が新しい順**に並べ、**先頭 N 件の digest を残し、それより古い digest を削除**
- **Artifact Registry**: 上記ルールで選んだリポジトリのみ。**package（イメージ）ごと**に更新時刻で並べ、**各 package で新しい N 件のバージョンだけ残し、古い参照を削除**（リポジトリ自体は削除しません）

N は **`--keep-latest`**（デフォルト **3**）。

## 実装上の注意（シェル／stdin）

Artifact Registry のトリムでは、`gcloud` の一覧出力を Python で並べ替え・分類します。このとき次の落とし穴を避ける実装にしています。

- **パイプとヒアドキュメントの併用**: `printf … | python3 <<'PY'` のようにすると、ヒアドキュメントが **標準入力を占有**するため、パイプから渡した CSV が Python に届きません。結果として削除候補が空になることがあります。**CSV は一時ファイルに書き、環境変数でパスを渡して読む**形が安全です。
- **`gcloud` の終了コード**: 一覧取得が成功しても、CLI 側の Python 警告などで **非ゼロ exit** になり得ます。stdout に取りたい出力がある場合は、**終了コードだけで処理を捨てない**必要があります。
- 環境によっては **`importlib.metadata` 関連のメッセージ**が `gcloud` の stderr に出ます。`export CLOUDSDK_PYTHON=/usr/bin/python3` で抑えられる場合があります（上の「実行前チェック」を参照）。

## dry-run 例

```bash
bash deploy/suspend_and_trim_images.sh --dry-run \
  --delete-pubsub --delete-gcr-images --delete-ar-images --keep-latest 3
```

（`--delete-pubsub` などはこの形式で指定します。余計な単語を入れないでください。）

実際の削除・更新は行いません。`[dry-run] would run:` でコマンドを表示します。

## 実施前の最終確認（本番 3 点）

1. `gcloud config get-value project` が**本当に対象プロジェクト**か（`.env.gcp` の `GCP_PROJECT_ID` と一致していること）
2. **`--dry-run`** で GCR / AR の**削除対象が想定通り**か
3. **`--keep-latest 3`** で残したい最新イメージが **KEEP 側**に含まれるか（出力の `KEEP:` / `# trim` 行を確認）

推奨の流れ: dry-run → 出力確認 → `--yes` 付きで実行 → **翌日** Billing Reports で SKU を確認。

## 実行例

確認後:

```bash
bash deploy/suspend_and_trim_images.sh --yes \
  --delete-pubsub --delete-gcr-images --delete-ar-images --keep-latest 3
```

Pub/Sub だけ触りたい場合:

```bash
bash deploy/suspend_and_trim_images.sh --yes --delete-pubsub
```

## 再開時に必要なこと

- **イメージを削った**場合、次回は **`deploy/resume_poc.sh` や `deploy_webhook.sh` / `deploy_worker.sh` で再ビルド・再デプロイ**が必要です。
- **`--delete-pubsub` でトピックを消した**場合、**`setup_pubsub.sh` 等でトピック・サブスクリプションの再作成**が必要です（Worker URL に合わせたプッシュ設定など）。
- **完全な 0 円を保証するものではありません**。ログ、GCS、他 SKU の**微小課金**は **Billing → Reports** で確認してください。
- **課金の見方・コピペ用テンプレート:** [GCP_BILLING_CHECK_TEMPLATE.md](GCP_BILLING_CHECK_TEMPLATE.md)

## 関連ドキュメント

- 停止レベル全体: [GCP_SUSPEND_AND_RESUME.md](GCP_SUSPEND_AND_RESUME.md)
- 課金確認テンプレート（Option 1 後）: [GCP_BILLING_CHECK_TEMPLATE.md](GCP_BILLING_CHECK_TEMPLATE.md)
- デプロイ: [deploy/README.md](../deploy/README.md)
