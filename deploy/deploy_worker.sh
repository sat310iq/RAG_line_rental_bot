#!/usr/bin/env bash
# Build and deploy Worker to Cloud Run (Pub/Sub Push -> Slack).
# Run from project root. Set GCP_PROJECT_ID or gcloud config set project.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="line-worker"
AR_REPO="${AR_REPO:-cloud-run}"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/${SERVICE_NAME}"
REVISION_SUFFIX="$(date -u +%Y%m%d-%H%M)"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

cd "$ROOT_DIR"
echo "Building $IMAGE_NAME from $ROOT_DIR (Dockerfile.worker)..."
gcloud builds submit . \
  --config=deploy/cloudbuild_worker.yaml \
  --substitutions="_IMAGE_NAME=${IMAGE_NAME}" \
  --project "$PROJECT_ID"

echo "Deploying $SERVICE_NAME to Cloud Run (revision: ${REVISION_SUFFIX})..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_NAME" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 256Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 10 \
  --timeout 30 \
  --revision-suffix "$REVISION_SUFFIX" \
  --project "$PROJECT_ID"

echo "Done. Revision: ${SERVICE_NAME}-${REVISION_SUFFIX}"
echo "To roll back: gcloud run services update-traffic ${SERVICE_NAME} --to-revisions=PREV_REVISION=100 --region=${REGION}"
echo "Set SLACK_WEBHOOK_URL in Cloud Run console. Then run: ./deploy/setup_pubsub.sh (Worker URL from gcloud run services describe ${SERVICE_NAME} --region=${REGION} --format='value(status.url)')"
