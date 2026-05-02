#!/usr/bin/env bash
# Option 1: Cloud Run min-instances=0 (no delete), optional Pub/Sub cleanup,
# optional GCR / Artifact Registry image trim (keep latest N digests per image/repo package).
# See docs/GCP_SUSPEND_AND_IMAGE_TRIM.md

set -euo pipefail

export CLOUDSDK_PYTHON="${CLOUDSDK_PYTHON:-/usr/bin/python3}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib/gcp_poc_common.sh
source "$SCRIPT_DIR/lib/gcp_poc_common.sh"

gcp_poc_trap_err

KEEP_LATEST=3
DRY_RUN=0
YES=0
DELETE_PUBSUB=0
DELETE_GCR=0
DELETE_AR=0

usage() {
  echo "Usage: $0 [--dry-run] [--yes] [--keep-latest N]"
  echo "          [--delete-pubsub] [--delete-gcr-images] [--delete-ar-images]"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --yes) YES=1 ;;
    --keep-latest)
      KEEP_LATEST="${2:?--keep-latest requires N}"
      shift
      ;;
    --delete-pubsub) DELETE_PUBSUB=1 ;;
    --delete-gcr-images) DELETE_GCR=1 ;;
    --delete-ar-images) DELETE_AR=1 ;;
    -h|--help) usage ;;
    *) echo "Unknown: $1"; usage ;;
  esac
  shift
done

if ! [[ "$KEEP_LATEST" =~ ^[0-9]+$ ]] || [[ "$KEEP_LATEST" -lt 1 ]]; then
  echo "ERROR: --keep-latest must be a positive integer"
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  TARGET GCP PROJECT (mis-delete guard: must match .env.gcp)   ║"
echo "╚══════════════════════════════════════════════════════════════╝"

gcp_poc_load_env_gcp
gcp_poc_verify_project_match

PROJECT_ID="${GCP_PROJECT_ID:?}"
REGION="${GCP_REGION:-asia-northeast1}"

echo ""
echo "  GCP_PROJECT_ID: $PROJECT_ID"
echo "  GCP_REGION:     $REGION"
echo "  KEEP_LATEST:    $KEEP_LATEST"
echo "  DRY_RUN:        $DRY_RUN"
echo "  delete pubsub:  $DELETE_PUBSUB | gcr: $DELETE_GCR | ar: $DELETE_AR"
echo ""

if gcp_poc_prod_warning "$PROJECT_ID"; then
  if [[ "$YES" != "1" ]]; then
    read -r -p "Type project id to confirm (prod-like id): " typed
    if [[ "$typed" != "$PROJECT_ID" ]]; then
      echo "Aborted."
      exit 1
    fi
  else
    echo "[NOTE] --yes on prod-like project id: $PROJECT_ID"
  fi
fi

if [[ "$YES" != "1" ]] && [[ "$DRY_RUN" != "1" ]]; then
  read -r -p "Proceed on project=$PROJECT_ID ? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Aborted."; exit 1 ;; esac
fi

run_gcloud() {
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would run: $*"
  else
    "$@"
  fi
}

SUM_SUSPEND=""
SUM_DEL_SUB=""
SUM_DEL_TOPIC=""
SUM_KEEP_PUBSUB=""
SUM_GCR_DEL=""
SUM_GCR_KEEP=""
SUM_AR_DEL=""
SUM_AR_KEEP=""

short_resource_name() {
  echo "${1##*/}"
}

# ========== [PROJECT CHECK] ==========
echo "======== [PROJECT CHECK] ========"
echo "OK: deploy/.env.gcp matches gcloud active project."
echo ""

# ========== [CLOUD RUN] ==========
echo "======== [CLOUD RUN] =========="
echo "Action: set min-instances=0 if line-webhook / line-worker exist (never delete services)."

for svc in line-webhook line-worker; do
  if gcp_poc_cloud_run_exists "$PROJECT_ID" "$REGION" "$svc"; then
    echo "  Found Cloud Run: $svc → min-instances=0"
    SUM_SUSPEND="${SUM_SUSPEND}${svc} "
    if [[ "$DRY_RUN" == "1" ]]; then
      echo "  [dry-run] gcloud run services update $svc --min-instances=0 ..."
    else
      gcloud run services update "$svc" --min-instances=0 --region="$REGION" --project="$PROJECT_ID" --quiet
    fi
  else
    echo "  skip: Cloud Run not found: $svc"
  fi
