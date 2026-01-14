# Lead Validator - Production Deployment Guide

Complete guide for deploying the email verification backend to a production VPS.

> **WARNING: Do not run PowerShell commands on the VPS. Do not run bash heredocs in PowerShell.**
>
> This guide has two sections:
> - **Part A**: Run on VPS (Ubuntu bash)
> - **Part B**: Run on Windows PowerShell
>
> Copy commands from the correct section only!

---

## Prerequisites

- Ubuntu 22.04+ VPS with:
  - Minimum 2GB RAM, 2 vCPU
  - 20GB+ storage
  - Public IPv4 address
  - Port 25 outbound (for SMTP verification)
- Domain `validator.2ndimpression.co` pointed to VPS IP `76.13.27.113` (A record, not CNAME)
- SSH access to VPS

## Architecture

The application now uses Redis for job state management and RQ for background job processing:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Caddy     │────▶│   Backend   │────▶│   Redis     │
│ (HTTPS/TLS) │     │  (Gunicorn) │     │ (Job State) │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   ▲
                           ▼                   │
                    ┌─────────────┐            │
                    │  RQ Worker  │────────────┘
                    │ (Background)│
                    └─────────────┘
```

**Components:**
- **Caddy**: Reverse proxy with automatic HTTPS
- **Backend**: Flask API (can now run multiple Gunicorn workers!)
- **Redis**: Shared job state store and RQ queue backend
- **Worker**: RQ worker for background email verification

## Gunicorn Workers (Now Safe!)

With Redis-based job state, you can now safely run multiple Gunicorn workers:

```bash
GUNICORN_WORKERS=2   # Recommended for production
GUNICORN_THREADS=4   # Threads per worker
```

The default is now 2 workers with 4 threads each, providing good concurrency for the API while RQ workers handle the actual email verification.

## Recommended Production Settings

The following settings are optimized for production use:

```bash
# Job health monitoring (prevents false "stalled" detection during slow SMTP)
JOB_HEARTBEAT_INTERVAL_SECONDS=15   # Time-based heartbeat (default)
JOB_HEARTBEAT_INTERVAL_ROWS=10      # Row-based heartbeat (backward compat)
JOB_STALL_TIMEOUT_MINUTES=60        # Mark job as stalled after 60 min inactivity

# Catch-all cache (big performance win - avoids redundant SMTP checks)
CATCH_ALL_CACHE_TTL_MINUTES=1440    # Cache catch-all results for 24 hours

# Gunicorn (CRITICAL: keep workers=1)
GUNICORN_WORKERS=1
GUNICORN_THREADS=8
GUNICORN_TIMEOUT=180
```

## Note: Domain Ownership

The domain `validator.2ndimpression.co` is served entirely from this VPS. Any previous Vercel configuration can be ignored/removed.

---

# Part A: Run on VPS (Ubuntu bash)

All commands in this section are for **bash on the VPS**. Prompt shown as `root@vps:~#` or `user@vps:~$`.

## Quick Deploy (Recommended)

Use the automated runbook script for fastest deployment:

```bash
# SSH into VPS first, then run:
cd /opt/emailverifier
bash scripts/runbook_vps.sh
```

The script will:
1. Pull latest code
2. Generate a new API key
3. Write `.env`
4. Build and start Docker containers
5. Print your API key at the end

---

## Manual Setup (Step-by-Step)

### 1. Initial Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin and utilities
sudo apt install -y docker-compose-plugin git curl openssl jq

# Verify installation
docker --version
docker compose version

# Log out and back in for group changes
exit
```

SSH back in and continue:

```bash
# Create app directory
sudo mkdir -p /opt/emailverifier
sudo chown $USER:$USER /opt/emailverifier
cd /opt/emailverifier

# Clone repository
git clone https://github.com/archerverified/emailverifier.git .

# Create data directories
mkdir -p data/storage data/caddy/data data/caddy/config
```

### 2. Configuration

```bash
cd /opt/emailverifier

# Generate API key
API_KEY=$(openssl rand -hex 32)
echo "Your API key: $API_KEY"

# Copy environment template (handles both naming conventions)
if [ -f .env.example ]; then
  cp .env.example .env
elif [ -f env.example ]; then
  cp env.example .env
fi

# Replace placeholder with generated key
sed -i "s|CHANGE_ME__GENERATE_WITH_OPENSSL_RAND_HEX_32|$API_KEY|g" .env

# Verify .env looks correct
cat .env | grep APP_API_KEY
```

### 3. Firewall Setup

```bash
# Allow SSH (keep this!)
sudo ufw allow ssh

# Allow HTTP and HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Enable firewall
sudo ufw enable

# Verify rules
sudo ufw status
```

### 4. Deploy

```bash
cd /opt/emailverifier

# Build and start containers
docker compose up -d --build

# Check status
docker compose ps

# View logs (Ctrl+C to exit)
docker compose logs -f backend
```

### 5. Verify Deployment

```bash
# Internal health check (via container)
docker compose exec backend curl -fsS http://localhost:5050/health

# External HTTPS check (once Caddy provisions certificate, ~1-2 min)
curl -fsS https://validator.2ndimpression.co/health

# Test auth (should return 401)
curl -sS -X POST https://validator.2ndimpression.co/verify | head -c 200

# Test with API key (replace YOUR_API_KEY with actual key)
curl -sS -H "X-API-Key: YOUR_API_KEY" https://validator.2ndimpression.co/schema
```

---

## Operations (VPS)

### View Logs

```bash
# All services
docker compose logs -f

