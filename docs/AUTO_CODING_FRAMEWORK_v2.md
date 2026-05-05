# Cursor × Python Auto Coding Framework v2

> 2026-05-05 | Brooks + Pocock + Talk Python 統合版  
> rental_rag / Decision OS 対応

関連: [CURSOR_PROMPTS_FRAMEWORK_v2.md](./CURSOR_PROMPTS_FRAMEWORK_v2.md)（Prompt A〜E）

---

## 思想的基盤

```
Brooks（1986/2010）     Pocock（2026）         Talk Python（2026）
「概念的整合性」    +   「PRD→Kanban→Agent」 +  「小コミット・read-only先行」
      ↓
  このフレームワーク
  「意思決定の分解と制御」
```

**核心命題：** Auto codingとは「コード生成」ではなく「意思決定の分解と制御」である。

人間の責務（委譲禁止）

- 概念的整合性の保持（CONTEXT.md / ADR）
- Essential Complexityの解決（何を作るか）
- 設計制約の定義（AGENTS.md）
- 最終QAの判断

AIの責務（委譲すべき）

- Accidental Complexityの実装
- テスト生成・デバッグ
- ドキュメント生成
- Kanbanチケットの実行

---

## フルワークフロー（9フェーズ）

```
Phase 0  Context Setup      ← 最重要・毎回確認
Phase 1  Idea / Problem
Phase 2  Research           [optional]
Phase 3  Prototype          [optional]
Phase 4  PRD                ← 設計固定・AIの唯一の真実
Phase 5  AGENTS.md          ← v2新規追加・制約の明文化
Phase 6  Kanban             ← タスク分解
Phase 7  Agent Loop         ← 実装ループ
Phase 8  Continuous QA      ← 常時・後工程ではない
Phase 9  Eval / Learning    ← Superforecasting接続
```

---

## Phase 0｜Context Setup（最重要）

**目的：** AIに「どう振る舞うか」を教える。スキップ禁止。

### 必須ファイル構成

```
project/
  CONTEXT.md      # ドメイン知識・語彙定義・ADR
  AGENTS.md       # Agent行動仕様（§5参照）
  PRD.md          # 設計固定（§4参照）
  .cursor/
    rules         # Cursor常時ロードルール（→ Cursor Prompt A）
  docs/
    research.md   # Research蓄積
    eval_log.md   # Eval記録
    decisions/    # ADR置き場
```

### Cursorへの読み込み順

```
1. .cursor/rules    ← 常時ロード（軽量・原則のみ）
2. AGENTS.md        ← タスク開始時に参照指示
3. CONTEXT.md       ← ドメイン質問時に参照指示
4. PRD.md           ← 実装前に確認指示
```

### チェックリスト

- [ ] CONTEXT.md に ADR-001 記載済み
- [ ] AGENTS.md に Forbidden Actions 記載済み
- [ ] .cursor/rules に基本原則記載済み
- [ ] PRD.md が最新状態

---

## Phase 1｜Idea / Problem

**目的：** 問題定義とMVPスコープの確定。

### アウトプット

```
- 問題文（1〜3文）
- MVPスコープ（in / out）
- 成功基準（数値）
- Decision OSとの接続（仮説）
```

### Cursor Prompt（→ Prompt B: PM Agent）

```
後述 Cursor Prompt集 §B 参照
```

---

## Phase 2｜Research（optional）

**目的：** 探索コストの前倒し。実装中の「発見」を減らす。

### 発動条件（いずれか）

- 新規ライブラリの採用判断が必要
- パフォーマンス目標が不明確
- アーキテクチャの代替案がある
- 過去の失敗パターンが想起される

### やること

```
1. read-onlyモードでAgentに既存コードを解析させる（Talk Python原則）
2. docs/research.md に発見を記録
3. 「採用 / 不採用 + 理由」まで結論を出す
```

### Cursor Prompt（→ Prompt C: Research Agent）

