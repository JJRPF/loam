#!/usr/bin/env bash
# ==============================================================================
# Loam: Raspberry Pi deployment
# Builds the web app, syncs the code to the Pi, restarts the API and checks health.
#
# Usage: ./scripts/deploy-pi.sh
#
# Needs, set up once by the owner (see "Deploying" in the README):
#   1. SSH key login to the Pi:            ssh-copy-id <user>@core-node.local
#   2. Passwordless sudo for ONE command:  <user> ALL=(root) NOPASSWD: /usr/bin/systemctl restart loam-api
# No password is ever passed to ssh or sudo; both checks below fail early if a step is missing.
# ==============================================================================

set -euo pipefail

PI_HOST="${LOAM_PI_HOST:-core-node.local}"
PI_USER="${LOAM_PI_USER:-jjrpfister}"
PI_DIR="/home/${PI_USER}/loam"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=8)

die() { echo "ERROR: $*" >&2; exit 1; }

echo "== Deploying Loam to ${PI_USER}@${PI_HOST} =="

# 0. Preflight: key login and the one sudo command, before anything is built or copied
echo "[0/4] Checking key-based SSH and passwordless sudo for the restart..."
ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" true 2>/dev/null \
    || die "cannot log in to ${PI_USER}@${PI_HOST} with an SSH key (no password prompt is used).
       Run once:  ssh-copy-id ${PI_USER}@${PI_HOST}   (README > Deploying)"
ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "sudo -n -l /usr/bin/systemctl restart loam-api" >/dev/null 2>&1 \
    || die "${PI_USER} may not run 'sudo systemctl restart loam-api' without a password on the Pi.
       Run once on the Pi:
         echo '${PI_USER} ALL=(root) NOPASSWD: /usr/bin/systemctl restart loam-api' | sudo tee /etc/sudoers.d/loam-deploy
         sudo chmod 440 /etc/sudoers.d/loam-deploy && sudo visudo -c   (README > Deploying)"

# 1. Build the frontend with the production settings, the same as the Firebase Hosting build
echo "[1/4] Building the web app..."
# shellcheck source=scripts/web-build-env.sh
. "${ROOT}/scripts/web-build-env.sh"
build_web_app "${ROOT}"

# 2. Sync the code (never .env, data, the venv or git history)
echo "[2/4] Syncing the code to ${PI_DIR}..."
rsync -az \
    --exclude '.env' \
    --exclude 'data' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'frontend/node_modules' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    -e "ssh ${SSH_OPTS[*]}" \
    "${ROOT}/" "${PI_USER}@${PI_HOST}:${PI_DIR}/"

# 3. Restart the API
echo "[3/4] Restarting loam-api..."
ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "sudo -n systemctl restart loam-api"

# 4. Health
echo "[4/4] Checking health..."
sleep 3
HEALTH=$(ssh "${SSH_OPTS[@]}" "${PI_USER}@${PI_HOST}" "curl -s http://127.0.0.1:8085/health || echo failed")
echo "Health: ${HEALTH}"
case "${HEALTH}" in *'"status":"ok"'*) ;; *) die "health check did not report ok";; esac

echo "Deployed. API (Tailscale Funnel): https://core-node.tailcd5892.ts.net   LAN: http://${PI_HOST}:8085"
echo "Run migrations separately when a release adds one:  ssh ${PI_USER}@${PI_HOST} 'cd ${PI_DIR} && .venv/bin/python -m scripts.migrate'"
