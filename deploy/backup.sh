#!/bin/sh
# Backs up the database (pg_dump custom format) and the media volume, then removes old backups.
# Runs in the `backup` service (docker-compose.yml). Restore steps: docs/operations.md › Backups.
#   BACKUP_INTERVAL_HOURS  how often (default 24)
#   BACKUP_KEEP_DAYS       how long to keep backups (default 14)
#   BACKUP_ONCE=1          one backup, then exit:  docker compose run --rm -e BACKUP_ONCE=1 backup
set -eu

interval_hours="${BACKUP_INTERVAL_HOURS:-24}"
keep_days="${BACKUP_KEEP_DAYS:-14}"
target=/backups

backup() {
    stamp="$(date -u +%Y%m%d-%H%M%S)"
    # Write to temporary names first, so a half-written file never looks like a backup.
    pg_dump --format=custom --file="$target/.db-$stamp.dump"
    mv "$target/.db-$stamp.dump" "$target/db-$stamp.dump"
    tar czf "$target/.media-$stamp.tgz" -C /media .
    mv "$target/.media-$stamp.tgz" "$target/media-$stamp.tgz"
    find "$target" -maxdepth 1 \( -name 'db-*.dump' -o -name 'media-*.tgz' \) -mtime "+$keep_days" -delete
    echo "$stamp" > "$target/latest.txt"
    echo "backup $stamp done: $(du -h "$target/db-$stamp.dump" | cut -f1) database, $(du -h "$target/media-$stamp.tgz" | cut -f1) media"
}

mkdir -p "$target"
backup
[ "${BACKUP_ONCE:-0}" = "1" ] && exit 0
while true; do
    sleep "$((interval_hours * 3600))"
    backup || echo "backup failed; retrying at the next interval" >&2
done
