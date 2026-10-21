#!/bin/bash
#
# One-time (and rerunnable) setup of the Pi for GitHub-driven deploys. RUN AS ROOT BY THE OWNER, after reading it:
# every change on the Pi is an owner decision (DEPLOYMENT.md lists them). Nothing here is run by CI.
#
#   provision.sh check                          read-only: what is there, what is missing, free memory
#   provision.sh install --deploy-pubkey FILE   users, mirror, scripts, sudoers, deploy key, release dirs,
#                                               staging database/.env/unit. Does NOT touch the running production API.
#   provision.sh switch-production              the one step that changes production: points the loam-api unit
#                                               at the release layout (a drop-in), restarts it, checks health
#
# Idempotent: every step checks before it changes. Secrets (the staging .env, its database password) are generated
# on the Pi, kept 0600, and never printed.

set -euo pipefail

SELF_DIR=$(cd "$(dirname "$0")" && pwd)
PROD_USER="${LOAM_PROD_USER:-jjrpfister}"
STAGING_USER=loam-staging
DEPLOYER=loam-deployer
GROUP=loam-deploy
DEPLOY_DIR=/srv/loam-deploy
LIB=/usr/local/lib/loam-deploy
REPO_URL=https://github.com/JJRPF/loam.git
PG_CONTAINER="${LOAM_PG_CONTAINER:-loam-postgis}"
STAGING_PORT=8086
STAGING_MEMORY_MAX="${STAGING_MEMORY_MAX:-600M}"

say() { printf '• %s\n' "$*"; }
warn() { printf '⚠ %s\n' "$*" >&2; }
die() { echo "❌ $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "run as root (sudo $0 ...)"

PROD_HOME=$(getent passwd "$PROD_USER" | cut -d: -f6) || die "no user $PROD_USER"
[ -n "$PROD_HOME" ] || die "no user $PROD_USER"
PROD_ROOT="$PROD_HOME/loam-deploy/production"
STAGING_HOME="/home/$STAGING_USER"
STAGING_ROOT="$STAGING_HOME/loam-deploy/staging"

prod_database_url() {  # prints DATABASE_URL from the production .env (never logged)
  "$SELF_DIR/loam-with-env" "$PROD_HOME/loam/.env" python3 -c 'import os;print(os.environ.get("DATABASE_URL",""))'
}
super_psql() {  # super_psql <dbname> reads SQL on stdin; the superuser is the production DATABASE_URL's
  local url pw user
  url=$(prod_database_url)
  user=$(python3 -c 'import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).username or "loam")' "$url")
  pw=$(python3 -c 'import sys,urllib.parse as u;print(u.unquote(u.urlparse(sys.argv[1]).password or ""))' "$url")
  docker exec -i -e PGPASSWORD="$pw" "$PG_CONTAINER" psql -v ON_ERROR_STOP=1 -q -h localhost -U "$user" -d "$1"
}

cmd_check() {
  echo "== memory =="; free -m | sed -n 1,2p
  echo "   (production API, GraphHopper and PostGIS share this; the staging unit is capped at $STAGING_MEMORY_MAX)"
  [ ! -r "/sys/fs/cgroup/system.slice/loam-api.service/memory.current" ] || \
    echo "   loam-api now: $(( $(cat /sys/fs/cgroup/system.slice/loam-api.service/memory.current) / 1048576 )) MiB"
  echo "== tools =="
  for t in git python3 flock curl jq docker visudo tailscale setfacl; do
    command -v "$t" >/dev/null && echo "   ok      $t" || echo "   MISSING $t"
  done
  echo "== users =="
  for u in "$PROD_USER" "$DEPLOYER" "$STAGING_USER"; do id "$u" >/dev/null 2>&1 && echo "   ok      $u" || echo "   missing $u"; done
  echo "== production unit =="
  systemctl cat loam-api 2>/dev/null | grep -E '^(User|WorkingDirectory|ExecStart|EnvironmentFile|#)' || echo "   no loam-api unit?"
  echo "== funnel =="; tailscale funnel status 2>&1 | sed 's/^/   /' || true
  echo "== database =="
  if pw_url=$(prod_database_url 2>/dev/null) && [ -n "$pw_url" ]; then
    case "$pw_url" in *loam_dev_pw*) warn "production's DATABASE_URL still uses the development password from the public repo. Rotate it (DEPLOYMENT.md): staging users could otherwise reach the production database with it.";; esac
  fi
}

