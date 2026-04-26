# 賃貸 RAG PoC 運用マニュアル

本書は `rental_rag_poc` を**ローカル評価から GCP / Cloud Run 本番まで**運用するための**ハブ文書**です。実装詳細より**いつ・何を・どの順で**実行するかを中心にまとめています。

---

## この文書の読者と使うタイミング

| 読者 | 主に使う場面 |
|------|----------------|
| **開発者** | KB・閾値の変更、reindex、eval、Docker での本番相当確認、デプロイ手順の実行 |
| **運用担当 / 障害当番** | デプロイ後のスモーク、Cloud Run ログ確認、障害時の切り分け（セクション 9 〜） |
| **リリース判定（Tech Lead 等）** | full eval 結果と**品質ゲート**による Ship / No Ship（セクション 2 ステップ 4、QUALITY_GATE 参照） |

迷ったら **冒頭の「30 秒チェックリスト」** → **セクション 2 の標準パイプライン**の順に辿ってください。

---

## 30 秒チェックリスト（リリース・ナレッジ変更のたび）

変更を本番に載せる前に、次を上から順に確認します。

1. `data/faq_kb.csv`（やドキュメント）を変えた → **必ず** `python scripts/reindex_vector_db.py`
2. `python scripts/run_simple_eval.py --mode smoke`（必要なら `--mode full`）
3. `python scripts/preflight_check.py`
4. `docker build -f deploy/Dockerfile.webhook -t rag-line-webhook .` → `docker run ...` → `./scripts/container_smoke_test.sh http://127.0.0.1:8080`
5. `bash deploy/deploy_webhook.sh`
6. `BASE_URL=（Cloud Run URL） ./scripts/post_deploy_smoke.sh`
7. Cloud Run ログで **`CONFIG_SUMMARY`** を開き、下記「ログで見る項目」と突き合わせ

---

## 1. 対象と前提

| 項目 | 内容 |
|------|------|
| リポジトリルート | `rental_rag_poc/`（このディレクトリでコマンドを実行する） |
| 本番コンポーネント | LINE Webhook（Cloud Run）、必要に応じて Worker / Pub/Sub |
| Python | **3.11 推奨**（`Dockerfile.webhook` は 3.11。起動時チェックは 3.11 未満で失敗） |
| 主要データ | `data/faq_kb.csv`、`data/documents/`、`data/vector_store/`（再インデックスで生成） |

---

## 2. 標準運用パイプライン（必ず守る順序）

ナレッジや閾値を変えたあとに本番へ載せる場合は、次の順で実施します。

1. **ナレッジ・設定の変更**（CSV / ドキュメント / `.env` の方針を決める）
2. **再インデックス**: `python scripts/reindex_vector_db.py`  
   - `data/vector_store/manifest.json` が更新される（**ビルド・デプロイと突合せの根拠**）
3. **評価**（任意だがリリース前は推奨）
   - 全件: `python scripts/run_simple_eval.py --mode full`
   - 軽量: `python scripts/run_simple_eval.py --mode smoke`
   - 結果は `data/eval/eval_results.jsonl` と `eval_metrics.json`。`_eval_meta` に `run_id`・`git_commit`・manifest が入る
4. **品質判断（出荷判定）** — **形式的なチェックではなく、ここで Ship を止めてよい**  
   - 詳細は [QUALITY_GATE.md](QUALITY_GATE.md)。この文書での**最低限の目安**は次のとおり（ブロック級）:
     - **`hallucination_fact_error`**: 事実誤りは原則 **0**（1 件でもリリース停止を検討）
     - **PII / 漏えい系**: **0%**
     - **ID 正規化成功率**: **≥ 0.9**（未満は評価設計の見直し優先）
   - 目標級の目安: **Recall@5（平均）≥ 0.5**、completeness / evidence binding はタイプ別に QUALITY_GATE を参照
