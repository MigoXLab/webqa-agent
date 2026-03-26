#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ------- Pre-flight checks -------

if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Please install Docker first: https://docs.docker.com/get-docker/"
fi

if ! docker compose version &>/dev/null; then
    error "Docker Compose V2 is not available. Please update Docker."
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker daemon is not running. Please start Docker first."
fi

# ------- .env check -------

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        warn ".env not found, creating from .env.example ..."
        cp .env.example .env
        warn "Please edit .env and fill in your LLM API Key, then re-run this script."
        exit 1
    else
        error ".env.example not found. Cannot continue."
    fi
fi

if grep -q "LLM_API_KEY=sk-xxx" .env 2>/dev/null; then
    warn "LLM_API_KEY is still the placeholder value in .env"
    warn "Please edit .env and fill in your actual API Key, then re-run this script."
    exit 1
fi

# ------- Build & Start -------

info "Building all images (backend + agent + frontend) ..."
docker compose --profile build-only build

info "Starting services ..."
docker compose up -d

# ------- Health check -------

info "Waiting for services to be ready ..."
sleep 3

HEALTHY=true
for svc in webqa-be webqa-fe; do
    if docker ps --format '{{.Names}}' | grep -q "^${svc}$"; then
        info "  ✓ ${svc} is running"
    else
        warn "  ✗ ${svc} is not running"
        HEALTHY=false
    fi
done

echo ""
if [ "$HEALTHY" = true ]; then
    info "All services are up!"
    echo ""
    echo "  Frontend:     http://localhost"
    echo "  Backend API:  http://localhost:8000/docs"
    echo ""
    info "Useful commands:"
    echo "  docker compose logs -f webqa-be          # View backend logs"
    echo "  docker ps --filter label=app=webqa-agent # View running agents"
    echo "  docker compose down                      # Stop all services"
else
    warn "Some services failed to start. Check logs:"
    echo "  docker compose logs"
fi
