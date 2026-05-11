# Kanban — rental_rag_poc
> Framework v2対応 | Updated: 2026-05-05
> Prompt D（Kanban Agent）の出力先 / 人間による手動管理も可

---

## ステータス定義

| 記号 | 意味 |
|---|---|
| `[ ]` | Backlog（未着手） |
| `[>]` | In Progress（着手中） |
| `[x]` | Done（完了） |
| `[!]` | Blocked / Escalation中 |

---

## 実行順序マップ（現スプリント）

```
[LINEテスト完了] ← 現在地
      ↓
  TASK-001（eval基盤）
      ↓
  TASK-002（performance test整備）
      ↓
  TASK-003（research.md初期作成）
      ↓
  以降はPrompt Dで生成
```

---

## Sprint 1｜LINEテスト後 基盤整備

### [TASK-001] Eval基盤の統一

**ステータス:** `[ ]`  
**依存:** LINEテスト完了  
**スコープ:** `docs/eval_log.md`（新規作成）  
**見積:** 30分

**実装内容:**
- `docs/eval/`・`forecast_log.md` など分散したeval記録を `docs/eval_log.md` に統一
- 以下のフォーマットで初期エントリを作成

```markdown
## 2026-05-05 Sprint 1 Baseline

| 指標 | 計測値 | 目標 | 判定 |
|---|---|---|---|
| Bug Rate | - | < 0.1 | - |
| Regeneration Rate | - | < 20% | - |
| needs_clarification Rate | - | 5〜15% | - |
| KB fast path Hit Rate | - | > 60% | - |
| Hot path p95 latency | - | < 500ms | - |
```

**完了条件:**
- [ ] `docs/eval_log.md` 作成済み
- [ ] Baselineエントリ記入済み
- [ ] 既存evalファイルへのリンクを冒頭に記載
- [ ] ruff / mypy エラー0（Pythonファイル変更がある場合）

**Escalationトリガー:** なし（ドキュメント作業のみ）

---

### [TASK-002] Performance Test基盤整備

**ステータス:** `[ ]`  
**依存:** TASK-001  
**スコープ:** `tests/performance/`（新規ディレクトリ）  
**見積:** 60分

**実装内容:**
- `tests/performance/` ディレクトリ作成
- `tests/performance/test_latency.py` 作成
- KB fast path（Semantic Cache hit）の latency を計測するテストを実装
- 基準値：hot path p95 < 500ms / KB fast path < 100ms

```python
# テスト構成イメージ
def test_kb_fastpath_latency():
    """KB fast path (cache hit) must respond within 100ms."""
    ...

def test_hot_path_p95_latency():
    """Hot path p95 must be under 500ms."""
    ...
```

**完了条件:**
- [ ] `tests/performance/test_latency.py` 作成
- [ ] pytest で計測テストが実行できる
- [ ] ruff / mypy エラー0
- [ ] pytest グリーン
- [ ] AGENTS.md §5 Test Rules の第4ゲートが機能することを確認

**Escalationトリガー:** 計測値が目標の2倍以上ある場合 → 人間に報告して停止

---

### [TASK-003] research.md 初期作成

**ステータス:** `[ ]`  
**依存:** なし（TASK-001と並行可）  
**スコープ:** `docs/research.md`（新規作成）  
**見積:** 30分

**実装内容:**
- `docs/research.md` を新規作成
- これまでの技術的判断をさかのぼって記録
- 最低限、以下の3件を初期エントリとして記録

```markdown
## 2026-05-05: SentenceTransformer モデル選定
**背景:** 日本語賃貸クエリへの適合性確認
**発見:** ...
**結論:** 採用 / 現行モデル名
**参照:** ...

## 2026-05-05: FAISS インデックス構成
**背景:** ...
**結論:** ...

## 2026-05-05: Semantic Cache TTL設定
**背景:** ...
**結論:** TTL=3600s を採用
**参照:** CONTEXT.md
```

**完了条件:**
- [ ] `docs/research.md` 作成済み
- [ ] 初期エントリ3件以上記録
- [ ] Prompt C（Research Agent）の出力先として使える状態

**Escalationトリガー:** なし

---

## Sprint 2｜Cloud Run 本番化タスク

### [TASK-010] Firestore 冪等性の不整合対応

**ステータス:** `[x]`  
**依存:** Phase 2-1（Firestore idempotency 実装済み）  
**スコープ:** `src/interfaces/line/idempotency.py`  
**見積:** 45〜60分

**設計メモ（1行）:**  
`_firestore_mark_aborted` の read-then-delete が非トランザクションのため、2インスタンス競合時に `processing` エントリが残る可能性がある。

**実装内容:**
- `_firestore_mark_aborted` をトランザクション化（`firestore.transactional` デコレータ）
- Firestore TTL ポリシーの設計メモ追加（`line_message_ids` コレクションに TTL フィールド設定案）
- `FIRESTORE_IDEMPOTENCY_ENABLED=true` での統合テストケース追加（Firestore エミュレータ or モック）

**完了条件:**
- [ ] `_firestore_mark_aborted` がトランザクション内で status 確認 → delete を行う
- [ ] pytest グリーン維持（276 passed 以上）
- [ ] ruff / mypy（対象ファイル）エラー 0

**Escalationトリガー:** Firestore エミュレータのセットアップが困難な場合 → モックで代替し人間に確認

---

### [TASK-004] TBD — LINEテスト結果による

**ステータス:** `[ ]`  
**依存:** LINEテスト完了 + TASK-001〜003  
**スコープ:** TBD  
**見積:** TBD

> Prompt D に以下を渡して生成：
> ```
> PRD: <LINEテスト後に作成するPRD>
> ```

---

## Backlog（未スプリント割り当て）

> 将来的に対応する可能性があるタスク。優先度未決定。

