# -*- mode: ruby -*-
# vi: set ft=ruby :

# This Vagrantfile spins up a fully configured Ubuntu Server VM
# with Docker and Docker Compose pre-installed. It automatically
# deploys the Homelab Dashboard stack on boot!

ENV['VAGRANT_DEFAULT_PROVIDER'] = 'libvirt'

Vagrant.configure("2") do |config|
  # We are using bento/ubuntu-24.04 because the 'bento' project (by Chef)
  # meticulously builds 'libvirt' provider images for all releases.
  config.vm.box = "bento/ubuntu-24.04"

  # Assign a static IP so you always know where your dashboard is
  config.vm.network "private_network", ip: "192.168.56.10"

  # Forward ports to the host machine for easy access
  # Dashboard UI/API
  config.vm.network "forwarded_port", guest: 80, host: 8080, auto_correct: true
  config.vm.network "forwarded_port", guest: 443, host: 8443, auto_correct: true
  
  # Forward port for direct Backend API access (useful for dev)
  config.vm.network "forwarded_port", guest: 8000, host: 8000, auto_correct: true
  # Forward port for direct Frontend Vite access (useful for dev)
  config.vm.network "forwarded_port", guest: 3000, host: 3000, auto_correct: true

  # Allocate reasonable resources (using libvirt for KVM)
  config.vm.provider "libvirt" do |lv|
    lv.memory = "2048"
    lv.cpus   = 2
  end

  # The provisioning script that runs the FIRST time you type `vagrant up`
  config.vm.provision "shell", inline: <<-SHELL
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
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
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
    
    # 6. Setup backend .env if it doesn't exist
    if [ ! -f backend/.env ]; then
      cp backend/.env.example backend/.env
      echo "Created backend/.env from template"
    fi

    # 7. Start the production stack!
    docker compose up -d

    echo "==========================================="
    echo "Provisioning Complete!"
    echo "Dashboard available at: http://192.168.56.10"
    echo "Or via localhost forwarding: http://localhost:8080"
    echo "==========================================="
  SHELL
end
