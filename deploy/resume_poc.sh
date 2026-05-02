#!/usr/bin/env bash
# Rebuild and redeploy PoC: Worker -> Pub/Sub -> Webhook. Run from repo root.
# Usage: bash deploy/resume_poc.sh [--dry-run] [--yes] [--reason="..."]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/gcp_poc_common.sh
source "$SCRIPT_DIR/lib/gcp_poc_common.sh"

gcp_poc_trap_err

DRY_RUN=0
YES=0
REASON=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes) YES=1 ;;
    --reason=*) REASON="${1#--reason=}" ;;
    -h|--help)
      echo "Usage: $0 [--dry-run] [--yes] [--reason=...]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
  shift
done

ROOT="$(gcp_poc_root_dir)"
cd "$ROOT"

gcp_poc_load_env_gcp
gcp_poc_verify_project_match

PROJECT_ID="${GCP_PROJECT_ID:?}"
REGION="${GCP_REGION:-asia-northeast1}"

echo "======== GCP PoC resume ========"
echo "Project: $PROJECT_ID  Region: $REGION"
echo "Order:   deploy_worker.sh -> setup_pubsub.sh (Worker URL) -> deploy_webhook.sh"
echo "State:   $(gcp_poc_state_file "$ROOT")"
echo "Dry-run: $DRY_RUN"
echo "==============================="

if gcp_poc_prod_warning "$PROJECT_ID"; then
  if [[ "$YES" != "1" ]]; then
    read -r -p "Type project id to confirm: " typed
    if [[ "$typed" != "$PROJECT_ID" ]]; then
      echo "Aborted."
      exit 1
    fi
  fi
fi

gcp_poc_acquire_lock "$ROOT"

VECTOR_STORE_DIR="$ROOT/data/vector_store"
if [[ ! -d "$VECTOR_STORE_DIR" ]] || [[ -z "$(ls -A "$VECTOR_STORE_DIR" 2>/dev/null)" ]]; then
  echo "ERROR: data/vector_store is missing or empty. Run: python3 scripts/reindex_vector_db.py"
  exit 1
fi

if [[ "$YES" != "1" ]] && [[ "$DRY_RUN" != "1" ]]; then
  read -r -p "Deploy Worker + Pub/Sub + Webhook on $PROJECT_ID? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Aborted."; exit 1 ;; esac
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[dry-run] would run: deploy/deploy_worker.sh"
  echo "[dry-run] would run: deploy/setup_pubsub.sh \"\$WORKER_URL\""
  echo "[dry-run] would run: deploy/deploy_webhook.sh"
  exit 0
fi

export GCP_PROJECT_ID="$PROJECT_ID"
export GCP_REGION="$REGION"

echo ">>> $(date -u +"%Y-%m-%dT%H:%M:%SZ") deploy_worker.sh"
bash "$SCRIPT_DIR/deploy_worker.sh"

WORKER_URL="$(gcp_poc_worker_url "$PROJECT_ID" "$REGION")"
if [[ -z "$WORKER_URL" ]]; then
  echo "ERROR: could not read line-worker URL"
  exit 1
fi
echo "Worker URL: $WORKER_URL"

echo ">>> $(date -u +"%Y-%m-%dT%H:%M:%SZ") setup_pubsub.sh"
bash "$SCRIPT_DIR/setup_pubsub.sh" "$WORKER_URL"

echo ">>> $(date -u +"%Y-%m-%dT%H:%M:%SZ") deploy_webhook.sh"
bash "$SCRIPT_DIR/deploy_webhook.sh"

WEBHOOK_URL="$(gcloud run services describe line-webhook --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)' 2>/dev/null || true)"

gcp_poc_log_operation "$ROOT" "resume_gcp_poc" "${REASON:-manual}" "resume" "Worker+PubSub+Webhook active"

export GCP_POC_ST=active GCP_POC_CRWH=min0 GCP_POC_CRWO=min0 GCP_POC_PS=exists GCP_POC_IG=exists GCP_POC_IA=unknown GCP_POC_WURL="$WORKER_URL"
frag="$(python3 <<'PY'
import json, os
print(json.dumps({
    "status": os.environ["GCP_POC_ST"],
    "cloud_run_webhook": os.environ["GCP_POC_CRWH"],
    "cloud_run_worker": os.environ["GCP_POC_CRWO"],
    "pubsub": os.environ["GCP_POC_PS"],
    "images_gcr": os.environ["GCP_POC_IG"],
    "images_artifact": os.environ["GCP_POC_IA"],
    "worker_url": os.environ.get("GCP_POC_WURL", ""),
}))
PY
)"
gcp_poc_state_merge "$ROOT" "$frag"

echo ""
echo "Done. State: $(gcp_poc_state_file "$ROOT")"
echo ""
echo "Verify:"
echo "  curl -sS \"${WEBHOOK_URL}/\"   # expect JSON ok"
echo "  gcloud run services list --region=$REGION --project=$PROJECT_ID"
echo ""
echo "LINE Developers: set Webhook URL to ${WEBHOOK_URL}/webhook (if using LINE)."
gcp_poc_billing_describe "$PROJECT_ID"
echo ""
echo "Also open Billing Reports in Console to confirm usage."
