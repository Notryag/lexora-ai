#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="${LEXORA_PROJECT_DIR:-/home/zx/lexora-ai}"
HEALTH_URL="${LEXORA_PUBLIC_HEALTH_URL:-https://lexora.selfapi.art/api/v1/health}"
API_IMAGE=""
WEB_IMAGE=""
EXECUTE=0

usage() {
  cat <<'EOF'
Usage: deploy-production.sh --api-image IMAGE --web-image IMAGE [--execute]

Without --execute the script only validates and prints the deployment commands.
Images must use ghcr.io/notryag/lexora-{api,web} with a full commit SHA or digest.
EOF
}

while (($#)); do
  case "$1" in
    --api-image) API_IMAGE="${2:-}"; shift 2 ;;
    --web-image) WEB_IMAGE="${2:-}"; shift 2 ;;
    --execute) EXECUTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

validate_image() {
  local image="$1"
  local repository="$2"
  [[ "$image" =~ ^${repository}:[0-9a-f]{40}$ ]] ||
    [[ "$image" =~ ^${repository}@sha256:[0-9a-f]{64}$ ]]
}

validate_image "$API_IMAGE" 'ghcr.io/notryag/lexora-api' || {
  printf 'Invalid API image; use a full commit SHA tag or digest\n' >&2
  exit 2
}
validate_image "$WEB_IMAGE" 'ghcr.io/notryag/lexora-web' || {
  printf 'Invalid Web image; use a full commit SHA tag or digest\n' >&2
  exit 2
}

command -v docker >/dev/null
command -v flock >/dev/null
command -v curl >/dev/null

cd "$PROJECT_DIR"
compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
export LEXORA_API_IMAGE="$API_IMAGE"
export LEXORA_WEB_IMAGE="$WEB_IMAGE"

exec 9>"/tmp/lexora-production-deploy.lock"
flock -n 9 || { printf 'Another Lexora deployment is running\n' >&2; exit 1; }

"${compose[@]}" config --quiet

if [[ $EXECUTE -eq 0 ]]; then
  printf 'Dry run: configuration is valid; no container was changed.\n'
  printf 'API: %s\nWeb: %s\n' "$API_IMAGE" "$WEB_IMAGE"
  printf 'Run the same command with --execute to pull and deploy these images.\n'
  exit 0
fi

current_image() {
  local container_id
  container_id="$("${compose[@]}" ps -q "$1")"
  [[ -n "$container_id" ]] && docker inspect --format '{{.Config.Image}}' "$container_id"
}

previous_api="$(current_image api || true)"
previous_web="$(current_image web || true)"

rollback_hint() {
  printf 'Rollback with the previous local image pair:\n' >&2
  printf 'LEXORA_API_IMAGE=%q LEXORA_WEB_IMAGE=%q ' "$previous_api" "$previous_web" >&2
  printf '%q ' "${compose[@]}" up -d --no-build api web >&2
  printf '\n' >&2
}
trap rollback_hint ERR

"${compose[@]}" pull api web
"${compose[@]}" up -d --no-build api web

wait_healthy() {
  local service="$1"
  local container_id status
  for _ in {1..60}; do
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id")"
      [[ "$status" == healthy ]] && return 0
    fi
    sleep 2
  done
  printf '%s did not become healthy\n' "$service" >&2
  return 1
}

wait_container_healthy() {
  local container="$1"
  local status
  for _ in {1..60}; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")"
    [[ "$status" == healthy ]] && return 0
    sleep 2
  done
  printf '%s did not become healthy\n' "$container" >&2
  return 1
}

wait_container_healthy platform-postgres
wait_healthy api
wait_healthy web
curl -fsSL --connect-timeout 5 --max-time 15 "$HEALTH_URL" >/dev/null

trap - ERR
"${compose[@]}" ps api web
printf 'Deployment completed and %s is healthy.\n' "$HEALTH_URL"
