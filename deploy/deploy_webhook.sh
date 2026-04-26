#!/usr/bin/env bash
# Build and deploy LINE Webhook to Cloud Run (RAG + Reply + Pub/Sub publish).
# Run from project root. Set GCP_PROJECT_ID or gcloud config set project.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-asia-northeast1}"
SERVICE_NAME="line-webhook"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

cd "$ROOT_DIR"

# Pre-check: vector store must exist so the image contains indexed KB (avoid empty RAG on Cloud Run)
VECTOR_STORE_DIR="$ROOT_DIR/data/vector_store"
if [[ ! -d "$VECTOR_STORE_DIR" ]] || [[ -z "$(ls -A "$VECTOR_STORE_DIR" 2>/dev/null)" ]]; then
  echo "ERROR: data/vector_store is missing or empty. Run reindex before deploy:"
  echo "  python3 scripts/reindex_vector_db.py   # or: source .venv/bin/activate && python scripts/reindex_vector_db.py"
  exit 1
fi
echo "Pre-check OK: data/vector_store exists with content."
echo "If you changed data/faq_kb.csv: run python3 scripts/reindex_vector_db.py before build (manifest kb_sha256 must match)."

if [[ "${SKIP_PREFLIGHT:-}" == "1" ]]; then
  echo "[WARNING] SKIP_PREFLIGHT=1 — skipping scripts/preflight_check.py (not recommended)"
else
  echo "Running preflight (KB vs manifest, deploy files)..."
  python3 scripts/preflight_check.py
  echo "Preflight OK."
fi

# Optional: if deploy/.env.gcp exists, warn when required keys are missing (Cloud Run env vars still set via console)
ENV_GCP="$ROOT_DIR/deploy/.env.gcp"
REQUIRED_KEYS=(LINE_CHANNEL_SECRET LINE_CHANNEL_ACCESS_TOKEN OPENAI_API_KEY)
if [[ -f "$ENV_GCP" ]]; then
  MISSING=()
  for key in "${REQUIRED_KEYS[@]}"; do
    if ! grep -qE "^${key}=.+" "$ENV_GCP" 2>/dev/null; then
      MISSING+=("$key")
    fi
  done
  if [[ ${#MISSING[@]} -gt 0 ]]; then
    printf "\033[1;33m[WARNING]\033[0m deploy/.env.gcp is missing or has empty value for: %s\n" "${MISSING[*]}"
    printf "\033[1;33m[WARNING]\033[0m Set these in Cloud Run console after deploy, or add to deploy/.env.gcp for reference.\n"
  fi
else
  printf "\033[1;36m[NOTE]\033[0m deploy/.env.gcp not found. Set OPENAI_API_KEY, LINE_CHANNEL_*, etc. in Cloud Run console after deploy.\n"
fi

echo "Building $IMAGE_NAME from $ROOT_DIR (Dockerfile.webhook)..."
gcloud builds submit . --config=deploy/cloudbuild_webhook.yaml --project "$PROJECT_ID"

echo "Deploying $SERVICE_NAME to Cloud Run..."
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_NAME" \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60 \
  --project "$PROJECT_ID"

echo "Done. Set OPENAI_API_KEY, LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, GCP_PROJECT_ID, PUBSUB_TOPIC_NAME in Cloud Run console."
echo "To match local behaviour (e.g. ペット/ガス): set CSV_SCORE_THRESHOLD=0.40 and RAG_RETRIEVAL_K=16 (or leave unset for code default 16). See docs/LOCAL_VS_CLOUDRUN.md"
