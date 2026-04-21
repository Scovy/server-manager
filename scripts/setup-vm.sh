#!/bin/bash
# setup-vm.sh - Prepares the Vagrant VM on first boot

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
echo "==========================================="
echo "Provisioning Homelab VM..."
echo "==========================================="

# Improve apt reliability on flaky mirrors and NAT links in VirtualBox/WSL setups.
cat >/etc/apt/apt.conf.d/99-vagrant-retries <<'EOF'
Acquire::Retries "5";
Acquire::http::Timeout "20";
Acquire::https::Timeout "20";
Acquire::ForceIPv4 "true";
EOF

# Prefer the global archive endpoint over geo-routed us.archive when mirror edges are unstable.
if [ -f /etc/apt/sources.list ]; then
  sed -i 's|http://us.archive.ubuntu.com/ubuntu|http://archive.ubuntu.com/ubuntu|g' /etc/apt/sources.list
fi

# Backports are not required for this VM bootstrap and often add slow/failing index fetches.
if [ -f /etc/apt/sources.list ]; then
  sed -i 's|^deb \(.*noble-backports.*\)|# \1|g' /etc/apt/sources.list
fi

retry_apt_update() {
  local attempt=1
  local max_attempts=4
  until apt-get update; do
    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "apt-get update failed after ${max_attempts} attempts"
      return 1
    fi
    echo "apt-get update failed, retrying (${attempt}/${max_attempts})..."
    attempt=$((attempt + 1))
    rm -rf /var/lib/apt/lists/partial/*
  done
}

# 1. Update and install prerequisites
retry_apt_update
apt-get install -y ca-certificates curl gnupg lsb-release

# 2. Add Docker's official GPG key & repository
install -m 0755 -d /etc/apt/keyrings
curl --retry 5 --retry-delay 2 -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Install Docker Engine, CLI, and Compose plugin
retry_apt_update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Add the 'vagrant' user to the docker group so you don't need 'sudo' inside the VM
usermod -aG docker vagrant

echo "==========================================="
echo "Docker installed successfully!"
echo "Starting Homelab Dashboard..."
echo "==========================================="

# 5. Navigate to the synced folder (which is the repository root)
cd /vagrant

# 6. Setup root .env (Caddy/TLS config) if it is missing or empty
if [ ! -s .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    sed -i 's|^SITE_ADDRESS=.*|SITE_ADDRESS=192.168.56.10|' .env
    sed -i 's|^DOMAIN=.*|DOMAIN=192.168.56.10|' .env
    sed -i 's|^ACME_EMAIL=.*|ACME_EMAIL=admin@example.com|' .env
    echo "Created root .env from .env.example (local HTTPS enabled)"
  else
    echo "Warning: .env.example not found. Caddy TLS may not be configured."
  fi
fi

# 7. Setup backend/.env if it is missing or empty
if [ ! -s backend/.env ]; then
  if [ -f backend/.env.example ]; then
    cp backend/.env.example backend/.env
    sed -i 's|^DATABASE_URL=.*|DATABASE_URL=sqlite+aiosqlite:///./data/homelab.db|' backend/.env
    sed -i 's|^DOMAIN=.*|DOMAIN=https://192.168.56.10|' backend/.env
    sed -i 's|^CORS_ORIGINS=.*|CORS_ORIGINS=https://192.168.56.10,http://localhost:5173,http://localhost:3000|' backend/.env
    echo "Created backend/.env from backend/.env.example"
  else
    echo "Warning: backend/.env.example not found. Backend might not start correctly."
  fi
fi

# 8. Start the production stack!
# Watchtower will be started as part of this stack, and it will pull the latest images from GHCR
docker compose -f docker-compose.prod.yml up -d

echo "==========================================="
echo "Provisioning Complete!"
echo "Dashboard available at: https://192.168.56.10"
echo "Or via localhost forwarding: https://localhost:8443"
echo "If your browser warns about trust, install Caddy local CA in your trust store."
echo "==========================================="
