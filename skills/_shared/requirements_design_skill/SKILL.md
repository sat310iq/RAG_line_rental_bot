---
name: requirements_design_skill
description: >
  要件の整理、仕様化、トレーサビリティ、受入条件の定義。FR/NFR/ユーザーストーリー、
  曖昧さの解消、既存ドキュメント（spec）との整合確認に使う。
triggers:
  - requirement
  - 要件
  - 仕様
  - spec
  - acceptance
  - 受入
  - user story
  - トレーサビリティ
---

# Requirements design

## When to use

- 新機能・変更の**何を満たせば成功か**を言語化する前
- 既存 [`docs/spec.md`](../../../../docs/spec.md) や ADR と矛盾がないか確認する前

## Procedure

1. スコープと非スコープを1段落で書く。
2. 受入条件を箇条書き（測定可能ならメトリクス付き）。
3. 参照すべき既存ドキュメントパスを `resources/references.md` にリンクする。

## Output format

- 目的 / スコープ / 受入条件 / 未決事項 / 次のアクション
