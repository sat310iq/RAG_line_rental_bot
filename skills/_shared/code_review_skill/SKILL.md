---
name: code_review_skill
description: >
  変更 diff の妥当性、エッジケース、命名、テスト不足、セキュリティ・PII。
  PoC でも最低限のレビュー観点を固定する。
triggers:
  - code review
  - レビュー
  - PR
  - diff
  - refactor
---

# Code review

## When to use

- PR またはローカル変更をマージする前
- リファクタが「挙動変更なし」を満たすか確認したいとき

## Procedure

1. 変更の目的とスコープがコミットメッセージ・説明と一致するか確認。
2. `resources/checklist.md` を踏む。
3. テスト追加・更新が変更と対応しているか確認。

## Output format

- サマリ / 指摘（重要度付き） / 必須修正 / 任意改善
