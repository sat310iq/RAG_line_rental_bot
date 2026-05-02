#!/usr/bin/env bash
# Read-only inventory of GCP resources relevant to this PoC (no deletes).
# Usage: bash deploy/check_gcp_resources.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/gcp_poc_common.sh
source "$SCRIPT_DIR/lib/gcp_poc_common.sh"

ROOT="$(gcp_poc_root_dir)"
if ! gcp_poc_load_env_gcp; then
  echo "WARN: deploy/.env.gcp missing; using gcloud config project only."
  PROJECT_ID="$(gcloud config get-value project 2>/dev/null | tr -d '\n')"
  REGION="${GCP_REGION:-asia-northeast1}"
else
  gcp_poc_verify_project_match || exit 1
  PROJECT_ID="${GCP_PROJECT_ID:?}"
  REGION="${GCP_REGION:-asia-northeast1}"
fi

echo "=============================="
echo "GCP PoC resource check"
echo "Project: $PROJECT_ID  Region: $REGION"
echo "Local state file (if any): $(gcp_poc_state_file "$ROOT")"
echo "=============================="

gcp_poc_billing_describe "$PROJECT_ID"
echo ""

echo "--- Cloud Run ($REGION) ---"
gcloud run services list --region="$REGION" --project="$PROJECT_ID" --format="table(metadata.name,status.url)" 2>/dev/null || echo "(list failed)"
echo ""

echo "--- Pub/Sub topics ---"
gcloud pubsub topics list --project="$PROJECT_ID" --format="table(name)" 2>/dev/null || echo "(list failed)"
echo ""

echo "--- Pub/Sub subscriptions ---"
gcloud pubsub subscriptions list --project="$PROJECT_ID" --format="table(name,topic,pushConfig.pushEndpoint)" 2>/dev/null || echo "(list failed)"
echo ""

echo "--- GCR images (line-webhook / line-worker) ---"
for img in line-webhook line-worker; do
  path="gcr.io/${PROJECT_ID}/${img}"
  echo ">> $path"
  gcloud container images list-tags "$path" --project="$PROJECT_ID" --limit=5 --format="table(digest,tags)" 2>/dev/null || echo "  (none or not found)"
done
echo ""

echo "--- Artifact Registry repositories ($REGION) ---"
gcloud artifacts repositories list --project="$PROJECT_ID" --location="$REGION" --format="table(name,format)" 2>/dev/null || echo "(none or API disabled)"
echo ""

echo "--- GCS buckets (project) ---"
gcloud storage buckets list --project="$PROJECT_ID" --format="table(name)" 2>/dev/null \
  || gsutil ls -p "$PROJECT_ID" 2>/dev/null \
  || echo "(list failed; try Cloud Console)"
echo ""

echo "--- Enabled APIs (first 40) ---"
gcloud services list --enabled --project="$PROJECT_ID" --format="value(config.name)" 2>/dev/null | head -40 || echo "(list failed)"
echo ""

if [[ -f "$(gcp_poc_state_file "$ROOT")" ]]; then
  echo "--- Local state (.state/gcp_poc_state.json) ---"
  cat "$(gcp_poc_state_file "$ROOT")"
  echo ""
fi

echo "=============================="
echo "Please verify Billing in Console:"
echo "  https://console.cloud.google.com/billing"
echo "gcloud billing projects describe does NOT show full cost breakdown."
echo "=============================="
