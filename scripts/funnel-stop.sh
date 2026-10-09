#!/usr/bin/env bash
# ==============================================================================
# Loam — Tailscale Funnel Stop Script
# Disables public Funnel ingress and resets Tailscale Serve mappings.
# ==============================================================================

set -euo pipefail

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${BOLD}${YELLOW}Tearing down Loam Tailscale Funnel and Serve ingress...${NC}"

if command -v tailscale &>/dev/null; then
    echo -e "${BLUE}[INFO] Resetting Tailscale Funnel...${NC}"
    tailscale funnel reset --yes 2>/dev/null || tailscale funnel 443 off 2>/dev/null || true

    echo -e "${BLUE}[INFO] Resetting Tailscale Serve...${NC}"
    tailscale serve reset --yes 2>/dev/null || true

    echo -e "${BOLD}${GREEN}✔ Tailscale Serve & Funnel ingress successfully stopped.${NC}"
else
    echo -e "${YELLOW}[WARNING] Tailscale command not found.${NC}"
fi
