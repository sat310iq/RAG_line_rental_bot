#!/usr/bin/env bash
# One-shot deploy: Webhook -> Worker -> Pub/Sub. Run from project root or any dir.
# Prereq: gcloud CLI, gcloud auth login, gcloud config set project (or set GCP_PROJECT_ID).
# Optional: copy deploy/.env.gcp.example to deploy/.env.gcp and set GCP_PROJECT_ID, GCP_REGION.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Pre-flight checks ---
if ! command -v gcloud &>/dev/null; then
  echo "Error: gcloud CLI not found. Install Google Cloud SDK and add gcloud to PATH."
  exit 1
fi

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1)"
if [[ -z "${ACTIVE_ACCOUNT}" ]]; then
  echo "Error: Not logged in to gcloud. Run: gcloud auth login"
  exit 1
fi

# Load deploy/.env.gcp if present (so GCP_PROJECT_ID, GCP_REGION are set for child scripts)
if [[ -f "$SCRIPT_DIR/.env.gcp" ]]; then
  set -a
  # shellcheck source=deploy/.env.gcp.example
  source "$SCRIPT_DIR/.env.gcp"
  set +a
fi

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: GCP project not set. Set GCP_PROJECT_ID in deploy/.env.gcp or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

REGION="${GCP_REGION:-asia-northeast1}"
echo "Deploy target: project=$PROJECT_ID region=$REGION"
echo ""

cd "$ROOT_DIR"

# --- Webhook ---
if [[ "${DEPLOY_SKIP_WEBHOOK:-0}" != "1" ]]; then
  echo "=== Deploying Webhook ==="
  "$SCRIPT_DIR/deploy_webhook.sh"
  echo ""
else
  echo "=== Skipping Webhook (DEPLOY_SKIP_WEBHOOK=1) ==="
fi

# --- Worker ---
if [[ "${DEPLOY_SKIP_WORKER:-0}" != "1" ]]; then
  echo "=== Deploying Worker ==="
  "$SCRIPT_DIR/deploy_worker.sh"
  echo ""
else
  echo "=== Skipping Worker (DEPLOY_SKIP_WORKER=1) ==="
fi

# --- Pub/Sub: get Worker URL and create/update push subscription ---
if [[ "${DEPLOY_SKIP_PUBSUB:-0}" != "1" ]]; then
  echo "=== Setting up Pub/Sub ==="
  WORKER_URL="$(gcloud run services describe line-worker --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)' 2>/dev/null)"
  if [[ -z "${WORKER_URL}" ]]; then
    echo "Error: Could not get line-worker URL. Deploy Worker first or set DEPLOY_SKIP_PUBSUB=1 to skip."
    exit 1
  fi
  "$SCRIPT_DIR/setup_pubsub.sh" "$WORKER_URL"
  echo ""
else
  echo "=== Skipping Pub/Sub (DEPLOY_SKIP_PUBSUB=1) ==="
fi

echo "Deploy complete. Set Cloud Run env vars (OPENAI_API_KEY, LINE_*, SLACK_WEBHOOK_URL, etc.) in the console or via gcloud run services update if not already set."
