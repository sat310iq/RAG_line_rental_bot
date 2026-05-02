---
name: architecture_review_skill
description: >
  システム境界、コンポーネント責務、データフロー、失敗モード、運用制約のレビュー。
  RAG/ルーティング/外部依存の見落としを防ぐ。
triggers:
  - architecture
  - アーキテクチャ
  - 設計レビュー
  - boundary
  - 境界
  - data flow
---

# Architecture review

## When to use

- 大きめの変更や新規コンポーネント追加の前後
- 「どこが単一障害点か」「どこでキャッシュ/タイムアウトするか」を確認したいとき

## Procedure

1. コンテキスト図を1枚に収める（外部: LINE/API/Chroma/OpenAI 等）。
2. 読み取り専用パスと書き込みパスを分ける。
3. `resources/checklist.md` を上から確認する。

## Output format

- 現状の論点 / リスク / 推奨パターン / フォローアップ
