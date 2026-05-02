# 用語追加・修正ガイド

## `data/legal_terms_dict.yaml` のフォーマット

```yaml
terms:
  - word: 用語名          # 必須: 検索キー（完全一致で検出）
    plain: 平易な説明      # 必須: 入居者向けの短い説明（1文）
    context: 補足説明      # 任意: 用語が使われる場面・状況
    aliases:              # 任意: 表記ゆれ（これも検出対象になる）
      - 別表記1
      - 別表記2
```

## 追加の判断基準

追加する:

- 入居者が意味を知らない可能性が高い法律・不動産用語
- 契約書・重要事項説明書に実際に出現する語
- aliasが必要な表記ゆれがある語（例: 明渡し / 明け渡し）

追加しない:

- 日常語として理解できる語（「解約」「退去」等）
- 契約書に出現しない一般的な法律用語
- 既存エントリの部分文字列になる語（長い語が先に検出されるため不要）
  例: 「抵当権」は「根抵当権」「将来抵当権」に包含されるため単独追加は慎重に

## plain の書き方ルール

| ルール | 例 |
|---|---|
| 1文で完結する | 「建物が借金のかたになっている状態」 |
| 主語を省略しない | NG: 「借金のかた」 OK: 「建物が借金のかたになっている状態」 |
| 法的判断を含めない | NG: 「借主に不利な権利」 |
| 入居者目線で書く | 「裁判所が建物を強制的に売ること」 |

## 修正時の注意

- `word` を変更する場合は `aliases` への移動を検討する
- `plain` を変更した場合は動作確認スクリプトで出力を確認する
- 削除する場合は `rag_answerer.py` の回帰テストを実行する

## 追加後の確認コマンド

```bash
# 追加した用語が検出されるか確認
python3 -c "
from src.legal_term_resolver import LegalTermResolver
resolver = LegalTermResolver.from_default()

# 追加した用語を含むテスト文を入れる
test_text = '（追加した用語を含む文章をここに入れる）'
matched = resolver.detect(test_text)
print('検出用語:', [t.word for t in matched])
injection = resolver.build_prompt_injection(test_text)
print('injection:')
print(injection)
"
```