5. **ビルド前 preflight**: `python scripts/preflight_check.py`  
   - KB の内容と manifest の `kb_sha256` が一致しない場合は**ここで失敗**する（再インデックス忘れの検知）
6. **本番相当コンテナで確認**（推奨）
   - `docker build -f deploy/Dockerfile.webhook -t rag-line-webhook .`
   - `docker run --rm -p 8080:8080 --env-file .env rag-line-webhook`  
     ローカルで API キーが **共有 `.env`（例: `../LangGraph/code/.env`）のみ**のときは、`--env-file .env --env-file ../LangGraph/code/.env` のように **2 個指定**（後ろが先に出たキーで上書き）するとプレースホルダ問題を避けられる。詳細は README「本番相当 Docker」。
   - `./scripts/container_smoke_test.sh http://127.0.0.1:8080`
7. **デプロイ**: `bash deploy/deploy_webhook.sh`（プロジェクト・認証済みであること）
   - スクリプト内で preflight が再度走る。**`SKIP_PREFLIGHT=1` の扱いは下記「緊急時ショートカット」を必ず読むこと。**
8. **デプロイ後スモーク**: `BASE_URL=https://（Cloud Run URL） ./scripts/post_deploy_smoke.sh`
9. **ログ確認**: Cloud Run ログで **`CONFIG_SUMMARY`** を検索し、下記の項目が意図どおりか確認する

### Cloud Run ログ（CONFIG_SUMMARY）で見る項目

`CONFIG_SUMMARY` 行の JSON 内で、少なくとも次をローカル・直前リリースと比較します。

| 確認項目 | 中身の例（フィールド名はログの `config` / `manifest` に準ずる） |
|----------|------------------------------------------------------------------|
| retrieval | `rag_retrieval_k`（既定 **10**） |
| 閾値 | `csv_score_threshold`（既定 **0.40**）、`pdf_score_threshold` |
| モデル | `openai_model`、`openai_embedding_model` |
| manifest | `manifest.built_at`、`manifest.kb_sha256`（先頭 16 文字で突合でも可） |
| **env の出所** | `env_source`（`loaded_override_path`・`rental_env_loaded`・`fallback_load_dotenv_cwd` など。どの `.env` 層が効いたかの切り分け用） |
| 秘密の有無 | `OPENAI_API_KEY` 等が **SET** か（値そのものは出ない） |
| 実行環境 | `python_version`、`runtime_cwd` |

設計思想の詳細は [TESTING_LAYERS.md](TESTING_LAYERS.md)、ローカルと本番の差分観点は [LOCAL_VS_CLOUDRUN.md](LOCAL_VS_CLOUDRUN.md) を参照してください。

---

## 3. 日常運用（変更がないとき）

- **監視**: Cloud Run のエラーレート、レイテンシ、ログに `Startup check failed` や OpenAI エラーがないか
- **コスト**: 予算アラート（GCP Budgets）。停止・整理は [GCP_SUSPEND_AND_RESUME.md](GCP_SUSPEND_AND_RESUME.md)、[GCP_SUSPEND_AND_IMAGE_TRIM.md](GCP_SUSPEND_AND_IMAGE_TRIM.md)
- **LINE**: Webhook URL が Cloud Run の最新 URL と一致しているか（デプロイやドメイン変更後は要確認）

### 週次・月次（任意だが推奨）

| 頻度 | 内容 |
|------|------|
| **週次** | エラーレート・レイテンシの傾向、OpenAI 429/5xx の有無、`/ready` 503 の有無をざっと確認 |
| **月次** | full eval の結果と [QUALITY_GATE.md](QUALITY_GATE.md) の閾値を見直す。[EVAL_DATA_EXPANSION.md](EVAL_DATA_EXPANSION.md) に沿って eval セット拡張の候補をメモ |

---

## 4. ナレッジ更新のチェックリスト

