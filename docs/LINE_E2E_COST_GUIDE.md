# LINE連携 運用手順（起動→テスト→停止・コスト最適化）

## 前提
- `.env` にLINE/Slackの認証情報を設定済み
- 依存インストール済み（`pip install -r requirements.txt`）

## 手順（手動）

### 1) 起動
```bash
python3 -m src.interfaces.line.main
```

### 2) ngrok起動（任意・外部公開が必要な場合）
```bash
ngrok http 8000
```

### 3) テスト
ローカル確認:
```bash
SKIP_VERIFY=true bash scripts/test_line_webhook.sh
```

LINE実機:
- LINE DevelopersのWebhook URLに `https://<ngrokのドメイン>/webhook` を設定
- LINEアプリからメッセージ送信 → 返信/Slack通知を確認

### 4) 停止（コスト最適化）
- サーバ/ ngrok を停止（ターミナルで `Ctrl+C`）
- 実機テストを終えたら必ず停止する

## 手順（自動スクリプト）
```bash
bash scripts/line_e2e_cycle.sh
```

### オプション
- `RUN_NGROK=true`：ngrokを起動（インストール済みの場合）
- `SKIP_VERIFY=true`：署名検証スキップ（既定: true）
- `TEXT=...`：テストメッセージ

例:
```bash
RUN_NGROK=true TEXT="設備の故障です" bash scripts/line_e2e_cycle.sh
```

## コスト最適化のポイント
- ngrok/サーバは必要な時だけ起動し、確認後すぐ停止
- 実機テストの頻度を下げ、ローカルテストを優先
- `python3 -m src.interfaces.line.main` はローカル実行のため、これだけではGoogle Cloudの資源は稼働し続けない
- GCP課金はCloud Run/VM/PubSub等のクラウド資源を起動している場合に発生する