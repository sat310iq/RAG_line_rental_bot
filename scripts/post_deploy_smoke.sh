#!/usr/bin/env bash
# Post-deploy smoke against Cloud Run URL (public HTTPS).
# Usage: BASE_URL=https://line-webhook-xxxxx.run.app ./scripts/post_deploy_smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:?Set BASE_URL to the Cloud Run service URL (https://...)}"
BASE_URL="${BASE_URL%/}"

echo "Post-deploy smoke: ${BASE_URL}"
curl -fsS "${BASE_URL}/health"
echo ""
code="$(curl -s -o /tmp/ready_prod.json -w '%{http_code}' "${BASE_URL}/ready")"
cat /tmp/ready_prod.json
echo ""
if [[ "${code}" != "200" ]]; then
  echo "FAIL: /ready returned HTTP ${code}" >&2
  exit 1
fi

echo "Check Cloud Run logs for CONFIG_SUMMARY and manifest (kb_sha256)."
echo "post_deploy_smoke.sh OK"
