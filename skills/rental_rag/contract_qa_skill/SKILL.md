---
name: contract_qa_skill
description: >
  賃貸借契約書（マスタ TXT/PDF）に基づく回答、条番号・出典形式（第N条）、
  contract-source 経路・検索・rerank。個別契約の確定判断はエスカレーション。
triggers:
  - 契約
  - 第
  - 条
  - 本文
  - 特約
  - 別表
  - contract source
  - RAG
---

# Contract QA

## When to use

- 「契約のどこに書いてあるか」「第N条は何とあるか」系
- `contract_source`・マスタチャンク・`search_debug_info` を調べる実装・検証

## Procedure

1. 入口判定: [`src/contract_query_router.py`](../../../../src/contract_query_router.py)、共有意図: [`src/contract_query_intent.py`](../../../../src/contract_query_intent.py)。
2. 回答・出典表示: [`src/contract_rag_format.py`](../../../../src/contract_rag_format.py)、生成: [`src/rag_answerer.py`](../../../../src/rag_answerer.py)。
3. 設定（閾値・TopK）: [`src/config.py`](../../../../src/config.py)。

## Output format

- 結論 / 根拠（ファイル・条・ページ等）/ 注意（雛形条項である旨）/ 次アクション
