# ローカルテストガイド

## LINE Webhook（FastAPI）

### 前提
- Python 3.11+
- `.env` に以下を設定済み
  - `LINE_CHANNEL_SECRET`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `SLACK_NOTIFY`（trueでSlack通知）
  - `SLACK_WEBHOOK_URL`（通知先のIncoming Webhook）

### 起動
```bash
bash scripts/start_line_webhook.sh
```

### 疑似Webhook送信（署名検証スキップ）
```bash
SKIP_VERIFY=true bash scripts/test_line_webhook.sh
```

### 確認ポイント
- `--channel line` と同様に summaryのみが返る
- 緊急時は先頭に【緊急・注意】が付く
- `SLACK_NOTIFY=true` のときのみSlack通知される
