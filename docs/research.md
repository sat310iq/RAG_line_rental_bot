# Research Log — rental_rag_poc
> Prompt C（Research Agent）の出力先
> 更新タイミング：新ライブラリ評価 / パフォーマンス調査 / アーキ代替案検討 / 閾値調整時

---

## 使い方
```
1. Prompt C を Cursor チャットに貼る
2. Research Agentが調査して本ファイルに追記する
3. 「採用 / 不採用 + 理由」まで必ず結論を出す
4. 未解決はOpen Questionsセクションへ
```

---

## フォーマット（テンプレート）

```markdown
## YYYY-MM-DD: <トピック>
**背景:** なぜ調査したか
**発見:** 何がわかったか（箇条書き）
**比較:**
| 選択肢 | Pros | Cons | latency影響 |
|---|---|---|---|
| A | | | |
| B | | | |
**結論:** 採用 / 不採用 + 理由
**参照:** URL or ファイルパス
```

---

## 初期エントリ（既知の設計判断を遡及記録）

### 2026-05-05: SentenceTransformer モデル選定（Semantic Cache用）
**背景:** Semantic Cache のクエリ類似度計算に使うモデルの選定。ドキュメント埋め込みは別系統（OpenAI `text-embedding-3-small`）。
**発見:**
- 用途は「クエリ同士のcos類似度」のみ。ドキュメント検索精度とは別軸。
- `paraphrase-multilingual-MiniLM-L12-v2`：多言語対応・軽量（~70MB）・推論が高速
- 日本語特化モデル（multilingual-e5など）は精度が高いがサイズが大きくCloud Runコールドスタートに不利
- キャッシュヒット判定の閾値（cos≥0.85）とセットで評価する必要がある
**比較:**
| モデル | サイズ | 日本語精度 | Cold Start影響 |
|---|---|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | ~70MB | 十分（賃貸ドメイン語彙） | 小 |
| multilingual-e5-large | ~560MB | 高 | 大 |
**結論:** 採用（`paraphrase-multilingual-MiniLM-L12-v2`）。Semantic Cache は補助的位置付けのため軽量優先。
**参照:** `src/query_cache.py` L41 / CONTEXT.md / ADR-001

---

### 2026-05-05: ベクトルストア選定（ChromaDB）
**背景:** ドキュメント埋め込み・検索を担うベクトルDBの選定。埋め込みモデルは OpenAI `text-embedding-3-small`。
**発見:**
- ChromaDB Persistent は SQLite+HNSW ベース。ローカルファイル完結でクラウド専用インフラ不要。
- FAISS は高速だが Cloud Run コンテナ再起動でメモリインデックスが消滅する（永続化に別実装が必要）
- 現 KB 規模（FAQ ~80件 + Master TXT チャンク数十件）ではHNSWとFlatの差は無視できる
**比較:**
| 選択肢 | 永続化 | 更新コスト | Cloud Run適合 |
|---|---|---|---|
| ChromaDB (HNSW) | ✅ SQLite永続 | reindex_vector_db.py 1コマンド | ✅ |
| FAISS Flat | ❌ メモリのみ | 全再構築 | ❌（再起動で消滅） |
| Pinecone | ✅ | API経由 | ✅ 高コスト |
**結論:** 採用（ChromaDB）。PoC規模では性能十分、ローカル=クラウド原則を満たす。スケールアウト時は Pinecone/Weaviate への移行を検討。
**参照:** `src/vector_store_manager.py` / `data/vector_store/` / AGENTS.md §2

---

### 2026-05-05: Semantic Cache TTL設定
**背景:** キャッシュ鮮度と計算コスト削減のバランス
**発見:**
- 賃貸情報は物件ごとに変動するが、一般的なQ&A（敷金とは？など）は長期安定
- TTL短すぎ → キャッシュ効果薄、コスト増
- TTL長すぎ → 古い情報が返る可能性
- Exact hit と Semantic hit で TTL を分けることで、完全一致は長く保持・曖昧一致は早めに失効
**結論:** 採用（exact TTL=3600s / semantic TTL=1800s / cos閾値=0.85）。KB更新時はキャッシュバージョンキー（KB mtime + manifest sha256）で自動無効化。
**参照:** `src/config.py` L184-196 / `src/query_cache.py` / AGENTS.md §4 Cache Rules

---

### 2026-05-05: needs_clarification 閾値
**背景:** 意図確信度の閾値設計。低すぎると頻繁に確認が入りUX悪化、高すぎると誤回答増加。
**発見:**
- 目標値：全クエリの5〜15%で発動が適切（eval_log.md参照）
- 現行閾値：（LINEテスト後に計測・記録）
**結論:** 継続観察。LINEテスト結果でneeds_clarification Rateを計測してから調整。
**参照:** AGENTS.md §3 / eval_log.md

---

