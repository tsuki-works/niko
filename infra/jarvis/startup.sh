#!/usr/bin/env bash
# Jarvis VM startup script.
#
# Runs as root via metadata_startup_script on first boot AND on every reboot.
# Designed to be idempotent: re-running picks up the latest code on $branch
# and the latest secret versions, then restarts the unit.
#
# Templated by Terraform — substituted variables: ${repo_url}, ${branch},
# ${project_id}, ${discord_guild_id}.

set -euo pipefail

REPO_URL="${repo_url}"
BRANCH="${branch}"
PROJECT_ID="${project_id}"
DISCORD_GUILD_ID="${discord_guild_id}"

APP_DIR=/opt/niko
VENV="$APP_DIR/.venv"
ENV_DIR=/etc/jarvis
ENV_FILE="$ENV_DIR/env"
UNIT_FILE=/etc/systemd/system/jarvis.service

log() { echo "[startup] $*"; }

# 1. System packages
log "installing apt dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  git python3 python3-venv python3-pip ca-certificates

# 2. Service user — separate from the GCP service account; owns the code dir
if ! id jarvis >/dev/null 2>&1; then
  log "creating jarvis system user"
  useradd --system --no-create-home --shell /usr/sbin/nologin jarvis
fi

# 2a. Trust /opt/niko for git ops as root.
# Without this, second-and-subsequent boots fail with
# `fatal: detected dubious ownership in repository at '/opt/niko'`
# because step 3 chowns the tree to `jarvis` but git ops run as root.
git config --system --add safe.directory "$APP_DIR"

# 3. Code: clone or refresh
if [ ! -d "$APP_DIR/.git" ]; then
  log "cloning $REPO_URL ($BRANCH) to $APP_DIR"
  git clone --branch "$BRANCH" --depth 50 "$REPO_URL" "$APP_DIR"
else
  log "refreshing $APP_DIR to origin/$BRANCH"
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" reset --hard "origin/$BRANCH"
fi
chown -R jarvis:jarvis "$APP_DIR"

# 4. Python virtualenv + deps
if [ ! -d "$VENV" ]; then
  log "creating venv at $VENV"
  python3 -m venv "$VENV"
fi
log "installing bot/requirements.txt"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$APP_DIR/bot/requirements.txt"
chown -R jarvis:jarvis "$VENV"

# 5. Environment file from Secret Manager
log "fetching secrets from project $PROJECT_ID"
mkdir -p "$ENV_DIR"

DISCORD_BOT_TOKEN=$(gcloud secrets versions access latest \
  --secret=jarvis-discord-token --project="$PROJECT_ID")
JARVIS_POST_SECRET=$(gcloud secrets versions access latest \
  --secret=jarvis-post-secret --project="$PROJECT_ID")
ANTHROPIC_API_KEY=$(gcloud secrets versions access latest \
  --secret=anthropic-api-key --project="$PROJECT_ID")

umask 077
cat > "$ENV_FILE" <<EOF
DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN
DISCORD_GUILD_ID=$DISCORD_GUILD_ID
JARVIS_POST_SECRET=$JARVIS_POST_SECRET
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
JARVIS_HTTP_PORT=8080
JARVIS_LOG_LEVEL=INFO
EOF
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

# 6. systemd unit
log "installing systemd unit"
install -m 0644 "$APP_DIR/infra/jarvis/jarvis.service" "$UNIT_FILE"
systemctl daemon-reload
systemctl enable jarvis.service
systemctl restart jarvis.service

log "done — bot should come online within ~10 seconds"
log "verify: systemctl status jarvis  /  journalctl -u jarvis -n 50"
log "health: curl http://localhost:8080/healthz"
