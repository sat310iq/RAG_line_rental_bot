# FAQ / KB データの場所（このリポジトリ）

## 既定パス（コード）

| 設定 | デフォルト | 定義 |
|------|------------|------|
| `kb_csv_path` | `data/faq_kb.csv` | [`src/config.py`](../../../../src/config.py) |
| `faq_csv_path` | `data/faq_kb.csv` | 同上（レガシー名・フォールバック用途） |

解決メソッド: `Config.get_kb_csv_path()` / `get_faq_csv_path()`（`Path` を返す）。

## 実行時

- 環境変数または `.env` で上書き可能（`BaseSettings`）。クラウドでは実パスが異なる場合あり → [`docs/LOCAL_VS_CLOUDRUN.md`](../../../../docs/LOCAL_VS_CLOUDRUN.md)。

## 関連コード

- KB ロード・fast path: [`src/kb_fast_path.py`](../../../../src/kb_fast_path.py)
- レスポンダ: [`src/responder.py`](../../../../src/responder.py)
