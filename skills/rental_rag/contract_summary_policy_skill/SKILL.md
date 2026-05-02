---
name: contract_summary_policy_skill
description: >
  契約書・重要事項説明書の内容をAIで要約・説明する際の運用ポリシー。
  条項の場所案内・平易な説明・法律用語の解説は許可するが、
  法的評価・リスク判断・修正提案は禁止する。
  contract_source_qa_prompt の変更・レビュー時に必ず参照する。
triggers:
  - 契約書要約
  - 条項説明
  - 免責表示
  - 非弁
  - policy
  - contract summary
---

# Contract Summary Policy Skill

## When to use

- `contract_source_qa_prompt` を変更・レビューするとき
- 新しい契約書QAのユースケースを追加するとき
- 回答内容が適法範囲内かレビューするとき
- 免責表示の文言を確認・更新するとき

## Procedure

1. `resources/policy.md` を読み、許可・禁止事項を確認する
2. 変更対象のプロンプトまたは回答を `resources/legal_boundary_checklist.md` で照合する
3. 禁止事項に該当する場合はプロンプトを修正する
4. `resources/prompt_additions.md` から最新の禁止事項および免責表示を取得する
5. `src/rag_answerer.py` の `contract_source_qa_prompt` に反映する（許可・禁止・免責表示をプロンプトと同期）
6. `tests/test_rag_contract_prompt_selection.py` で回帰テストを実行する

## Output format

- チェックリスト照合結果（OK / 要修正）
- 修正が必要な場合: 該当箇所と修正案
- 免責表示の付与確認
