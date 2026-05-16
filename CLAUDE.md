# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Build & Test

```bash
# 仮想環境
source .venv/bin/activate   # または .venv/bin/python で直接実行

# テスト（ユニット）
.venv/bin/python -m pytest tests/ -q

# 特定テスト
.venv/bin/python -m pytest tests/test_kb_fast_path.py tests/test_clarification_numeric_reply.py -q

# 統合テスト（実API/ベクターDB使用）
.venv/bin/python -m pytest tests/ -m integration -q

# ルーター評価（A/B比較・キャッシュ無効化）
.venv/bin/python scripts/run_eval.py \
  --dataset eval/datasets/line_rag_eval_router_abcd_v1.csv \
  --ab-compare --disable-semantic-cache

# ベクターDB再インデックス（data/ 変更後に必須）
.venv/bin/python scripts/reindex_vector_db.py

# ローカルサーバー起動
.venv/bin/python -m uvicorn src.api.main:app --reload
```

### 評価後の確認ファイル

```bash
cat data/eval/ab_summary.json           # route_metrics.router_kpis を主に見る
cat data/eval/ab_scored_summary.json
cat data/eval/ab_diff_report.jsonl
cat data/eval/route_mismatch_report.jsonl
```

### 主要 KPI（`route_metrics.router_kpis`）

| KPI | 意味 | 目標 |
|---|---|---|
| `A_non_rag_rate` | FAQ クエリが RAG を使わず処理される割合 | 1.0 |
| `B_rag_rate` | 契約クエリが RAG に到達する割合 | 1.0 |
| `D_escalation_rate` | 法的クエリがエスカレーションされる割合 | 1.0 |
| `Recall@5` | 期待 doc が上位 5 件に含まれる割合 | ≥ 0.5 |
| `hallucination_fact_error` | 明確な虚偽 | **0.0 必須** |

---

## Architecture Overview

**Routing-First RAG** — RAG をデフォルトにしない設計。

```
User Query
    ↓
[1] Fast Path        keyword match → 即答（サブ秒）
    ↓
[2] Rule Engine      deterministic logic（費用・禁止事項）
    ↓
[3] Clarification    短い・曖昧なクエリを確認質問
    ↓
[4] Escalation       法的・判断系 → 管理会社にエスカレーション
    ↓
[5] RAG              契約書参照クエリのみ（最後の手段）
```

### クエリ分類（A/B/C/D）

| タイプ | 例 | ルート |
|---|---|---|
| A（非RAG） | "水漏れしています" / "Is smoking allowed?" | Fast Path / Rule |
| B（RAG） | "契約の違約金は？" | RAG |
| C（Clarification） | "ガスの件" | Clarification |
| D（Escalation） | "違法ですか？" / "補償請求できますか？" | Escalation |

### 主要ファイル

| ファイル | 役割 |
|---|---|
| `src/kb_fast_path.py` | Fast Path（キーワードスコアリング） |
| `src/rag_answerer.py` | RAG メインロジック（検索・生成） |
| `src/router/` | ルーティング判定 |
| `src/interfaces/line/handler.py` | LINE webhook |
| `src/config.py` | 全設定値（env 変数との対応） |
| `data/faq_kb.csv` | FAQ ナレッジベース |
| `data/documents/` | 契約書 TXT（Master TXT） |
| `data/vector_store/` | Chroma ベクターDB（コミット禁止） |

### 情報源の優先順位（ADR-001）

**Master TXT（契約書 TXT）＞ KB（CSV）**  
KB は Master TXT の要約・ルーティング層。数値が含まれる KB エントリは必ず原文条番号ポインタを付ける。

---

## Conventions & Patterns

### 変更時のルール

1. **レイヤーを混ぜない** — KB 変更・RAG 変更・deploy 変更を 1 コミットに混在させない
2. **KB 変更後は必ず再インデックス** — `scripts/reindex_vector_db.py` を実行してから評価
3. **ローカル＝クラウド原則** — クラウド専用の閾値をコードに埋め込まない。差分は env var で管理
4. **A/B 評価は `--disable-semantic-cache` 必須** — キャッシュ汚染を防ぐ
5. **`git add .` 禁止** — `git add -p` または個別ファイル指定

### コミット禁止ファイル

```
.env
data/vector_store/
eval/runs/
logs/
deploy/.env.gcp
```

### Fast Path 変更時の必須テスト

```bash
.venv/bin/python -m pytest tests/test_kb_fast_path.py tests/test_clarification_numeric_reply.py -q
```

### 変更後の報告フォーマット

1. 変更したファイル
2. 各変更の目的
3. 実行したテスト
4. 実行した評価（該当する場合）
5. 既知リスク
6. 次に推奨するコマンド

### 評価が悪いときの診断順序（Metrics v2）

1. `IDMatchRate < 0.9` → 評価設計を直す（検索を触るな）
2. `Recall@5 < 50%` → Retrieval or Corpus
3. `Completeness < 1.0` → Generation 制御
4. `EvidenceBinding < 0.8` → Prompt / Schema
5. `Hallucination.fact_error > 0` → **即ブロック**
