#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-"$PROJECT_ROOT/.venv/bin/python"}"
RUN_NGROK="${RUN_NGROK:-false}"
SKIP_VERIFY="${SKIP_VERIFY:-true}"
TEXT="${TEXT:-ペットの飼育はできますか？}"

cleanup() {
  if [[ -n "${WEBHOOK_PID:-}" ]]; then
    kill "$WEBHOOK_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "${NGROK_PID:-}" ]]; then
    kill "$NGROK_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Pythonが見つかりません: $PYTHON_BIN" >&2
  echo "例: PYTHON_BIN=\"$PROJECT_ROOT/.venv/bin/python\" bash scripts/line_e2e_cycle.sh" >&2
  exit 1
fi

echo "[1/4] LINE Webhook起動"
"$PYTHON_BIN" -m src.interfaces.line.main >/tmp/line_webhook.log 2>&1 &
WEBHOOK_PID=$!
sleep 1

if [[ "$RUN_NGROK" = "true" ]]; then
  if command -v ngrok >/dev/null 2>&1; then
    echo "[2/4] ngrok起動"
    ngrok http 8000 >/tmp/ngrok.log 2>&1 &
    NGROK_PID=$!
    sleep 1
  else
    echo "ngrokが見つかりません。RUN_NGROKをfalseにするか、ngrokをインストールしてください。" >&2
  fi
else
  echo "[2/4] ngrokはスキップ"
fi

echo "[3/4] ローカルテスト実行"
SKIP_VERIFY="$SKIP_VERIFY" TEXT="$TEXT" bash "$PROJECT_ROOT/scripts/test_line_webhook.sh"

echo "[4/4] 停止（コスト最適化）"
echo "完了しました。"
