---
name: legal_terms_skill
description: >
  賃貸契約・重要事項説明書に含まれる法律・不動産用語辞書の管理・更新・横展開。
  用語の追加・修正・TXTからの自動抽出・他PoC展開の手順を提供する。
  辞書本体: data/legal_terms_dict.yaml
  実装本体: src/legal_term_resolver.py
triggers:
  - 法律用語
  - 辞書更新
  - legal terms
  - term extraction
  - 用語追加
  - 辞書横展開
---

# Legal Terms Skill

## When to use

- `data/legal_terms_dict.yaml` に用語を追加・修正するとき
- 新しいTXTファイルを追加したあと、用語候補を抽出するとき
- 辞書を別のPoC（Decision OS等）に横展開するとき
- `src/legal_term_resolver.py` の動作を確認・修正するとき

## Procedure

### 用語の追加・修正

1. `resources/auto_extract_guide.md` の抽出スクリプトを実行して候補を出す
2. 候補を `resources/term_update_guide.md` のフォーマットでレビューする
3. `data/legal_terms_dict.yaml` に追記する
4. 動作確認スクリプトを実行する（下記）
5. `src/rag_answerer.py` のデプロイが必要な場合は deploy_webhook.sh を実行する

### 動作確認スクリプト

```bash
python3 -c "
from src.legal_term_resolver import LegalTermResolver
resolver = LegalTermResolver.from_default()
print('辞書件数:', len(resolver._terms))
terms = [t.word for t in resolver._terms]
print('用語一覧:', terms)
"
```

### 他PoCへの横展開

1. `data/legal_terms_dict.yaml` を横展開先の `data/` にコピーする
2. 横展開先の `src/legal_term_resolver.py` の `DEFAULT_DICT_PATH` を更新する
3. 横展開先ドメインの用語を追加・削除してカスタマイズする

## Output format

- 追加した用語数・用語名の一覧
- 動作確認スクリプトの出力
- 横展開の場合: コピー先パスと変更箇所