## Open Questions

> 未解決の技術的問い。Researchフェーズで解決したらエントリに昇格する。

| # | 問い | 優先度 | 関連タスク |
|---|---|---|---|
| OQ-002 | KB fast path の最小ヒット率はどう計測するか | 中 | TASK-002後 |
| OQ-003 | needs_clarification閾値の最適値（LINEテスト後） | 中 | Sprint 2 |
| OQ-004 | Semantic Cacheの物件固有クエリスキップ実装方法 | 低 | Backlog |
| OQ-006 | 弁護士法72条フィルタが「条項の紹介」と「法的断定」を正しく区別できているか（B-6テスト前提） | 高 | LINEテスト前 |

### 解決済みOpen Questions

| ID | 状態 | 内容 | 解決日 |
|---|---|---|---|
| OQ-005 | ✅ 解決済み | ハザードマップURL登録完了 | 2026-05-05 |
| OQ-001 | ✅ 解決済み | 手動計測（`time.perf_counter`）を採用。pytest-timeout は「テストの打ち切り」であり計測用途には不向き。TASK-002 で `tests/performance/test_latency.py` として実装済み。 | 2026-05-17 |

---

### 2026-05-11: rag_search_timeout_sec 3s → 10s への変更根拠（TASK-007）
**背景:** Cloud Run warm インスタンスでタイムアウトエラー（"Timeout searching"）が発生。原因調査が必要だった。
**発見:**
- 旧設定 3s は Cold Start 排除後のウォーム状態でも稀にタイムアウト
- ChromaDB クエリは GCP 2GiB インスタンスで最大 5〜7s かかることを実測
- Cloud Run タイムアウト 60s に対して 10s は余裕があり、ユーザー体感に影響しない
- `print()` → `logger.info()` 変更で Cloud Run Logs Explorer からタイムアウト原因が追跡可能になった
**結論:** 採用（10s）。Cloud Run 最小インスタンス数 1 でコールドスタートを排除し、10s が実質的な上限として機能。
**参照:** `src/config.py` L64 / commit a15e470 / `docs/CLOUD_RUN_CONSTRAINTS.md`（タイムアウト設定の根拠を同ファイルに追記済み）

---

### 2026-05-12: KB fast path スコアリング設計（TASK-008 / 活用形修正）
**背景:** フォールバック率 26% の原因が「活用形不一致」にあることが判明。KB の primary/secondary キーワードを辞書形で登録していたが、クエリは活用形で来ることが多い。
**発見:**
- `normalize_for_match()` は NFKC + lower + 記号除去のみ。活用形は変換されない。
- `_term_matches()` は部分一致 (`tn in q_norm`) で判定 → 辞書形キーワードが活用形クエリにヒットしない
- 7 インテント（鍵_紛失・設備_エアコン・設備_ガス故障・設備_停電・契約_家賃減額・契約_無断同居・管理会社_連絡先）で miss→hit/clarification に改善
- スコアリング重み: primary=3pt / secondary=1pt / synonym=1pt / exclude=-5pt
- **exact_primary_bonus**: クエリ正規化形が primary キーワードと完全一致した場合、追加で +3pt（`src/kb_fast_path.py` L194-198）。これにより単語 1 語の完全一致で閾値 4pt を単独突破できる。
**結論:** 採用（活用形を secondary に追加）。辞書形に加えて代表的な活用形（〜ました・〜ません・〜したい）を secondary として登録するルールを確立。スコア閾値（4pt）は変更せず活用形で到達可能にする。
**参照:** `data/faq_kb.csv` / `src/kb_fast_path.py` L23-27, L194-219 / commit 96919b5 / docs/eval_log.md Sprint 2

---

## 2026-05-05: Master TXT KB登録内容確認（LINEテスト前）
**背景:** LINE_TEST_CHECKLIST.md v2（B-1〜B-24）対応のため
**確認項目と結果:**

| 確認項目 | 登録済み | 備考 |
|---|---|---|
| 特約①〜⑫の内容 | ✅ | `data/documents/グランマーレ大分空港契約書.txt` に連番で記載あり |
| 別表I 原状回復（貸主・借主負担区分） | ✅ | 第I部（通常損耗/故意過失）を確認 |
| 別表II 部位別負担（クロス面単位など） | ✅ | 第II部に「クロス 面単位」等の記載あり |
| 国東市ハザードマップURL | ✅ | `重要事項説明書.txt` にWEB版URLを追記済み |
| 重説§1 抵当権補足の内容 | ✅ | `重要事項説明書.txt` に抵当権補足説明を確認 |

**結論:** 登録済み
**参照:** `data/documents/グランマーレ大分空港契約書.txt`, `data/documents/重要事項説明書.txt`（`data/master/` 配下は未配置のためMaster TXT運用ファイルとして `data/documents/` を確認）