---

## Phase 3｜Prototype（optional）

**目的：** 思考の圧縮。早期フィードバック。

### 発動条件

- UI/UXの確認が必要
- 新技術の動作確認が必要
- PRDを書く前にスパイクが必要

### ルール

```
- prototype/ ディレクトリに隔離
- 本番コードへのコピーは明示的に行う
- prototypeのコードはそのまま本番に使わない
```

---

## Phase 4｜PRD（設計固定）

**目的：** AIの唯一の真実。ここが曖昧だと全て崩壊する。

### 必須構造

```markdown
# PRD: <機能名>

## Objective
何を解決するか（1〜2文）

## Background
なぜ今やるか

## User Story
As a <ユーザー>, I want to <アクション>, so that <価値>.

## Acceptance Criteria
- [ ] 基準1（数値付き）
- [ ] 基準2
- [ ] 基準3

## Architecture
- 採用パターン・コンポーネント構成

## Constraints
- 技術制約
- ビジネス制約（弁護士法72条など）
- パフォーマンス制約（500ms以内など）

## Non-Goals
- やらないことの明示

## Open Questions
- 未解決事項（Researchで解決する）
```

---

## Phase 5｜AGENTS.md（v2新規追加）

**目的：** Pocockモデルとの最大差分。AIの行動を制約する。

### 核心：設計制約が探索空間を絞る（Brooks）

```
良い制約 = AIが「何をしないか」を明確に知っている状態
悪い制約 = 実装手段の強制（how の制約）
```

→ 詳細は `AGENTS.md` 参照（別ファイル・完成済み）

---

## Phase 6｜Kanban（タスク分解）

**目的：** PRDをAgentが実行できる粒度に落とす。

### 粒度ルール

```
1タスク = 30〜90分（実装 + テスト込み）
1タスク = 1コミット
1タスク = 依存関係1方向のみ
```

### タスクテンプレート

```markdown
## [TASK-001] <タイトル>

**依存:** TASK-XXX（なければ「なし」）
**スコープ:** src/<対象ファイル>
**完了条件:**
  - [ ] 実装完了
  - [ ] pytest グリーン
  - [ ] ruff / mypy エラー0
  - [ ] レスポンスタイム基準クリア（該当時）
**Escalationトリガー:** <Agent停止条件>
```

### Cursor Prompt（→ Prompt D: Kanban生成）

---

## Phase 7｜Agent Loop（実装）

**目的：** Cursorエージェントによる実装ループ。

### ループ構造

```
┌─────────────────────────────────────┐
│  Plan（タスク読解・影響範囲確認）    │
│    ↓                                │
│  Execute（実装）                    │
│    ↓                                │
│  Observe（4つのゲート確認）         │
│    ↓                 ↓              │
│  ✅ 全グリーン    ❌ 失敗           │
│    ↓              ↓                 │
│  Commit         Fix（最大3回）      │
│    ↓              ↓                 │
│  次タスクへ    3回失敗→Escalation   │
└─────────────────────────────────────┘
```

### Observe 4ゲート（数値基準）

```bash
ruff check src/ tests/          # エラー0件
mypy src/                       # エラー0件
pytest tests/ -v                # 全件パス
pytest tests/performance/ --timeout=1  # hot path < 500ms
```

### 重要ルール

```
- 1タスクごとに必ずcommit（rollback前提）
- diffは小さく保つ（大きなdiff = 破綻のリスク）
- FAISSインデックス変更前は必ずバックアップ
- Master TXT は絶対に変更しない（ADR-001）
```

### Cursor Prompt（→ Prompt E: Worker Agent）

---

## Phase 8｜Continuous QA（常時）

**目的：** 後工程QAではなくタスク単位QA。

### QA層の構造

```
Layer 1: 自動（Agent Loopの4ゲート）← Phase 7で実施
Layer 2: 人間レビュー（PRに対して）← 毎PR必須
Layer 3: 統合テスト（デプロイ前）  ← Cloud Run前
```

