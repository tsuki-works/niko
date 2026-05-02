# `infra/jarvis/` — GCE deploy for Jarvis 2.0

Terraform that stands up a single Compute Engine VM (`e2-micro`, free tier,
`us-west1-a`) running the Jarvis Discord bot under systemd. Secrets live
in GCP Secret Manager; the VM's startup script fetches them on boot.

This is PR 5 of the six-PR Jarvis 2.0 plan
(`docs/superpowers/specs/2026-05-01-jarvis-bot-design.md`). Exit criteria:
**bot survives reboot; uptime check green for 24h.**

## Layout

| File | Purpose |
|---|---|
| `versions.tf` | Terraform + `google` provider pins |
| `variables.tf` | `project_id`, `region`, `zone`, `vm_name`, `repo_url`, `branch` |
| `main.tf` | Required APIs, service account, IAM, firewall (IAP-SSH only), VM |
| `secrets.tf` | Four Secret Manager slots + `secretAccessor` IAM for the VM SA |
| `outputs.tf` | VM name/zone/internal IP, SA email, IAP-SSH command |
| `jarvis.service` | systemd unit (User=jarvis, EnvironmentFile=/etc/jarvis/env) |
| `startup.sh` | Idempotent VM bootstrap (apt, git clone, venv, secrets, unit) |

## State backend

**Local state for now.** When the team needs concurrent applies (probably
when a second person needs to operate this), migrate to a GCS bucket:

```hcl
# Add to versions.tf
terraform {
  backend "gcs" {
    bucket = "niko-tsuki-tf-state"
    prefix = "jarvis"
  }
}
```

Then `terraform init -migrate-state`. Until then, the local `.tfstate` file
sits next to these files and **must not be committed** (it contains
resource IDs and metadata, no secret values).

## One-time bootstrap

Prerequisites:
- `gcloud` authenticated as a user with project owner/editor on `niko-tsuki`
- `terraform >= 1.6` installed
- A Discord bot application created in the Developer Portal, **with the
  Message Content privileged intent enabled** and the bot already invited
  to the Tsuki Works guild

### 1. Set the active project + auth

```bash
gcloud config set project niko-tsuki
gcloud auth application-default login
```

### 2. Apply Terraform — creates APIs, secret slots, SA, IAM, VM

```bash
cd infra/jarvis
terraform init
terraform plan
terraform apply
```

The first apply takes 3–5 minutes (mostly enabling APIs and provisioning
the VM). The startup script will fail on first boot because the secret
slots exist but have no versions yet — that's expected; we add versions
next, then reboot.

### 3. Add secret values

**Do not paste secrets into shell history or commit messages.** Use the
GCP Console UI for the cleanest flow:

1. Console → Security → Secret Manager → click `jarvis-discord-token`
2. **+ NEW VERSION** → paste the bot token from Discord Dev Portal → Add
3. Repeat for `jarvis-post-secret` (any 32+ character random string;
   generate with `openssl rand -hex 32` if you don't have one)
4. Repeat for `anthropic-api-key` (the key from `#shared-creds` in Discord)
5. Repeat for `github-token` — a PAT with `read:org` + `repo` scopes
   (fine-grained equivalent OK). Without a value here the bot still
   boots, but only `get_recent_messages` is registered as a tool;
   `get_current_sprint`, `get_recent_commits`, `search_repo_docs`,
   `get_pr`, `get_issue`, and `open_issue` are unavailable.

Or via CLI, with `--data-file=-` to keep the value off the command line:

```bash
# Reads from stdin; type or paste, then Ctrl+D (Ctrl+Z on Windows)
gcloud secrets versions add jarvis-discord-token --data-file=-
gcloud secrets versions add jarvis-post-secret    --data-file=-
gcloud secrets versions add anthropic-api-key     --data-file=-
gcloud secrets versions add github-token          --data-file=-
```

### 4. Reboot the VM so the startup script picks up the new secret versions

```bash
gcloud compute instances reset jarvis --zone us-west1-a
```

After ~60s, the bot should appear online in the Tsuki Works Discord.

## Verification

### Bot is online

Look at the Discord member list — the Jarvis bot user should show as
online (green dot). Sending `@Jarvis ping` in any channel where the bot
has access should produce a response (PR 2 conversational path).

### Health endpoint

```bash
gcloud compute ssh jarvis --zone us-west1-a --tunnel-through-iap
```

On the VM:

```bash
sudo systemctl status jarvis
sudo journalctl -u jarvis -n 100 --no-pager
curl -s http://localhost:8080/healthz | jq
```

Expected `/healthz`:

```json
{"status": "ok", "commit_sha": "<sha>", "started_at": "<iso8601>"}
```

### Survives reboot (spec exit criterion)

```bash
gcloud compute instances reset jarvis --zone us-west1-a
```

Wait ~90s, re-check `systemctl status jarvis` → should be `active (running)`.
The startup script re-runs on every boot and is idempotent, so the bot
comes back with the latest code on `master`.

## Day-2: deploying a new bot version

The startup script clones from `master` and re-runs on every boot, so
the simplest deploy is:

```bash
gcloud compute instances reset jarvis --zone us-west1-a
```

For a faster path (no full reboot, ~10s):

```bash
gcloud compute ssh jarvis --zone us-west1-a --tunnel-through-iap -- \
  "cd /opt/niko && sudo git fetch origin master && sudo git reset --hard origin/master && \
   sudo /opt/niko/.venv/bin/pip install -q -r /opt/niko/bot/requirements.txt && \
   sudo systemctl restart jarvis"
```

A GitHub Actions workflow that does this automatically on push-to-master
(scoped to `bot/**`) is the obvious follow-up — out of scope for PR 5.

## Rollback

To revert to a previous commit:

```bash
gcloud compute ssh jarvis --zone us-west1-a --tunnel-through-iap -- \
  "cd /opt/niko && sudo git reset --hard <commit-sha> && \
   sudo systemctl restart jarvis"
```

To rotate the Discord token (if it leaks):

1. Discord Dev Portal → Bot → **Reset Token**
2. Console → Secret Manager → `jarvis-discord-token` → **+ NEW VERSION**
3. Reset the VM so startup picks up the new version

## Security notes

- **No public ingress.** Firewall allows only TCP/22 from the GCP IAP
  range (`35.235.240.0/20`). Discord/Anthropic/Firestore traffic is
  outbound only via the ephemeral public IP.
- **Bot doesn't store secrets in the repo.** `/etc/jarvis/env` is
  written at startup, mode `600`, owned by root.
- **Service account has minimal scope:** `secretAccessor` on the three
  secrets, `logWriter`/`metricWriter`/`datastore.user` at project level.
  No broad project IAM.
- **OS Login is enabled** so SSH access is gated by GCP IAM, not by
  static keys on the VM.

## Known limitations / follow-ups

- **No formal Cloud Monitoring uptime check.** Adding one requires
  either exposing `:8080/healthz` publicly (security cost) or standing
  up an internal LB (overkill for one VM). Manual `systemctl status` +
  `journalctl` is sufficient until alerting becomes load-bearing.
- **No auto-deploy on push to master.** Worth a small follow-up GHA
  workflow scoped to `bot/**` that does the SSH + git pull + restart.
- **Local Terraform state.** Migrate to GCS once a second operator
  needs to run `apply`.
- **Single zone, no failover.** A zonal outage takes the bot down for
  the duration of the outage. Acceptable for an internal tool; revisit
  if the bot becomes load-bearing for customer-facing flows.
