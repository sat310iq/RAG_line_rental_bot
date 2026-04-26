# ペット・ガスで「該当する回答なし」になる原因の分析

## 1. 回答は存在するか（データの確認）

**faq_kb.csv** には次の行が含まれており、回答は存在します。

| 質問キーワード | intent | keywords（抜粋） | 想定回答 |
|----------------|--------|------------------|----------|
| ペット | ペット飼育の可否 | ペット\|動物\|飼育\|犬\|猫... | ペットの飼育は全面的に禁止... |
| ガス | 生活_ガス | ガス\|問い合わせ\|給湯器\|給湯 | ガスについての問い合わせ先：ダイプロ高田国東販売... |
| 給湯器 | 生活_ガス / 設備_故障 | 給湯器\|給湯 / 給湯器\|浴室\|... | ガス問い合わせ先 または 故障時の連絡案内 |

- **ペット飼育の可否**（4行目）: `keywords` に「ペット」を含む。
- **生活_ガス**（8行目）: `keywords` に「ガス」「給湯器」「給湯」を含む。

したがって、「ペット」「ガス」「給湯器」で該当する**データはある**状態です。

---

## 2. なぜ「該当なし」になるか（ロジックの流れ）

RAG の流れは次のとおりです。

1. **deal コレクションの検索**  
   `vector_store_manager.search(question, sources=["deal"])` で、Chroma（ベクトル）と BM25（キーワード）のハイブリッド検索を行う。  
   - 取得件数は `RAG_RETRIEVAL_K`（既定 16）。  
   - deal には faq_kb.csv を reindex したドキュメントが入っている（intent・keywords 付き）。

2. **キーワード一致での採用**  
   `_filter_scored_results(..., allow_keyword_override=True)` で、  
   **「検索結果に含まれるドキュメントのうち、metadata.keywords に質問の語が含まれるもの」** があれば、スコア閾値（CSV_SCORE_THRESHOLD）を無視してそのドキュメントを採用する。  
   - 例: 質問「ペット」→ 検索結果に「ペット飼育の可否」の doc が含まれ、keywords に「ペット」がある → キーワード一致として採用。

3. **該当なしになる条件**  
   `csv_docs` も `pdf_docs` も空のとき、`fallback_message`（「該当する情報が見つからないため...」）が返る。  
   つまり **「deal の検索結果に、ペット/ガス/給湯器のドキュメントが 1 件も含まれていない」** と該当なしになる。

したがって、**「該当なし」＝ deal 検索結果に該当 FAQ が載っていない** と考えられます。

---

## 3. 考えられる原因（優先度順）

### A. イメージ内のベクトルストアが空または古い（最もありがち）

- **事実**: Dockerfile.webhook は **reindex を実行していない**。`COPY data/ ./data/` で、**ビルド時点の data/** をそのままコピーしている。
- **影響**:  
  - ビルド前に `python3 scripts/reindex_vector_db.py` を実行していないと、`data/vector_store` が空 or 古い。  
  - その状態でビルドすると、Cloud Run のコンテナ内も deal が 0 件 or 古い FAQ のまま。
- **確認**: Cloud Run のログで起動直後に  
  `Vector store initialized: deal=13 master=...` のような行が出ているか確認する。  
  **deal=0** なら、イメージに reindex 済みの data/ が入っていない。

**対処**: デプロイ前に必ず **「reindex → その直後にビルド」** する。

```bash
python3 scripts/reindex_vector_db.py
./deploy/deploy_webhook.sh
```

（または `scripts/deploy_webhook_build_only.sh` でビルドのみ行い、その後デプロイ。）

---

### B. RAG_RETRIEVAL_K が小さく、短いクエリで該当 FAQ が候補に入らない

- **事実**: 取得件数は `RAG_RETRIEVAL_K`（既定 16）。deal が 13 件なら、クエリ「ペット」だけだとベクトル検索の順位が低く、上位 K 件に含まれない可能性がある。BM25 は「ペット」を含むドキュメントを返しやすいが、BM25 とベクトルのマージ結果の並び次第では、該当 doc が K 件から漏れることもある。
- **影響**: キーワード一致は **「検索結果に含まれる doc」** にしか効かない。候補に含まれていなければ該当なしになる。
- **確認**: コードの既定は 16。Cloud Run で `RAG_RETRIEVAL_K` を 5 などにしていないか確認する（未設定なら 16 が使われる）。

**対処**: 未設定のまま（既定 16）にするか、必要なら 16 以上を明示する。ローカル＝クラウドで揃える（AGENTS.md の「ローカル＝クラウドのデプロイルール」参照）。

---

### C. CSV_SCORE_THRESHOLD が高く、キーワード一致前にスコアで落ちている（現在のコードでは起こりにくい）

- **事実**: キーワード一致がある場合は **閾値チェックをスキップ** して採用する。したがって、**「候補に該当 doc が含まれている」** ことが前提。候補に含まれていれば、スコアが 0.40 未満でもキーワード一致で採用される。
- **影響**: 閾値の差で該当なしになるのは、主に「候補にそもそも入っていない」場合（上記 A または B）。

**対処**: 既定 0.40 のまま（ローカル＝クラウドで統一済み）。特別な理由がなければ変更不要。

---

### D. BM25 コーパスがイメージにない

- **事実**: deal の BM25 は `data/vector_store/bm25_corpora/kb_deal_csv.jsonl` から読み込む。reindex 時にこのファイルが作られる。
- **影響**: ビルド前の reindex をしていない、または `data/vector_store` ごとコピーされていないと、BM25 が使えずキーワード検索が弱くなる。短いクエリ「ペット」「ガス」は BM25 が効きやすいため、BM25 がないと該当 doc が候補に出にくい。

**対処**: A と同様に、reindex を実行したうえでビルドする。

---

## 4. 確認してほしいこと（チェックリスト）

| 確認項目 | 方法 |
|----------|------|
| 起動ログで deal 件数 | Cloud Run ログで `Vector store initialized: deal=13 master=...` を検索。deal=0 ならイメージに reindex 済み data が入っていない。 |
| 検索結果 0 件のログ | `[INFO] CSV search returned 0 results.` が出ているか。出ていれば deal 検索が空。 |
| キーワード一致のログ | `[INFO] CSV keyword match detected. ... (matched intent: ペット飼育の可否)` や `生活_ガス` が出ているか。出ていればキーワード一致で採用されている。 |
| デプロイ前の reindex | 直近のデプロイの**前**に `python3 scripts/reindex_vector_db.py` を実行したか。 |
| 環境変数 | Cloud Run で `RAG_RETRIEVAL_K` / `CSV_SCORE_THRESHOLD` を変更していないか（未設定ならコード既定 16 / 0.40）。 |

---

## 5. 推奨アクション

1. **ローカルで reindex を実行し、その直後にビルド・デプロイする**  
   - `python3 scripts/reindex_vector_db.py`  
   - `./deploy/deploy_webhook.sh`（または build-only のあと deploy）
2. **デプロイ後の Cloud Run ログで**  
   - `Vector store initialized: deal=13 ...` を確認（deal が 0 でないこと）。  
   - 「ペット」や「ガス」で質問したリクエストのログで、`CSV keyword match detected` または `CSV search returned 0 results` のどちらが出ているかを確認する。
3. **ローカルとクラウドの設定を揃える**  
   - 設定の差分は `docs/LOCAL_VS_CLOUDRUN.md` と AGENTS.md の「ローカル＝クラウドのデプロイルール」に従う。

以上により、ペット・ガス・給湯器で「該当する回答なし」になる原因を切り分けし、再現して修正できます。