- [ ] `data/faq_kb.csv`（および必要なら `data/documents/`）を編集・コミット
- [ ] `python scripts/reindex_vector_db.py` を実行
- [ ] `data/vector_store/manifest.json` の `built_at` / `kb_sha256` を目視
- [ ] `python scripts/preflight_check.py` が通る
- [ ] 必要なら `run_simple_eval.py`（smoke または full）
- [ ] 同一コミット・同一 vector_store 状態で Docker イメージをビルドしてデプロイ

**注意**: KB だけ更新して再インデックスを忘れると、起動時または preflight で失敗します。これは意図した安全装置です。

---

## 5. 緊急時ショートカット（強い注意）

運用を短縮するフラグやエンドポイントは、**暫定対応以外に使わないこと。**

### `SKIP_PREFLIGHT=1`（deploy_webhook.sh）

- **用途**: 障害復旧・緊急ロールバックなど、やむを得ない場面の**一時的な**回避のみ。
- **禁止**: 「面倒だから」常時利用。
- **使用後の必須作業**: 同一コミット・正しい `data/` の状態で、**必ず** `reindex`（必要なら）→ `preflight_check.py` → **コンテナ smoke** → 通常デプロイを**やり直す**。理由をチケットまたは PR に残す。

### `ENABLE_DEBUG_RAG_ENDPOINT=true` と `POST /debug/rag`

- **用途**: 非本番・ネットワーク制限下でのみ、RAG の最短動作確認。
- **禁止**: インターネットに公開した Cloud Run での常時有効化（未認証の質問 APIと同等のリスク）。
- 本番で必要な場合は、**別途認証・IP 制限・すぐ無効化**をセットにすること。

---

## 6. デプロイと GCP 操作

- スクリプト一覧・ビルドのみ／反映のみの分割: [deploy/README.md](../deploy/README.md)
- 環境変数は **Cloud Run コンソール**で設定（イメージに `.env` は含めない）
- 本番で必須になりがちな変数例: `OPENAI_API_KEY`、`LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`、`GCP_PROJECT_ID`、`PUBSUB_TOPIC_NAME`（構成による）
- 閾値・検索系: `CSV_SCORE_THRESHOLD=0.40`、`RAG_RETRIEVAL_K=16` などは [LOCAL_VS_CLOUDRUN.md](LOCAL_VS_CLOUDRUN.md) と揃える

---

## 7. ヘルスチェックとスモーク

| エンドポイント | 意味 |
|----------------|------|
| `GET /` または `GET /health` | プロセス生存 |
| `GET /ready` | vector store・manifest・Chroma 等、**RAG 実行準備**ができているか（未準備は HTTP 503） |

コンテナ内での RAG 動作を短時間で試すには、**非本番・限定環境のみ** `.env` で `ENABLE_DEBUG_RAG_ENDPOINT=true` とし `POST /debug/rag`（JSON `{"question":"..."}`）を使う。**インターネットに公開したまま有効化しないこと**（セクション 5 参照）。

---

## 8. 評価・テストの使い分け

| 層 | コマンド・手段 | 用途 |
|----|----------------|------|
| 単体・回帰（高速） | `pytest` | 分岐・閾値・フォールバックの安定確認 |
| スモーク eval | `run_simple_eval.py --mode smoke` | 固定 8 問前後で E2E 品質の早期検知 |
| フル eval | `run_simple_eval.py --mode full` | リリース判定・指標集計 |

詳細は [TESTING_LAYERS.md](TESTING_LAYERS.md)、Ship 基準の全文は [QUALITY_GATE.md](QUALITY_GATE.md)。

---

## 9. 監査・トレーサビリティ

- **manifest**: `data/vector_store/manifest.json`（どの KB ハッシュで index したか）
- **eval 出力**: 各行の `_eval_meta` と `eval_metrics.json` の `eval_run`
- **起動ログ**: `CONFIG_SUMMARY` 行（本番とローカルで JSON を突き合わせ可能）
- **OPIK / Comet**: オフラインと本番の分離方針は [OPIK_COMET_OPERATION.md](OPIK_COMET_OPERATION.md)

---

