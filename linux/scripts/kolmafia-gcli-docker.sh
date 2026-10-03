#!/usr/bin/env bash
set -euo pipefail

# Execute stdin as a short KoLmafia GCLI batch inside the web Docker container.
#
# This is the first-pass fallback transport. It does not sanitize commands and
# intentionally leaves control with the operator. It streams the batch into a
# temporary file inside the container, then runs KoLmafia in headless --CLI mode
# against that file. This avoids host bind-mount permission problems.

container="${KOLMAFA_DOCKER_CONTAINER:-kolmafia-web}"
container_user="${KOLMAFA_DOCKER_USER:-root}"
container_home="${KOLMAFA_CONTAINER_KOLMAFIA_HOME:-/config/.kolmafia}"
jar_path="${KOLMAFA_CONTAINER_JAR:-/etc/kolmafia/kolmafia.jar}"

if ! command -v docker >/dev/null 2>&1; then
  printf 'docker is required for kolmafia-gcli-docker.sh\n' >&2
  exit 127
fi

input=$(cat)
if [[ -z "${input//[$' \t\r\n']/}" ]]; then
  printf 'no GCLI command provided on stdin\n' >&2
  exit 2
fi

{
  printf '%s\n' "${input}"
  case "${input}" in
    *$'\n'quit|*$'\n'quit$'\n'|quit|*$'\n'exit|*$'\n'exit$'\n'|exit) ;;
    *) printf 'quit\n' ;;
  esac
} | docker exec -i \
  -u "${container_user}" \
  -e KOLMAFA_CONTAINER_HOME="${container_home}" \
  -e KOLMAFA_JAR_PATH="${jar_path}" \
  "${container}" /bin/sh -lc '
    set -eu
    mkdir -p "${KOLMAFA_CONTAINER_HOME}/scripts"
    batch_file=$(mktemp "${KOLMAFA_CONTAINER_HOME}/scripts/kolmafa-bridge.XXXXXX.txt")
    cleanup() { rm -f "${batch_file}"; }
    trap cleanup EXIT
    cat >"${batch_file}"
    cd "${KOLMAFA_CONTAINER_HOME}"
    exec java \
      -Duser.home=/config \
      -DuseCWDasROOT \
      -Djava.awt.headless=true \
      -jar "${KOLMAFA_JAR_PATH}" \
      --CLI "$(basename "${batch_file}")"
  '
