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

ensure_env_file() {
  local env_path="$1"
  local example_path="$2"
  if [ ! -s "$env_path" ]; then
    if [ -f "$example_path" ]; then
      cp "$example_path" "$env_path"
      echo "Created $env_path from $example_path"
    else
      touch "$env_path"
      echo "Created empty $env_path"
    fi
  fi
}

ensure_env_key() {
  local env_path="$1"
  local key="$2"
  local value="$3"

  if grep -qE "^${key}=" "$env_path"; then
    return 0
  fi

  echo "${key}=${value}" >> "$env_path"
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

# 6. Ensure root .env exists and has required Caddy/TLS keys.
# Only missing keys are appended; existing values are preserved.
ensure_env_file .env .env.example
ensure_env_key .env SITE_ADDRESS 192.168.56.10
ensure_env_key .env DOMAIN 192.168.56.10
ensure_env_key .env ACME_EMAIL admin@example.com
ensure_env_key .env ACME_CA https://acme-v02.api.letsencrypt.org/directory

# 7. Ensure backend/.env exists and has required backend keys.
# Only missing keys are appended; existing values are preserved.
ensure_env_file backend/.env backend/.env.example
ensure_env_key backend/.env DATABASE_URL sqlite+aiosqlite:///./data/homelab.db
ensure_env_key backend/.env DOMAIN https://192.168.56.10
ensure_env_key backend/.env CORS_ORIGINS https://192.168.56.10,http://localhost:5173,http://localhost:3000

# 8. Start the production stack!
# Watchtower will be started as part of this stack, and it will pull the latest images from GHCR
docker compose -f docker-compose.prod.yml up -d

echo "==========================================="
echo "Provisioning Complete!"
echo "Dashboard available at: https://192.168.56.10"
echo "Or via localhost forwarding: https://localhost:8443"
echo "If your browser warns about trust, install Caddy local CA in your trust store."
echo "==========================================="
