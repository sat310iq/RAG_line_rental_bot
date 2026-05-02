#!/usr/bin/env bash
# Smoke test against a running LINE webhook container (local or CI).
# Usage: ./scripts/container_smoke_test.sh [BASE_URL]
# Default BASE_URL=http://127.0.0.1:8080
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8080}"
BASE_URL="${BASE_URL%/}"

echo "Smoke: GET ${BASE_URL}/health"
curl -fsS "${BASE_URL}/health"
echo ""

echo "Smoke: GET ${BASE_URL}/ready"
code="$(curl -s -o /tmp/ready.json -w '%{http_code}' "${BASE_URL}/ready")"
cat /tmp/ready.json
echo ""
if [[ "${code}" != "200" ]]; then
  echo "FAIL: /ready returned HTTP ${code}" >&2
  exit 1
fi

# Optional: POST /debug/rag when ENABLE_DEBUG_RAG_ENDPOINT=true in container env
if [[ "${SMOKE_TEST_DEBUG_RAG:-}" == "1" ]]; then
  echo "Smoke: POST ${BASE_URL}/debug/rag (SMOKE_TEST_DEBUG_RAG=1)"
  curl -fsS -X POST "${BASE_URL}/debug/rag" \
    -H "Content-Type: application/json" \
    -d '{"question":"ゴミ出しのルールは？"}'
  echo ""
fi

echo "container_smoke_test.sh OK"
