#!/usr/bin/env bash
# Build only: build LINE Webhook image and push to GCR. Does NOT deploy to Cloud Run.
# Run from project root. Set GCP_PROJECT_ID or gcloud config set project.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
IMAGE_NAME="gcr.io/${PROJECT_ID}/line-webhook"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

cd "$ROOT_DIR"

# Pre-check: vector store must exist so the image contains indexed KB (avoid empty RAG on Cloud Run)
VECTOR_STORE_DIR="$ROOT_DIR/data/vector_store"
if [[ ! -d "$VECTOR_STORE_DIR" ]] || [[ -z "$(ls -A "$VECTOR_STORE_DIR" 2>/dev/null)" ]]; then
  echo "ERROR: data/vector_store is missing or empty. Run reindex before build:"
  echo "  python3 scripts/reindex_vector_db.py   # or: source .venv/bin/activate && python scripts/reindex_vector_db.py"
  exit 1
fi
echo "Pre-check OK: data/vector_store exists with content."

echo "Building $IMAGE_NAME from $ROOT_DIR (build only; no deploy)..."
gcloud builds submit . --config=deploy/cloudbuild_webhook.yaml --project "$PROJECT_ID"

echo "Done. Image $IMAGE_NAME is built. To deploy to Cloud Run, run:"
echo "  ./deploy/deploy_webhook.sh   # full deploy (will build again), or"
echo "  gcloud run deploy line-webhook --image $IMAGE_NAME --region \${GCP_REGION:-asia-northeast1} --platform managed --allow-unauthenticated --memory 1Gi --cpu 1 --min-instances 0 --max-instances 5 --timeout 60 --project $PROJECT_ID"
