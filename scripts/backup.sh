#!/usr/bin/env bash
# Consistent online backup of the SQLite database. Keeps the last 14 copies.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/var/backups/urls}"
COMPOSE="docker compose -f /opt/urls/app/docker-compose.yml"
STAMP="$(date +%F_%H%M%S)"

mkdir -p "$BACKUP_DIR"
$COMPOSE exec -T app python -c "
import sqlite3, os
if os.path.exists('/data/backup.db'): os.remove('/data/backup.db')
src = sqlite3.connect('/data/urls.db'); dst = sqlite3.connect('/data/backup.db')
src.backup(dst); dst.close(); src.close()"
$COMPOSE cp app:/data/backup.db "$BACKUP_DIR/urls-$STAMP.db"
$COMPOSE exec -T app rm -f /data/backup.db
chmod 600 "$BACKUP_DIR/urls-$STAMP.db"
ls -1t "$BACKUP_DIR"/urls-*.db | tail -n +15 | xargs -r rm --
echo "Backup written: $BACKUP_DIR/urls-$STAMP.db"