done
echo ""

# ========== [PUBSUB] ==========
echo "======== [PUBSUB] ========"

if [[ "$DELETE_PUBSUB" != "1" ]]; then
  echo "skip: --delete-pubsub not set (no Pub/Sub changes)."
  SUM_KEEP_PUBSUB="unchanged (--delete-pubsub off)"
else
  CANDIDATE_TOPICS=()
  CANDIDATE_SUBS=()

  # NOTE: use indexed loops (not "${arr[@]}") so bash 3.2 + set -u works on empty arrays.
  _gcp_trim_add_topic() {
    local x="${1:-}"
    [[ -z "$x" ]] && return
    local i n="${#CANDIDATE_TOPICS[@]}"
    for ((i = 0; i < n; i++)); do
      [[ "${CANDIDATE_TOPICS[i]}" == "$x" ]] && return
    done
    CANDIDATE_TOPICS+=("$x")
  }
  _gcp_trim_add_sub() {
    local x="${1:-}"
    [[ -z "$x" ]] && return
    local i n="${#CANDIDATE_SUBS[@]}"
    for ((i = 0; i < n; i++)); do
      [[ "${CANDIDATE_SUBS[i]}" == "$x" ]] && return
    done
    CANDIDATE_SUBS+=("$x")
  }

  # Prefer deploy/.env.gcp (same keys as setup_pubsub.sh); defaults are fallback.
  [[ -n "${PUBSUB_TOPIC_NAME:-}" ]] && _gcp_trim_add_topic "$PUBSUB_TOPIC_NAME"
  _gcp_trim_add_topic "rag-line-events"
  _gcp_trim_add_topic "line-events"
  _gcp_trim_add_topic "line-events-dlq"
  [[ -n "${PUBSUB_SUBSCRIPTION_NAME:-}" ]] && _gcp_trim_add_sub "$PUBSUB_SUBSCRIPTION_NAME"
  _gcp_trim_add_sub "rag-line-events-sub"

  echo "Mode: delete matching subscriptions first, then candidate topics."
  echo "Candidate topics (env PUBSUB_TOPIC_NAME first if set, then defaults):"
  echo "    ${CANDIDATE_TOPICS[*]}"
  echo "Candidate subscriptions (env PUBSUB_SUBSCRIPTION_NAME first if set, then defaults):"
  echo "    ${CANDIDATE_SUBS[*]}"
  echo "Also deletes any subscription whose topic short name is in the topic list above."

  sub_should_delete() {
    local sub_full="$1" topic_full="$2"
    local ss ts
    ss="$(short_resource_name "$sub_full")"
    ts="$(short_resource_name "${topic_full:-}")"
    local s
    for s in "${CANDIDATE_SUBS[@]}"; do
      [[ "$ss" == "$s" ]] && return 0
    done
    local t
    for t in "${CANDIDATE_TOPICS[@]}"; do
      [[ "$ts" == "$t" ]] && return 0
    done
    return 1
  }

  subs_json="$(gcloud pubsub subscriptions list --project="$PROJECT_ID" --format=json 2>/dev/null || echo '[]')"

  while IFS= read -r sub_full; do
    [[ -z "$sub_full" ]] && continue
    topic_full="$(echo "$subs_json" | python3 -c "
import json,sys
sub=sys.argv[1]
data=json.load(sys.stdin)
for row in data:
    if row.get('name','')==sub:
        print(row.get('topic',''))
        break
