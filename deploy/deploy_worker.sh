#!/usr/bin/env bash
# Build and deploy Worker to Cloud Run (Pub/Sub Push -> Slack).
# Run from project root. Set GCP_PROJECT_ID or gcloud config set project.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="line-worker"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

cd "$ROOT_DIR"
echo "Building $IMAGE_NAME from $ROOT_DIR (Dockerfile.worker)..."
gcloud builds submit . --config=deploy/cloudbuild_worker.yaml --project "$PROJECT_ID"

echo "Deploying $SERVICE_NAME to Cloud Run..."
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
  --project "$PROJECT_ID"

echo "Done. Set SLACK_WEBHOOK_URL in Cloud Run console. Then run: ./deploy/setup_pubsub.sh https://line-worker-XXXXX-XX.a.run.app (use the actual Worker URL from gcloud run services describe line-worker --region=$REGION --format='value(status.url)')."
