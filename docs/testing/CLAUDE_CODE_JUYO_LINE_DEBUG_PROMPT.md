# Claude Code 用プロンプト — 重要事項説明書（重説）が LINE で答えられない問題の調査・修正

以下を **Claude Code のチャットにそのまま貼り付け**て実行してください。作業ディレクトリはリポジトリルート  
`Assignment 3 - Solutions/rental_rag_poc` とする。

---

## 背景（症状）

本番／検証 LINE で、**重要事項説明書の内容を問う質問**に対し、次のような不整合が報告されている。

1. **「重要事項説明書の3番では家賃や共益費はいくらと…」**  
   応答が「3番に金額の記載なし」と否定する一方、リポジトリ上の `data/documents/重要事項説明書.txt` の **「## 3. 賃料及び…」** には **家賃 31,700円・共益費 2,500円・水道料 3,300円** 等が明記されている。
2. **貸主による契約解除のケース** 等、重説／契約に関連しうる質問で **汎用の「確認できません」** に落ちる。
3. **「津波災害警戒区域ですか」** 等 — 同一 TXT 内に **「津波災害警戒区域：外」** があるにもかかわらず、根拠が見つからない扱い。
4. **「重要事項説明書に石綿使用調査内容の記載は…」** — TXT に **「## 13. 石綿使用調査内容」** があるのに、**「契約書（根拠情報）内では確認できません。」** と返る（ユーザーは重説を指定しているのに文言が「契約書」固定）。

---

## 仮説（調査の出発点）

次を **コードとログの両面**で潰す。優先度は上から。

| # | 仮説 | 確認方法の例 |
|---|------|----------------|
| H1 | **ベクトルストアに `重要事項説明書.txt` チャンクが入っていない**（未 reindex・Cloud Run イメージが古い） | ローカル `data/vector_store` の manifest / `scripts/reindex_vector_db.py` 後の再デプロイ確認 |
| H2 | **検索はヒットするが `contract_source` 経路のフィルタで重要事項チャンクが落ちる** | `rag_answerer.py` の master merge / `retrieval_metadata_boost` / `prefers_contract_master_chunks` 周りの trace |
| H3 | **プロンプト方針で「数値を出すな」と抑止され、重説§3の事実まで伏せている** | `contract_source_qa_prompt` 付近と、回答生成ログの evidence 件数 |
| H4 | **根拠ゼロ時の `_contract_source_not_found_answer` が常に「契約書（根拠情報）…」固定**で、重説質問でも誤ったラベルになる | `rag_answerer.py` 845 行付近。質問が重説か契約かでメッセージ分岐すべき |
| H5 | **LINE ハンドラ側で `contract_source_q` が False** のまま FAQ だけ参照している | `src/interfaces/line/handler.py` および RAG 呼び出し時の `debug` / ログキー |

---

## タスク（順番に実施）

### Phase 0 — 再現と一次切り分け（コード変更なし）

1. リポジトリで `data/documents/重要事項説明書.txt` を開き、次の文字列が **ファイルに実在する**ことを確認（grep 可）:  
   `31,700円` / `2,500円` / `津波災害警戒区域` / `石綿使用調査`
2. `python3 -c` または小スクリプトで次を確認し、結果をチャットに貼る:  
   - `is_contract_source_question("重要事項説明書の3番では家賃や共益費はいくらと記載されていますか")`  
   - `is_important_matters_question(...)`  
   （`src.contract_query_router` を import）
3. **ローカル**で `scripts/run_simple_eval.py` は重いので、可能なら **`POST /debug/rag`**（`ENABLE_DEBUG_RAG_ENDPOINT=true` の環境のみ）または既存の `tests/test_rag_contract_prompt_selection.py` 系で、同一質問の **retrieved doc_kind** が取れる経路を探す。

### Phase 1 — 検索パイプライン

1. `RAGAnswerer` の **contract source 分岐**（`contract_source_q` が True のときの retrieval → merge → `_select_docs_for_contract_source`）を読み、**`doc_kind == important_matters` の Document が evidence に残る条件**を文章化する。
2. `src/retrieval_metadata_boost.py` で `is_important_matters_question` / `extract_important_matters_section_id` が **スコアにどう効くか**確認。セクション番号「3番」と chunk の `section_id` の対応がズレていないか。
3. `vector_store_manager` の検索・閾値で **master TXT が落ちないか** を確認。

### Phase 2 — プロンプトと「未検知」メッセージ

1. 根拠チャンクに **重要事項説明書が含まれる場合**、回答が「記載なし」になるのは **LLM 指示の過剰防御**か検証。
2. `_contract_source_not_found_answer` の固定文を見直し:  
   - 質問に「重要事項説明書」「重説」が含まれる場合は **「重要事項説明書（根拠情報）内では…」** など文書種別を合わせる、または **「マスター文書（契約書・重要事項説明書）内では…」** のように中立化する。

### Phase 3 — 本番相当確認

1. `deploy/Dockerfile.webhook` と Cloud Build が **`data/documents/*.txt` と `data/vector_store` をイメージに含める**設計か確認。含まれない場合、**本番だけ KB が古い／空**になり得る。
2. 修正後は **`python3 scripts/reindex_vector_db.py`**（要 OpenAI）→ **preflight** → **pytest** → 必要なら **再デプロイ**の順をドキュメントに残す。

---

## 完了条件

- [ ] 上記 **症状 1〜4** のうち少なくとも **1 と4** を、ローカルまたはステージングで **正しい根拠付き回答**にできる（または「条文に照らし管理会社へ」の適切なエスカレーションに一本化できる）ことを示す。
- [ ] **根拠ゼロ時の文言**が、重説質問で「契約書」とだけ言い切らない。
- [ ] 回帰テストを追加または更新（例: `tests/test_important_matters_query_router.py` に加え、**検索結果に `important_matters` が含まれる**統合テストが望ましい）。
- [ ] `docs/eval_log.md` または `docs/testing/LINE_MANUAL_TEST_CASES.md` に **再現手順と期待**を 1 ブロック追記。

---

## 禁止事項

- `.env` の **API キー・LINE トークン・チャネルシークレット**をチャットやコミットに貼らない。
- 本番 Cloud Run の URL に **クエリにシークレットを付けない**。

---

## 参考パス（読む順）

- `data/documents/重要事項説明書.txt`
- `src/contract_query_router.py`（`is_contract_source_question` / `is_important_matters_question`）
- `src/rag_answerer.py`（`_contract_source_not_found_answer`、contract source merge）
- `src/retrieval_metadata_boost.py`
- `src/document_txt_splitters.py`（`split_important_matters_txt_to_documents`）
- `tests/fixtures/granmare_important_matters_cases.yaml` / `tests/test_granmare_important_matters_cases.py`

---

## オペレータ向け短縮版（1 メッセージ）

```text
重要事項説明書の質問が LINE で誤答・未回答になる件を調査してください。
data/documents/重要事項説明書.txt には §3 の金額・津波区域・石綿節があるのに、
契約書not_found文言や「記載なし」になる。仮説: ベクトル未取り込み、
retrievalフィルタ、プロンプトの数値禁止、_contract_source_not_found_answer の
「契約書」固定文言。rag_answerer / retrieval_metadata_boost / vector_store /
Dockerfile の順で原因特定し、テスト追加と eval_log か LINE 手動手順への追記まで。
秘密は貼らない。
```
