# TXTファイルからの用語自動抽出ガイド

新しいTXTファイルを追加したあと、または辞書の網羅性を確認したいときに使う。
抽出結果は候補であり、そのまま辞書に追加しない。必ず手動レビューを行う。

## 抽出スクリプト

```bash
python3 -c "
import re
from pathlib import Path
import yaml

# スキャン対象ディレクトリ
docs_dir = Path('data/documents')

# 法律・不動産用語のパターン
patterns = [
    r'[一-龯]{2,}権',      # ○○権（抵当権・賃借権等）
    r'[一-龯]{2,}義務',    # ○○義務
    r'[一-龯]{2,}責任',    # ○○責任
    r'[一-龯]{2,}解除',    # ○○解除
    r'[一-龯]{2,}違約',    # ○○違約
    r'競[売落]',           # 競売・競落
    r'明[渡け]',           # 明渡し・明け渡し
    r'猶予期間',
    r'対抗',
    r'登記',
    r'原状回復',
    r'善管注意',
    r'連帯保証',
]

with open('data/legal_terms_dict.yaml', encoding='utf-8') as f:
    dict_data = yaml.safe_load(f)

existing = set()
for t in dict_data.get('terms', []):
    existing.add(t['word'])
    for a in t.get('aliases', []):
        existing.add(a)

candidates = set()
for txt_file in sorted(docs_dir.glob('*.txt')):
    print(f'=== {txt_file.name} ===')
    content = txt_file.read_text(encoding='utf-8', errors='ignore')
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            candidates.add(match.group())

print()
print('=== 新規候補（辞書未登録）===')
new_candidates = candidates - existing
for term in sorted(new_candidates):
    print(f'  - {term}')
print(f'新規候補: {len(new_candidates)}件 / 全候補: {len(candidates)}件')
"
```

## 抽出後のレビュー手順

1. 出力された「新規候補」を確認する
2. `term_update_guide.md` の「追加の判断基準」で各候補を評価する
3. 追加する候補について `word` / `plain` / `context` / `aliases` を決める
4. `data/legal_terms_dict.yaml` に追記する
5. 動作確認スクリプトを実行する

## ノイズの除去基準

抽出候補からの除外パターン:

| パターン | 理由 | 例 |
|---|---|---|
| 断片・接頭語 | 意味が不完全 | `明け`、`他本` |
| 日常語 | 説明不要 | `契約解除`（「解約」で十分） |
| 既存エントリの部分文字列 | 長い語が優先されるため不要 | `抵当権`（`将来抵当権`に包含） |
| 文脈依存語 | 単独では意味が不明 | `注意義務` |

## 他PoCへの横展開時

横展開先のTXTファイルに対して同じスクリプトを実行する。
抽出スクリプト内の `docs_dir` を横展開先に合わせて変更する。

```python
# 例: Decision OS の場合（抽出スクリプト先頭の docs_dir を差し替え）
docs_dir = Path("path/to/decision_os/data/documents")
```
