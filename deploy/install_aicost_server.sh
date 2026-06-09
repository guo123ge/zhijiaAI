#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/aicost}"
RELEASE_ROOT="${RELEASE_ROOT:-$(pwd)}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-http://124.221.103.75}"
DB_PATH="${DB_PATH:-$APP_ROOT/data/valuation.db}"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

if [ -z "${JWT_SECRET_KEY:-}" ]; then
  echo "JWT_SECRET_KEY is required. Example:"
  echo "  JWT_SECRET_KEY=\$(openssl rand -hex 32) bash deploy/install_aicost_server.sh"
  exit 1
fi

echo "[1/8] Installing system dependencies"
$SUDO dnf install -y python3 python3-pip nginx sqlite rsync >/dev/null

if ! command -v pm2 >/dev/null 2>&1; then
  echo "pm2 is not installed or not in PATH. Install Node.js/PM2 first, then rerun."
  exit 1
fi

echo "[2/8] Creating directories"
$SUDO mkdir -p "$APP_ROOT/backend" "$APP_ROOT/frontend" "$APP_ROOT/data" "$APP_ROOT/backups"
$SUDO chown -R "$USER":"$USER" "$APP_ROOT"

echo "[3/8] Syncing backend and frontend"
rsync -a --delete \
  --exclude 'venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  "$RELEASE_ROOT/backend/" "$APP_ROOT/backend/"
rsync -a --delete "$RELEASE_ROOT/frontend/dist/" "$APP_ROOT/frontend/dist/"
rsync -a "$RELEASE_ROOT/deploy/" "$APP_ROOT/deploy/"

echo "[4/8] Creating Python virtualenv"
python3 -m venv "$APP_ROOT/backend/venv"
"$APP_ROOT/backend/venv/bin/pip" install --upgrade pip >/dev/null
"$APP_ROOT/backend/venv/bin/pip" install -r "$APP_ROOT/backend/requirements.txt" >/dev/null

echo "[5/8] Writing production env"
cat > "$APP_ROOT/backend/.env.production" <<EOF
APP_ENV=production
DATABASE_URL=sqlite:///$DB_PATH
JWT_SECRET_KEY=$JWT_SECRET_KEY
CORS_ALLOW_ORIGINS=$PUBLIC_ORIGIN
AI_PROVIDER=${AI_PROVIDER:-disabled}
AI_TIMEOUT_SECONDS=${AI_TIMEOUT_SECONDS:-20}
AI_ENABLE_AUDIT_LOGS=${AI_ENABLE_AUDIT_LOGS:-false}
EMBEDDING_BACKEND=${EMBEDDING_BACKEND:-hash}
AI_AUTO_SAVE_MEMORY=${AI_AUTO_SAVE_MEMORY:-false}
AI_MEMORY_EXTRACTOR_MAX_ITEMS=${AI_MEMORY_EXTRACTOR_MAX_ITEMS:-3}
EOF
chmod 600 "$APP_ROOT/backend/.env.production"

echo "[6/8] Writing PM2 config"
cat > "$APP_ROOT/pm2.aicost.config.cjs" <<EOF
module.exports = {
  apps: [
    {
      name: "aicost-api",
      cwd: "$APP_ROOT/backend",
      script: "$APP_ROOT/backend/venv/bin/uvicorn",
      args: "app.main:app --host 127.0.0.1 --port $BACKEND_PORT",
      interpreter: "none",
      env_file: "$APP_ROOT/backend/.env.production",
    },
  ],
};
EOF

echo "[7/8] Starting PM2 app"
pm2 start "$APP_ROOT/pm2.aicost.config.cjs" --update-env
pm2 save

echo "[8/8] Preparing backup script"
chmod +x "$APP_ROOT/deploy/backup_sqlite.sh"

echo "Install complete."
echo "Next: add deploy/nginx.aicost-ip.conf locations to the active Nginx server block, then run:"
echo "  sudo nginx -t && sudo systemctl reload nginx"
echo "Health checks:"
echo "  curl http://127.0.0.1:$BACKEND_PORT/healthz"
echo "  curl $PUBLIC_ORIGIN/api/aicost/healthz"