" "$sub_full" 2>/dev/null || true)"
    if sub_should_delete "$sub_full" "$topic_full"; then
      sn="$(short_resource_name "$sub_full")"
      echo "  DELETE subscription: $sn (topic $(short_resource_name "${topic_full:-none}"))"
      SUM_DEL_SUB="${SUM_DEL_SUB}${sn} "
      if [[ "$DRY_RUN" == "1" ]]; then
        run_gcloud gcloud pubsub subscriptions delete "$sn" --project="$PROJECT_ID" --quiet
      else
        if gcp_poc_pubsub_subscription_exists "$PROJECT_ID" "$sn"; then
          gcloud pubsub subscriptions delete "$sn" --project="$PROJECT_ID" --quiet || true
        else
          echo "  skip: subscription already gone: $sn"
        fi
      fi
    fi
  done < <(echo "$subs_json" | python3 -c "import json,sys; [print(r.get('name','')) for r in json.load(sys.stdin)]" 2>/dev/null || true)

  for tshort in "${CANDIDATE_TOPICS[@]}"; do
    if gcp_poc_pubsub_topic_exists "$PROJECT_ID" "$tshort"; then
      echo "  DELETE topic: $tshort"
      SUM_DEL_TOPIC="${SUM_DEL_TOPIC}${tshort} "
      run_gcloud gcloud pubsub topics delete "$tshort" --project="$PROJECT_ID" --quiet
    else
      echo "  skip topic not found: $tshort"
    fi
  done

  if [[ -z "${SUM_DEL_SUB// }" ]] && [[ -z "${SUM_DEL_TOPIC// }" ]]; then
    SUM_KEEP_PUBSUB="no matching subs/topics to delete"
  else
    SUM_KEEP_PUBSUB="removed: subs=[${SUM_DEL_SUB}] topics=[${SUM_DEL_TOPIC}]"
  fi
fi
echo ""

# ========== [GCR] ==========
echo "======== [GCR] ========"
if [[ "$DELETE_GCR" != "1" ]]; then
  echo "skip: --delete-gcr-images not set."
  SUM_GCR_KEEP="unchanged"
else
  prune_gcr_repo() {
    local repo_path="$1"
    local keep_n="$2"
    echo "  Image: $repo_path (keep newest $keep_n digest(s) by list-tags timestamp)"
    if ! gcloud container images list-tags "$repo_path" --project="$PROJECT_ID" --limit=1 --format="value(digest)" &>/dev/null; then
      echo "  skip: no digests or missing: $repo_path"
      return 0
    fi
    local json
    json="$(gcloud container images list-tags "$repo_path" --project="$PROJECT_ID" --format=json 2>/dev/null || echo '[]')"
    local plan
    plan="$(echo "$json" | KEEP="$keep_n" python3 <<'PY'
import json, os, sys

def ts_key(row):
    ts = row.get("timestamp") or {}
    if isinstance(ts, dict):
        return ts.get("datetime") or str(ts.get("seconds") or "")
    return str(ts) if ts else ""

keep = int(os.environ.get("KEEP", "3"))
data = json.loads(sys.stdin.read() or "[]")
if not data:
    print("NONE")
    sys.exit(0)
rows = sorted(data, key=lambda r: ts_key(r), reverse=True)

def full_digest(d):
    d = (d or "").strip()
    return d if d.startswith("sha256:") else f"sha256:{d}"

to_del = [full_digest(r["digest"]) for r in rows[keep:] if r.get("digest")]
print("KEEP:", json.dumps([full_digest(r["digest"]) for r in rows[:keep] if r.get("digest")]))
print("DEL:", json.dumps(to_del))
PY
)"

    if echo "$plan" | grep -q '^NONE$'; then
      echo "  skip: empty list"
      return 0
    fi
    keep_line="$(echo "$plan" | grep '^KEEP:' | head -1)"
    del_line="$(echo "$plan" | grep '^DEL:' | head -1)"
    echo "  ${keep_line:-KEEP: []}"
    del_json="${del_line#DEL: }"
    if [[ "$del_json" == "[]" ]] || [[ -z "$del_json" ]]; then
      echo "  Nothing to prune (within keep-latest)."
      SUM_GCR_KEEP="${SUM_GCR_KEEP}${repo_path##*/}(all) "
      return 0
    fi
    echo "  Digests to delete: $del_json"
    while IFS= read -r dg; do
      [[ -z "$dg" ]] && continue
      dg="${dg//\"/}"
      SUM_GCR_DEL="${SUM_GCR_DEL}${dg:0:16}... "
      ref="${repo_path}@${dg}"
      echo "    delete $ref"
      run_gcloud gcloud container images delete "$ref" --force-delete-tags --project="$PROJECT_ID" --quiet
    done < <(echo "$del_json" | python3 -c "import json,sys; print('\n'.join(json.loads(sys.stdin.read())))" 2>/dev/null || true)
    SUM_GCR_KEEP="${SUM_GCR_KEEP}${repo_path##*/} kept ${keep_n} "
  }

  for img in line-webhook line-worker; do
    prune_gcr_repo "gcr.io/${PROJECT_ID}/${img}" "$KEEP_LATEST"
  done
