---
name: implementation_plan_skill
description: >
  実装計画の分解、フェーズ境界、リスク、検証方法。エディタ・CLI エージェント共通の
  プロンプト雛形と段階計画テンプレートを使う。
triggers:
  - implementation plan
  - 実装計画
  - phased
  - 段階
  - rollout
---

# Implementation plan

## When to use

- 複数ファイル・複数PRにまたがる変更を始める前
- 「いつどこまでで止めるか」を合意したいとき

## Procedure

1. `templates/phased_plan.md` を複製し、フェーズと完了条件を埋める。
2. 各フェーズの検証コマンド（pytest 等）を書く。
3. 必要なら `templates/agent_prompt.md` をベースにエージェント指示を整える。

## Output format

- フェーズ一覧 / 成果物 / 検証 / ロールバック / オープンイシュー
