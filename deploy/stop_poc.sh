#!/usr/bin/env bash
# Stop or tear down GCP PoC resources (idempotent). Run from repo root.
# Usage:
#   bash deploy/stop_poc.sh --mode=suspend [--dry-run] [--yes] [--delete-images] [--reason="..."]
#   bash deploy/stop_poc.sh --mode=delete [--dry-run] [--yes] [--delete-images] [--delete-artifacts] [--reason="..."]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/gcp_poc_common.sh
source "$SCRIPT_DIR/lib/gcp_poc_common.sh"

gcp_poc_trap_err

MODE=""
DRY_RUN=0
YES=0
DELETE_IMAGES=0
DELETE_ARTIFACTS=0
REASON=""

usage() {
  echo "Usage: $0 --mode=suspend|delete [--dry-run] [--yes] [--delete-images] [--delete-artifacts] [--reason=...]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode=suspend) MODE=suspend ;;
    --mode=delete) MODE=delete ;;
    --dry-run) DRY_RUN=1 ;;
    --yes) YES=1 ;;
    --delete-images) DELETE_IMAGES=1 ;;
    --delete-artifacts) DELETE_ARTIFACTS=1 ;;
    --reason=*)
      REASON="${1#--reason=}"
      ;;
    -h|--help) usage ;;
    *) echo "Unknown arg: $1"; usage ;;
  esac
  shift
done

if [[ -z "$MODE" ]]; then
  echo "ERROR: --mode=suspend or --mode=delete is required."
  usage
fi

if [[ "$DELETE_ARTIFACTS" == "1" ]] && [[ "$MODE" != "delete" ]]; then
  echo "ERROR: --delete-artifacts is only valid with --mode=delete"
  exit 1
fi

ROOT="$(gcp_poc_root_dir)"
cd "$ROOT"

gcp_poc_load_env_gcp
gcp_poc_verify_project_match

PROJECT_ID="${GCP_PROJECT_ID:?}"
REGION="${GCP_REGION:-asia-northeast1}"
TOPIC="${PUBSUB_TOPIC_NAME:-rag-line-events}"
SUB="${PUBSUB_SUBSCRIPTION_NAME:-rag-line-events-sub}"

echo "======== GCP PoC stop ========"
echo "Project:  $PROJECT_ID"
echo "Region:   $REGION"
echo "Mode:     $MODE"
echo "Pub/Sub:  topic=$TOPIC subscription=$SUB"
echo "Services: line-webhook, line-worker"
echo "State:    $(gcp_poc_state_file "$ROOT")"
echo "Dry-run:  $DRY_RUN"
echo "============================"

if gcp_poc_prod_warning "$PROJECT_ID"; then
  if [[ "$YES" != "1" ]]; then
    read -r -p "Type project id to confirm (prod-like name): " typed
    if [[ "$typed" != "$PROJECT_ID" ]]; then
      echo "Aborted (project id mismatch)."
      exit 1
    fi
  else
    echo "[NOTE] Proceeding with --yes on prod-like project id."
  fi
fi

gcp_poc_acquire_lock "$ROOT"

if [[ "$YES" != "1" ]] && [[ "$DRY_RUN" != "1" ]]; then
  read -r -p "Proceed with mode=$MODE on project=$PROJECT_ID? [y/N] " ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 1 ;;
  esac
fi

EXPECTED_OUTCOME=""
if [[ "$MODE" == "suspend" ]]; then
  EXPECTED_OUTCOME="Cloud Run min-instances=0; Pub/Sub removed; images kept unless --delete-images"
else
  EXPECTED_OUTCOME="Cloud Run and Pub/Sub removed; GCR PoC images if --delete-images; AR if --delete-artifacts"
fi

dry="$DRY_RUN"

run_suspend() {
  gcp_poc_cloud_run_set_min_instances "$PROJECT_ID" "$REGION" line-webhook "$dry"
  gcp_poc_cloud_run_set_min_instances "$PROJECT_ID" "$REGION" line-worker "$dry"
  gcp_poc_delete_pubsub_subscription_idempotent "$PROJECT_ID" "$SUB" "$dry"
  gcp_poc_delete_pubsub_topic_idempotent "$PROJECT_ID" "$TOPIC" "$dry"
  if [[ "$DELETE_IMAGES" == "1" ]]; then
    gcp_poc_delete_gcr_image_repo_idempotent "$PROJECT_ID" "gcr.io/${PROJECT_ID}/line-webhook" "$dry"
    gcp_poc_delete_gcr_image_repo_idempotent "$PROJECT_ID" "gcr.io/${PROJECT_ID}/line-worker" "$dry"
    gcp_poc_delete_artifact_line_images "$PROJECT_ID" "$REGION" "$dry"
  fi
}