fi
echo ""

# ========== [ARTIFACT REGISTRY] ==========
# Uses csv[no-heading](package,version,create_time,update_time) — avoids flaky JSON field names.
echo "======== [ARTIFACT REGISTRY] ========"
if [[ "$DELETE_AR" != "1" ]]; then
  echo "skip: --delete-ar-images not set."
  SUM_AR_KEEP="unchanged"
else
  repo_names=""
  while IFS= read -r rline; do
    [[ -z "$rline" ]] && continue
    short="${rline##*/}"
    if [[ "$short" == *cloud-run-source* ]]; then
      repo_names="${repo_names}${short}"$'\n'
    fi
  done < <(gcloud artifacts repositories list --project="$PROJECT_ID" --location="$REGION" --format="value(name)" 2>/dev/null || true)

  if [[ -z "${repo_names//[$'\n']/}" ]]; then
    echo "  skip: no repository name contains 'cloud-run-source' in $REGION"
    SUM_AR_KEEP="no matching repo"
  else
    echo "  Repositories (name contains cloud-run-source):"
    echo "$repo_names" | sed '/^$/d' | sed 's/^/    - /'

    while IFS= read -r repo_short; do
      [[ -z "$repo_short" ]] && continue
      base="${REGION}-docker.pkg.dev/${PROJECT_ID}/${repo_short}"
      echo "  --- repository $repo_short ---"

      # gcloud may exit non-zero while still printing CSV on stdout (e.g. bundled Python warnings).
      ar_csv=""
      ar_csv="$(gcloud artifacts docker images list "$base" --project="$PROJECT_ID" --limit=5000 \
        --format='csv[no-heading](package,version,create_time,update_time)' 2>/dev/null)" || true

      if [[ -z "${ar_csv//[$'\n\r']/}" ]]; then
        echo "  skip: no stdout from csv list (permissions, API, or empty repo): $base"
        SUM_AR_KEEP="${SUM_AR_KEEP}${repo_short}:empty_csv "
        continue
      fi

      # Cannot use "printf | python <<'PY'" — the here-doc replaces stdin. Feed CSV via temp file.
      _ar_tmp="$(mktemp "${TMPDIR:-/tmp}/gcp_ar_trim.XXXXXX")"
      printf '%s\n' "$ar_csv" > "$_ar_tmp"
      ar_plan=""
      ar_plan="$(KEEP_LATEST="$KEEP_LATEST" AR_CSV_PATH="$_ar_tmp" python3 <<'PY'
import csv, os, sys
from collections import defaultdict

keep_n = int(os.environ.get("KEEP_LATEST", "3"))
path = os.environ.get("AR_CSV_PATH", "")

def image_ref(pkg, ver):
    if not pkg or not ver:
        return ""
    v = ver.strip()
    if v.startswith("sha256:"):
        return "%s@%s" % (pkg, v)
    if len(v) == 64 and all(c in "0123456789abcdef" for c in v.lower()):
        return "%s@sha256:%s" % (pkg, v)
    return "%s:%s" % (pkg, v)

rows_by_pkg = defaultdict(list)
try:
    with open(path, newline="") as fp:
        for row in csv.reader(fp):
            if len(row) < 2:
                continue
            pkg, ver = row[0].strip(), row[1].strip()
            if not pkg or not ver:
                continue
            if ".pkg.dev" not in pkg:
                continue
            ct = row[2].strip() if len(row) > 2 else ""
            ut = row[3].strip() if len(row) > 3 else ""
            sort_key = ut or ct
            rows_by_pkg[pkg].append((ver, sort_key))
except Exception as e:
    print("ERROR csv_parse %s" % e)
    sys.exit(0)

if not rows_by_pkg:
    print("META reason=no_rows_after_parse")
    sys.exit(0)

