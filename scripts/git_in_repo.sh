#!/usr/bin/env bash
# Run git with cwd set to the rental_rag_poc repository root (this script lives in scripts/).
# Usage (from a parent directory):
#   ./rental_rag_poc/scripts/git_in_repo.sh status --short
#   ./rental_rag_poc/scripts/git_in_repo.sh add -p
#   ./rental_rag_poc/scripts/git_in_repo.sh commit -m "message"
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ ! -d .git ]; then
  echo "Error: not inside rental_rag_poc git repo (missing .git in ${REPO_ROOT})" >&2
  exit 1
fi

exec git "$@"
