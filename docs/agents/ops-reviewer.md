# Ops Reviewer（運用レビュー役）

## 役割

ランタイムの安全性・再現性・障害切り分けのしやすさをレビューする。

## 観点

- 冪等性・重複 Webhook
- メモリ・埋め込みモデル初期化（`ops_memory_risk`）
- タイムアウト・フォールバック（`timeout_fallback`）
- LINE 返信経路（`line_reply_failure`）

## チェックリスト

- 重い処理が毎リクエストで増えないか  
- ログで失敗種別が追えるか  
- Cloud Run の制約（CPU・メモリ・コールドスタート）を踏まえた設定か  
