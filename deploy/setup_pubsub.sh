#!/usr/bin/env bash
# Create Pub/Sub topic and push subscription to Worker URL.
# Usage: ./setup_pubsub.sh <WORKER_URL>
# Example: ./setup_pubsub.sh https://line-worker-xxxxx-an.a.run.app

set -euo pipefail

WORKER_URL="${1:?Usage: $0 <WORKER_URL>}"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
TOPIC_NAME="${PUBSUB_TOPIC_NAME:-rag-line-events}"
SUB_NAME="${PUBSUB_SUBSCRIPTION_NAME:-rag-line-events-sub}"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Set GCP_PROJECT_ID or run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "Project: $PROJECT_ID Topic: $TOPIC_NAME Sub: $SUB_NAME Push: $WORKER_URL"

gcloud pubsub topics create "$TOPIC_NAME" --project="$PROJECT_ID" 2>/dev/null || true
gcloud pubsub subscriptions create "$SUB_NAME" \
  --project="$PROJECT_ID" \
  --topic="$TOPIC_NAME" \
  --push-endpoint="$WORKER_URL" \
  --ack-deadline=30 \
  2>/dev/null || echo "Subscription may already exist; update with: gcloud pubsub subscriptions update $SUB_NAME --push-endpoint=$WORKER_URL"

echo "Done. Ensure Cloud Run Worker allows unauthenticated invocations for Push (or use authenticated push)."
