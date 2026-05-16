# Claude 向け実装指示 — 重要事項説明書（重説）を RAG で正しく回答できるようにする

以下を **そのまま Claude Code / Claude に貼り付け**て実行する。作業ルートは `rental_rag_poc` のリポジトリ直下。

**ルーティング全体（KB / 契約ソース / 一般 RAG・フラグ早見表）:** `docs/architecture/MASTER_DOCUMENT_ROUTING.md`

---

## 目的

ユーザーが **重要事項説明書（重説）の記載内容**を問う質問に対し、**`data/documents/重要事項説明書.txt` に実際に書いてある事実**に基づいて回答できるようにする。  
LINE 本番で起きていた **「金額があるのに記載なし」「重説なのに契約書固定の not_found」「津波・石綿など本文にあるのにヒットしない」** をなくす。

---

## 正本と検証クエリ（必ず通す）

正本: `data/documents/重要事項説明書.txt`

次の質問で、**根拠チャンクに `doc_kind=important_matters` かつ該当セクションが含まれる**こと、**回答本文がファイル内容と矛盾しない**ことを確認する。

| 目的 | 質問例 | 期待（ファイル上の事実） |
|------|--------|---------------------------|
| §3 月額 | 重要事項説明書の3番では家賃や共益費はいくらと記載されていますか | 家賃 31,700円、共益費 2,500円、水道 3,300円 等が記載されている |
| §8 解除 | 重要事項説明書の契約の解除について、借主の解約予告はどう書いてありますか | 1ヶ月前までに書面での通知／賃料1ヶ月分で即時解約 等 |
| §11 区域 | 津波災害警戒区域ですか | **外**（該当節に「津波災害警戒区域：外」） |
| §12 ハザード | 洪水浸水想定区域と高潮浸水想定区域はどう記載されていますか | 表の **有/無** と注記に整合 |
| §13 石綿 | 重要事項説明書に石綿使用調査内容の記載はありますか | 調査結果記録なし・概要記載なし 等（否定ではなく「記載内容の要約」） |
| 特約 | 重説の特約④では短期解約違約金はどう記載されていますか | 特約④の段階・金額が本文どおり |

**禁止**: 根拠があるのに「記載されていない」と一律で潰す、重説の質問に対し **「契約書のみ」** と誤ラベルする（not_found 文言は `契約書・重要事項説明書（根拠情報）…` のように両方を含めるか、質問に応じて文書種別を合わせる）。

---

## 実装観点（調査 → 修正の順）

### 1. インデックスとデプロイ

- `Config` の `MASTER_TXT_FILES`（または同等）に **`重要事項説明書.txt` が含まれる**こと。`load_txt_documents` で `doc_kind=important_matters` のチャンクが生成されることをテストで担保（既存: `tests/test_document_txt_splitters.py` の `TestImportantMattersIndexing`）。
- **`data/vector_store` が Docker / Cloud Run イメージに含まれる**前提なら、**reindex 後に再ビルド・再デプロイ**しないと本番だけ古い索引のままになる。`deploy/Dockerfile.webhook` と `deploy_webhook.sh` を確認。

### 2. ルーティング

- `is_contract_source_question` / `is_important_matters_question`（`src/contract_query_router.py`）で、**「重要事項説明書」「重説」「重要事項の◯番」** が **マスター参照（contract source）** に入ることを維持する。
- **「抵当権が実行されたら？」** のように書籍名を付けない質問は False のままでよい（チェックリスト B-19 は別経路）。混乱するならログに `contract_source_q` を出す。

### 3. 検索・ランキング

- `src/retrieval_metadata_boost.py` で **重要事項クエリ**のとき **`important_matters` チャンクが契約書に押し負けない**こと。`extract_important_matters_section_id` と chunk の `section_id` の対応を確認（**「重説の16番」** のように `の` 直後に番号が来る表記では section ID が取れない既知挙動がある。必要なら正規表現を改善するか、プロンプトで「重説 16番」のように運用する）。

### 4. 回答生成（LLM）

- contract source 用プロンプト（`rag_answerer.py` 付近）が **重説の**具体的数値・表の内容を **根拠がある限り述べる**よう、過剰な「金額は伏せる」が **重説 §3 にまで適用されていない**か確認。契約書条文の「数値なし」方針と、**重説の月額費用表**は切り分ける。

### 5. 根拠ゼロ時の文言

- `_contract_source_not_found_answer` は **「契約書・重要事項説明書（根拠情報）内では確認できません。」** のように両文書を含める（回帰: `tests/test_contract_source_not_found.py`）。

---

## 完了条件（チェックリスト）

- [ ] 上記検証クエリを **ローカル**で `RAGAnswerer.answer` または `run_simple_eval` / 既存スクリプトで実行し、**幻覚・「記載なし」の誤否定**がない。
- [ ] `python3 -m pytest tests/ -q` が通る（既知の flaky があれば別 issue 化）。
- [ ] `docs/eval_log.md` か本ファイル末尾に **検証コマンドと結果の一言**を追記（任意）。
- [ ] 本番反映時は **vector store 再生成 + イメージ再ビルド**の手順を README か OPERATIONS に1行追記（任意）。

---

## 秘密・安全

- API キー・LINE トークンをチャットやコミットに含めない。
- 個人情報を master TXT に戻さない（既にマスク済みの運用を崩さない）。

---

## 参照ファイル（読む順の目安）

1. `data/documents/重要事項説明書.txt`
2. `src/contract_query_router.py`
3. `src/rag_answerer.py`（contract source merge、not_found、prompt 選択）
4. `src/retrieval_metadata_boost.py`
5. `src/document_loader.py` / `src/document_txt_splitters.py`
6. `tests/test_important_matters_query_router.py`
7. `tests/fixtures/granmare_important_matters_cases.yaml`
8. `docs/testing/CLAUDE_CODE_JUYO_LINE_DEBUG_PROMPT.md`（背景・仮説）

---

## コピペ用短縮版

```text
重要事項説明書.txt を RAG が正しく答えるように実装・修正してください。
正本は data/documents/重要事項説明書.txt。検証: §3 金額、§8 解除、§11 津波区域「外」、
§12 洪水/高潮、§13 石綿、特約④。インデックス・Cloud Run 再デプロイ、
contract_source / retrieval_metadata_boost、プロンプトの数値抑止の過剰適用、
_contract_source_not_found_answer の文書ラベルを確認。pytest 全通過。
秘密を貼らない。詳細は docs/testing/CLAUDE_CODE_JUYO_RAG_IMPLEMENTATION_PROMPT.md
```
