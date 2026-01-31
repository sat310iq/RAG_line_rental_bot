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

### Evaluation Metrics Interpretation

#### Recall@5
- **Meaning**: Percentage of expected documents found in top 5 search results
- **Good**: > 0.5 (at least half of expected documents found)
- **Poor**: < 0.3 (most expected documents not found)
- **Common Issues**: ID format mismatch, search query quality, document indexing

#### Hallucination
- **Meaning**: Amount of information in answer not supported by evidence (0-1, higher = worse)
- **Good**: < 0.3 (mostly fact-based)
- **Poor**: > 0.7 (many unsupported claims)
- **Common Causes**: Insufficient search results, weak prompt constraints, LLM overconfidence

#### Relevance
- **Meaning**: How well answer addresses the question (0-1, higher = better)
- **Good**: > 0.8 (answer is highly relevant)
- **Poor**: < 0.5 (answer doesn't address question well)

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

