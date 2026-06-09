#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${AICOST_DB_PATH:-/opt/aicost/data/valuation.db}"
BACKUP_DIR="${AICOST_BACKUP_DIR:-/opt/aicost/backups}"
RETENTION_DAYS="${AICOST_BACKUP_RETENTION_DAYS:-14}"

mkdir -p "$BACKUP_DIR"

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_file="$BACKUP_DIR/valuation-$timestamp.db"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "$DB_PATH" ".backup '$backup_file'"
else
  cp "$DB_PATH" "$backup_file"
fi

find "$BACKUP_DIR" -name 'valuation-*.db' -type f -mtime +"$RETENTION_DAYS" -delete
echo "Backed up $DB_PATH to $backup_file"