## 10. 障害時・挙動差の調査

次の順で切り分けます（詳細は [RUNBOOK_RAG_INCIDENT.md](RUNBOOK_RAG_INCIDENT.md)）。

1. Cloud Run ログの `CONFIG_SUMMARY` とローカル（または直前のリリース）の差分
2. 環境変数（特に閾値・検索 K・モデル名）
3. `manifest.json` の `kb_sha256` と現在の `faq_kb.csv` が一致するか
4. `data/vector_store` がイメージに焼かれているか（空デプロイになっていないか）
5. OpenAI や外部 API のエラー
6. メモリ・タイムアウト・cold start

---

## 11. Cloud Run 運用上の注意

- 書き込み可能な永続領域は事実上 **`/tmp` のみ**想定。アプリの state はクラウド側ストレージに逃がす設計が安全です。
- 相対パスはコンテナの `WORKDIR`（`/app`）基準です。詳細は [CLOUD_RUN_CONSTRAINTS.md](CLOUD_RUN_CONSTRAINTS.md)。

---

## 12. ファイル・秘密情報の扱い

- **ローカルで `.env` が二段あるときの責務**（既定の読み込み順は `src/config.py` の `bootstrap_dotenv` 参照）  
  - **共有**（例: 親リポジトリ隣接の `../LangGraph/code/.env`、または `RENTAL_RAG_SHARED_ENV_FILE`）: OpenAI / Comet など**チーム共通の秘密・モデル系**  
  - **`rental_rag_poc/.env`**: LINE / Slack・PoC 固有パスなど**このプロジェクト専用**（共有を `override=False` で補完のみ）。`RENTAL_RAG_SHARED_ENV_FILE` を**シェルで export してから**起動しないと、変数自体は dotenv 1 周目では見えない（ブートストラップ前に OS 環境へ載せる必要あり）。
- **コミットしない**: `.env`、`deploy/.env.gcp`（`.gitignore` 済み）
- **ベイクする**: `docker build` 時点の `data/`（vector_store を含む）。**秘密を `data/` に置かないこと**
- キャッシュ: `.pytest_cache` 等は原則コミット不要（`.gitignore` 参照）

---

## 13. 評価セット拡張・改善サイクル

新規 FAQ を増やす際の優先順位は [EVAL_DATA_EXPANSION.md](EVAL_DATA_EXPANSION.md) を参照し、full eval の結果と品質ゲートに沿って改善します。

---

## 14. 関連ドキュメント一覧

| ドキュメント | 内容 |
|--------------|------|
| [README.md](../README.md) | セットアップ・機能概要・eval / Docker 手順 |
| [deploy/README.md](../deploy/README.md) | GCP デプロイスクリプト |
| [LOCAL_VS_CLOUDRUN.md](LOCAL_VS_CLOUDRUN.md) | ローカルと本番の設定差分 |
| [TESTING_LAYERS.md](TESTING_LAYERS.md) | pytest / smoke / full |
| [QUALITY_GATE.md](QUALITY_GATE.md) | Ship 判定の指標（全文） |
| [RUNBOOK_RAG_INCIDENT.md](RUNBOOK_RAG_INCIDENT.md) | 障害切り分け手順 |
| [CLOUD_RUN_CONSTRAINTS.md](CLOUD_RUN_CONSTRAINTS.md) | 本番制約 |
| [OPIK_COMET_OPERATION.md](OPIK_COMET_OPERATION.md) | observability 分離 |

**文書の位置づけ**: 本書は**運用のハブ**、README はセットアップと概要、各 `docs/` は深掘りです。

---

## 改訂履歴

- 初版：運用パイプライン・チェックリスト・関連ドキュメントへの導線を統合
- 改訂：読者と利用タイミング、30 秒チェックリスト、品質ゲート抜粋、CONFIG_SUMMARY 確認項目（`env_source`）、週次/月次、緊急ショートカットの強い注意、文書の位置づけ、`.env` 共有と PoC 固有の責務
