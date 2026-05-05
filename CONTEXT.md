# rental_rag 共有語彙（CONTEXT）

このファイルはコード実装に基づく用語定義と、運用・プロダクト上まだ決め切れていない論点を分離して書く。

---

## 1. KB fast path（KB hit）と RAG path

| 用語 | 定義（実装） |
|------|----------------|
| **KB fast path** | `faq_kb.csv` を `load_kb_csv` で読み、`fast_path_enabled=true` の行だけを `try_kb_fast_path`（`src/kb_fast_path.py`）でキーワードスコアリングする経路。FAISS / ベクトル検索は使わない。 |
| **KB hit** | 上記の結果 `KBFastPathResult.kind == "hit"` で、`answer` フィールドのプレーンテキストをそのまま返すこと。 |
| **RAG path** | KB fast path が miss（または契約ソース質問で KB hit が抑止）のあと、`RAGAnswerer` がベクトルストア検索・リランク・LLM 生成まで行う経路。 |

**処理順（`RAGAnswerer.answer` 内）**  
1. QueryCache（完全一致 → 許可時は意味的類似）  
2. 管理会社エスカレーション / 個別契約ハンドオフ  
3. 契約ナビ曖昧パターン（clarification）  
4. **KB fast path**（hit / clarification）— `contract_source_q` が真のときは hit を出さない（`not contract_source_q`）  
5. ベクトル検索・生成  

**LINE webhook（`src/interfaces/line/handler.py`）**  
- 先に **同一の** `try_kb_fast_path` を実行し、hit / clarification なら **そこで返信して終了**（`RAGAnswerer` を呼ばない）。  
- miss のときだけ `rag_answerer.answer(..., persist_cache=False)`。返信成功後に `bundle.query_cache.set(effective_text, response)` でキャッシュのみ更新。

**コードとコメントの差分（把握用）**  
- `kb_fast_path.py` 先頭コメントは「fast path hit/clarification must not populate QueryCache」とあるが、**CLI / チャット等で `persist_cache=True` のまま KB hit が `answer` 内に到達した場合**は `_persist_to_cache` が呼ばれ得る（ただし `decision_path=direct` は `include_embedding=False` で exact 寄りのエントリ）。LINE 経路では fast path 分岐ではキャッシュに触れない。

---

## 2. Semantic Cache（QueryCache の意味的ヒット）

| 項目 | 実装 |
|------|------|
| クラス | `src/query_cache.py` の `QueryCache` |
| 既定しきい値 | `Config.cache_semantic_threshold`、**既定値 0.85**（`env.example` の `CACHE_SEMANTIC_THRESHOLD=0.85` と一致）。プロンプト等で「0.80」と書く場合は **デプロイ環境の実値を確認**すること。 |
| 取得順 | `get`: 完全一致 → `allow_semantic` が真ならコサイン類似度がしきい値以上の最良エントリ。 |
| **RAG path との前後** | `RAGAnswerer.answer` の **先頭** でキャッシュ参照。ミスしたあと KB fast path・検索・生成が走る。 |
| **KB hit との前後（LINE）** | KB fast path は **キャッシュ参照より前**（handler 側で完結）。KB で返した応答は QueryCache に **書かない**。 |
| **KB hit との前後（RAGAnswerer のみ）** | キャッシュ参照が **KB fast path より前**。キャッシュに載っている過去応答（RAG で生成したもの等）があれば KB より先に返る。 |

---

## 3. clarification（確認質問）と `needs_clarification_when_short`

CSV 列名は **`needs_clarification_when_short`**（「needs_clarification」単体ではない）。

`try_kb_fast_path` で `kind="clarification"` になる主な理由:

| 理由（`match_detail` / ログ） | 条件の要約 |
|------------------------------|------------|
| `ambiguous_topic` | 閾値未満だがスコア>0 かつ `_is_ambiguous_topic_query`（例: `AMBIGUOUS_TOPIC_PATTERNS`、または「の件/について/のことで」+ 曖昧トピック1語 + シグナル弱） |
| `ambiguity` | トップ2候補がともに閾値以上かつスコア差が `kb_fast_path_ambiguity_delta` 以下 |
| `short_query` | 正規化クエリ長が `kb_fast_path_short_max_len` 以下 **かつ** 当該行 `needs_clarification_when_short=true` **かつ** `clarification_prompt` あり **かつ** `is_specific_even_if_short` でない |

「短い質問でも即答できる場合」は、同一意図への **prior clarification**（LINE の `clarification_followup`）で `short` 判定が緩む、または `is_specific_even_if_short`（完全一致ボーナス・十分な長さ・高スコア等）でショート用確認をバイパスする、などコードで分岐している。

**Skills と実装**  
- 運用ガイドや SKILL が「needs_clarification」と言う場合は、多くは **この CSV 列または clarification 系の挙動全体**を指すメタファーとして読む。厳密名は上記 CSV 列と `clarification_reason` を正とする。

