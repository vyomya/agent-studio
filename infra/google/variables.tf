variable "project_id" {
  description = "Google Cloud project id (gcloud config get-value project)."
  type        = string
}

variable "region" {
  type    = string
  default = "us-east1"
}

variable "zone" {
  description = "Change to another zone in the region (us-east1-c, us-east1-d) if this one has no capacity."
  type        = string
  default     = "us-east1-b"
}

variable "machine_type" {
  description = "2 vCPU / 8 GB."
  type        = string
  default     = "e2-standard-2"
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "admin_cidr" {
  description = "Who may SSH in. Your IP as x.x.x.x/32 when you can."
  type        = string
  default     = "0.0.0.0/0"
}

variable "disk_gbs" {
  type    = number
  default = 30
}
