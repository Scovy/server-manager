variable "subscription_id" {
  description = "Azure subscription ID."
  type        = string
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "westeurope"
}

variable "name_prefix" {
  description = "Prefix for Azure resource names."
  type        = string
  default     = "servermanager"
}

variable "admin_username" {
  description = "Linux admin username for SSH."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "SSH public key content for VM login."
  type        = string
}

variable "vm_size" {
  description = "Azure VM size."
  type        = string
  default     = "Standard_B2s"
}

variable "repo_url" {
  description = "Git repository URL for app deployment."
  type        = string
  default     = "https://github.com/scovy/server-manager.git"
}

variable "repo_branch" {
  description = "Git branch to deploy."
  type        = string
  default     = "main"
}

variable "domain" {
  description = "Public domain to use after setup. Leave empty to bootstrap on raw IP only."
  type        = string
  default     = ""
}

variable "acme_email" {
  description = "Email used for ACME registration in setup defaults."
  type        = string
  default     = "admin@example.com"
}

variable "bootstrap_site_address" {
  description = "Initial Caddy site address used before setup wizard switch, e.g. ':80' or 'http://x.x.x.x'."
  type        = string
  default     = ":80"
}

variable "tags" {
  description = "Resource tags."
  type        = map(string)
  default     = {}
}
