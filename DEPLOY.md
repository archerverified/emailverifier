# Lead Validator - Production Deployment Guide

Complete guide for deploying the email verification backend to a production VPS.

## Prerequisites

- Ubuntu 22.04+ VPS with:
  - Minimum 2GB RAM, 2 vCPU
  - 20GB+ storage
  - Public IPv4 address
  - Port 25 outbound (for SMTP verification)
- Domain name pointed to VPS IP (for HTTPS)
- SSH access to VPS

## Quick Start

### 1. Server Setup

SSH into your VPS and run:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt install -y docker-compose-plugin

# Verify installation
docker --version
docker compose version

# Log out and back in for group changes
exit
```

SSH back in and continue:

```bash
# Create app directory
sudo mkdir -p /opt/lead-validator
sudo chown $USER:$USER /opt/lead-validator
cd /opt/lead-validator

# Clone repository
git clone https://github.com/archerverified/emailverifier.git .

# Create data directories
mkdir -p data/storage data/caddy/data data/caddy/config

# Rename dockerignore
mv dockerignore.txt .dockerignore
```

### 2. Configuration

```bash
# Copy environment template
cp env.example .env

# Edit configuration
nano .env
```

**Critical settings to change:**

```env
# Your domain (required for HTTPS)
DOMAIN=validator.2ndimpression.co

# Generate a secure API key
APP_API_KEY=$(openssl rand -hex 32)

# Set production mode
FLASK_ENV=production
VALIDATOR_MODE=real
```

Generate API key:

```bash
# Generate and display a secure key
openssl rand -hex 32

# Then add it to .env
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
cd /opt/lead-validator

# Build and start containers
docker compose up -d --build

# Check status
docker compose ps

# View logs
docker compose logs -f backend

# Test health endpoint
curl http://localhost:5050/health
```

### 5. Verify HTTPS

Once Caddy provisions the certificate (may take 1-2 minutes):

```bash
# Test HTTPS endpoint
curl https://validator.2ndimpression.co/health

# Test with API key
curl -H "X-API-Key: YOUR_API_KEY" https://validator.2ndimpression.co/schema
```

## Testing

### Health Check

```bash
curl https://validator.2ndimpression.co/health
# Expected: {"status":"ok"}
```

### API Key Authentication

```bash
# Without key (should fail with 401)
curl -X POST https://validator.2ndimpression.co/verify
# Expected: {"error":{"code":"UNAUTHORIZED",...}}

# With key
curl -H "X-API-Key: YOUR_KEY" https://validator.2ndimpression.co/schema
# Expected: {"endpoints":[...]}
```

### Rate Limiting

```bash
# Test rate limit (run 15 times quickly)
for i in {1..15}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -H "X-API-Key: YOUR_KEY" \
    -X POST https://validator.2ndimpression.co/verify
done
# Should see 429 after 10 requests
```

### Email Verification

```bash
# Upload a test CSV
echo -e "email\ntest@example.com" > /tmp/test.csv

curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@/tmp/test.csv" \
  https://validator.2ndimpression.co/verify
```

### SMTP Connectivity (Port 25)

```bash
# Test outbound SMTP
nc -zv gmail-smtp-in.l.google.com 25

# Or with telnet
telnet gmail-smtp-in.l.google.com 25
# Type: QUIT to exit

# If blocked, contact your VPS provider
```

## Operations

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
cd /opt/lead-validator

# Pull latest code
git pull origin main

# Rebuild and restart
docker compose up -d --build

# Verify health
curl https://validator.2ndimpression.co/health
```

### Backup

```bash
# Create backup directory
mkdir -p /opt/backups

# Backup data (SQLite + outputs)
tar -czf /opt/backups/lead-validator-$(date +%Y%m%d).tar.gz \
  -C /opt/lead-validator data/storage

# List backups
ls -la /opt/backups/
```

### Restore

