variable "tenancy_ocid" {
  type = string
}

variable "user_ocid" {
  type = string
}

variable "fingerprint" {
  type = string
}

variable "private_key_path" {
  description = "Path to the OCI API signing key (.pem). Never commit it."
  type        = string
}

variable "region" {
  description = "Your OCI home region, e.g. us-ashburn-1"
  type        = string
}

variable "compartment_ocid" {
  description = "Compartment for all resources. The tenancy OCID (root compartment) is fine for a take-home."
  type        = string
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "Who may SSH in. Use your IP as x.x.x.x/32 when you can; 0.0.0.0/0 relies on key-only auth."
  type        = string
  default     = "0.0.0.0/0"
}

variable "ad_number" {
  description = "Availability domain (1-based). Change this if you hit 'Out of host capacity'."
  type        = number
  default     = 1
}

variable "ocpus" {
  description = "Always Free A1 allowance is 2 OCPU / 12 GB total (since mid-2026). Drop to 1 / 6 if capacity is tight."
  type        = number
  default     = 2
}

variable "memory_gbs" {
  type    = number
  default = 12
}

variable "boot_volume_gbs" {
  description = "Always Free includes 200 GB of block storage in total."
  type        = number
  default     = 100
}
