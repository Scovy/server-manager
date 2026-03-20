#!/bin/bash
# setup-vm.sh - Prepares the Vagrant VM on first boot

export DEBIAN_FRONTEND=noninteractive
echo "==========================================="
echo "Provisioning Homelab VM..."
echo "==========================================="

# 1. Update and install prerequisites
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release

# 2. Add Docker's official GPG key & repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

# 3. Install Docker Engine, CLI, and Compose plugin
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Add the 'vagrant' user to the docker group so you don't need 'sudo' inside the VM
usermod -aG docker vagrant

echo "==========================================="
echo "Docker installed successfully!"
echo "Starting Homelab Dashboard..."
echo "==========================================="

# 5. Navigate to the synced folder (which is the repository root)
cd /vagrant

# 6. Setup root .env if it doesn't exist
if [ ! -f .env ]; then
  # check if .env.example exists before copying
  if [ -f backend/.env.example ]; then
    cp backend/.env.example .env
    echo "Created .env from template"
  else
    echo "Warning: backend/.env.example not found. Stack might not start correctly."
  fi
fi

# 7. Start the production stack!
# Watchtower will be started as part of this stack, and it will pull the latest images from GHCR
docker compose -f docker-compose.prod.yml up -d

echo "==========================================="
echo "Provisioning Complete!"
echo "Dashboard available at: http://192.168.56.10"
echo "Or via localhost forwarding: http://localhost:8080"
echo "==========================================="