```bash
# Stop services
docker compose down

# Restore from backup
tar -xzf /opt/backups/lead-validator-YYYYMMDD.tar.gz \
  -C /opt/lead-validator

# Restart services
docker compose up -d
```

### Log Rotation

Docker handles log rotation automatically. To configure:

```bash
# Edit /etc/docker/daemon.json
sudo nano /etc/docker/daemon.json
```

Add:

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

```bash
# Restart Docker
sudo systemctl restart docker
```

### Caddy Access Logs

```bash
# View Caddy access logs
docker compose exec caddy cat /data/access.log | tail -20

# Or from host
cat data/caddy/data/access.log | tail -20
```

## DNS & rDNS Setup

### Forward DNS (A Record)

In your domain registrar/DNS provider:

```
Type: A
Name: api (or @ for root)
Value: YOUR_VPS_IP
TTL: 300
```

### Reverse DNS (PTR Record)

For better email deliverability, set rDNS on your VPS:

1. Log into your VPS provider panel (e.g., Vultr, DigitalOcean)
2. Find "Reverse DNS" or "PTR Record" settings
3. Set PTR to: `validator.2ndimpression.co`
4. Verify:
   ```bash
   dig -x YOUR_VPS_IP +short
   # Should return: validator.2ndimpression.co.
   ```

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose logs backend

# Common issues:
# - Port already in use: Check for existing processes
sudo lsof -i :5050

# - Permission denied on storage
sudo chown -R 1000:1000 data/storage
```

### Certificate Not Provisioning

```bash
# Check Caddy logs
docker compose logs caddy

# Common issues:
# - DNS not propagated: wait 5-10 minutes
# - Port 80/443 blocked: check firewall
# - Rate limited: wait 1 hour (Let's Encrypt limit)

# Force certificate renewal
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### Port 25 Blocked

Many VPS providers block outbound port 25 by default. Solutions:

1. **Request unblock**: Contact VPS support
2. **Use relay**: Configure an SMTP relay service
3. **Different provider**: Some providers (Vultr, OVH) allow port 25

Test:

```bash
nc -zv gmail-smtp-in.l.google.com 25
# If timeout, port is blocked
```

### Rate Limited

```bash
# Check current limits
curl -s https://validator.2ndimpression.co/metrics | jq .

# Clear rate limiter (restart backend)
docker compose restart backend
```

### Database Locked

```bash
# Check for processes using DB
docker compose exec backend fuser data/storage/lead_validator.db

# Restart to clear locks
docker compose restart backend
```

## Rollback

If something goes wrong:

```bash
# Rollback to previous version
cd /opt/lead-validator

# Tag current as broken (optional)
docker tag lead-validator-backend:latest lead-validator-backend:broken

# Checkout previous commit
git log --oneline -5  # Find good commit
git checkout COMMIT_HASH

# Rebuild
docker compose up -d --build

# If needed, restore data
tar -xzf /opt/backups/lead-validator-YYYYMMDD.tar.gz -C /opt/lead-validator
```

## Security Checklist

- [ ] Changed default API key in `.env`
- [ ] Firewall enabled (UFW)
- [ ] Only ports 22, 80, 443 open
- [ ] SSH key authentication (disable password)
- [ ] Regular backups scheduled
- [ ] Log monitoring enabled
- [ ] HTTPS working
- [ ] rDNS configured

## Monitoring (Optional)

### Basic Health Monitoring

Add to crontab for alerts:

```bash
crontab -e
```

```
*/5 * * * * curl -sf https://validator.2ndimpression.co/health || echo "Lead Validator DOWN" | mail -s "Alert" admin@yourdomain.com
```

### Resource Monitoring

```bash
# View resource usage
docker stats

# Check disk usage
df -h
du -sh data/storage/*
```

## Support

- Repository: https://github.com/archerverified/emailverifier
- Issues: https://github.com/archerverified/emailverifier/issues
