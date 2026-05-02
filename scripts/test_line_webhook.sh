#!/usr/bin/env bash
set -euo pipefail

URL="${URL:-http://localhost:8000/webhook}"
TEXT="${TEXT:-ペットの飼育はできますか？}"
SKIP_VERIFY="${SKIP_VERIFY:-false}"

payload=$(cat <<EOF
{
  "events": [
    {
      "type": "message",
      "replyToken": "dummy",
      "source": { "userId": "U123456" },
      "message": { "type": "text", "text": "$TEXT" }
    }
  ]
}
EOF
)

if [ "$SKIP_VERIFY" = "true" ]; then
  curl -s -X POST "$URL?skip_verify=true" \
    -H "Content-Type: application/json" \
    -H "X-Line-Signature: dummy" \
    -d "$payload"
else
  echo "署名検証ありのテストは未対応です。SKIP_VERIFY=true で実行してください。"
fi
