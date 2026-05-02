variable "project_id" {
  description = "GCP project ID hosting the Jarvis bot."
  type        = string
  default     = "niko-tsuki"
}

variable "region" {
  description = "GCE region."
  type        = string
  default     = "us-west1"
}

variable "zone" {
  description = "GCE zone for the Jarvis VM. e2-micro free-tier is restricted to us-west1, us-central1, us-east1."
  type        = string
  default     = "us-west1-a"
}

variable "vm_name" {
  description = "Compute Engine instance name."
  type        = string
  default     = "jarvis"
}

variable "machine_type" {
  description = "GCE machine type. e2-micro is the always-free tier (1 instance per project per month in eligible regions)."
  type        = string
  default     = "e2-micro"
}

variable "boot_disk_image" {
  description = "Boot disk image family."
  type        = string
  default     = "debian-cloud/debian-12"
}

variable "boot_disk_size_gb" {
  description = "Boot disk size in GB. Free tier covers 30 GB pd-standard."
  type        = number
  default     = 30
}

variable "repo_url" {
  description = "HTTPS URL the VM clones niko from. Public repo, no auth needed."
  type        = string
  default     = "https://github.com/tsuki-works/niko.git"
}

variable "branch" {
  description = "Git branch the VM checks out and runs."
  type        = string
  default     = "master"
}

variable "discord_guild_id" {
  description = "Discord guild ID the bot joins. Tsuki Works guild."
  type        = string
  default     = "1495086675523797032"
}
