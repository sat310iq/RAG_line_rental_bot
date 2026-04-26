# LinkedIn Post Templates

## Short version

Most RAG systems overuse LLMs.

I tried the opposite approach:  
Don't use RAG unless necessary.

Built a rental chatbot where:
- 80% handled by rules
- RAG only for contracts
- Risky queries escalate to humans

Result:  
Lower cost + safer responses

Note:
- This repo includes both a public PoC profile and deploy structure templates.
- No real secrets are committed; copy from `*.example` and set values locally.

Code: [GitHub link]

## Detailed version

Instead of improving RAG, I tried reducing it.

In a rental chatbot use case:
- Most tenant questions are repetitive (FAQ)
- Only a small portion require contract understanding
- Some should not be answered by AI at all

So I designed a routing-first system:
1. Rule-based (FAQ)
2. Clarification
3. RAG (contracts only)
4. Escalation (legal/financial)

This reduced:
- unnecessary LLM calls
- hallucination risk
- legal exposure

The interesting part:  
RAG is no longer the default, but the exception.

Operational note:
- This repository intentionally co-locates public PoC code and deploy templates.
- Secret values are excluded from Git and must be configured per environment.

GitHub: [link]