for pkg in sorted(rows_by_pkg.keys()):
    best_ver = {}
    for ver, sk in rows_by_pkg[pkg]:
        if ver not in best_ver or sk > best_ver[ver]:
            best_ver[ver] = sk
    items = sorted(((sk, ver) for ver, sk in best_ver.items()), key=lambda x: x[0], reverse=True)
    n = len(items)
    keep_items = items[:keep_n]
    del_items = items[keep_n:]
    nk = len(keep_items)
    nd = len(del_items)
    print("META pkg=%s total_unique_versions=%d keep_latest_setting=%d keep_refs=%d del_refs=%d" % (pkg, n, keep_n, nk, nd))
    print("KEEP_BEGIN")
    for sk, ver in keep_items:
        r = image_ref(pkg, ver)
        if r:
            print(r)
    print("KEEP_END")
    print("DEL_BEGIN")
    for sk, ver in del_items:
        r = image_ref(pkg, ver)
        if r:
            print(r)
    print("DEL_END")
PY
)"
      rm -f "$_ar_tmp"

      if echo "$ar_plan" | grep -q '^ERROR csv_parse'; then
        echo "  skip: CSV parse error:"
        echo "$ar_plan" | grep '^ERROR ' | sed 's/^/    /'
        continue
      fi

      if echo "$ar_plan" | grep -q '^META reason=no_rows_after_parse'; then
        echo "  skip: CSV produced no rows after parse (unexpected empty)"
        continue
      fi

      echo "$ar_plan" | grep '^META ' | sed 's/^/    /'

      del_count=0
      keep_count=0
      phase=""
      while IFS= read -r pline; do
        case "$pline" in
          KEEP_BEGIN) phase=keep; echo "    --- KEEP ($KEEP_LATEST newest) ---" ;;
          DEL_BEGIN) phase=del; echo "    --- DEL (older versions) ---" ;;
          KEEP_END|DEL_END) phase="" ;;
          "")
            ;;
          *)
            if [[ "$phase" == "keep" ]]; then
              echo "    KEEP  $pline"
              keep_count=$((keep_count + 1))
            elif [[ "$phase" == "del" ]]; then
              echo "    DEL   $pline"
              del_count=$((del_count + 1))
              SUM_AR_DEL="${SUM_AR_DEL}${pline##*/} "
              if [[ "$DRY_RUN" == "1" ]]; then
                echo "    [dry-run] gcloud artifacts docker images delete \"$pline\" --delete-tags --quiet"
              else
                gcloud artifacts docker images delete "$pline" --delete-tags --quiet --project="$PROJECT_ID" 2>/dev/null || \
                  echo "    (delete failed or gone: $pline)"
              fi
            fi
            ;;
        esac
      done <<< "$ar_plan"

      if [[ "$del_count" -eq 0 ]] && [[ "$keep_count" -eq 0 ]]; then
        echo "    note: no KEEP/DEL lines (check META line above). If total>0 but del=0, all versions fit in keep-latest."
      elif [[ "$del_count" -eq 0 ]]; then
        echo "    note: nothing to delete (unique versions <= keep-latest $KEEP_LATEST)."
      fi

      SUM_AR_KEEP="${SUM_AR_KEEP}${repo_short}(${keep_count}kept/${del_count}del) "
    done <<< "$(echo "$repo_names" | sed '/^$/d')"
  fi
fi
echo ""

# ========== [SUMMARY] ==========
echo "======== [SUMMARY] ========"
echo "Cloud Run (min-instances=0 only; services never deleted):"
if [[ -n "${SUM_SUSPEND// }" ]]; then
  echo "  Updated: $SUM_SUSPEND"
else
  echo "  (none updated — no services or dry-run placeholder)"
fi
echo "Pub/Sub:"
echo "  $SUM_KEEP_PUBSUB"
echo "GCR:"
echo "  Deleted digests (truncated log): ${SUM_GCR_DEL:-none}"
echo "  Kept note: ${SUM_GCR_KEEP:-}"
echo "Artifact Registry:"
echo "  Deleted refs (truncated): ${SUM_AR_DEL:-none}"
echo "  Repos trimmed: ${SUM_AR_KEEP:-}"
echo ""
echo "Next: bash deploy/check_gcp_resources.sh"
echo "Billing: Console → Billing → Reports (not a guarantee of zero cost)."
echo "======== done ========"
