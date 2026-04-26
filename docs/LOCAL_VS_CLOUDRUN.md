# ローカル（Mac）と Cloud Run の差分と揃え方

**ルール（固定）**: ローカルで確認した振る舞いをそのままクラウドにデプロイする。コードの既定値は `env.example` と整合させてあり、Cloud Run で環境変数を追加しなければローカルと同じ挙動になる。詳細は `AGENTS.md` の「ローカル＝クラウドのデプロイルール」を参照。

---

以下は、過去に差分があった項目と、現在の揃え方のメモです。ローカルでは「ペット」「ガス」が期待どおり返るが、Cloud Run では該当なしになる場合の主な原因は **設定の違い** と **データの同期** でした。

## 1. ビジネスロジックに関わる設定（ローカル＝クラウドで統一済み）

次の項目は応答内容・検索挙動に直結するため、**コードの既定値と env.example を一致**させている。Cloud Run で未設定なら同じ値が使われる。

| 変数 | 既定値 | 役割 |
|------|--------|------|
| OPENAI_MODEL | gpt-4o-mini | 応答生成モデル |
| OPENAI_EMBEDDING_MODEL | text-embedding-3-small | 埋め込みモデル |
| RAG_RETRIEVAL_K | 16 | ソースあたりの取得件数（ペット・ガス等のキーワードヒットに影響） |
| RAG_RERANK_CANDIDATES | 20 | リランク候補数 |
| RAG_RERANK_TOP_N | 3 | リランク後の採用件数 |
| RAG_SEARCH_TIMEOUT_SEC | 3.0 | 検索タイムアウト（秒） |
| CSV_SCORE_THRESHOLD | 0.40 | CSV（FAQ/KB）のスコア閾値 |
| PDF_SCORE_THRESHOLD | 0.58 | PDF のスコア閾値（`env.example` の 0.60 はやや厳しめの明示例） |
| ENABLE_QUERY_CACHE | true | クエリキャッシュの有無 |
| CACHE_TTL_SEC | 3600 | キャッシュ TTL（秒） |
| FALLBACK_MESSAGE | （固定文） | 該当なし時の返信文 |

**補足**: 以前は `OPENAI_MODEL` のコード既定が `gpt-5-mini`（誤記）だったため、Cloud Run 未設定時のみモデルがずれていた。`gpt-4o-mini` に統一済み。

## 2. 設定の差分一覧（参考・過去）

| 項目 | ローカル（.env / env.example） | Cloud Run（未設定時のコード既定値） | 影響 |
|------|-------------------------------|-------------------------------------|------|
| **CSV_SCORE_THRESHOLD** | **0.40**（env.example） | **0.40**（config 既定に統一済み） | ローカルとクラウドで同じ既定値。 |
| **RAG_RETRIEVAL_K** | **16**（env.example） | **16**（config 既定） | 取得候補数。deal の FAQ 行が hybrid の top-K に入るよう余裕を持たせる。 |
| **RAG_VECTOR_STORE_PATH** | `data/vector_store`（相対） | 未設定なら `data/vector_store`（コンテナ内は /app が cwd のため /app/data/vector_store） | 同じ相対パスでよい。 |
| **KB_CSV_PATH** | `data/faq_kb.csv` | 未設定なら `data/faq_kb.csv` | 同上。 |
| **.env の有無** | あり（load_dotenv で読み込み） | なし（コンテナに .env はコピーしない） | Cloud Run はコンソールの「変数とシークレット」のみ。上記の閾値・K はここで設定する必要あり。 |

**なぜ「ペット」「ガス」が該当なしになるか（Cloud Run のみ）**

- キーワード一致（`ペット`→ペット飼育の可否、`ガス`→生活_ガス）は、**検索で返ってきた候補**の中にそのドキュメントが含まれているときだけ効く。
- 候補数は `RAG_RETRIEVAL_K`（既定 **16**）で決まる。K が小さいと、短いクエリで該当 FAQ が候補に入らず、キーワード一致が起きない。
- **イメージに reindex 済みの `data/vector_store` が入っていない**と deal 検索が空になりやすい（最頻）。
- `CSV_SCORE_THRESHOLD` はコード・env.example とも既定 **0.40**。Cloud Run の環境変数で **別値に上書きしていないか**確認すること。

## 3. ローカルと揃えるための Cloud Run 設定

Cloud Run の **変数とシークレット** で、次を設定するとローカルに近い挙動になります。

- **CSV_SCORE_THRESHOLD** = `0.40`  
  （ローカルの env.example と同じ。コード既定も 0.40）
- **RAG_RETRIEVAL_K** = `16` 以上推奨  
  （未設定ならコード既定の 16）
- 必須のまま: OPENAI_API_KEY, LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, GCP_PROJECT_ID, PUBSUB_TOPIC_NAME

## 4. データの同期（ペット・ガスが該当するか）

- **ローカル**: `data/vector_store` と `data/faq_kb.csv` は、`python3 scripts/reindex_vector_db.py` 実行時点の内容で一致している。
- **Cloud Run**: イメージは **ビルド時** の `data/` をそのまま含む。  
  - ビルド前に **同じ** `data/faq_kb.csv` で `reindex_vector_db.py` を実行していないと、イメージ内の `data/vector_store` が古い or 空になり、ペット・ガスがヒットしない。
- **手順**: 毎回「`reindex` → その直後に `./deploy/deploy_webhook.sh`」でビルドすると、ローカルと Cloud Run で同じ FAQ/KB とベクトルストアになる。

## 5. コードの扱い

- 実行している **コード** は同一（同じリポジトリの `src/` をビルドに使う）。
- 違うのは **環境変数** と **ビルドに含めた data/** だけ。

## 6. チェックリスト（Cloud Run でペット・ガスを返したいとき）

詳細な原因分析（なぜ該当なしになるか・確認項目・対処）は **docs/RAG_ペット・ガス該当なし分析.md** を参照。

1. Cloud Run に **CSV_SCORE_THRESHOLD=0.40** を明示するか、上書き変数を削除して既定に任せる。
2. **RAG_RETRIEVAL_K** は 16 以上推奨（未設定で既定 16）。
3. ローカルで `python3 scripts/reindex_vector_db.py` を実行したうえで、`./deploy/deploy_webhook.sh` で再ビルド・再デプロイする。
4. 必要なら Cloud Run のログで `Vector store initialized: deal=13 master=...` を確認し、deal が 0 でないことを確認する。
