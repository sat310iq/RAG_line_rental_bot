# Step 1: コンテナ最小整備（Cloud Run 向け）

**目的**: GCP リソース作成やデプロイに先立ち、アプリを **stateless / container-ready** に整える。  
**範囲外（Step 2 以降）**: Artifact Registry への push、Cloud Run 初回 deploy、Secret Manager 登録、CI/CD。

## エンドポイントの意味（固定）

| パス | 役割 |
|------|------|
| `GET /health` | **Liveness**: プロセスが起動し HTTP を返せるか。ベクターストアや OpenAI は検証しない。 |
| `GET /ready` | **Readiness**: RAG 推論に必要な依存（Chroma コレクション、KB パス、manifest 等）が揃っているか。 |

Cloud Run のコンテナ契約では **`0.0.0.0`** で **`PORT` 環境変数**のポートを listen する必要がある（[Container runtime contract](https://cloud.google.com/run/docs/container-contract)）。

## エントリポイント

- **Uvicorn モジュール**: `src.api.main:app`（[`src/api/main.py`](../../src/api/main.py) は [`src.interfaces.line.main`](../../src/interfaces/line/main.py) を再エクスポート）。
- **ローカル直実行**: `python -m src.interfaces.line.main`（`PORT` 未設定時は **8080**）。

## 起動モード: `RAG_SKIP_STARTUP_CHECKS`

| 値 | lifespan の挙動 |
|----|----------------|
| `false`（デフォルト） | `run_startup_checks` を実行（本番想定・fail-fast）。 |
| `true` | 厳格チェックを**スキップ**し、`load_config` のみ。`GET /health` は常に 200 になりやすい。 |

**用途**: ローカルで `OPENAI_API_KEY=dummy` のまま **コンテナが起動するか**だけ確認する（Step 1 完了条件）。  
**本番**: `false` のまま運用し、不整合は起動時に検知する。

深い依存の確認は **`GET /ready`** に任せる。

## 環境変数（主要）

| 変数 | 必須 | 説明 |
|------|------|------|
| `OPENAI_API_KEY` | はい（アプリ起動時） | OpenAI 利用。プレースホルダ文字列は拒否。 |
| `PORT` | いいえ | 未設定時は **8080**（`Dockerfile` の `ENV PORT=8080` と一致）。 |
| `RAG_SKIP_STARTUP_CHECKS` | いいえ | `true` で lifespan の vector 厳格チェックをスキップ。 |
| `ENABLE_COMET_LOGGING` 等 | いいえ | 既存 `Config` 参照。 |

Cloud Run では **Secret Manager** のシークレットを **同名環境変数**にマウントするだけでよい（Step 1 では未接続）。

## `data/` の同梱方針

- **同梱する（推奨）**: `data/faq_kb.csv`、`data/documents/`（PDF/TXT）、**`data/vector_store/`**（Chroma + BM25 成果物）。初回ビルド前に `python scripts/reindex_vector_db.py` で生成すること。
- **コンテナに含めない（`.dockerignore`）**: 評価用の `data/eval/*.jsonl`、生成メトリクス JSON、スモーク用の大きな成果物など。ランタイムの LINE/RAG には不要なもの。
- **`data/eval/` の YAML/CSV**: エイリアスや semantic 設定がランタイムで必要なら同梱される（評価結果ファイルのみ除外）。

**注意**: Cloud Run のファイルシステムはエフェメラル。永続ボリュームは Step 2 以降で設計。

## ローカルビルド・疎通（Step 1 完了条件）

Cloud Run に載せるイメージを **Mac（Apple Silicon）でビルド**する場合は、`docker build --platform linux/amd64` が必要になることがある（[Step 2](STEP2_GCP_DEPLOY.md) Part 3 参照）。

```bash
cd rental_rag_poc
docker build -t rental-rag-poc:local .

docker run --rm -p 8080:8080 \
  -e PORT=8080 \
  -e OPENAI_API_KEY=dummy \
  -e RAG_SKIP_STARTUP_CHECKS=true \
  rental-rag-poc:local
```

別ターミナル:

```bash
curl -s http://localhost:8080/health
# 期待: HTTP 200, JSON に "status":"ok"
```

`/ready` は vector store 等が揃っていれば 200、不足なら 503 になり得る（データ同梱の有無による）。

## Dockerfile の要点

- ベース: `python:3.11-slim`
- `WORKDIR /app`
- `requirements.txt` を先にコピーして `pip install`
- `COPY src/ scripts/ data/`
- `ENV PORT=8080`、`CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}`

## コンテナレジストリ

**Artifact Registry** を使う（Container Registry の `gcr.io` への書き込みは 2025-03-18 以降停止済み）。push と deploy は **Step 2**。

## Step 2 の予告

- 手順の詳細は [STEP2_GCP_DEPLOY.md](STEP2_GCP_DEPLOY.md)（Artifact Registry、Secret Manager、Cloud Run 初回デプロイ、疎通確認）。

## 検証メモ（自動化環境）

- **pytest**: 全テスト通過で設定・インポートの破壊がないことを確認できる。
- **`docker build`**: Docker Desktop（または同等）が起動している環境で実行すること。デーモン未起動時は `Cannot connect to the Docker daemon` となる。
- **インポート確認**（Docker なし）: `OPENAI_API_KEY` と必要なら `RAG_SKIP_STARTUP_CHECKS` を付与して `python -c "from src.api.main import app"` が成功すればエントリは有効。
