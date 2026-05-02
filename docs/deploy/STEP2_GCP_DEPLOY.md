# Step 2: GCP 最小セットアップと Cloud Run 初回デプロイ

**前提**: [Step 1](STEP1_CONTAINERIZE.md) 完了（`Dockerfile`、`/health`、`RAG_SKIP_STARTUP_CHECKS`、エントリ `src.api.main:app`）。

**デプロイ計画・現状課題の要約（外部 AI 向け）**: [GCP_DEPLOY_PLAN_AND_ISSUES.md](GCP_DEPLOY_PLAN_AND_ISSUES.md)

**ローカルと Cloud で応答が違う / 遅いとき**: [TROUBLESHOOT_LOCAL_VS_CLOUD.md](TROUBLESHOOT_LOCAL_VS_CLOUD.md)

**このドキュメントの範囲**: Artifact Registry、Secret Manager、Cloud Run の**最小構成**と初回疎通。**GitHub Actions / Cloud Build、カスタムドメイン、Cloud Scheduler、本格監視、複数環境分離は含まない**。

**レジストリ**: Container Registry（`gcr.io` への書き込みは廃止方向）ではなく **Artifact Registry** を使う（[標準リポジトリの作成](https://cloud.google.com/artifact-registry/docs/repositories/create-repos)）。

**リージョン**: **Artifact Registry と Cloud Run は同一リージョン**に揃える（別リージョンだと pull 失敗・遅延・構成ミスの原因になりやすい）。

**課金**: プロジェクトに **課金アカウントがリンク**されている必要がある。未設定のままだと `gcloud services enable` が `Billing account ... is not open` / `UREQ_PROJECT_BILLING_NOT_OPEN` で失敗する。[コンソールで課金を有効化](https://console.cloud.google.com/billing)してから Part 1 を再実行する。

---

## 目的

Step 1 で container-ready にした RAG PoC を、最小構成で **Google Cloud Run に初回デプロイ**し、疎通を確認する。

---

## Step 2 のゴール（完了条件）

1. Artifact Registry に Docker リポジトリがある
2. Secret Manager に最低限のシークレットがある（例: `openai-api-key`）
3. Cloud Run サービスが 1 つ動く
4. `GET /health` が **200** を返す
5. `GET /ready` の挙動を確認できる
6. 代表的な 1〜2 問で API 疎通を確認できる（例: `POST /debug/rag` が有効な場合）

### 実行順のまとめ

1. Part 1: API 有効化  
2. Part 2: Artifact Registry 作成  
3. Part 3: `docker build` → `tag` → `push`  
4. Part 4: Secret 新規作成、または既存なら `versions add`  
5. Part 5: `gcloud run deploy`  
6. Part 6: `/health` → `/ready` → 代表質問（必要なら `/debug/rag`）  
7. **デプロイ後は必ず** [GCP_DEPLOY_PLAN_AND_ISSUES.md §7.8](GCP_DEPLOY_PLAN_AND_ISSUES.md) **チェックリストを実行**（最短: `GET /ready` → 200、LINE「ガス」、ログに `kb_fast_path_hit` または `kb_fast_path_clarification`）

---

## 推奨変数（例）

| 変数 | 例 | 説明 |
|------|-----|------|
| `PROJECT_ID` | （`gcloud config get-value project`） | GCP プロジェクト ID |
| `REGION` | `asia-northeast1` | Tokyo。Artifact Registry と Cloud Run を**同じリージョン**に揃える |
| `REPOSITORY` | `rental-rag-poc` | Artifact Registry のリポジトリ名 |
| `SERVICE` | `rental-rag-poc` | Cloud Run サービス名 |

イメージ URL の形式:

`REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/IMAGE:TAG`

例: `asia-northeast1-docker.pkg.dev/my-project/rental-rag-poc/rental-rag-poc:initial`

**イメージタグ**: 手順では `initial` を使ってよい。運用で追跡しやすくするなら日付やセマンバージョンも可（例: `20260411-1`、`v0.1.0`）。以降の `docker tag` / `gcloud run deploy --image=...` は同じタグに合わせる。

Cloud Run はデプロイ時に**イメージ digest を revision に固定**するが、運用上はレジストリ側で **`latest` タグだけに頼らず**、`YYYYMMDD-N` など**意味のある固定タグ**で push・`--image=...:そのタグ` でデプロイすると、どのビルドか追跡しやすい。

---

## Part 1: GCP API の有効化

**前提**: 上記「課金」が済んでいること。

次の API を有効にする。

- Cloud Run Admin API
- Artifact Registry API
- Secret Manager API

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

**Done**: 以降の `gcloud` コマンドが権限・課金の範囲で通る。

---

## Part 2: Artifact Registry 作成

Docker 形式のリポジトリをリージョンに 1 つ作成する（[ドキュメント](https://cloud.google.com/artifact-registry/docs/repositories/create-repos)）。

```bash
export PROJECT_ID=$(gcloud config get-value project)
export REGION=asia-northeast1
export REPOSITORY=rental-rag-poc

gcloud artifacts repositories create "${REPOSITORY}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="RAG PoC container images"
```

**Done**: プッシュ先として `${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}` が利用可能。

---

## Part 3: Docker 認証・ビルド・Push

Artifact Registry へ push する前に [Docker 認証を設定](https://cloud.google.com/artifact-registry/docs/docker/authentication)する。

```bash
gcloud auth configure-docker "${REGION}-docker.pkg.dev"
```

ビルドとタグ、プッシュ（**プロジェクトルート＝リポジトリ内の `rental_rag_poc` ディレクトリ**。`Dockerfile` がある階層）。

**カレントディレクトリの注意**: すでに `.../rental_rag_poc` にいる状態で **`cd rental_rag_poc` と打つと失敗する**（その下に同名フォルダはない）。初回だけ親から移動するか、`pwd` で場所を確認してから `docker build` する。

**Cloud Run は `linux/amd64` 向けイメージが必要**（[ランタイム](https://cloud.google.com/run/docs/container-contract)）。**Apple Silicon（M1/M2/M3）の Mac** でそのまま `docker build` すると ARM 用マニフェストになり、`must support amd64/linux` でデプロイが失敗することがある。その場合は **`--platform linux/amd64`** を付けて再ビルド・再 push する。

```bash
docker build --platform linux/amd64 -t rental-rag-poc:local .

docker tag rental-rag-poc:local \
  "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/rental-rag-poc:initial"

docker push \
  "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/rental-rag-poc:initial"
```

（上記は **`rental_rag_poc` をカレントにしたターミナル**で実行する。別の場所にいる場合は、先にそのディレクトリへ `cd` する。）

**コピペの注意**: 説明文の **`#` で始まる行はシェルのコメント**として貼るのは問題ないが、**プレースホルダだけの行**（例: `# ... tag と push ...`）をそのまま実行すると、環境によっては `command not found: #` になる。続きの **`gcloud run deploy`** は Part 5 のコマンドをそのまま使う。

別タグで push する場合は、`docker tag` の行と `docker push` の末尾を同じタグに揃える（上記「推奨変数」のタグ例参照）。

**Done**: Artifact Registry に `rental-rag-poc:initial`（または指定タグ）が存在する。

---

## Part 4: Secret Manager 登録

機密値は **Secret Manager** に置き、Cloud Run では **環境変数へマウント**する（[シークレットの作成](https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets)）。**`gcloud run deploy --set-env-vars` に API キーを直書きしない。**

**既に同名の secret がある場合**: `gcloud secrets create` は失敗する。下記の **`versions add`** で新バージョンを追加する（初回のみ `create`）。

初回の最小例:

| Secret 名（例） | マッピング先 env |
|-----------------|------------------|
| `openai-api-key` | `OPENAI_API_KEY` |

将来追加しうるもの: `line-channel-secret`、`line-channel-access-token`、`comet-api-key` など。

新規作成:

```bash
printf '%s' "${OPENAI_API_KEY}" | \
  gcloud secrets create openai-api-key --data-file=-
```

既存シークレットに新バージョン:

```bash
printf '%s' "${OPENAI_API_KEY}" | \
  gcloud secrets versions add openai-api-key --data-file=-
```

**Done**: `openai-api-key` がプロジェクトに存在する。

**ローテーション（将来）**: 値を更新するときは `gcloud secrets versions add` で新バージョンを追加する。Cloud Run で `OPENAI_API_KEY=openai-api-key:latest` のように **`:latest`** を参照している場合、新しいバージョンが**次のインスタンス起動などで**取り込まれる（挙動を確実にしたいときは revision を再デプロイしてもよい）。

---

## Part 5: Cloud Run 初回デプロイ

[コンテナを Cloud Run にデプロイ](https://cloud.google.com/run/docs/quickstarts/deploy-container)する。イメージは Part 3 で push したものを指定する。

**初期方針（初回疎通優先）**

- `min-instances=0`（デフォルトで可）
- 認証: まずは `--allow-unauthenticated` でもよい（外部公開を狭めたい場合は後で IAM を変更）
- 初回は **`RAG_SKIP_STARTUP_CHECKS=true`** でプロセス起動を優先（[Step 1](STEP1_CONTAINERIZE.md) の lightweight 起動）
- **`OPENAI_API_KEY`** は Secret から注入
- **`PORT`** は Cloud Run が注入するため、通常は明示不要

Cloud Run の**実行サービスアカウント**が Secret を読むには **Secret Manager Secret Accessor**（`roles/secretmanager.secretAccessor`）が必要。`--set-secrets` 利用時はプロジェクト設定によって実行 SA への参照が自動で付くこともあるが、**Permission denied** になる場合は下記「Secret 参照の権限エラー時」を実施する。

```bash
export SERVICE=rental-rag-poc

gcloud run deploy "${SERVICE}" \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/rental-rag-poc:initial" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars=RAG_SKIP_STARTUP_CHECKS=true \
  --set-secrets=OPENAI_API_KEY=openai-api-key:latest
```

**LINE Webhook 向けの推奨（安定性優先）**: 同一インスタンスで複数リクエストが重なると埋め込みモデル・RAG でメモリが逼迫しやすい。`--concurrency=1` を付けると **1 コンテナあたり同時処理が 1 件**になり、OOM や返信欠落のリスクを下げやすい（スループットはインスタンス数でスケール）。

```bash
# 上記 gcloud run deploy に追加する例
#   --concurrency=1
```

**Done**: デプロイ完了後、Cloud Run の **URL** が表示される（コンソールでも確認可）。**初回 deploy URL** をこのドキュメントの運用メモや社内 Wiki に記録してよい。

### Secret 参照の権限エラー時（どの SA に付けるか）

1. サービスが使う**実行サービスアカウント**を確認する（空なら多くの場合、プロジェクトのデフォルト Compute 用 SA `PROJECT_NUMBER-compute@developer.gserviceaccount.com` が使われる）。

```bash
gcloud run services describe "${SERVICE}" --region="${REGION}" \
  --format='value(spec.template.spec.serviceAccountName)'
```

2. 表示されたメール（または `--service-account` で指定した SA）に、シークレット `openai-api-key` への **Accessor** を付与する。

```bash
gcloud secrets add-iam-policy-binding openai-api-key \
  --member="serviceAccount:<SERVICE_ACCOUNT_EMAIL>" \
  --role="roles/secretmanager.secretAccessor"
```

3. 必要に応じて新しい revision をデプロイする（例: 同じ `gcloud run deploy` を再実行）。

---

## Part 6: 初回疎通確認

デプロイ後に表示される **HTTPS ベース URL**（例: `https://rental-rag-poc-xxxxx-an.a.run.app`）に対して確認する。

### 1. `/health`

```bash
curl -s -o /dev/null -w "%{http_code}" "https://<cloud-run-url>/health"
curl -s "https://<cloud-run-url>/health"
```

期待: HTTP **200**、JSON に `"status":"ok"` 付近。

### 2. `/ready`

```bash
curl -s -w "\n%{http_code}\n" "https://<cloud-run-url>/ready"
```

`RAG_SKIP_STARTUP_CHECKS=true` のときも **lifespan は vector チェックをスキップ**するが、`/ready` 内の [`readiness_status`](../../src/startup_check.py) は **ベクターストア・Chroma 等を検証**する。イメージに `data/vector_store` が同梱されていれば **200**、不足があれば **503** になり得る。**現状の応答コードと本文を記録**する。

### 3. 代表的な 1〜2 問での API 疎通

LINE の `POST /webhook` は署名検証があるため、手早く試すなら **開発用**に `ENABLE_DEBUG_RAG_ENDPOINT=true` を付与した revision で **`POST /debug/rag`** を使う（本番では無効推奨）。

例（鍵紛失・水道料金など短い質問）:

```bash
curl -s -X POST "https://<cloud-run-url>/debug/rag" \
  -H "Content-Type: application/json" \
  -d '{"question":"鍵を紛失した場合の対応を教えて"}'
```

**Done**: `/health` が安定し、必要なら `/debug/rag` または別経路で 1〜2 問の応答が返ることを確認する。

### デプロイ後は必ず実行（チェックリスト）

**デプロイ直後は [GCP_DEPLOY_PLAN_AND_ISSUES.md の §7.8](GCP_DEPLOY_PLAN_AND_ISSUES.md) を必ず実行する**（生存確認・fast path・deal ログ・遅延切り分けの正本）。

**最短確認（まずこれだけ）**: `GET /ready` → **200** → LINE で **「ガス」** を送る → Cloud Logging で **`kb_fast_path_hit`** または **`kb_fast_path_clarification`**。代表 10 件・KPI 目安・`Vector store initialized: deal=`（**deal > 0**）は §7.8 本文に従う。

---

## 簡易トラブルシュート

| 症状 | 確認すること |
|------|----------------|
| **`gcloud run deploy` が `must support amd64/linux` で失敗** | Mac ARM でビルドしたイメージの可能性。**`docker build --platform linux/amd64`** で作り直し、**同じタグで `push` してから**再デプロイ（Part 3 参照） |
| `/health` が **200 以外** | Cloud Run の **ログ**（起動失敗、Python の import エラー、`PORT` 未 listen 等）。[ログの表示](https://cloud.google.com/run/docs/logging) |
| `/ready` が **503** | `RAG_SKIP_STARTUP_CHECKS=true` でも **`/ready` は深いチェック**のまま。イメージに **`data/vector_store`** と manifest / BM25 が含まれているか、[Step 1](STEP1_CONTAINERIZE.md) のデータ同梱方針を確認 |
| **Secret 参照エラー**（起動時・リクエスト時） | 実行サービスアカウントに **`roles/secretmanager.secretAccessor`**（Part 5 の「Secret 参照の権限エラー時」） |
| **`The user-provided container failed to start and listen on the port ... PORT=8080`**（デプロイは失敗） | 起動までに時間がかかりすぎている、または起動直後にクラッシュしている。**ログ**で import エラー・OOM を確認。アプリ側で **`src/interfaces/line/main.py` がモジュール読み込み時に重い処理をしない**（lazy import）ようになっているか確認し、**`docker build --platform linux/amd64` でイメージを再ビルド・再 push してから**再デプロイ。必要なら **メモリ/CPU を増やす**、または **`--cpu-boost`**（利用可能なら）で起動時の CPU を上げる |

### Cloud Run ログの確認（詰まったらまずここ）

変数は Part 2〜5 と同じ（例: `SERVICE=rental-rag-poc`, `REGION=asia-northeast1`）。

**CLI（推奨・直近のコンテナログ）**

```bash
export SERVICE=rental-rag-poc
export REGION=asia-northeast1

gcloud run services logs read "${SERVICE}" --region="${REGION}" --limit=80
```

**ストリームで追う（デプロイ直後の起動失敗の調査向け）**

```bash
gcloud run services logs tail "${SERVICE}" --region="${REGION}"
```

（`logs tail` が無い古い gcloud の場合は [Logging コンソール](https://console.cloud.google.com/logs) で `resource.type="cloud_run_revision"` とサービス名で絞る。）

**プロジェクトを切り替える**

```bash
gcloud config get-value project
gcloud projects list
gcloud config set project YOUR_PROJECT_ID
```

`Permission denied` や `Project not found` のときは、**正しいプロジェクト ID** と **課金・IAM が付いたアカウント**で `gcloud auth login` 済みか確認する。

---

## Part 7: デプロイ後の最小調整（本番寄り）

- **`RAG_SKIP_STARTUP_CHECKS`**: 初回は `true` でよい。本番に寄せる場合は `false` に変更して再デプロイし、起動時に `run_startup_checks` が通ることを確認する。
- **環境変数一覧**と **使用イメージタグ**を記録する。
- 不要なら **`--allow-unauthenticated` をやめ**、認証付きアクセスに切り替える（Step 3 以降で詳細化可）。

---

## 参考リンク（Google Cloud）

- [Artifact Registry: リポジトリ作成](https://cloud.google.com/artifact-registry/docs/repositories/create-repos)
- [Artifact Registry: Docker 認証](https://cloud.google.com/artifact-registry/docs/docker/authentication)
- [Secret Manager: シークレットの作成とアクセス](https://cloud.google.com/secret-manager/docs/creating-and-accessing-secrets)
- [Cloud Run: クイックスタート（コンテナのデプロイ）](https://cloud.google.com/run/docs/quickstarts/deploy-container)
- [Cloud Run: コンテナ ランタイム契約（`PORT` / `0.0.0.0`）](https://cloud.google.com/run/docs/container-contract)

---

## Step 3 予告

- `RAG_SKIP_STARTUP_CHECKS=false` を前提とした strict 運用
- Cloud Run の認証制限
- Cloud Scheduler によるスモーク
- CI/CD（Cloud Build または GitHub Actions）
- ログ・アラートの最小設定
