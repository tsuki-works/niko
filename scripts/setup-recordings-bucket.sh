#!/usr/bin/env bash
# Bootstrap GCS bucket + IAM for WS-side call recordings (#82).
# Idempotent enough for one-shot bootstrap; re-running on an existing
# bucket fails cleanly at create-bucket and the rest are upserts.
set -euo pipefail

PROJECT="${PROJECT:-niko-tsuki}"
BUCKET="${BUCKET:-niko-recordings}"
REGION="${REGION:-us-central1}"
SA="${SA:-347262010229-compute@developer.gserviceaccount.com}"

echo "Creating bucket gs://${BUCKET} in ${REGION}..."
gcloud storage buckets create "gs://${BUCKET}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --uniform-bucket-level-access || echo "(bucket may already exist; continuing)"

echo "Setting per-blob lifecycle (delete when daysSinceCustomTime >= 0)..."
TMP_LIFECYCLE="$(mktemp)"
cat > "${TMP_LIFECYCLE}" <<'EOF'
{"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"daysSinceCustomTime":0}}]}}
EOF
gcloud storage buckets update "gs://${BUCKET}" --lifecycle-file="${TMP_LIFECYCLE}"
rm -f "${TMP_LIFECYCLE}"

echo "Granting Cloud Run runtime SA roles/storage.objectAdmin on bucket..."
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.objectAdmin"

echo "Granting SA serviceAccountTokenCreator on itself (for V4 signed URLs)..."
gcloud iam service-accounts add-iam-policy-binding "${SA}" \
  --member="serviceAccount:${SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="${PROJECT}"

echo "Done. Bucket gs://${BUCKET} is ready for recordings."