| ID | タイトル | 理由 |
|---|---|---|
| BACKLOG-001 | needs_clarification 閾値チューニング | Eval結果次第 |
| BACKLOG-002 | Semantic Cache ヒット率改善 | Eval結果次第 |
| BACKLOG-003 | RAG正答率のeval set整備 | 品質基準の定量化 |
| BACKLOG-004 | ADR-002 作成（次の設計変更時） | 変更発生時 |

### [TASK-005] 既存コードのlint・型エラー解消

**ステータス:** `[ ]`  
**依存:** なし（LINEテストと並行可）  
**スコープ:** `src/` `tests/` 配下の既存エラー  
**見積:** 60〜90分

**実装内容:**
- `ruff check src/ tests/` のエラーを解消
- `mypy src/` の型エラーを解消

**完了条件:**
- [ ] ruff エラー0件
- [ ] mypy エラー0件
- [ ] pytest 257 passed 維持

**Escalationトリガー:** 修正により pytest が失敗した場合

---

### [TASK-006] clarification文脈引き継ぎ・退去解約取りこぼし対策

**ステータス:** `[x]`  
**依存:** TASK-A/B/C（122c42f）  
**スコープ:** `src/interfaces/line/handler.py` `src/rag_answerer.py` `docs/testing/LINE_MANUAL_TEST_CASES.md`  
**見積:** 45〜60分

**実装内容:**
- `answer()`に`prior_clarification_*`引数を追加
- `try_kb_fast_path()`にprior文脈を渡す処理を追加
- `_inject_tai_kyo_kaiyaku_deal_row()`を追加（退去解約の取りこぼし対策）
- `LINE_MANUAL_TEST_CASES.md`に`prior_clarification`回帰試験セクションを追加

**完了条件:**
- [ ] pytest 257 passed 以上を維持
- [ ] ruff / mypy（src対象ファイルのみ）エラー0
- [ ] `LINE_MANUAL_TEST_CASES.md`の回帰試験手順が確認できる状態

**Escalationトリガー:** pytestが落ちた場合

**コミットメッセージ候補:**
`feat(rag): add prior_clarification context propagation and taikiyo injection [TASK-006]`

---

### [TASK-007] 検索タイムアウト対策

**ステータス:** [x]
**依存:** なし
**スコープ:** src/rag_answerer.py / Cloud Run設定
**実装内容:**
  - deal/master各コレクションのタイムアウト閾値を見直し
  - Cloud Run 最小インスタンス数を1に設定（cold start排除）
  - CPU/メモリ設定の確認・調整
**完了条件:**
  - [ ] "Timeout searching" ログが出なくなる
  - [ ] pytest グリーン維持（271 passed以上）
  - [ ] ruff / mypy（対象ファイル）エラー0
**見積:** 60分
**Escalationトリガー:** タイムアウト原因が外部API起因の場合

---

### [TASK-008] フォールバック過多の削減

**ステータス:** [ ]
**依存:** TASK-007
**スコープ:** data/documents/ / src/kb_fast_path.py
**実装内容:**
  - ログでmissしたクエリを特定・リストアップ
  - faq_kb.csv / Master TXTにカバレッジ追加
  - kb_fast_pathの閾値・同義語を調整
**完了条件:**
  - [ ] フォールバック率 < 20%（eval_log.mdで計測）
  - [ ] pytest グリーン維持
  - [ ] ruff / mypy（対象ファイル）エラー0
**見積:** 60〜90分
**Escalationトリガー:** なし

---

### [TASK-009] B-6監査ログの強化

**ステータス:** [x]
**依存:** なし（TASK-007と並行可）
**スコープ:** src/management_escalation.py / src/interfaces/line/handler.py
**実装内容:**
  - 返信本文（マスク版）・法的断定フラグ・判定理由を構造化ログに出力
  - Cloud RunログからB-6合否を判定できる状態にする
**完了条件:**
  - [ ] B-6入力・出力・法的断定フラグがログに記録される
  - [ ] pytest グリーン維持
  - [ ] ruff / mypy（対象ファイル）エラー0
**見積:** 45分
**Escalationトリガー:** なし
**コミットメッセージ候補:**
  feat(compliance): add B-6 audit logging for legal assertion [TASK-009]

---

## Done

| ID | タイトル | 完了日 | コミット |
|---|---|---|---|
| TASK-009 | B-6監査ログの強化 | 2026-05-05 | 5bc4c48 |
| TASK-007 | 検索タイムアウト対策（3→10s, print→logger） | 2026-05-11 | a15e470 |
| TASK-010 | Firestore _mark_aborted トランザクション化 | 2026-05-11 | 1511a7d |
| TASK-006 | clarification文脈引き継ぎ・退去解約取りこぼし対策 | 2026-05-05 | fce8e9d |
| - | Cloud Run hardening Phase 1-3〜2-3 | 2026-05-11 | 48a4ac8 |
| - | AGENTS.md 作成 | 2026-05-05 | - |
| - | FRAMEWORK v2 作成 | 2026-05-05 | - |
| - | CURSOR_PROMPTS 作成 | 2026-05-05 | - |
| - | .cursor/rules 設置 | 2026-05-05 | - |

---

## Escalation Log

> Agentが停止して人間に報告した記録。

| 日時 | タスク | 理由 | 解決方法 |
|---|---|---|---|
| - | - | - | - |

---

## 運用ルール

```
1. Sprint開始時：実行順序マップを更新する
2. タスク着手時：ステータスを [ ] → [>] に変更する
3. タスク完了時：ステータスを [>] → [x] に変更し Done テーブルに移動
4. Escalation時：ステータスを [!] にして Escalation Log に記録
5. Sprint終了時：docs/eval_log.md に指標を記録する
```
