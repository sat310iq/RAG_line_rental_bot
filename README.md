# rental_rag_poc — Routing-First RAG Design

![Python](https://img.shields.io/badge/Python-3.10-blue)
![Status](https://img.shields.io/badge/status-PoC-orange)
![Focus](https://img.shields.io/badge/focus-Routing--First%20AI-green)

---

> **日本語サマリー**
> 賃貸入居者向けLINEチャットボットのPoCです。
> 「RAGをデフォルトにしない」設計を検証しました。
> クエリの大半はルールで処理し、RAGは契約書参照にのみ使用、法的判断はエスカレーションします。
> コスト削減・安全性向上・回答品質の維持を同時に狙う設計の記録です。

---

## The Core Idea

Most RAG systems try to improve retrieval.

This project takes the opposite approach.

**How far can we go WITHOUT using RAG?**

| | Typical RAG | This PoC |
|---|---|---|
| Default path | RAG for everything | Rule-based routing |
| Optimization target | Recall / answer quality | Routing accuracy |
| LLM usage | High | Minimal |
| Legal/financial queries | LLM answers | Escalated to humans |

**Result:** Lower cost · Safer responses · More predictable behavior

---

## What This Project Does NOT Do

- Does NOT use RAG for most queries
- Does NOT answer legal or judgment questions
- Does NOT rely on LLM for deterministic responses

RAG is the exception, not the default.

---

## Why This Matters

When building a chatbot for rental tenants, questions fall into three distinct categories:

- **FAQ / operational** — "How much is the water bill?" -> rule-based, no LLM needed
- **Contract reference** — "Where does it say that in the contract?" -> RAG appropriate
- **Legal / judgment** — "Can I sue?" / "Is this illegal?" -> must not be answered by AI

Treating all three the same way leads to high cost, hallucination risk, and legal exposure.

**The key insight: routing design matters more than model quality.**

---

## Architecture

```text
User query
    |
    v
1) Fast Path       — keyword match → immediate response (sub-second)
    |
    v
2) Rule Engine     — deterministic logic for fees, rules, prohibitions
    |
    v
3) Clarification   — resolve ambiguous short inputs (e.g. "gas", "certificate")
    |
    v
4) Escalation      — legal / financial judgment → hand off to property manager
    |
    v
5) RAG             — contract-level questions only (fallback, not default)
```

**RAG is layer 5, not layer 1.**

---

## Example Routing

| Category | Example query | Route |
|---|---|---|
| A — Non-RAG | "水漏れしています" / "Is smoking allowed?" | Rule Engine |
| A — Non-RAG | "ネットは無料ですか？" / "Is internet free?" | Fast Path |
| B — RAG | "契約の違約金は？" / "Where does the contract mention this?" | RAG |
| C — Clarification | "ガスの件なんですが" / "About gas" | Clarification |
| D — Escalation | "これ違法ですか？" / "Can I claim rent reduction?" | Escalation |

---

## Escalation = Core Feature, Not Edge Case

Some questions should not be answered by AI:

- "Can I claim compensation?"
- "Is this legally valid?"
- "Would I win if I sue?"

These are not retrieval problems. They are **responsibility problems.**

Design rule:
- RAG → provides context (understanding support)
- Escalation → owns the decision (refer to humans)

---

## Evaluation

Traditional RAG metrics (Recall@K, answer accuracy) measure retrieval quality.

This project measures **routing correctness** instead.

| Metric | Meaning | Result |
|---|---|---|
| `A_non_rag_rate` | Simple queries correctly NOT sent to RAG | 1.0 |
| `B_rag_rate` | Contract queries correctly sent to RAG | 1.0 |
| `D_escalation_rate` | Legal queries correctly escalated | 1.0 |

> Results are on a small synthetic dataset, not production traffic.
> The value is in the routing framework, not the numbers.

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/sat310iq/RAG_line_rental_bot.git
cd rental_rag_poc
pip install -r requirements.txt
```

### 2. Set up environment

```bash
cp env.example .env
# Edit .env — add your OPENAI_API_KEY
```

### 3. Run evaluation

```bash
python3 scripts/run_eval.py --dataset eval/datasets/line_rag_eval_router_abcd_v1.csv
```

This runs the router against the synthetic test dataset and prints routing accuracy per category (A/B/C/D).

---

## Tech Stack

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

---

## Repository Structure

```text
rental_rag_poc/
├── src/                    # Core: routing and RAG logic
│   ├── router/             # Fast Path, Rule Engine, Escalation, RAG
│   ├── rag/                # Hybrid search, rerank, generation
│   └── line/               # LINE webhook handler
├── scripts/
│   └── run_eval.py         # Evaluation entry point
├── tests/                  # Unit tests
├── eval/
│   └── datasets/
│       └── line_rag_eval_router_abcd_v1.csv  # Synthetic test data only
├── deploy/                 # Cloud Run deployment templates (no secrets)
├── docs/                   # Architecture and design notes
├── env.example             # Template → copy to .env
├── env.gcp.example         # Template → copy to .env.gcp
└── requirements.txt
```

---

## Public vs Deploy Profile

This repository contains two profiles in one codebase:

- **Public profile** — routing-first PoC concept, evaluation, architecture explanation
- **Deploy profile** — Cloud Run structure and operational docs (`deploy/`, `docs/deploy/`)

What is **never committed:**

```text
.env
deploy/.env.gcp
data/vector_store/
eval/runs/
logs/
```

Template-only workflow:

```bash
cp env.example .env
cp deploy/.env.gcp.example deploy/.env.gcp
# Fill in your own values. Do not commit these files.
```

---

## Limitations

- PoC only — not production-ready
- Evaluation dataset is synthetic and limited in diversity
- No live LINE integration included
- Contract documents are anonymized or synthetic
- Escalation rules are heuristic-based and require tuning for different contexts

---

## Future Work

- [ ] Confidence-based routing (probabilistic fallback between layers)
- [ ] Clarification layer improvement (multi-turn disambiguation)
- [ ] Escalation boundary tuning with real query logs
- [ ] Human-in-the-loop feedback loop for router training
- [ ] Evaluation on real (anonymized) production queries

---

## Background

This repo accompanies a LinkedIn article series on routing-first RAG design:

- Part 1: [RAGを"使いすぎない"設計へ](https://www.linkedin.com/pulse/stop-overusing-rag-designing-routing-first-ai-system-tenant-satoshi-e6bnc/)
- Part 2: AIはどこで止まるべきか？— Escalation設計 *(coming soon)*

---

## License

MIT
# 🏠 Rental RAG PoC — A Routing-First AI System

![Python](https://img.shields.io/badge/Python-3.10-blue)
![Status](https://img.shields.io/badge/status-PoC-orange)
![Focus](https://img.shields.io/badge/focus-Routing--First%20AI-green)

---

> **日本語サマリー**  
> 賃貸入居者向けチャットボットPoCです。  
> このプロジェクトは「RAGをどう改善するか」ではなく、「いつRAGを使わないか」を設計対象にします。  
> 契約文脈だけRAG、法務/判断系はエスカレーションに分離する設計を検証しています。

---

## The Insight

Most RAG systems try to improve retrieval.

This project found that this is the wrong problem.

👉 **The real problem is deciding when NOT to use RAG.**

This is a Proof-of-Concept chatbot for rental tenants.  
Instead of optimizing RAG accuracy, it asks:

👉 **How far can we go WITHOUT using RAG?**

---

## ❌ What This Project Does NOT Do

- Does NOT use RAG for most queries
- Does NOT answer legal or judgment questions
- Does NOT rely on LLM for deterministic responses

👉 RAG is the exception, not the default.

---

## ⚙️ Core Design

The system is built around **routing decisions**, not model capability.

```text
User Query
   ↓
[Fast Path]       → keyword-based instant answer
   ↓
[Rule Engine]     → deterministic logic
   ↓
[Clarification]   → resolve ambiguity
   ↓
[Escalation]      → hand off to humans (critical boundary)
   ↓
[RAG]             → contract-level retrieval only
```

👉 **RAG is layer 5, not layer 1**
👉 **Fallback, not default**

---

## 🧩 Query Types and Routing

| Type | Example | Route |
| ------------------ | --------------- | ------------- |
| FAQ / Operational | "水道代はいくら？" | Rule |
| Contract Reference | "契約書のどこに書いてある？" | RAG |
| Legal / Judgment | "違法ですか？" | Escalation |
| Ambiguous | "ガスの件" | Clarification |

---

## ⚖️ Escalation = Core Feature

Some questions should NOT be answered by AI:

- "Can I claim compensation?"
- "Is this legally valid?"
- "Would I win if I sue?"

👉 These are not retrieval problems.
👉 They are **responsibility problems**.

**Design rule:**

- RAG → provides context
- Escalation → owns the decision

---

## 📊 Evaluation Philosophy

Traditional RAG metrics:

- Recall@K
- Answer accuracy

This project focuses on:

👉 **Routing correctness**

### Key Metrics (Synthetic dataset)

| Metric | Meaning | Result |
| ----------------- | ------------------------------ | ------ |
| A_non_rag_rate | Simple queries NOT sent to RAG | 1.0 |
| B_rag_rate | Contract queries sent to RAG | 1.0 |
| D_escalation_rate | Risky queries escalated | 1.0 |

> These are measured on a small synthetic dataset.
> The value is in the **framework**, not the numbers.

---

## 🚀 Quick Start

```bash
git clone https://github.com/sat310iq/RAG_line_rental_bot.git
cd rental_rag_poc

pip install -r requirements.txt
cp env.example .env

# Add your OPENAI_API_KEY

python3 scripts/run_eval.py \
  --dataset eval/datasets/line_rag_eval_router_abcd_v1.csv \
  --ab-compare \
  --disable-semantic-cache
```

> Note: `--ab-compare` and `--disable-semantic-cache` are supported options in `scripts/run_eval.py --help`.

---

## 🏗️ Tech Stack

- Python / FastAPI / Uvicorn
- OpenAI API
- Chroma (vector DB)
- BM25 + hybrid retrieval
- LINE Webhook
- Cloud Run (deployment-ready)

---

## 🔐 Data & Privacy

- No real tenant data included
- Evaluation datasets are synthetic or anonymized
- Secrets (`.env`, API keys) are NOT committed

---

## 📁 Project Structure

```text
src/            # Routing + RAG core logic
scripts/        # Evaluation tools
eval/datasets/  # Synthetic test data
deploy/         # Cloud Run deployment templates
docs/           # Architecture & design notes
```

---

## ⚠️ Limitations

- PoC only (not production-ready)
- Limited evaluation dataset
- No live LINE integration
- Escalation rules are heuristic-based
- RAG limited to predefined documents

---

## 🔭 Future Work

- Confidence-based routing
- Better clarification (multi-turn)
- Escalation tuning from real logs
- Human-in-the-loop feedback
- Real-world evaluation dataset

---

## 💡 Why This Matters

Most RAG systems:

- Overuse LLM
- Increase cost
- Risk hallucination

This project shows:

👉 **System quality depends more on routing than on the model**

---

## 📝 Background

This repo accompanies a LinkedIn article series:

- Part 1: [Stop Overusing RAG](https://www.linkedin.com/in/YOUR_PROFILE)
- Part 2: [Escalation Design](https://www.linkedin.com/in/YOUR_PROFILE)
- (Upcoming) Routing KPI Design

---

## 💬 Discussion

👉 Where do you draw the line for escalation in your AI systems?
