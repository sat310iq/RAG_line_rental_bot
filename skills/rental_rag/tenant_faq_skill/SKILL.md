---
name: tenant_faq_skill
description: >
  入居者向けチャットの FAQ 応答、KB fast path、短文クエリ・clarification、
  CSV 由来の kb_faq 根拠。契約条文の逐条引用は contract_qa_skill。
triggers:
  - FAQ
  - 水道
  - ガス
  - ペット
  - clarification
  - kb_faq
---

# Tenant FAQ

## When to use

- 運用・設備・料金など FAQ 意図が [`data/faq_kb.csv`](../../../../data/faq_kb.csv) に載りうる質問
- [`src/kb_fast_path.py`](../../../../src/kb_fast_path.py) が関与する経路を説明・変更するとき

## Procedure

1. KB の実パスと設定キーは `resources/kb_path_reference.md` を正とする。
2. Fast path と RAG の境界は routing-first 前提（[`README.md`](../../../../README.md) / [`docs/architecture.md`](../../../../docs/architecture.md)）。
3. Clarification・数値返信などは KB メタと整合させる。

## Output format

- 利用者向け短文 / 根拠 intent または参照パス / 次アクション
