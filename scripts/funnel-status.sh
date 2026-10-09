#!/usr/bin/env bash
# ==============================================================================
# Loam — Tailscale Funnel Status Script
# Displays current Tailscale daemon status, Serve routes, and Funnel state.
# ==============================================================================

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BOLD}${BLUE}=== Tailscale Node Status ===${NC}"
if command -v tailscale &>/dev/null; then
    tailscale status 2>&1 || true
    echo ""
    echo -e "${BOLD}${BLUE}=== Tailscale Serve Status ===${NC}"
    tailscale serve status 2>&1 || true
    echo ""
    echo -e "${BOLD}${BLUE}=== Tailscale Funnel Status ===${NC}"
    tailscale funnel status 2>&1 || true
else
    echo -e "${YELLOW}Tailscale is not installed.${NC}"
fi
