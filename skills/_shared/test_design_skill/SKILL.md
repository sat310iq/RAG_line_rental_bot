---
name: test_design_skill
description: >
  単体・統合・回帰の切り分け、カバレッジの優先順位、フィクスチャ設計。
  RAG は実インデックス依存とモックの境界を明示する。
triggers:
  - test
  - テスト
  - pytest
  - regression
  - fixture
---

# Test design

## When to use

- 新機能にテストを足す前
- フレークや実行時間が増えたとき

## Procedure

1. 「決定的に assert できる層」を決める（純関数・パーサ・フォーマッタ）。
2. 外部依存（OpenAI/Chroma）はモックまたは smoke に限定するか方針を書く。
3. `resources/pyramid.md` の順で埋める。

## Output format

- テスト種別一覧 / 優先度 / データ準備 / 実行コマンド
