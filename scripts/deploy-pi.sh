#!/usr/bin/env bash
# ==============================================================================
# Loam — Raspberry Pi Deployment & Update Script
# Builds frontend, syncs codebase to core-node.local, and restarts services.
#
# Usage: ./scripts/deploy-pi.sh
# ==============================================================================

set -euo pipefail

PI_HOST="${LOAM_PI_HOST:-core-node.local}"
PI_USER="${LOAM_PI_USER:-jjrpfister}"
PI_DIR="/home/${PI_USER}/loam"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}  Deploying Loam to Raspberry Pi (${PI_HOST})       ${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"

# 1. Build frontend bundle locally
echo -e "${BLUE}[1/4] Building latest frontend PWA bundle...${NC}"
(
    cd "$(dirname "$0")/../frontend"
    npm run build
)

# 2. Sync files to Raspberry Pi
echo -e "${BLUE}[2/4] Syncing codebase to ${PI_USER}@${PI_HOST}:${PI_DIR}...${NC}"
rsync -avz \
    --exclude '.env' \
    --exclude 'data' \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'frontend/node_modules' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    -e "sshpass -p '${PI_USER}' ssh -o IdentityAgent=none -o PubkeyAuthentication=no" \
    "$(dirname "$0")/../" "${PI_USER}@${PI_HOST}:${PI_DIR}/"

# 3. Restart Loam API service on Raspberry Pi
echo -e "${BLUE}[3/4] Restarting loam-api on ${PI_HOST}...${NC}"
sshpass -p "${PI_USER}" ssh -o IdentityAgent=none -o PubkeyAuthentication=no "${PI_HOST}" \
    "echo '${PI_USER}' | sudo -S systemctl restart loam-api"

# 4. Verify Health Status
echo -e "${BLUE}[4/4] Verifying health check...${NC}"
sleep 2
HEALTH=$(sshpass -p "${PI_USER}" ssh -o IdentityAgent=none -o PubkeyAuthentication=no "${PI_HOST}" \
    "curl -s http://127.0.0.1:8085/health || echo 'failed'")

echo -e "Health response: ${HEALTH}"
echo ""
echo -e "${BOLD}${GREEN}✔ Deployment completed successfully!${NC}"
echo -e "Public URL: https://core-node.tailcd5892.ts.net"
echo -e "Local URL:  http://${PI_HOST}:8085"
echo -e "${BOLD}${GREEN}====================================================${NC}"