cmd_install() {
  local pubkey=""
  while [ $# -gt 0 ]; do case "$1" in --deploy-pubkey) pubkey="$2"; shift 2 ;; *) die "unknown option $1" ;; esac; done
  [ -n "$pubkey" ] && [ -r "$pubkey" ] || die "--deploy-pubkey FILE (the .pub of the CI deploy key) is required"
  grep -qE '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-[a-z0-9]+) ' "$pubkey" || die "$pubkey is not a public key"
  [ "$(wc -l < "$pubkey")" -le 1 ] || die "$pubkey must hold exactly one key"

  say "group and users"
  getent group "$GROUP" >/dev/null || groupadd --system "$GROUP"
  id "$DEPLOYER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$DEPLOYER"
  id "$STAGING_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$STAGING_USER"
  usermod -aG "$GROUP" "$PROD_USER"; usermod -aG "$GROUP" "$STAGING_USER"
  passwd -l "$DEPLOYER" >/dev/null 2>&1 || true
  chmod 750 "$STAGING_HOME"

  say "the deploy scripts (root-owned, in $LIB and /usr/local/bin)"
  install -d -m 755 "$LIB"
  install -m 755 "$SELF_DIR/write-deploy-info.py" "$SELF_DIR/loam-with-env" "$LIB/"
  install -m 755 -o root -g root "$SELF_DIR/loam-deploy-gate" "$SELF_DIR/loam-deploy-run" "$SELF_DIR/loam-mirror-sync" /usr/local/bin/
  sed "s/jjrpfister/$PROD_USER/g" "$SELF_DIR/loam-deploy.sudoers" > /etc/sudoers.d/loam-deploy.new
  chmod 440 /etc/sudoers.d/loam-deploy.new
  visudo -cf /etc/sudoers.d/loam-deploy.new >/dev/null || { rm -f /etc/sudoers.d/loam-deploy.new; die "sudoers rule did not validate"; }
  mv /etc/sudoers.d/loam-deploy.new /etc/sudoers.d/loam-deploy
  sed -i "s/^PROD_USER=.*/PROD_USER=\"\${LOAM_PROD_USER:-$PROD_USER}\"/" /usr/local/bin/loam-deploy-gate

  say "the deploy key: forced command, nothing else"
  install -d -m 700 -o "$DEPLOYER" -g "$DEPLOYER" "/home/$DEPLOYER/.ssh"
  printf 'command="/usr/local/bin/loam-deploy-gate",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty %s\n' "$(cut -d' ' -f1,2 "$pubkey")" \
    > "/home/$DEPLOYER/.ssh/authorized_keys"
  chown "$DEPLOYER:$DEPLOYER" "/home/$DEPLOYER/.ssh/authorized_keys"; chmod 600 "/home/$DEPLOYER/.ssh/authorized_keys"

  say "the mirror and lock in $DEPLOY_DIR"
  install -d -m 2775 -o "$PROD_USER" -g "$GROUP" "$DEPLOY_DIR"
  touch "$DEPLOY_DIR/deploy.lock" "$DEPLOY_DIR/deploy.log"
  chown "$PROD_USER:$GROUP" "$DEPLOY_DIR/deploy.lock" "$DEPLOY_DIR/deploy.log"; chmod 664 "$DEPLOY_DIR/deploy.lock" "$DEPLOY_DIR/deploy.log"
  if [ ! -d "$DEPLOY_DIR/loam.git" ]; then
    sudo -u "$PROD_USER" git init --bare --quiet "$DEPLOY_DIR/loam.git"
    sudo -u "$PROD_USER" git --git-dir="$DEPLOY_DIR/loam.git" remote add origin "$REPO_URL"
    sudo -u "$PROD_USER" git --git-dir="$DEPLOY_DIR/loam.git" config core.sharedRepository group
  fi
  sudo -u "$PROD_USER" /usr/local/bin/loam-mirror-sync main
  chmod -R g+rX "$DEPLOY_DIR/loam.git"

  say "production release layout (the running API is not touched)"
  install -d -o "$PROD_USER" -g "$PROD_USER" "$PROD_HOME/loam-deploy" "$PROD_ROOT" "$PROD_ROOT/releases" "$PROD_ROOT/shared" "$PROD_ROOT/shared/venvs" "$PROD_ROOT/backups"
  [ -e "$PROD_ROOT/shared/.env" ] || sudo -u "$PROD_USER" ln -s "$PROD_HOME/loam/.env" "$PROD_ROOT/shared/.env"
  [ -e "$PROD_ROOT/shared/data" ] || { [ ! -d "$PROD_HOME/loam/data" ] || sudo -u "$PROD_USER" ln -s "$PROD_HOME/loam/data" "$PROD_ROOT/shared/data"; }
  [ -e "$PROD_ROOT/current" ] || sudo -u "$PROD_USER" ln -s "$PROD_HOME/loam" "$PROD_ROOT/current"
  chmod 600 "$PROD_HOME/loam/.env"

  say "staging: its own directories, .env, database and unit"
  install -d -m 750 -o "$STAGING_USER" -g "$STAGING_USER" "$STAGING_HOME/loam-deploy" "$STAGING_ROOT" "$STAGING_ROOT/releases" "$STAGING_ROOT/shared" "$STAGING_ROOT/shared/venvs"
  provision_staging_db_and_env
  provision_staging_data_access
  sed -e "s#@STAGING_ROOT@#$STAGING_ROOT#g" -e "s#@PORT@#$STAGING_PORT#g" -e "s#@MEMORY_MAX@#$STAGING_MEMORY_MAX#g" \
    "$SELF_DIR/loam-api-staging.service" > /etc/systemd/system/loam-api-staging.service
  systemctl daemon-reload
  systemctl enable loam-api-staging >/dev/null 2>&1 || true
  echo
  echo "Done. Next, in DEPLOYMENT.md order: refresh-staging-data.sh, a first 'stage-main', the Funnel on :8443,"
  echo "then (a separate, deliberate step) 'provision.sh switch-production'."
}

provision_staging_db_and_env() {
  local env_file="$STAGING_ROOT/shared/.env" pw
  if [ -f "$env_file" ]; then
    say "staging .env exists; kept"
    pw=$("$LIB/loam-with-env" "$env_file" python3 -c 'import os,urllib.parse as u;print(u.unquote(u.urlparse(os.environ["DATABASE_URL"]).password or ""))')
  else
    pw=$(openssl rand -hex 24)
    local key; key=$(openssl rand -hex 32)
    umask 077
    cat > "$env_file" <<ENV
# Staging settings, written by provision.sh. Secrets generated on this machine; not production's.
APP_ENV=staging
HOST=127.0.0.1
PORT=$STAGING_PORT
DATABASE_URL=postgresql://loam_staging:$pw@127.0.0.1:5432/loam_staging
GRAPHHOPPER_URL=http://127.0.0.1:8989
DATA_DIR=$STAGING_ROOT/shared/data
FIREBASE_PROJECT_ID=thepfisters
CORS_ORIGINS=https://loamstaging.thepfisters.com
CONNECTOR_SECRET_KEY=$key
ADMIN_EMAILS=
ENABLE_MIDPOINTS=false
SEED_HEAT_PUBLIC=true
ENV
    umask 022
    chown "$STAGING_USER:$STAGING_USER" "$env_file"; chmod 600 "$env_file"
  fi
  say "staging database loam_staging (role loam_staging; no access to the production database)"
  super_psql postgres <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'loam_staging') THEN CREATE ROLE loam_staging LOGIN; END IF;
END \$\$;
ALTER ROLE loam_staging PASSWORD '$pw';
SELECT 'CREATE DATABASE loam_staging OWNER loam_staging' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'loam_staging') \gexec
SQL
  super_psql loam_staging <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL
  # PUBLIC may connect to any database by default; the production database must not be one staging can open.
  local prod_db
  prod_db=$(python3 -c 'import sys,urllib.parse as u;print(u.urlparse(sys.argv[1]).path.lstrip("/").split("?")[0] or "loam")' "$(prod_database_url)")
  super_psql postgres <<SQL