run_delete() {
  gcp_poc_delete_pubsub_subscription_idempotent "$PROJECT_ID" "$SUB" "$dry"
  gcp_poc_delete_pubsub_topic_idempotent "$PROJECT_ID" "$TOPIC" "$dry"
  gcp_poc_cloud_run_delete_idempotent "$PROJECT_ID" "$REGION" line-webhook "$dry"
  gcp_poc_cloud_run_delete_idempotent "$PROJECT_ID" "$REGION" line-worker "$dry"
  if [[ "$DELETE_IMAGES" == "1" ]]; then
    gcp_poc_delete_gcr_image_repo_idempotent "$PROJECT_ID" "gcr.io/${PROJECT_ID}/line-webhook" "$dry"
    gcp_poc_delete_gcr_image_repo_idempotent "$PROJECT_ID" "gcr.io/${PROJECT_ID}/line-worker" "$dry"
  fi
  if [[ "$DELETE_ARTIFACTS" == "1" ]]; then
    echo "Artifact Registry: deleting line-webhook / line-worker packages in $REGION"
    gcp_poc_delete_artifact_line_images "$PROJECT_ID" "$REGION" "$dry"
  fi
}

if [[ "$MODE" == "suspend" ]]; then
  run_suspend
else
  run_delete
fi

# Decision log after successful steps (avoids "completed" entry when set -e aborts mid-way).
if [[ "$DRY_RUN" != "1" ]]; then
  gcp_poc_log_operation "$ROOT" "stop_gcp_poc" "${REASON:-manual}" "$MODE" "$EXPECTED_OUTCOME"
fi

# --- Update local state (best-effort; idempotent re-runs update observation) ---
if [[ "$DRY_RUN" != "1" ]]; then
  if [[ "$MODE" == "suspend" ]]; then
    st=suspended
    if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "line-webhook"; then cr_wh=min0; else cr_wh=deleted; fi
    if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "line-worker"; then cr_wo=min0; else cr_wo=deleted; fi
  else
    st=deleted
    if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "line-webhook"; then cr_wh=exists; else cr_wh=deleted; fi
    if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "line-worker"; then cr_wo=exists; else cr_wo=deleted; fi
  fi
  if gcp_poc_pubsub_topic_exists "$PROJECT_ID" "$TOPIC"; then ps=exists; else ps=deleted; fi

  ig=unknown
  wh_has=0
  wo_has=0
  gcloud container images list-tags "gcr.io/${PROJECT_ID}/line-webhook" --limit=1 --format="value(digest)" 2>/dev/null | grep -q . && wh_has=1 || true
  gcloud container images list-tags "gcr.io/${PROJECT_ID}/line-worker" --limit=1 --format="value(digest)" 2>/dev/null | grep -q . && wo_has=1 || true
  if [[ "$wh_has" == "1" ]] || [[ "$wo_has" == "1" ]]; then ig=exists; else ig=deleted; fi

  ia=unknown
  if [[ "$DELETE_ARTIFACTS" == "1" ]]; then ia=deleted; else ia=unknown; fi

  WORKER_URL_STORE=""
  if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "line-worker"; then
    WORKER_URL_STORE="$(gcp_poc_worker_url "$PROJECT_ID" "$REGION" || true)"
  fi

  export GCP_POC_ST="$st" GCP_POC_CRWH="$cr_wh" GCP_POC_CRWO="$cr_wo" GCP_POC_PS="$ps" GCP_POC_IG="$ig" GCP_POC_IA="$ia" GCP_POC_WURL="$WORKER_URL_STORE"
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
fi

gcp_poc_billing_describe "$PROJECT_ID"
echo ""
echo "Done. Review state: $(gcp_poc_state_file "$ROOT")"
echo "Next: bash deploy/check_gcp_resources.sh"
echo "Billing: verify in Cloud Console (Reports) — gcloud billing describe alone is not a full cost view."
