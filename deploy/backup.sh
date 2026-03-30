#!/bin/bash
# SQLite daily backup script — placeholder (no database yet)
# Will be configured with cron when database is added

BACKUP_DIR="/opt/survive-the-talk/backups"
DB_PATH="/opt/survive-the-talk/data/db.sqlite"
DATE=$(date +%Y-%m-%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/db_$DATE.sqlite'"
    echo "Backup completed: db_$DATE.sqlite"
else
    echo "No database file found at $DB_PATH — skipping backup"
fi

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "db_*.sqlite" -mtime +7 -delete
