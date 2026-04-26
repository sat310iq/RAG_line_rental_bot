# Rental RAG PoC (Routing-first Design)

![Python](https://img.shields.io/badge/Python-3.10-blue)
![Status](https://img.shields.io/badge/status-PoC-orange)
![Focus](https://img.shields.io/badge/focus-RAG%20Routing-green)

## Key Idea

Most RAG systems try to improve retrieval.

This project takes the opposite approach:

-> **Reduce RAG usage as much as possible**

### Design

- Rule-based routing for majority of queries (FAQ)
- Clarification for ambiguous inputs
- RAG only for contract-level questions
- Escalation for legal / risky queries

### Result

- Lower LLM cost
- Safer responses (avoid legal hallucination)
- More predictable system behavior

---

## What this project does

This is a Proof-of-Concept chatbot for rental tenants.

Instead of relying on RAG for everything, it:

1. Answers common questions via deterministic rules
2. Uses RAG only when contract-level context is required
3. Avoids answering risky questions and escalates to humans

---

## Architecture (Simplified)

```text
User Query
  ↓
[Router]
  ├── Rule (FAQ)
  ├── Clarification
  ├── RAG (contracts only)
  └── Escalation (legal/financial)
```

---

## Example Routing

| Query | Route |
|------|------|
| "水漏れしています" | Rule |
| "契約の違約金は？" | RAG |
| "これ違法ですか？" | Escalation |
| "ガスの件なんですが" | Clarification |

---

## Quick Start

```bash
pip install -r requirements.txt
cp env.example .env
python3 scripts/run_eval.py --dataset eval/datasets/line_rag_eval_router_abcd_v1.csv
```

## Public vs Deploy

This repository is structured with separation of concerns:

- Public: core logic, routing, evaluation
- Private: environment variables, API keys, deployment configs

⚠️ Secrets are NOT included.  
Use `*.example` files to configure your environment.

## Limitations

- Requires OpenAI API key
- RAG quality depends on document structure
- Clarification behavior differs between offline and LINE runtime
- Legal interpretation is intentionally limited (safe design)

## Future Work

- Improve retrieval accuracy (B-group queries)
- Enhance relevance guard (fail-closed logic)
- Expand escalation detection
- Reduce fallback frequency

## Why this matters

Most RAG systems:

- Overuse LLM
- Increase cost
- Risk hallucination

This project shows:

- RAG should be the exception, not the default
# rental_rag_poc

> **日本語サマリー**  
> 賃貸入居者向けLINEチャットボットのPoCです。  
> 「RAGをデフォルトにしない」設計を検証しました。  
> クエリの大半はルールで処理し、RAGは契約書参照にのみ使用、法的判断はエスカレーションします。  
> コスト削減・安全性向上・回答品質の維持を同時に狙う設計の記録です。

## Key Idea

Most RAG systems try to improve retrieval.

This project takes the opposite approach:

-> Reduce RAG usage as much as possible

Design:

- Rule-based routing for majority of queries
- RAG only for contract-level questions
- Escalation for risky/legal queries

Result:

- Lower cost
- Safer responses
- More predictable behavior

## What this project does

Most RAG systems treat retrieval as the default. This project does the opposite.

**Core idea: Don't use RAG unless necessary.**

| Approach | Typical RAG | This PoC |
|---|---|---|
| Default path | RAG for everything | Rule-based routing |
| Optimization target | Recall / answer quality | Routing accuracy |
| LLM usage | High | Minimal |
| Legal/financial queries | LLM answers | Escalated to humans |

**Result:**
- Reduced unnecessary LLM calls
- Improved safety on legal and financial queries
- Maintained acceptable answer quality

## Why this matters

When building a chatbot for rental tenants, most questions fall into predictable categories:

- **FAQ / operational** — "How much is the water bill?" -> rule-based answer, no LLM needed
- **Contract reference** — "Where does it say that in the contract?" -> RAG appropriate
- **Legal / judgment** — "Can I sue?" / "Is this illegal?" -> must not be answered by AI

Treating all three the same way leads to high cost, hallucination risk, and legal exposure.

The key insight: **routing design matters more than model quality.**

## Architecture

```text
User query
    |
    v
1) Fast Path       - keyword match -> immediate response (sub-second)
    |
    v
2) Rule Engine     - deterministic logic for fees, rules, prohibitions
    |
    v
3) Clarification   - resolve ambiguous short inputs (e.g. "gas", "certificate")
    |
    v
4) Escalation      - legal / financial judgment -> hand off to property manager
    |
    v
5) RAG             - contract-level questions only (fallback, not default)
```

RAG is layer 5, not layer 1.

## Example routing (A / B / C / D categories)

| Category | Example query | Route |
|---|---|---|
| A - Non-RAG | "Is smoking allowed?" | Rule Engine -> direct answer |
| A - Non-RAG | "Is internet free?" | Fast Path -> direct answer |
| B - RAG | "Where does the contract mention this?" | RAG -> source citation |
| B - RAG | "What does the important matters document say?" | RAG -> source citation |
| C - Clarification | "About gas" | Clarification -> ask follow-up |
| D - Escalation | "Can I claim rent reduction?" | Escalation -> refer to manager |
| D - Escalation | "Is this legally valid?" | Escalation -> refer to manager |

**Evaluation metrics (on synthetic test dataset):**

| Metric | Description | Result |
|---|---|---|
| `A_non_rag_rate` | Simple queries correctly NOT sent to RAG | 1.0 |
| `B_rag_rate` | Contract queries correctly sent to RAG | 1.0 |
| `D_escalation_rate` | Legal queries correctly escalated | 1.0 |

> Note: Results are on a small synthetic dataset, not production traffic. The value is in the routing framework, not the numbers.

## Tech stack

| Component | Technology |
|---|---|
| API server | Python / FastAPI / Uvicorn |
| Messaging | LINE Webhook |
| Deployment | Cloud Run |
| Vector store | Chroma |
| Retrieval | BM25 + vector hybrid search |
| LLM | OpenAI API |
| Knowledge base | CSV-based FAQ |
| Documents | Contract PDF / TXT |

## Public profile vs Deploy profile

This repository intentionally contains two profiles in one codebase:

- **Public profile (GitHub showcase)**: routing-first PoC concept, minimal runnable evaluation, and architecture explanation.
- **Deploy profile (GCP operations)**: Cloud Run deployment structure and operational docs for production-like setup.

What is public:
- project structure (`deploy/`, `docs/deploy/`) to explain how deployment is designed
- template files for environment configuration

What is never committed:
- real secrets (`.env`, `deploy/.env.gcp`)
- local artifacts (`data/vector_store/`, `eval/runs/`, `logs/`)

Template-only secret workflow:

```bash
cp env.example .env
cp env.gcp.example .env.gcp
cp deploy/.env.gcp.example deploy/.env.gcp
```

Then set your own values locally. Do not commit those generated `.env*` files.

## Quick start

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/rental_rag_poc.git
cd rental_rag_poc
pip install -r requirements.txt
```

### 2. Set up environment

```bash
cp env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### 3. Run evaluation

```bash
python3 scripts/run_eval.py --dataset eval/datasets/line_rag_eval_router_abcd_v1.csv
```

This runs the router against the synthetic test dataset and prints routing accuracy per category.

## Repository structure

```text
rental_rag_poc/
|- src/                    # Public core: routing and RAG logic
|  |- router/              # Routing logic (Fast Path, Rule Engine, Escalation, RAG)
|  |- rag/                 # RAG pipeline (hybrid search, rerank, generation)
|  `- line/                # LINE webhook handler
|- scripts/                # Public core: local run/eval scripts
|  `- run_eval.py          # Evaluation entry point
|- tests/                  # Public core: unit tests
|- eval/                   # Public core: synthetic/anonymized evaluation dataset
|  `- datasets/
|     `- line_rag_eval_router_abcd_v1.csv  # Synthetic test data (no real tenant data)
|- deploy/                 # Deploy profile: Cloud Run deployment scripts/templates
|- docs/deploy/            # Deploy profile: operational deployment documents
|- env.example             # Template only (local copy -> .env)
|- env.gcp.example         # Template only (local copy -> .env.gcp)
`- requirements.txt
```

## Limitations

- This is a PoC and not production-ready.
- The evaluation dataset is limited and may not reflect real-world diversity.
- The chatbot is not connected to a live LINE environment.
- Contract documents used are anonymized or synthetic.
- Escalation rules are heuristic-based and may require further tuning.

All evaluation datasets are synthetic or anonymized and do not contain real tenant data.

## Future work

- [ ] Confidence-based routing (probabilistic fallback between layers)
- [ ] Clarification layer improvement (multi-turn disambiguation)
- [ ] Escalation boundary tuning with real query logs
- [ ] Human-in-the-loop feedback loop for router training
- [ ] Evaluation on real (anonymized) production queries

## Background

This repo accompanies a LinkedIn article series on routing-first RAG design:

- Part 1: [RAGを"使いすぎない"設計へ](https://www.linkedin.com/in/YOUR_PROFILE)
- Part 2: AIはどこで止まるべきか? - Escalation設計 *(coming soon)*
- Posting templates: [docs/LINKEDIN_POST_TEMPLATES.md](docs/LINKEDIN_POST_TEMPLATES.md)
- Public release scope: [docs/PUBLIC_RELEASE_SCOPE.md](docs/PUBLIC_RELEASE_SCOPE.md)