### 人間レビューチェックリスト（PR単位）

```
- [ ] 概念的整合性は保たれているか（PRDとの乖離なし）
- [ ] Master TXTは変更されていないか（ADR-001）
- [ ] 弁護士法72条フィルタは機能しているか
- [ ] needs_clarificationロジックは正しいか
- [ ] Semantic Cacheは無効化されていないか
- [ ] 新規依存ライブラリはノートされているか
- [ ] コミットメッセージは規約通りか
```

---

## Phase 9｜Eval / Learning Loop

**目的：** Superforecasting接続。定量改善サイクル。

### 計測指標（スプリント単位）

| 指標 | 定義 | 目標 | Brier的解釈 |
|---|---|---|---|
| Bug Rate | バグ数 / コミット数 | < 0.1 | 精度 |
| Regeneration Rate | Agent再生成率 | < 20% | キャリブレーション |
| needs_clarification Rate | 確認返答 / 全クエリ | 5〜15% | 適切な不確実性表現 |
| KB fast path Hit Rate | Cacheヒット率 | > 60% | 効率 |
| p95 Latency | 95%tile レスポンス | < 500ms | 信頼性 |

### 改善サイクル

```
1. 計測（docs/eval_log.md に記録）
2. 最悪指標を1つ選ぶ
3. docs/research.md に改善仮説を記録
4. 修正タスクをKanbanに追加
5. 再計測
```

---

## Pocockモデルとの差分（v2）

| 項目 | Pocock | v1 | v2（今回） |
|---|---|---|---|
| PRD | ✅ | ✅ | ✅ |
| Kanban | ✅ | ✅ | ✅ + 粒度定義 |
| Agent Loop | ✅ | ✅ | ✅ + Observe数値基準 |
| Context Setup | △弱い | ✅ | ✅ + 読み込み順定義 |
| AGENTS.md | ❌ | ✅ | ✅ 完成版 |
| QA | 後工程 | 常時化 | 3層構造 |
| Escalation | ❌ | ❌ | ✅ 6トリガー |
| Eval | ❌ | 定義のみ | ✅ Brier接続 |
| Cursor Prompts | ❌ | ❌ | ✅ A〜E 全セット |

---

## 失敗パターンDB（随時更新）

| パターン | 原因 | 対策 |
|---|---|---|
| 技術負債の増幅 | 既存コードのパターン踏襲 | Research phaseでread-only解析先行 |
| 大きな差分で破綻 | タスク粒度が粗い | 30〜90分ルール厳守 |
| 設計逸脱 | コンテキスト不足 | Phase 0を毎回実施 |
| 法的回答の生成 | フィルタ漏れ | AGENTS.md §7 + unit test |
| Master TXT汚染 | Forbidden無視 | .cursor/rules に最優先記載 |
| Cacheヒット率低下 | 閾値調整漏れ | Eval Loopで定期計測 |

---

## rental_rag_poc でのパス対応（運用メモ）

フレームワークの汎用パスと、このリポジトリの実体の対応です。

| フレームワークの記載 | rental_rag_poc での参照先 |
|---|---|
| `docs/eval_log.md` | 評価・学習ログは `docs/eval/`、`docs/eval.md`、`docs/eval/forecast_log.md` 等に分散。新規に一本化する場合は Phase 0 で決める |
| `docs/research.md` | 未作成なら Phase 2 で新規作成してよい |
| `docs/decisions/`（ADR） | `docs/decisions/` に ADR ファイルあり。トリアージ・経緯メモは `docs/decision/` も利用 |
| `.cursor/rules` | 例: `rental_rag_framework_v2.mdc`、`rental_rag_poc.mdc` |

第4ゲート（`tests/performance/`）は未整備の場合がある。`AGENTS.md`・`QUALITY_GATE.md` に合わせて同等チェックに置き換える。
