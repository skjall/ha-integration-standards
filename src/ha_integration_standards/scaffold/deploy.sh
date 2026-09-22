#!/bin/bash
# Development deploy: mirrors the integration onto a Home Assistant host.
# For a normal installation use HACS instead (see the README).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.env"
  set +a
else
  echo "ERROR: .env not found. Template: .env.example"
  exit 1
fi

: "${SERVER:?SERVER not set in .env}"
: "${HA_CONFIG:?HA_CONFIG not set in .env}"

echo "Mirroring {{domain}} to $SERVER:$HA_CONFIG/custom_components/ ..."
ssh "$SERVER" "mkdir -p $HA_CONFIG/custom_components/{{domain}}"
rsync -a --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  "$SCRIPT_DIR/custom_components/{{domain}}/" \
  "$SERVER:$HA_CONFIG/custom_components/{{domain}}/"

echo "Done. Restart Home Assistant to load the new version."
