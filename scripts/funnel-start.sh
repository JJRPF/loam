#!/usr/bin/env bash
# ==============================================================================
# Loam — Tailscale Funnel Start Script
# Orchestrates local services (Vite PWA & FastAPI) and exposes unified HTTPS
# ingress via Tailscale Serve / Funnel for mobile dev testing and GPS validation.
#
# How Funnel is used: in production the Raspberry Pi exposes the API (port 8085) at
# https://core-node.tailcd5892.ts.net through Tailscale Funnel, and the web app itself is served by
# Firebase Hosting at https://loam.thepfisters.com, calling that API cross-origin. This script sets up
# the same kind of public HTTPS ingress for a development machine, e.g. to test GPS on a phone. It resets
# whatever Serve/Funnel mappings the machine has, so do not run it on the Pi.
# ==============================================================================

set -euo pipefail

# Colors for terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}  Loam — Tailscale Serve & Funnel Ingress Launcher  ${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"

# 1. Check Tailscale CLI
if ! command -v tailscale &>/dev/null; then
    echo -e "${RED}[ERROR] 'tailscale' command not found.${NC}"
    echo -e "Please install Tailscale:"
    echo -e "  sudo pacman -S tailscale"
    echo -e "  sudo systemctl enable --now tailscaled"
    exit 1
fi

# 2. Check Tailscale Daemon Status
BACKEND_STATE=$(tailscale status --json 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('BackendState', 'Unknown'))" 2>/dev/null || echo "Unknown")

if [ "$BACKEND_STATE" = "NeedsLogin" ] || [ "$BACKEND_STATE" = "NoState" ]; then
    echo -e "${YELLOW}[WARNING] Tailscale is not authenticated on this machine.${NC}"
    echo -e "Run the following command to log in:"
    echo -e "  tailscale login"
    echo -e "or:"
    echo -e "  tailscale up --operator=$(whoami)"
    exit 1
fi

# 3. Resolve Ports
BACKEND_PORT="${LOAM_BACKEND_PORT:-8080}"
FRONTEND_PORT="${LOAM_FRONTEND_PORT:-5173}"
SERVE_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --backend-port=*)
            BACKEND_PORT="${arg#*=}"
            ;;
        --frontend-port=*)
            FRONTEND_PORT="${arg#*=}"
            ;;
        --serve-only)
            SERVE_ONLY=true
            ;;
        --help|-h)
            echo "Usage: $0 [--backend-port=PORT] [--frontend-port=PORT] [--serve-only]"
            echo "Options:"
            echo "  --backend-port=PORT   FastAPI backend port (default: 8080, checks 8000)"
            echo "  --frontend-port=PORT  Vite dev server port (default: 5173)"
            echo "  --serve-only          Expose on tailnet only without public Funnel"
            exit 0
            ;;
    esac
done

# If default 8080 is not open but 8000 is open, adjust backend port automatically
if [ "$BACKEND_PORT" = "8080" ]; then
    if ! ss -tlpn 2>/dev/null | grep -q ":8080 " && ss -tlpn 2>/dev/null | grep -q ":8000 "; then
        BACKEND_PORT="8000"
    fi
fi

echo -e "${BLUE}[INFO] Checking local service listeners...${NC}"

# Check if backend is listening
BACKEND_ACTIVE=false
if ss -tlpn 2>/dev/null | grep -q ":${BACKEND_PORT} "; then
    BACKEND_ACTIVE=true
    echo -e "  Backend (FastAPI):  ${GREEN}Active on port ${BACKEND_PORT}${NC}"
else
    echo -e "  Backend (FastAPI):  ${YELLOW}No listener on port ${BACKEND_PORT}${NC} (start with: uvicorn app.main:app --port ${BACKEND_PORT})"
fi

# Check if frontend is listening
FRONTEND_ACTIVE=false
if ss -tlpn 2>/dev/null | grep -q ":${FRONTEND_PORT} "; then
    FRONTEND_ACTIVE=true
    echo -e "  Frontend (Vite):    ${GREEN}Active on port ${FRONTEND_PORT}${NC}"
else
    echo -e "  Frontend (Vite):    ${YELLOW}No listener on port ${FRONTEND_PORT}${NC}"
fi

# Determine frontend target
if [ "$FRONTEND_ACTIVE" = true ]; then
    FRONTEND_TARGET="http://127.0.0.1:${FRONTEND_PORT}"
    echo -e "${BLUE}[INFO] Routing root '/' to Vite dev server (${FRONTEND_TARGET})${NC}"
else
    FRONTEND_TARGET="http://127.0.0.1:${BACKEND_PORT}"
    echo -e "${BLUE}[INFO] Vite not detected on ${FRONTEND_PORT}. Routing root '/' to FastAPI static mount (${FRONTEND_TARGET})${NC}"