REVOKE CONNECT ON DATABASE "$prod_db" FROM PUBLIC;
REVOKE CONNECT ON DATABASE "$prod_db" FROM loam_staging;
SQL
}

provision_staging_data_access() {
  # Staging reads the elevation tiles and nothing else of production's: traverse-only on the home and checkout,
  # read on data/elevation. No ACL on .env, the code or backups.
  local d="$PROD_HOME/loam/data/elevation"
  install -d -o "$STAGING_USER" -g "$STAGING_USER" "$STAGING_ROOT/shared/data"
  if [ -d "$d" ] && command -v setfacl >/dev/null; then
    setfacl -m "u:$STAGING_USER:x" "$PROD_HOME" "$PROD_HOME/loam" "$PROD_HOME/loam/data"
    setfacl -R -m "u:$STAGING_USER:rX" "$d"
    [ -e "$STAGING_ROOT/shared/data/elevation" ] || ln -s "$d" "$STAGING_ROOT/shared/data/elevation"
    say "staging may read $d (and nothing else under $PROD_HOME/loam)"
  else
    warn "no $d or no setfacl: staging has no elevation tiles; routes there will lack elevation"
  fi
}

cmd_switch_production() {
  local dropin_dir=/etc/systemd/system/loam-api.service.d
  [ -L "$PROD_ROOT/current" ] || die "run install first"
  echo "The unit as it is now:"; systemctl cat loam-api | grep -E '^(User|WorkingDirectory|ExecStart|EnvironmentFile)' || true
  local exec_line
  exec_line=$(systemctl cat loam-api | sed -n 's/^ExecStart=//p' | tail -1)
  case "$exec_line" in *uvicorn*app.main:app*) ;; *) die "the current ExecStart is not 'uvicorn app.main:app ...'; edit the drop-in by hand (DEPLOYMENT.md)";; esac
  # keep the existing host/port arguments, change only the path to uvicorn
  local args; args=$(sed -E 's#^.*(uvicorn)[[:space:]]+##' <<<"$exec_line")
  install -d "$dropin_dir"
  cat > "$dropin_dir/release.conf" <<UNIT
# Written by provision.sh switch-production: run the release that loam-deploy-run switched on (a symlink).
[Service]
WorkingDirectory=$PROD_ROOT/current
ExecStart=
ExecStart=$PROD_ROOT/current/.venv/bin/uvicorn $args
UNIT
  systemctl daemon-reload
  systemctl restart loam-api
  for _ in $(seq 1 30); do
    curl -fsS --max-time 3 http://127.0.0.1:8085/health 2>/dev/null | grep -q '"status":"ok"' && { say "loam-api is healthy on the release layout"; return 0; }
    sleep 2
  done
  rm -f "$dropin_dir/release.conf"; systemctl daemon-reload; systemctl restart loam-api
  die "loam-api was not healthy after the switch; the drop-in was removed and the old unit restarted"
}

case "${1:-}" in
  check) cmd_check ;;
  install) shift; cmd_install "$@" ;;
  switch-production) cmd_switch_production ;;
  *) sed -n '2,15p' "$0"; exit 2 ;;
esac
