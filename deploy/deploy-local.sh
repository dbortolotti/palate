#!/usr/bin/env bash
set -Eeuo pipefail

APP_ROOT="${PALATE_PROD_ROOT:-/Volumes/xpg_usb4/prod/palate}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PALATE_PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.14/bin/python3}"
LABEL="${PALATE_LAUNCHD_LABEL:-com.palate.mcp}"
PLIST_DEST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
UID_VALUE="$(id -u)"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="$(command -v python3)"
fi

SHA="${GITHUB_SHA:-$(git -C "${SOURCE_DIR}" rev-parse HEAD)}"
SHORT_SHA="${SHA:0:12}"
RELEASES_DIR="${APP_ROOT}/releases"
SHARED_DIR="${APP_ROOT}/shared"
BASE_RELEASE_DIR="${RELEASES_DIR}/${SHORT_SHA}"
if [[ -e "${BASE_RELEASE_DIR}" ]]; then
  RELEASE_DIR="${BASE_RELEASE_DIR}-$(date -u +%Y%m%d%H%M%S)"
else
  RELEASE_DIR="${BASE_RELEASE_DIR}"
fi
CURRENT_LINK="${APP_ROOT}/current"
TMP_RELEASE="${RELEASE_DIR}.tmp.$$"
PREVIOUS_RELEASE="$(readlink "${CURRENT_LINK}" 2>/dev/null || true)"

log() {
  printf '[palate-deploy] %s\n' "$*"
}

restart_service() {
  if launchctl print "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1; then
    launchctl bootout "gui/${UID_VALUE}" "${PLIST_DEST}" || true
  fi

  launchctl bootstrap "gui/${UID_VALUE}" "${PLIST_DEST}"
  launchctl kickstart -k "gui/${UID_VALUE}/${LABEL}"
}

wait_for_health() {
  local url="${PALATE_HEALTH_URL:-http://127.0.0.1:8787/healthz}"
  local attempt

  for attempt in $(seq 1 30); do
    if curl -fsS "${url}" | grep -q '"status":"ok"'; then
      return 0
    fi
    sleep 1
  done

  return 1
}

rollback() {
  if [[ -n "${PREVIOUS_RELEASE}" && -d "${PREVIOUS_RELEASE}" ]]; then
    log "health check failed; rolling back to ${PREVIOUS_RELEASE}"
    ln -sfn "${PREVIOUS_RELEASE}" "${CURRENT_LINK}"
    restart_service || true
  else
    log "health check failed and no previous release exists"
  fi
}

bootstrap_shared_state() {
  mkdir -p \
    "${RELEASES_DIR}" \
    "${SHARED_DIR}/data" \
    "${SHARED_DIR}/backups" \
    "${SHARED_DIR}/logs" \
    "${SHARED_DIR}/secrets"
  chmod 700 "${SHARED_DIR}/secrets"

  if [[ ! -f "${SHARED_DIR}/.env" ]]; then
    if [[ -f "${SOURCE_DIR}/.env" ]]; then
      cp "${SOURCE_DIR}/.env" "${SHARED_DIR}/.env"
    elif [[ -f "${SOURCE_DIR}/.env.example" ]]; then
      cp "${SOURCE_DIR}/.env.example" "${SHARED_DIR}/.env"
    fi
    [[ -f "${SHARED_DIR}/.env" ]] && chmod 600 "${SHARED_DIR}/.env"
  fi

  if [[ ! -f "${SHARED_DIR}/data/palate.sqlite" && -f "${SOURCE_DIR}/data/palate.sqlite" ]]; then
    cp "${SOURCE_DIR}/data/palate.sqlite" "${SHARED_DIR}/data/palate.sqlite"
  fi

  for secret in \
    google-oauth-client.json \
    google-token.json \
    palate-auth-password \
    palate-oauth.json; do
    if [[ ! -f "${SHARED_DIR}/secrets/${secret}" && -f "${SOURCE_DIR}/secrets/${secret}" ]]; then
      cp "${SOURCE_DIR}/secrets/${secret}" "${SHARED_DIR}/secrets/${secret}"
    fi
  done
  for secret in \
    google-oauth-client.json \
    google-token.json \
    palate-auth-password \
    palate-oauth.json; do
    secret_path="${SHARED_DIR}/secrets/${secret}"
    [[ -f "${secret_path}" ]] && chmod 600 "${secret_path}"
  done
}

build_release() {
  rm -rf "${TMP_RELEASE}"
  mkdir -p "${TMP_RELEASE}"
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.github/' \
    --exclude '.venv/' \
    --exclude '.pytest_cache/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.env' \
    --exclude 'backups/' \
    --exclude 'data/' \
    --exclude 'logs/' \
    --exclude 'palate.egg-info/' \
    --exclude 'secrets/' \
    "${SOURCE_DIR}/" "${TMP_RELEASE}/"

  "${PYTHON_BIN}" -m venv "${TMP_RELEASE}/.venv"
  "${TMP_RELEASE}/.venv/bin/python" -m pip install --upgrade pip
  "${TMP_RELEASE}/.venv/bin/python" -m pip install -r "${TMP_RELEASE}/requirements.txt"

  (
    cd "${TMP_RELEASE}"
    export PALATE_AUTH_ENABLED=0
    export PALATE_BACKUP_ENABLED=0
    export PALATE_DB_PATH="${TMP_RELEASE}/.deploy-test/palate.sqlite"
    "${TMP_RELEASE}/.venv/bin/python" -m compileall -q palate tests
    "${TMP_RELEASE}/.venv/bin/python" -m unittest discover -s tests
  )
  rm -rf "${TMP_RELEASE}/.deploy-test"

  rm -rf "${RELEASE_DIR}"
  mv "${TMP_RELEASE}" "${RELEASE_DIR}"
}

backup_database() {
  if [[ ! -f "${SHARED_DIR}/data/palate.sqlite" ]]; then
    return 0
  fi

  (
    cd "${RELEASE_DIR}"
    export PALATE_DB_PATH="${SHARED_DIR}/data/palate.sqlite"
    export PALATE_BACKUP_DIR="${SHARED_DIR}/backups"
    export PALATE_BACKUP_GOOGLE_DRIVE_ENABLED=0
    "${RELEASE_DIR}/.venv/bin/python" - <<'PY'
from palate.backup import backup_once

result = backup_once()
print(result["sqlite"])
PY
  )
}

install_plist() {
  cp "${RELEASE_DIR}/deploy/com.palate.prod.plist" "${PLIST_DEST}"
  plutil -lint "${PLIST_DEST}"
}

prune_releases() {
  find "${RELEASES_DIR}" -mindepth 1 -maxdepth 1 -type d -print0 \
    | xargs -0 ls -dt 2>/dev/null \
    | tail -n +6 \
    | while IFS= read -r old_release; do
        [[ "${old_release}" == "$(readlink "${CURRENT_LINK}" 2>/dev/null)" ]] && continue
        rm -rf "${old_release}"
      done
}

main() {
  log "preparing shared production state at ${SHARED_DIR}"
  bootstrap_shared_state

  log "building release ${SHORT_SHA}"
  build_release

  log "creating pre-deploy database backup"
  backup_database || true

  log "installing LaunchAgent"
  install_plist

  log "switching current release"
  ln -sfn "${RELEASE_DIR}" "${CURRENT_LINK}"

  log "restarting ${LABEL}"
  restart_service

  log "checking health"
  if ! wait_for_health; then
    rollback
    exit 1
  fi

  prune_releases
  log "deployed ${RELEASE_DIR}"
}

main "$@"
