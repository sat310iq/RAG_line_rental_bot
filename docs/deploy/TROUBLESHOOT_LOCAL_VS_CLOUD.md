# トラブルシュート: ローカルと Cloud Run で応答が違う / 応答が遅い

現段階の論点は「返信不能」より **運用品質**（遅延・ローカル/Cloud の検索結果のずれ）に寄っていることが多い。**まず Cloud 実行環境の再現性**（データ同期・実行時設定）を揃えてから、アルゴリズム単体の議論に進むのが安全です。

## 優先順位（実務）

**最優先（この3つで多くの「ペット例の差」が説明できる）**

1. Cloud Run ログで **`Vector store initialized: deal=`**（**deal=0 なら次に進まない**）。  
2. **`CONFIG_SUMMARY`** / **`line-rag-lazy-init`** と、切り分け時のみ **`GET /debug/config`** で **local と Cloud の設定差**を確認。  
3. **`reindex` → 直後に `docker build` → deploy`**（イメージに閉じ込める時刻を揃える）。

**次点**

4. **`min-instances=1`** で初回メッセージに載る重い初期化コストを減らす（コスト増のトレードオフ）。  
5. **`RAG_RETRIEVAL_K=16`** の効果と **レイテンシ・後段コスト**のトレードオフを見る（下記「暫定調整」参照）。

---

## `deal=0` のとき

**検索品質（閾値・K・rerank）のチューニングは一旦止める。**  
deal 側に文書が載っていない状態では、パラメータをいじっても改善しにくい。先に **reindex 済み `data/` がイメージに入っているか**、Chroma 初期化エラーがないかを解消する。

---

## BM25 について

Chroma だけでなく、**`data/vector_store/bm25_corpora/*.jsonl`** は `reindex_vector_db.py` が生成する。Docker は `COPY data/` ごと載るため、**通常は vector store と同じタイミングで同期される**。  
「Chroma はあるが BM25 が空・古い」場合も挙動差の原因になりうるので、reindex 直後ビルドの運用を揃える。

---

## `RAG_RETRIEVAL_K` を 16 にした位置づけ

**キーワード救済の前段である recall（候補に FAQ 行が乗る率）を上げる暫定調整**として妥当。副作用として候補が増え、rerank や後段の負荷・応答時間がわずかに悪化しうる。  
本質的には「なぜその FAQ が top-K に入らないか」を別途分析する余地は残る。

---

## `/debug/config` について

**本番では `ENABLE_DEBUG_RAG_ENDPOINT=false` のまま**とし、設定 diff が必要なときだけ一時的に有効化する。

---

## その他の切り分け（必要になったら）

- **Python / パッケージ差**（例: Chroma まわりのバージョン）も、挙動が「Cloud だけ妙」ときの候補。主因ではないことも多い。  
- **遅延の定量化**: 将来、1 リクエストあたりの **LLM 呼び出し回数**（router / rerank / answer 等）をログに出すと説明がしやすい（未実装・任意）。

---

## 症状① レスポンスが 1 分以上かかる

**典型原因（重なりやすい）**

| 要因 | 説明 |
|------|------|
| **コールドスタート** | `min-instances=0` だと、初回リクエストでコンテナ起動 + 遅延 import + `VectorStoreManager` 初期化 + 初回 OpenAI/Chroma が乗る。数十秒〜 1 分超は起こりうる。 |
| **初回メッセージで RAG 遅延** | RAG は FastAPI `lifespan` で先行初期化（`rag_startup_init_*` ログ）。Webhook スレッドは `get_rag_bundle()` の既存インスタンスを使用。 |
| **複数回の LLM 呼び出し** | ルーター / プランナー / セマンティック再ランク / Responder など、1 質問で複数の API 往復がありうる。 |
| **`--concurrency=1`** | 同時処理は安全だが、キューイングで待ち時間が伸びる。 |

**推奨対策**

1. **本番 LINE**: `min-instances=1` を検討（常時ウォーム・コスト増）。  
2. デプロイ後 **GET `/ready`** で依存関係を先に温める。  
3. Cloud Run の **CPU を 1 以上**（スロットリング緩和は別ドキュメント参照）。  
4. ログで **初回のみ遅い**か **毎回遅い**かを切り分ける。

---

## 症状② ローカルでは FAQ が返るのに Cloud では「該当なし」に近い返答

**前提**: キーワード救済（CSV keyword match）は **「deal 検索の候補リストにその FAQ ドキュメントが 1 件でも含まれる」** ことが必要です。候補に入っていなければ、ペット行があってもマッチしません。

**優先度の高い原因**

### A. イメージ内の `data/vector_store` が空・古い（最頻）

- Docker は **ビルド時点の `COPY data/`** をそのまま載せます。  
- デプロイ前に **`python3 scripts/reindex_vector_db.py`** を実行していないと、Chroma/BM25 がローカルと一致しません。

**確認**: Cloud Run ログの

`Vector store initialized: deal=... master=...`

- **deal=0** なら、イメージにインデックスが入っていないか Chroma 初期化失敗の可能性大です。

**対処**: ローカルで reindex した直後にイメージをビルド・プッシュし直す（[LOCAL_VS_CLOUDRUN.md](../LOCAL_VS_CLOUDRUN.md) 手順）。

### B. Cloud Run の環境変数がローカルと違う

- **`CSV_SCORE_THRESHOLD`**, **`PDF_SCORE_THRESHOLD`**, **`RAG_RETRIEVAL_K`** がコンソールで別値になっていないか。  
- 契約書 **TXT** を参照する場合、Cloud Run に **`MASTER_TXT_FILES`**（例: `グランマーレ大分空港契約書.txt`）と **`PDF_DOCUMENTS_DIR=/app/data/documents`** が揃っているか。未設定だとローカルでは読めている master TXT が Cloud では探索対象外になります（`env.gcp.example` 参照）。  
- コード既定は `env.example` と揃えてありますが、**過去に手動設定した値が残っている**と差が出ます。

**確認**: 一時的に `ENABLE_DEBUG_RAG_ENDPOINT=true` を入れ、**GET `/debug/config`** で `csv_score_threshold` と `rag_retrieval_k` をローカルの `CONFIG_SUMMARY` と比較する。

### C. 候補数不足（短いクエリで FAQ が top-K から落ちる）

- ハイブリッド検索の上位 K 件に該当 intent が入らないと、キーワード救済が効きません。  
- 既定の **`RAG_RETRIEVAL_K` は 16**（FAQ 行数に余裕を持たせる）に更新済みです。Cloud で `10` 等に固定している場合は揃えるか、未設定にして既定値に任せる。

---

## すぐできるチェックリスト

1. Cloud ログに **`Vector store initialized: deal=`** が出ているか（deal>0）。  
2. **`CONFIG_SUMMARY`**（起動時）と **`line-rag-lazy-init`**（初回 RAG ロード時）の JSON で `csv_score_threshold` / `rag_retrieval_k` がローカルと同じか。  
3. ローカルで `reindex` → **その直後**に Docker ビルドしているか。  
4. 遅延だけの問題なら **`min-instances`** と **初回以外のレイテンシ**をログで確認。

---

## 進め方（ローカルで実行するコマンド）

プロジェクトルートは `rental_rag_poc/`（`README.md` があるディレクトリ）。

### Step 1（データ＋設定のローカル確認 → ビルド）

1. 必要ならインデックス再生成:  
   `python3 scripts/reindex_vector_db.py`
2. デプロイ前チェック（deal 件数・manifest・BM25・KB ハッシュ）:  
   `python3 scripts/preflight_check.py`  
   成功時は末尾に `STEP1_DATA_OK` と `PREFLIGHT OK`。
3. Cloud のログと並べるための設定 JSON（API キーが載る `.env` があること）:  
   `python3 scripts/preflight_check.py --print-config`  
   出力の `CONFIG_SNAPSHOT` を Cloud の `CONFIG_SUMMARY` または `GET /debug/config` と突き合わせる。
4. その直後に Docker ビルド・プッシュ・デプロイ（[STEP2_GCP_DEPLOY.md](STEP2_GCP_DEPLOY.md)）。

### Step 2（速度）

- Cloud Run で `min-instances=1` を試し、**初回メッセージ**と**2通目以降**の応答時間をログまたは体感で分けて記録する。

### Step 3（軽量評価・Phase 1 テストケースのみ）

評価用 CSV は **[`eval/datasets/line_rag_eval_v1.csv`](../eval/datasets/line_rag_eval_v1.csv)**（50 問）のみを使う。別スモーク CSV は置かない。

```bash
python3 scripts/run_eval.py --dataset eval/datasets/line_rag_eval_v1.csv
python3 scripts/summarize_eval.py
python3 scripts/review_failures.py -o /tmp/review.csv
```

デプロイ後も同じ CSV で再実行し、`fallback_used` や `answer` の傾向を比較する。一覧表のテンプレートは [`docs/eval/LOCAL_RUN_LINE_RAG_EVAL_V1_TABLE.md`](../eval/LOCAL_RUN_LINE_RAG_EVAL_V1_TABLE.md) を参照。

---

## ネクストステップ（3本柱）と完了条件

一言でいうと、**まず「Cloud のデータと設定がローカルと同じか」を確定する**。ここが固まる前に retrieval の閾値や recipe を触ると原因が混ざる。

### A. まず Cloud の再現性を固める

- `deal=0` なら検索品質の議論は止め、**reindex → build → deploy** を先にやる。  
- `CONFIG_SUMMARY` と（切り分け時のみ）`/debug/config` で、**ローカルと Cloud の設定差を消す**。

**Step 1 完了条件**

- ログに `Vector store initialized: deal>0`。  
- `CONFIG_SUMMARY` が local / Cloud で実質一致（意図した差分のみ）。  
- `/debug/config` の差分が説明できる（または本番では無効）。

### B. 次に速度を切り分ける

- `min-instances=1` を入れ、**コールドスタート起因か**を見る。  
- それでも遅いなら **検索が重いのか、LLM 多段が重いのか** を分ける。

**Step 2 完了条件**

- 初回と 2 回目以降の応答時間が分けて記録されている。  
- `min-instances=1` で改善するか確認済み（しない場合は理由メモ）。

### C. そのうえで Amplifier を軽く回す

- 代表質問だけでよい。**Cloud デプロイ後も同じ傾向か**を `run_eval.py` の JSONL で確認。  
- 失敗だけ少数 `review_failures.py` でレビューし、原因を 1 行ずつ残す。

**Step 3 完了条件**

- 代表質問で local / cloud の出力差が把握できている。  
- 失敗パターンが数件レビュー済み（タクソノミー or メモ 1 行）。

---

## 関連ドキュメント

- [LOCAL_VS_CLOUDRUN.md](../LOCAL_VS_CLOUDRUN.md)  
- [RAG_ペット・ガス該当なし分析.md](../RAG_ペット・ガス該当なし分析.md)  
- [STEP2_GCP_DEPLOY.md](STEP2_GCP_DEPLOY.md)（`--concurrency=1` など）
