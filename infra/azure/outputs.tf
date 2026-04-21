output "resource_group_name" {
  description = "Azure resource group name."
  value       = azurerm_resource_group.this.name
}

output "public_ip" {
  description = "Public IP address of the VM."
  value       = azurerm_public_ip.this.ip_address
}

output "vm_name" {
  description = "Virtual machine name."
  value       = azurerm_linux_virtual_machine.this.name
}

output "ssh_command" {
  description = "SSH command for VM access."
  value       = "ssh ${var.admin_username}@${azurerm_public_ip.this.ip_address}"
}

output "bootstrap_url" {
  description = "Initial app URL before setup switch."
  value       = "http://${azurerm_public_ip.this.ip_address}/setup"
}
