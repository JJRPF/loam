#!/usr/bin/env bash
# Nightly PostGIS dump (pg_dump -Fc) from the loam-postgis container, kept for 7 days.
# Run from cron on the Pi:  15 3 * * * /home/<user>/loam/scripts/backup_db.sh >> /home/<user>/loam-backups/backup.log 2>&1
# Backups stay on the Pi's disk. For protection against losing the Pi, copy them off the
# machine too (the plan suggests a free cloud bucket); that needs credentials only the owner has.
set -euo pipefail
DEST="${BACKUP_DIR:-$HOME/loam-backups/nightly}"
KEEP_DAYS="${KEEP_DAYS:-7}"
mkdir -p "$DEST"
chmod 700 "$DEST"
umask 077
OUT="$DEST/loam-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker exec -e PGPASSWORD="${PGPASSWORD:-loam_dev_pw}" loam-postgis pg_dump -h localhost -U loam -d loam -Fc > "$OUT.partial"
# a dump that pg_restore can list is a dump worth keeping
docker exec -i loam-postgis pg_restore -l < "$OUT.partial" > /dev/null
mv "$OUT.partial" "$OUT"
find "$DEST" -name 'loam-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "$(date -u +%FT%TZ) wrote $OUT ($(du -h "$OUT" | cut -f1))"