---

## 4. Master TXT と KB エントリ（権威のルール・実装）

| ソース | 役割 |
|--------|------|
| **Master TXT** | `master_txt_files` で列挙された全文テキストをチャンク化しベクトル化。契約・重要事項の **原文根拠** として検索される。 |
| **KB エントリ（CSV）** | 構造化 FAQ。fast path 用の `answer` と、ベクトルストア上の `type=kb_faq` チャンクの両方に関与し得る。 |
| **契約ソース質問** | `is_contract_source_question` が真のとき、KB fast path の **hit は使わない**（マスター文言への問い合わせを RAG に寄せる）。RAG 側は `rag_contract_source_drop_kb_faq_entirely`（既定 true）により、証拠・生成コンテキストから **kb_faq を落とし得る**。 |
| **非契約ソース** | リランク後、`kb_faq` チャンクがあれば `_select_docs_for_answer` で **kb_faq を優先**（マスターと併存時は FAQ 側を生成入力に寄せる）。 |

**情報の「正」と KB の位置づけ**  
- 優先順位・運用ルールは **第6節 ADR-001** に従う（Master TXT を正、KB は要約＋ルーティング）。

---

## 5. 関連設定キー（grep 用）

- KB fast path: `kb_fast_path_*`（`config.py`）
- キャッシュ: `enable_query_cache`, `cache_semantic_threshold`, `cache_semantic_ttl_sec`, …
- 契約ソース: `rag_contract_source_drop_kb_faq_entirely`, `contract_query_router.is_contract_source_question`

---

## 6. 実装メモ（ADR 候補）

1. **LINE: `try_kb_fast_path` に `prior_*` を渡すが、`RAGAnswerer.answer` 内の `try_kb_fast_path` 呼び出しには `prior_*` を渡していない**  
   miss 後に RAG へ進んだ場合、clarification フォロー状態が二段目で再現されない可能性がある。意図的かバグかを ADR で固定したい。

2. **「意味的キャッシュの既定しきい値 0.85」とドキュメント上の 0.80 の食い違い**  
   本番 `line-webhook-00018-sbq` の環境変数で上書きされているなら CONTEXT の数値を環境に合わせて更新する。

---

## ADR-001: KB と Master TXT の情報優先順位

**決定日**: 2026-05-04  
**ステータス**: 承認済み

### 決定

**Master TXT を「正」の情報源とする。KB エントリは Master TXT の要約＋ルーティング層に留める。**

### 背景

KB（CSV の `answer` / kb_faq チャンク）と Master TXT（重要事項説明書・契約書原文）の内容が将来的に食い違う可能性がある。どちらを整備の基準にするかを明示する必要があった。

### 理由

1. **法的優先順位**: 署名済み契約書・重要事項説明書は法的に KB より上位。KB を正にすると差分発生時に「どちらが有効か」という問題が生じる。
2. **メンテナンスコスト**: KB エントリは人手で書くため陳腐化する。Master TXT は差し替えのみで完結し、二重管理を避けられる。
3. **弁護士法72条との整合**: KB の `answer` が断言形式になると法的助言に近づく。「Master TXT の要約」という位置づけにすることで「詳細は契約書をご確認ください」という免責が自然に機能する。

### ルール

- KB エントリの `answer` は **Master TXT の要約** であり、正確な内容は原文を参照すること、という前提で記述する。
- 金額・日数・条件など **数値が含まれる場合**は、Master TXT の当該箇所へのポインタ（条番号・セクション名）を必ず含める。
- KB と Master TXT が食い違った場合は、**KB エントリを削除して RAG path に委ねる**。KB 側を訂正して正にすることはしない。
- KB は「即答できる明確な質問のルーティング」に徹し、曖昧・法的解釈を要する質問は RAG path（Master TXT 全文検索）へ流す。

### 影響する実装箇所

- `kb_handler.py` — KB エントリの `answer` 記述ポリシー
- `rag_answerer.py` — `_select_docs_for_answer` での KB vs Master TXT 選択ロジック
- KB CSV — 数値を含む全エントリのポインタ追記（今後の整備タスク）

（本リポジトリに `kb_handler.py` が無い場合は、上記ポリシーは `data/faq_kb.csv` 整備・`kb_fast_path.py`・関連 SKILL / 運用ドキュメントに紐づけて扱う。）

### 再検討トリガー

KB エントリ数が 100 件を超えた場合、または Master TXT の更新頻度が月1回を超えた場合は本 ADR を再検討する。

**2026-05-04 fix**: `RAGAnswerer.answer()` に `prior_clarification_*` 3引数を追加し、内部の `try_kb_fast_path` に転送。KB miss → RAG fallback 時のフォロー文脈ゼロクリアを修正。

---

*最終更新: 2026-05-04 — ADR-001 追記（Assignment 3 - Solutions / rental_rag_poc）。*
