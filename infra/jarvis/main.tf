locals {
  required_apis = [
    "compute.googleapis.com",
    "secretmanager.googleapis.com",
    "iap.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "jarvis" {
  account_id   = "jarvis-vm"
  display_name = "Jarvis bot VM"
  description  = "Runtime SA for the Jarvis Discord bot on GCE."

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "jarvis_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.jarvis.email}"
}

resource "google_project_iam_member" "jarvis_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.jarvis.email}"
}

# Firestore native — used by bot/jarvis/memory.py for thread memory.
resource "google_project_iam_member" "jarvis_datastore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.jarvis.email}"
}

# Allow IAP-tunneled SSH only. The VM has no other ingress; the Discord
# gateway is outbound and uses the VM's ephemeral public IP for egress.
resource "google_compute_firewall" "jarvis_iap_ssh" {
  name    = "${var.vm_name}-iap-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"] # GCP IAP source range
  target_tags   = [var.vm_name]
}

resource "google_compute_instance" "jarvis" {
  name         = var.vm_name
  machine_type = var.machine_type
  zone         = var.zone
  tags         = [var.vm_name]

  boot_disk {
    initialize_params {
      image = var.boot_disk_image
      size  = var.boot_disk_size_gb
      type  = "pd-standard"
    }
  }

  network_interface {
    network = "default"
    access_config {
      # Ephemeral public IP — required for outbound to Discord/Anthropic
      # without paying for a Cloud NAT. No inbound (IAP-SSH only).
    }
  }

  service_account {
    email  = google_service_account.jarvis.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
  }

  metadata_startup_script = templatefile("${path.module}/startup.sh", {
    repo_url         = var.repo_url
    branch           = var.branch
    project_id       = var.project_id
    discord_guild_id = var.discord_guild_id
  })

  labels = {
    component = "jarvis"
    managed   = "terraform"
  }

  depends_on = [
    google_secret_manager_secret_iam_member.jarvis_discord_token,
    google_secret_manager_secret_iam_member.jarvis_post_secret,
    google_secret_manager_secret_iam_member.anthropic_api_key,
  ]
}
