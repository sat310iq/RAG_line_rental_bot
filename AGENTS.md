# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Task Management

This project uses Beads (`bd`) for task tracking. Use `bd` commands to:

- Create and track tasks
- Manage dependencies between tasks
- View ready-to-work tasks with `bd ready`
- Get workflow context with `bd prime`

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
bd prime              # Get workflow context (~1-2k tokens)
bd create "Title" -p 0  # Create a P0 task
bd dep add <child> <parent>  # Link tasks (child depends on parent)
```

## Workflow

1. Check ready tasks: `bd ready`
2. Create new tasks: `bd create "Description" -p <priority>`
3. Link dependencies: `bd dep add <child> <parent>`
4. View task details: `bd show <id>`
5. Claim work: `bd update <id> --status=in_progress`
6. Complete work: `bd close <id>`

## Planモードでのタスク作成

**PlanモードでBeadsタスクを作成する際は、必ずテンプレートを使用してください。**

### 手順

1. **タスクタイプの判定**
   - 通常タスク（新機能、改善、リファクタリング）→ `beads-task-template.md`
   - バグ調査（原因特定、障害対応）→ `bug-triage-template.md`

2. **テンプレートの読み込み**
   - `.cursor/rules/beads-task-template.md` または `.cursor/rules/bug-triage-template.md` を読み込む

3. **テンプレートに基づいてdescriptionを生成**
   - ユーザーから取得した情報（Objective, Context, Constraints等）をテンプレートに埋める
   - **テンプレートの全セクションを含める**（Objective, Success Criteria, Decision Hygiene Protocol, Deliverables, Constraints, Test Plan, Execution Plan, Reporting Format）
   - バグ調査の場合は**Hypothesis Table（仮説3つ以上）**が必須

4. **Beads Issueとして作成**
   - `bd create`コマンドが使える場合: `bd create --title="..." --type=[task|bug] --priority=[0|1|2] --description="[生成したdescription]"`
   - `bd`コマンドが使えない場合: `.beads/issues.jsonl`にJSON Lines形式で直接追加（詳細は`.cursor/rules/beads-plan-mode.md`を参照）

### テンプレートファイル

- 通常タスク: `.cursor/rules/beads-task-template.md`
- バグ調査: `.cursor/rules/bug-triage-template.md`
- Planモード詳細手順: `.cursor/rules/beads-plan-mode.md`

### 重要ルール

- ✅ テンプレートの**すべてのセクション**を含める
- ✅ 仮説は最低3つ（バグ調査の場合）
- ✅ テスト計画は**先に**書く
- ✅ Decision Hygiene Protocolを必ず含める
- ✅ 適切なpriorityを設定（0=最高, 1=高, 2=中）

### ローカル＝クラウドのデプロイルール（固定）

**ルール**: ローカル（MacPC）で確認した振る舞いをそのままクラウド（Cloud Run）にデプロイする。今後もこの原則を守る。

- **設定の一致**: コードの既定値（`src/config.py`）はローカルの `env.example` / `.env` と整合させる。Cloud Run で環境変数を追加しない限り、ローカルと同じ既定値が使われるようにする。
- **データの一致**: デプロイ前に必ずローカルで `python3 scripts/reindex_vector_db.py` を実行し、その直後の `data/`（`data/vector_store`, `data/faq_kb.csv` 等）でビルドする。`deploy_webhook.sh` の事前チェック（vector_store の存在）を守る。
- **差分の禁止**: クラウド専用で「ローカルと違う閾値・取得件数」をコードに埋め込まない。クラウド用の調整は環境変数で行い、既定値はローカルと同じにする。
- 詳細: `docs/LOCAL_VS_CLOUDRUN.md` を参照。

### 評価方法と結果の見方

評価スクリプト（`scripts/run_simple_eval.py`）を実行すると、以下のメトリクスが計算されます：

- **Recall@5 / Recall@10**: 期待されるドキュメントが検索結果の上位5件/10件に含まれる割合
- **MRR**: 期待されるドキュメントが最初に出現する順位の逆数の平均
- **Relevance**: 回答が質問に関連しているか（LLM評価）
- **Hallucination**: 回答に根拠情報に基づかない情報が含まれる割合（LLM評価）
- **PII Leakage Rate**: 個人情報が漏洩した質問の割合
- **Prohibited Mention Rate**: 禁止事項が言及された質問の割合

評価結果は`data/eval/`ディレクトリに保存され、Comet ML (OPIK)にも記録されます。詳細は`README.md`の「評価メトリクスの見方」セクションを参照してください。

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
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

## Evaluation System Improvements

### Phase 1: Initial Fixes (2026-01-23)

#### Problem
- Recall@k metrics were 0.0 because document IDs were not correctly extracted from evidence
- LLM-generated evidence strings did not match expected document ID formats

#### Solution
- Modified `RAGAnswerer.answer()` to extract actual document IDs from reranked documents
- Replaced LLM-generated evidence with actual document IDs (intent for FAQ, stable_id for OPS, filename+page for PDF)
- Simplified `extract_doc_ids_from_evidence()` since evidence now contains IDs directly
- Added cache clearing in evaluation script for fresh results

#### Results
- **Before**: avg_recall_at_5: 0.00, avg_relevance: 0.90, avg_hallucination: 0.90
- **After**: avg_recall_at_5: 0.10, avg_relevance: 0.80, avg_hallucination: 0.80
- Evaluation results are now correctly recorded in Comet ML (OPIK)

### Phase 2: Comprehensive Improvements (2026-01-23)

#### Problems Identified
1. **Recall@5 = 0.00**: Expected document IDs in `eval_questions.csv` did not match actual ID formats
   - FAQ: Expected IDs like `restoration` but actual IDs are `intent` values from CSV
   - OPS logs: Expected IDs like `LOG001` but actual IDs are `stable_id` (SHA1 hash)
   - PDF: Format was correct (`contract.pdf p5`) but search results were empty
2. **Hallucination = 0.86**: High hallucination rate due to insufficient search results
3. **OPIK Integration**: Data was being logged to wrong project ("Default Project")

#### Solutions Implemented

1. **ID Mapping System** (`src/eval_id_mapper.py`)
   - Created ID mapper utility to convert expected IDs to actual document IDs
   - Handles FAQ intents, OPS log stable_ids, and PDF filename+page formats
   - Automatically loads mappings from CSV files

2. **Evaluation Script Integration** (`scripts/run_simple_eval.py`)
   - Integrated ID mapper into evaluation pipeline
   - Automatically maps expected IDs before comparison
   - Supports source type hints for better mapping accuracy

3. **Search Debug Logging** (`src/rag_answerer.py`)
   - Added comprehensive debug logging for search process
   - Logs search results by source, subquery, and document IDs
   - Helps identify why search returns empty results

4. **Prompt Improvements** (`src/rag_answerer.py`)
   - Strengthened hallucination prevention in answer prompt
   - Added explicit instruction: "根拠情報に記載されていない情報は一切含めない"
   - Added warning when evidence is insufficient
   - Improved fallback handling for insufficient search results

5. **Evaluation Analysis Script** (`scripts/analyze_eval_results.py`)
   - Created analysis script to identify patterns in evaluation results
   - Analyzes retrieval failures and hallucination patterns
   - Generates improvement suggestions automatically
   - Saves analysis results to JSON file

6. **OPIK Project Fix** (`src/opik_integration.py`, `.env`)
   - Fixed OPIK project name configuration
   - Set `OPIK_PROJECT_NAME` environment variable to match `COMET_PROJECT_NAME`
   - Ensures data is logged to correct project (`RAG_POC`)

7. **Evaluation Dataset Updates** (`data/eval/eval_questions.csv`)
   - Updated `relevant_doc_ids` to use actual ID formats
   - FAQ: Use intent values (e.g., `restoration`, `ペット飼育の可否`)
   - OPS logs: Use stable_id values (e.g., `e07dee1e3fe6fe84`)
   - PDF: Keep filename+page format (e.g., `contract.pdf p5`)

#### Expected Results
- **Recall@5**: 0.00 → 0.50+ (with correct ID mapping)
- **Hallucination**: 0.86 → 0.50- (with improved search and prompts)
- **Evaluation Reproducibility**: Improved with consistent ID mapping

#### Files Changed
- `data/eval/eval_questions.csv`: Updated relevant_doc_ids to actual formats
- `src/eval_id_mapper.py`: New ID mapping utility
- `scripts/run_simple_eval.py`: Integrated ID mapper
- `src/rag_answerer.py`: Added debug logging and improved prompts
- `scripts/analyze_eval_results.py`: New analysis script
- `src/opik_integration.py`: Fixed OPIK project configuration
- `.env`: Set OPIK_PROJECT_NAME to RAG_POC

### Metrics v2 and Decision Hygiene

#### Metrics v2 Overview

このプロジェクトは**Metrics v2（Decision Hygiene準拠）**を使用しています。Metrics v2は以下の4つの原則に基づいています：

1. **診断可能性（Diagnostic）**: 数値が悪いとき「どこを直せばよいか」が分かる
2. **役割分離（Layered）**: Retrieval / Evaluation / Generation / Safety を混ぜない
3. **質問タイプ条件付き（Conditional）**: すべての質問に同じ指標を当てない
4. **目標値に意味がある（Actionable）**: 改善 or 放置の判断に使える

#### Question Typing（質問タイプ分類）

すべての指標は質問タイプに条件付けられます。質問タイプは以下6種類：

- `fact_lookup`: 単一事実を尋ねる質問
- `procedure`: 手続き・フローを尋ねる質問
- `policy_confirmation`: 可否確認（〜できますか）
- `policy_enumeration`: 禁止/義務の列挙
- `explanation`: 理由・背景説明
- `open_ended`: 曖昧・相談系

質問タイプはLLMベースで自動分類され、`eval_questions.csv`の`question_type`列で手動オーバーライド可能です。

#### Decision Rules（意思決定ルール）

評価が悪いときは、以下の順序で意思決定を行います：

1. **IDMatchRate < 0.9?** → 評価設計を直す（検索触るな）
2. **Recall@5 < 50%?** → Retrieval or Corpus
3. **Completeness < 1.0?** → Generation制御
4. **EvidenceBinding < 0.8?** → Prompt / Schema / Post-process
5. **Hallucination.fact_error > 0?** → 即ブロック

詳細は`src/decision_rules.py`を参照してください。

#### OPIK運用ルール（Decision Hygiene版）

**Rule 1**: 評価が悪いとき、まず metrics の意味を疑え

- ID normalization success rate < 0.9 の場合は評価設計の問題
- Retrievalを触る前に評価設計を確認

**Rule 2**: IDMatchRate < 0.9 のとき Retrieval を触るな

- 評価定義が壊れている可能性が高い
- `eval_questions.csv`の期待IDを確認

**Rule 3**: Hallucination は分解せよ。1数値で語るな

- `hallucination_fact_error`: 明確な虚偽（0.0が必須）
- `hallucination_unsourced_claim`: 根拠なし断定
- `hallucination_overreach`: 証拠外推論

**Rule 4**: 質問タイプ未定義の評価は無効

- すべての評価は質問タイプに条件付き
- 質問タイプが`unknown`の場合は警告を出力

#### Evaluation Metrics Interpretation（Metrics v2）

##### Retrieval Metrics

- **Recall@5**: 期待されるドキュメントが検索結果の上位5件に含まれる割合
  - **Good**: ≥ 0.5
  - **Poor**: < 0.4（評価設計疑い）または < 0.3（検索問題）
  - **質問タイプ別**: `recall_at_5.fact_lookup`, `recall_at_5.policy_enumeration` など

- **Hit@1**: Single-source質問（fact_lookup）専用
  - 単一期待ドキュメントが1位に来たか

##### Evaluation Metrics

- **ID Normalization Success Rate**: IDマッピング成功率
  - **< 0.9**: 評価設計が壊れている → Retrieval改善は禁止
  - **≥ 0.9**: 評価設計は健全 → Retrieval改善を検討

##### Generation Metrics

- **Answer Completeness**: 質問タイプ別の完全性
  - `policy_enumeration`: 列挙項目数 ≥ 3
  - `procedure`: 手順ステップ数 ≥ 2
  - `fact_lookup`: 単一明確回答

- **Evidence Binding Rate**: 引用付き項目の割合
  - 目標: `policy_enumeration` ≥ 0.8, `procedure` ≥ 0.7

##### Safety Metrics

- **Hallucination（分解）**:
  - `hallucination_fact_error`: **0.0が必須**（明確な虚偽は許容不可）
  - `hallucination_unsourced_claim`: 根拠なし断定（低いほど良い）
  - `hallucination_overreach`: 証拠外推論（低いほど良い）

- **Prohibited Mention Rate（typed）**:
  - `confirmation`: 低いほど良い（可否確認質問）
  - `enumeration`: 高いほど良い（列挙質問）

#### Beads / INC / ADR との接続

- **metrics v2改修** → ADR（Architecture Decision Record）
- **評価破綻** → INC（Incident Report、evaluation incident）
- **閾値変更** → ADR + metrics version bump

評価レポート生成:

```bash
python scripts/generate_eval_report.py
```

生成されたレポートは`docs/eval/OPIK_EVAL_REPORT_*.md`に保存され、Decision Hygieneテンプレートに準拠しています。

### Troubleshooting Guide

#### Recall@5 = 0.00
1. Check ID format: Compare `expected_doc_ids` in eval_questions.csv with actual IDs
2. Run ID mapper: Use `src/eval_id_mapper.py` to verify mappings
3. Check search debug logs: Look for empty search results
4. Verify vector store: Re-index if documents are missing

#### High Hallucination (> 0.7)
1. Check Recall@5: Low recall often correlates with high hallucination
2. Review search results: Use debug logs to see what documents were retrieved
3. Check prompt: Ensure "no speculation" instructions are clear
4. Verify evidence quality: Check if retrieved documents are relevant

#### OPIK Data Not Showing
1. Check project name: Verify `OPIK_PROJECT_NAME` in `.env` matches OPIK UI
2. Check experiments tab: Data appears under Experiments, not Traces
3. Verify API key: Ensure `COMET_API_KEY` is set correctly
4. Check logs: Look for OPIK initialization messages in evaluation output

---

## Project-specific Cursor Rules

# Cursor Operating Rules for rental_rag_poc

## Mission

Cursor must act as a safe development orchestrator, not only a code generator.

The priorities are:

1. Keep changes small.
2. Preserve evaluation reliability.
3. Avoid deployment and data-management mistakes.
4. Make every change observable and reviewable.

---

## 1. Scope Control

Before editing files, Cursor must state:

- Target objective
- Files likely to change
- Layer affected:
  - KB / fast path
  - LINE handler
  - RAG logic
  - evaluation
  - deploy
  - docs
- Expected tests or checks

Do not mix unrelated layers in one change.

Bad:

- KB + RAG + deploy + docs in one patch

Good:

- KB fast path only
- evaluation only
- deploy script only

---

## 2. Commit Unit Rules

Use small commits by purpose.

Recommended order:

1. KB / fast path / clarification
2. LINE handler / API integration
3. RAG / query cache
4. evaluation / A-B analysis
5. deploy / Cloud Run
6. docs

Cursor must not suggest `git add .`.

Use:

```bash
git status --short
git diff --stat
git add -p
```

---

## 3. Evaluation Rules

For A/B evaluation, semantic cache must be disabled unless explicitly testing cache behavior.

Default command:

```bash
python3 scripts/run_eval.py --ab-compare --disable-semantic-cache
```

After evaluation, check:

```bash
cat data/eval/ab_summary.json
cat data/eval/ab_scored_summary.json
cat data/eval/ab_diff_report.jsonl
cat data/eval/route_mismatch_report.jsonl
```

`ab_summary.json` の **`route_metrics.router_kpis`** を主に見る（`schema_version` 2）: `A_non_rag_rate`（A×kb_only）、`B_rag_rate`（B×rag レッグ）、`D_escalation_rate`（D×`auto` 追加実行）、`C_clarification_rate` はオフラインでは `null`（LINE E2E）。全体 `route_match` は **`route_metrics.legacy_route_match`** にあり補助指標。

The evaluation report must mention:

- fallback rate
- latency p50 / p95
- cost per 1000 requests
- match_tier distribution
- diff count between KB_only and RAG

---

## 4. Cache Rules

Evaluation cache namespaces must stay separated.

Required namespaces:

```text
eval:kb_only
eval:rag
eval:auto_router
```

Semantic cache must not leak answers across modes.

If adding or modifying cache behavior, Cursor must explain:

- exact cache behavior
- semantic cache behavior
- namespace behavior
- evaluation impact

---

## 5. KB / Fast Path Rules

Fast path changes must preserve these invariants:

- Ambiguous short queries should clarify.
- Specific short queries can hit.
- Same ambiguous query repeated should not silently become hit.
- Number replies such as `1` / `2` are resolved only within clarification state.
- Normal standalone `1` / `2` must not be interpreted.

Required tests for clarification-related changes:

```bash
python3 -m pytest tests/test_kb_fast_path.py tests/test_clarification_numeric_reply.py
```

When editing `data/faq_kb.csv`, always consider whether reindex is needed:

```bash
python3 scripts/reindex_vector_db.py
```

---

## 6. RAG / Decision Path Rules

RAG changes must preserve observability.

Answers should expose or log:

- system
- decision_path
- retrieval_used
- fallback_used
- latency_ms

If changing decision routing, verify:

- KB_only behavior
- RAG behavior
- fallback behavior
- should_escalate behavior

---

## 7. LINE / Cloud Run Rules

Do not mix LINE deployment changes with RAG logic changes unless explicitly requested.

For LINE webhook changes, verify:

- `/health`
- `/ready`
- `Processing LINE message`
- `LINE Reply API success`
- `kb_fast_path_hit`
- `kb_fast_path_clarification`
- `kb_fast_path_miss`

Deployment should keep secrets and env vars explicit.

Do not assume a new Cloud Run service has inherited secrets.

---

## 8. Logging Rules

Any new branch or decision path must be observable.

Important fields:

- event
- line_user_id
- normalized_query
- intent
- decision_path
- fallback_used
- raw_text
- resolved_text

If logs are not structured JSON, provide Logs Explorer queries using `textPayload`.

---

## 9. Data / Artifact Rules

Do not commit generated or heavy files unless explicitly intended.

Usually avoid:

```text
data/vector_store/
eval/runs/
large PDFs
temporary logs
```

If generated files are required for deployment, explain why.

---

## 10. Required Response Format After Changes

After implementing changes, Cursor must report:

1. Changed files
2. Purpose of each change
3. Tests run
4. Evaluation run, if applicable
5. Known risks
6. Next recommended command

---

## 11. Anti-patterns

Cursor must avoid:

- Huge mixed commits
- `git add .`
- A/B evaluation with semantic cache leakage
- Fast path changes without tests
- Deploy changes without `/health` and `/ready`
- Logs that cannot be queried
- Silent fallbacks to missing legacy data

---

## Core Rule

Small change. Fixed evaluation. Observable behavior.


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