fi

# 4. Configure Tailscale Serve Path Routing
echo -e "${BLUE}[INFO] Resetting existing Tailscale Serve / Funnel mappings...${NC}"
tailscale funnel reset --yes 2>/dev/null || true
tailscale serve reset --yes 2>/dev/null || true

echo -e "${BLUE}[INFO] Applying unified route mappings...${NC}"
SERVE_CHECK=$(timeout 2s tailscale serve --bg --yes --set-path /health "http://127.0.0.1:${BACKEND_PORT}/health" 2>&1 || true)
if echo "$SERVE_CHECK" | grep -qi "Serve is not enabled"; then
    echo -e "${RED}[ERROR] Tailscale Serve is not enabled on your tailnet.${NC}"
    echo -e "$SERVE_CHECK"
    echo -e "${YELLOW}Please visit the URL above in your browser to enable Serve for this node, then re-run this script.${NC}"
    exit 1
fi

tailscale serve --bg --yes --set-path /api "http://127.0.0.1:${BACKEND_PORT}/api"
tailscale serve --bg --yes --set-path /ws "http://127.0.0.1:${BACKEND_PORT}/ws"
tailscale serve --bg --yes --set-path /docs "http://127.0.0.1:${BACKEND_PORT}/docs"
tailscale serve --bg --yes --set-path /openapi.json "http://127.0.0.1:${BACKEND_PORT}/openapi.json"
tailscale serve --bg --yes --set-path / "${FRONTEND_TARGET}"

# 5. Enable Funnel (Public HTTPS)
if [ "$SERVE_ONLY" = true ]; then
    echo -e "${YELLOW}[INFO] Running in tailnet-only serve mode (--serve-only specified).${NC}"
else
    echo -e "${BLUE}[INFO] Enabling Tailscale Funnel on port 443...${NC}"
    FUNNEL_OUT=$(tailscale funnel --bg --yes 443 on 2>&1 || true)
    if echo "$FUNNEL_OUT" | grep -qi "Funnel is not enabled"; then
        echo -e "${RED}[ERROR] Tailscale Funnel is not enabled on your tailnet.${NC}"
        echo -e "$FUNNEL_OUT"
        echo -e "${YELLOW}Please enable Funnel in the Tailscale Admin Console for this node, then re-run this script.${NC}"
        exit 1
    fi
fi

# 6. Retrieve Domain Name
TS_DOMAIN=$(tailscale status --json 2>/dev/null | python3 -c "import sys, json; print(json.load(sys.stdin).get('Self', {}).get('DNSName', '').rstrip('.'))" 2>/dev/null || echo "")

echo ""
echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}  Loam Ingress Configured Successfully!             ${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"

if [ -n "$TS_DOMAIN" ]; then
    if [ "$SERVE_ONLY" = true ]; then
        echo -e "  Tailnet URL:        ${BOLD}https://${TS_DOMAIN}${NC}"
    else
        echo -e "  Public Funnel URL:  ${BOLD}https://${TS_DOMAIN}${NC}"
    fi
    echo -e "  API Docs:           https://${TS_DOMAIN}/docs"
    echo -e "  Health Check:       https://${TS_DOMAIN}/health"
    echo -e "  WebSocket:          wss://${TS_DOMAIN}/ws"
else
    echo -e "  ${YELLOW}Node domain could not be resolved automatically.${NC}"
    echo -e "  Run 'tailscale serve status' to inspect configured routes."
fi

echo ""
echo -e "${BOLD}Unified Routing Scheme:${NC}"
echo -e "  /api/*          -> http://127.0.0.1:${BACKEND_PORT}/api/*"
echo -e "  /ws             -> http://127.0.0.1:${BACKEND_PORT}/ws"
echo -e "  /docs           -> http://127.0.0.1:${BACKEND_PORT}/docs"
echo -e "  /openapi.json   -> http://127.0.0.1:${BACKEND_PORT}/openapi.json"
echo -e "  /health         -> http://127.0.0.1:${BACKEND_PORT}/health"
echo -e "  /*              -> ${FRONTEND_TARGET}/*"
echo ""
echo -e "${BOLD}Mobile Verification Checklist:${NC}"
echo -e "  1. Open ${BOLD}https://${TS_DOMAIN:-<node>.<tailnet>.ts.net}${NC} on mobile browser."
echo -e "  2. Tap 'Add to Home Screen' to verify PWA installability."
echo -e "  3. Tap 'Locate Me' in the Plan panel to verify secure GPS geolocation."
echo -e "  4. Generate a route option to verify SSE candidate streaming."
echo ""
echo -e "${YELLOW}To tear down ingress, run:${NC} ./scripts/funnel-stop.sh"
echo -e "${BOLD}${GREEN}====================================================${NC}"