# Backend only
docker compose logs -f backend

# Last 100 lines
docker compose logs --tail=100 backend
```

### Restart Services

```bash
# Restart all
docker compose restart

# Restart backend only
docker compose restart backend
```

### Update Application

```bash
cd /opt/emailverifier

# Pull latest code
git fetch --all
git reset --hard origin/main

# Rebuild and restart
docker compose up -d --build

# Verify health
curl -fsS https://validator.2ndimpression.co/health
```

### Backup

```bash
# Create backup directory
mkdir -p /opt/backups

# Backup data (SQLite + outputs)
tar -czf /opt/backups/lead-validator-$(date +%Y%m%d).tar.gz \
  -C /opt/emailverifier data/storage

# List backups
ls -la /opt/backups/
```

### Restore

```bash
# Stop services
cd /opt/emailverifier
docker compose down

# Restore from backup
tar -xzf /opt/backups/lead-validator-YYYYMMDD.tar.gz \
  -C /opt/emailverifier

# Restart services
docker compose up -d
```

---

## Troubleshooting (VPS)

### Container Won't Start

```bash
# Check logs
docker compose logs backend

# Check if port in use
sudo lsof -i :5050

# Fix storage permissions
sudo chown -R 1000:1000 data/storage
```

### Certificate Not Provisioning

```bash
# Check Caddy logs
docker compose logs caddy
```

**Top 3 causes:**
1. **DNS not pointing to VPS**: `validator.2ndimpression.co` must resolve to `76.13.27.113` (A record, not CNAME)
2. **Ports blocked**: Firewall not allowing 80/443
3. **Let's Encrypt rate limit**: Wait 1 hour if too many recent attempts

```bash
# Force certificate reload
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### Port 25 Blocked

```bash
# Test outbound SMTP
nc -zv gmail-smtp-in.l.google.com 25

# If timeout, port is blocked - contact VPS provider
```

### Database Locked

```bash
# Restart to clear locks
docker compose restart backend
```

---

## DNS & rDNS Setup

### Forward DNS (A Record)

In your domain registrar/DNS provider, set:

```
Type: A
Name: validator
Value: 76.13.27.113
TTL: 300
```

### Reverse DNS (PTR Record)

1. Log into your VPS provider panel
2. Find "Reverse DNS" or "PTR Record" settings
3. Set PTR to: `validator.2ndimpression.co`
4. Verify:
   ```bash
   dig -x 76.13.27.113 +short
   # Should return: validator.2ndimpression.co.
   ```

---

## Rollback (VPS)

```bash
cd /opt/emailverifier

# Checkout previous commit
git log --oneline -5  # Find good commit
git checkout COMMIT_HASH

# Rebuild
docker compose up -d --build

# If needed, restore data
tar -xzf /opt/backups/lead-validator-YYYYMMDD.tar.gz -C /opt/emailverifier
```

---

# Part B: Run on Windows PowerShell

All commands in this section are for **PowerShell on Windows**. Prompt shown as `PS C:\>`.

## Quick Test (Recommended)

Use the automated test script:

```powershell
# In PowerShell, from repo root:
.\scripts\runbook_windows.ps1
```

---

## Manual Testing

### 1. DNS Check

```powershell
nslookup validator.2ndimpression.co
```

Expected: Should resolve to `76.13.27.113`

### 2. HTTPS Health Check

```powershell
curl.exe -s "https://validator.2ndimpression.co/health"
```

Expected output:
```json
{"status":"ok"}
```

### 3. Auth Check (expect 401)

```powershell
curl.exe -i -X POST "https://validator.2ndimpression.co/verify"
```

Expected: HTTP 401 with JSON error body containing `"code":"UNAUTHORIZED"`

### 4. Verify with API Key

```powershell
# Set your API key (from VPS deployment)
$ApiKey = "YOUR_API_KEY_HERE"

# Create temp CSV
"email`ntest@example.com" | Out-File -Encoding ascii "$env:TEMP\test.csv"

# Upload and verify
curl.exe -s -H "X-API-Key: $ApiKey" -F "file=@$env:TEMP\test.csv" "https://validator.2ndimpression.co/verify"
```

Expected: JSON response with `job_id`

### 5. Check Job Status

```powershell
$JobId = "JOB_ID_FROM_PREVIOUS_STEP"
curl.exe -s "https://validator.2ndimpression.co/progress?job_id=$JobId"
```

---

## Verify Checklist

| URL | Expected |
|-----|----------|
| `https://validator.2ndimpression.co/` | HTML UI loads |
| `https://validator.2ndimpression.co/ui.css` | CSS file (200) |
| `https://validator.2ndimpression.co/health` | `{"status":"ok"}` |
| `https://validator.2ndimpression.co/schema` | JSON schema |
| `POST /verify` without key | 401 Unauthorized |
| `POST /verify` with key + CSV | 200 with job_id |

---

## Security Checklist

- [ ] Changed default API key in `.env`
- [ ] Firewall enabled (UFW) on VPS
- [ ] Only ports 22, 80, 443 open
- [ ] SSH key authentication (disable password auth)
- [ ] Regular backups scheduled
- [ ] HTTPS working
- [ ] rDNS configured

---

## Support

- Repository: https://github.com/archerverified/emailverifier
- Issues: https://github.com/archerverified/emailverifier/issues
