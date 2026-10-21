#!/usr/bin/env bash
# Run one command through the Pi's deploy gate from GitHub Actions (plain SSH to the Pi's tailnet name):
#
#   LOAM_DEPLOY_SSH_KEY=... scripts/deploy/ci/pi-gate.sh deploy <sha> <meta-b64>
#   scripts/deploy/ci/pi-gate.sh status
#
# The tailnet connection (tailscale/github-action, tag:ci) is made by the workflow first. The host key is pinned in
# .github/pi_known_hosts and verified (StrictHostKeyChecking=yes); the account is loam-deployer, whose one key can
# run only the gate's four commands (scripts/deploy/pi/loam-deploy-gate).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
HOST="${LOAM_PI_HOST:-core-node.tailcd5892.ts.net}"
KNOWN_HOSTS="${LOAM_PI_KNOWN_HOSTS:-${ROOT}/.github/pi_known_hosts}"

die() { echo "::error::$*" >&2; exit 1; }

[ -n "${LOAM_DEPLOY_SSH_KEY:-}" ] || die "LOAM_DEPLOY_SSH_KEY is not set (the repo owner adds it; see DEPLOYMENT.md)"
grep -qE '^[^#].* (ssh-ed25519|ecdsa-sha2-[a-z0-9]+|ssh-rsa) ' "${KNOWN_HOSTS}" \
    || die "${KNOWN_HOSTS} holds no host key yet (the repo owner adds the Pi's; see DEPLOYMENT.md)"
[ "$#" -ge 1 ] || die "usage: pi-gate.sh <gate command...>"

key="$(mktemp)"
trap 'rm -f "${key}"' EXIT
umask 077
printf '%s\n' "${LOAM_DEPLOY_SSH_KEY}" > "${key}"

ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile="${KNOWN_HOSTS}" \
    -o ConnectTimeout=20 -o ServerAliveInterval=30 -i "${key}" "loam-deployer@${HOST}" "$*"
