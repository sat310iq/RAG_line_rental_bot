# Skill OS 計画（Phase 1 ドキュメント）

この PoC では **実行コードは `src/` に据え置き**、`skills/` に Anthropic Agent Skills 風の再利用パッケージ（手順・テンプレ・軽量インデックス）を置く。

## レイアウト

```text
skills/
  _shared/           # 汎用開発 Skill（他 PoC にも持ち運び可能）
  rental_rag/        # 本チャットボット固有
  registry.yaml      # Skill メタのインデックス（機械可読）
```

`_shared` と `rental_rag` は兄弟ディレクトリ（混在させない）。

詳細は [`skills/registry.yaml`](../../skills/registry.yaml)（コメントに triggers の正本ルールあり）。

## Progressive Disclosure

1. `registry.yaml` または各 `SKILL.md` の frontmatter（`name`, `description`, `triggers`）だけで候補を絞る。
2. 必要な Skill の `SKILL.md` 本文を読む。
3. 長文・チェックリストは `resources/` / `templates/` に分離済み。

参考にしたパターン: フラットな Cursor Agent Skills サンプル（`triggers`・ローダ・`.cursorrules` 連携）は Phase 2 で `**/SKILL.md` スキャン等として検討。

## 現状アーキテクチャ図

ソースファイル（編集用）: [`diagrams/current_arch.mmd`](diagrams/current_arch.mmd)

## 将来アーキテクチャ図（草案）

[`diagrams/future_arch.mmd`](diagrams/future_arch.mmd) — SkillSelector を上位に置く案。**運用上の正は現状図**。

## Phase 境界

| Phase | 内容 |
|-------|------|
| 1（完了） | `SKILL.md` + `resources/` / `templates/`、`registry.yaml`、本書。**アプリコード変更なし**。 |
| 2 | `SkillSelector`（ルールベース）と `registry.yaml` / `SKILL.md` の読み取り。任意で `.cursorrules` 同期スクリプト。 |
| 3 | 各 Skill に `tests/cases.jsonl` 等で評価ケース。 |

## 既存コードとの対応（概要）

| Skill | 主な関連 |
|-------|----------|
| `tenant_faq_skill` | `src/kb_fast_path.py`, KB CSV（`kb_path_reference.md`） |
| `contract_qa_skill` | `src/rag_answerer.py`, `src/contract_query_router.py`, `src/contract_rag_format.py` |
| `eval_review_skill` | `docs/eval.md`, `docs/QUALITY_GATE.md`, eval ディレクトリ |

## 将来 TODO（コード側と整合）

- 条見出しインデックスによる「第 N 条固定」からの脱却（契約マスタのメタデータ設計）。
- contract-source retry の動的クエリ（埋め込み類似など）は別 PR で計測後に。

## 関連ドキュメント

- [`architecture.md`](../architecture.md) — システム全体
- [`skills/registry.yaml`](../../skills/registry.yaml) — Skill インデックス
