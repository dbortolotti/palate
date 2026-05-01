#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${PALATE_GITHUB_REPO:-dbortolotti/palate}"
REPO_URL="https://github.com/${REPO}"
RUNNER_ROOT="${PALATE_RUNNER_ROOT:-/Users/oric/actions-runner/palate-prod}"
RUNNER_NAME="${PALATE_RUNNER_NAME:-palate-prod-$(hostname -s)}"
RUNNER_LABELS="${PALATE_RUNNER_LABELS:-palate-prod}"
LAUNCHD_LABEL="${PALATE_RUNNER_LAUNCHD_LABEL:-com.github.runner.palate-prod}"
PLIST_PATH="${HOME}/Library/LaunchAgents/${LAUNCHD_LABEL}.plist"
UID_VALUE="$(id -u)"

log() {
  printf '[palate-runner] %s\n' "$*"
}

runner_package_arch() {
  case "$(uname -m)" in
    arm64) printf 'osx-arm64' ;;
    x86_64) printf 'osx-x64' ;;
    *)
      printf 'unsupported architecture: %s\n' "$(uname -m)" >&2
      exit 1
      ;;
  esac
}

download_runner() {
  local version
  local package_arch
  local archive
  local url

  version="$(gh api repos/actions/runner/releases/latest --jq '.tag_name' | sed 's/^v//')"
  package_arch="$(runner_package_arch)"
  archive="${RUNNER_ROOT}/actions-runner-${package_arch}-${version}.tar.gz"
  url="https://github.com/actions/runner/releases/download/v${version}/actions-runner-${package_arch}-${version}.tar.gz"

  mkdir -p "${RUNNER_ROOT}"
  if [[ ! -f "${RUNNER_ROOT}/config.sh" ]]; then
    log "downloading actions runner ${version} for ${package_arch}"
    curl -fsSL "${url}" -o "${archive}"
    tar -xzf "${archive}" -C "${RUNNER_ROOT}"
    rm -f "${archive}"
  fi
}

configure_runner() {
  local token

  if [[ -f "${RUNNER_ROOT}/.runner" ]]; then
    log "runner already configured at ${RUNNER_ROOT}"
    return 0
  fi

  token="$(gh api \
    --method POST \
    "repos/${REPO}/actions/runners/registration-token" \
    --jq '.token')"

  log "configuring runner ${RUNNER_NAME}"
  (
    cd "${RUNNER_ROOT}"
    ./config.sh \
      --unattended \
      --url "${REPO_URL}" \
      --token "${token}" \
      --name "${RUNNER_NAME}" \
      --labels "${RUNNER_LABELS}" \
      --work "_work" \
      --replace
  )
}

install_launch_agent() {
  mkdir -p "${HOME}/Library/LaunchAgents" "${RUNNER_ROOT}/logs"
  cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LAUNCHD_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd ${RUNNER_ROOT} &amp;&amp; ./run.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${RUNNER_ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${RUNNER_ROOT}/logs/runner.out.log</string>
  <key>StandardErrorPath</key>
  <string>${RUNNER_ROOT}/logs/runner.err.log</string>
</dict>
</plist>
PLIST

  plutil -lint "${PLIST_PATH}"
  launchctl bootout "gui/${UID_VALUE}/${LAUNCHD_LABEL}" 2>/dev/null || true
  launchctl bootstrap "gui/${UID_VALUE}" "${PLIST_PATH}"
  launchctl kickstart -k "gui/${UID_VALUE}/${LAUNCHD_LABEL}"
}

main() {
  command -v gh >/dev/null
  command -v curl >/dev/null

  download_runner
  configure_runner
  install_launch_agent
  log "runner service installed as ${LAUNCHD_LABEL}"
}

main "$@"
