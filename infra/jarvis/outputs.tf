output "vm_name" {
  description = "Compute Engine instance name."
  value       = google_compute_instance.jarvis.name
}

output "vm_zone" {
  description = "Compute Engine instance zone."
  value       = google_compute_instance.jarvis.zone
}

output "vm_internal_ip" {
  description = "Internal IP of the Jarvis VM."
  value       = google_compute_instance.jarvis.network_interface[0].network_ip
}

output "service_account_email" {
  description = "Service account the VM runs as."
  value       = google_service_account.jarvis.email
}

output "ssh_command" {
  description = "Convenience IAP-SSH command."
  value       = "gcloud compute ssh ${google_compute_instance.jarvis.name} --zone ${var.zone} --tunnel-through-iap --project ${var.project_id}"
}

output "secret_ids" {
  description = "Secret Manager resource IDs (not values)."
  value = {
    discord_token = google_secret_manager_secret.jarvis_discord_token.id
    post_secret   = google_secret_manager_secret.jarvis_post_secret.id
    anthropic_key = google_secret_manager_secret.anthropic_api_key.id
  }
}
