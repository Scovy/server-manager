# -*- mode: ruby -*-
# vi: set ft=ruby :

# This Vagrantfile spins up a fully configured Ubuntu Server VM
# with Docker and Docker Compose pre-installed. It automatically
# deploys the Homelab Dashboard stack on boot!

ENV['VAGRANT_DEFAULT_PROVIDER'] = 'virtualbox'

Vagrant.configure("2") do |config|
  # We are using bento/ubuntu-24.04 because the 'bento' project (by Chef)
  # meticulously builds 'libvirt' provider images for all releases.
  config.vm.box = "bento/ubuntu-24.04"
  
  # Use rsync to sync folders when running from WSL to Windows VirtualBox
  config.vm.synced_folder ".", "/vagrant", type: "rsync",
    rsync__exclude: [".git/", "frontend/node_modules/", "backend/venv/", "backend/.venv/"]

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

  # Allocate reasonable resources (using virtualbox)
  config.vm.provider "virtualbox" do |vb|
    vb.memory = "8192"
    vb.cpus   = 6
    vb.gui    = false # GUI is usually not needed for server-manager
  end

  # The provisioning script that runs the FIRST time you type `vagrant up`
  config.vm.provision "shell", path: "scripts/setup-vm.sh"
end
