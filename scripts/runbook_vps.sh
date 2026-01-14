#!/usr/bin/env bash
# =============================================================================
# Lead Validator - VPS Deployment Runbook
# =============================================================================
# Run this script on your Ubuntu VPS to deploy or update the application.
# Usage: bash scripts/runbook_vps.sh
#
# Prerequisites:
# - Docker and Docker Compose plugin installed
# - Git installed
# - Running as user with docker group access
# =============================================================================

set -euo pipefail

APP_DIR="/opt/emailverifier"
DOMAIN="validator.2ndimpression.co"

echo "=========================================="
echo "Lead Validator - VPS Deployment"
echo "=========================================="
echo ""

# Navigate to app directory
if [ ! -d "$APP_DIR" ]; then
    echo "ERROR: $APP_DIR does not exist."
    echo "First-time setup? Run:"
    echo "  sudo mkdir -p $APP_DIR && sudo chown \$USER:\$USER $APP_DIR"
    echo "  cd $APP_DIR && git clone https://github.com/archerverified/emailverifier.git ."
    exit 1
fi

cd "$APP_DIR"
echo "Working directory: $(pwd)"

# Pull latest code
echo ""
echo "1. Pulling latest code..."
git fetch --all
git reset --hard origin/main
echo "   Done."

# Ensure data directories exist
echo ""
echo "2. Creating data directories..."
mkdir -p data/storage data/caddy/data data/caddy/config
echo "   Done."

# Generate API key
echo ""
echo "3. Generating API key..."
API_KEY="$(openssl rand -hex 32)"
echo "   Generated."

# Detect env template
echo ""
echo "4. Writing .env file..."
if [ -f .env.example ]; then
    ENV_TEMPLATE=".env.example"
elif [ -f env.example ]; then
    ENV_TEMPLATE="env.example"
else
    echo "ERROR: No env template found (.env.example or env.example)"
    exit 1
fi
echo "   Using template: $ENV_TEMPLATE"

# Create .env from template with API key substitution
# CRITICAL: Keep GUNICORN_WORKERS=1 (already set in template)
cat "$ENV_TEMPLATE" | sed "s|CHANGE_ME__GENERATE_WITH_OPENSSL_RAND_HEX_32|$API_KEY|g" > .env
echo "   Done."
echo ""
echo "   IMPORTANT SETTINGS (already configured in template):"
echo "   - GUNICORN_WORKERS=1 (required for job state consistency)"
echo "   - JOB_HEARTBEAT_INTERVAL_SECONDS=15 (prevents false stall detection)"
echo "   - JOB_STALL_TIMEOUT_MINUTES=60 (allows slow SMTP operations)"
echo "   - CATCH_ALL_CACHE_TTL_MINUTES=1440 (caches catch-all checks for 24h)"

# Build and start services
echo ""
echo "5. Building and starting Docker containers..."
docker compose up -d --build
echo "   Done."

# Wait for services to be healthy
echo ""
echo "6. Waiting for services to start (15 seconds)..."
sleep 15

# Check internal health
echo ""
echo "7. Checking internal health..."
if docker compose exec -T backend curl -fsS http://localhost:5050/health > /dev/null 2>&1; then
    echo "   Backend is healthy!"
else
    echo "   WARNING: Backend health check failed. Check logs:"
    echo "   docker compose logs backend"
fi

# Check external health
echo ""
echo "8. Checking external HTTPS..."
if curl -fsS "https://$DOMAIN/health" > /dev/null 2>&1; then
    echo "   HTTPS is working!"
else
    echo "   WARNING: HTTPS check failed. Certificate may still be provisioning."
    echo "   Wait 1-2 minutes and try: curl https://$DOMAIN/health"
fi

# Print summary
echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "API Key (SAVE THIS - you will need it for the UI and API calls):"
echo ""
echo "  $API_KEY"
echo ""
echo "Test commands:"
echo "  curl https://$DOMAIN/health"
echo "  curl -H \"X-API-Key: $API_KEY\" https://$DOMAIN/schema"
echo ""
echo "View logs:"
echo "  docker compose logs -f backend"
echo ""
echo "NOTE: validator.2ndimpression.co is served entirely from this VPS."
echo "      Any Vercel configuration can be ignored/removed."
echo ""