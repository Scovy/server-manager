# Azure Terraform Deployment

This Terraform stack creates an Ubuntu VM on Azure and auto-deploys Server Manager with Docker Compose.

## What gets created

- Resource Group
- VNet + Subnet
- Public IP (Static)
- NSG with inbound `22`, `80`, `443`
- Linux VM (Ubuntu 22.04)
- Cloud-init bootstrap that installs Docker and starts `docker-compose.prod.yml`

## Prerequisites

- Terraform `>= 1.6`
- Azure CLI logged in (`az login`)
- Azure subscription with quota for the selected VM size
- SSH public key

## Configure

```bash
cd infra/azure
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars
```

Recommended first-run value:

- `bootstrap_site_address = ":80"`

This keeps the setup wizard reachable via:

- `http://<public-ip>/setup`

After setup, the app switches to domain/HTTPS automatically.

## Deploy

```bash
terraform init
terraform plan
terraform apply
```

Useful outputs:

- `public_ip`
- `bootstrap_url`
- `ssh_command`

## Post-deploy flow

1. Open `bootstrap_url` from Terraform output.
2. Complete setup wizard with your domain + email.
3. Ensure your DNS `A` record points to the VM public IP.
4. Confirm domain cert issuance in Caddy logs:

```bash
docker logs -f homelab_caddy
```

## Destroy

```bash
terraform destroy
```
