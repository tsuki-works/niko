# Secret Manager slots. Values are written out-of-band during bootstrap
# (see infra/jarvis/README.md), not by Terraform — keeps secrets out of
# state and out of TF logs.

resource "google_secret_manager_secret" "jarvis_discord_token" {
  secret_id = "jarvis-discord-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "jarvis_post_secret" {
  secret_id = "jarvis-post-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "anthropic_api_key" {
  secret_id = "anthropic-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "jarvis_discord_token" {
  secret_id = google_secret_manager_secret.jarvis_discord_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jarvis.email}"
}

resource "google_secret_manager_secret_iam_member" "jarvis_post_secret" {
  secret_id = google_secret_manager_secret.jarvis_post_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jarvis.email}"
}

resource "google_secret_manager_secret_iam_member" "anthropic_api_key" {
  secret_id = google_secret_manager_secret.anthropic_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.jarvis.email}"
}
