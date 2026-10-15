#!/bin/sh
# Каждую ночь: дамп базы и архив фото в /backups, старше BACKUP_KEEP_DAYS — удаляются.
set -eu

: "${BACKUP_AT:=02:30}"
: "${BACKUP_KEEP_DAYS:=14}"
export PGPASSWORD="$POSTGRES_PASSWORD"

backup() {
  stamp=$(date +%Y-%m-%d_%H%M)
  pg_dump -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "/backups/db_$stamp.dump.part" || return 1
  mv "/backups/db_$stamp.dump.part" "/backups/db_$stamp.dump" || return 1
  tar -czf "/backups/media_$stamp.tar.gz.part" -C /media . || return 1
  mv "/backups/media_$stamp.tar.gz.part" "/backups/media_$stamp.tar.gz" || return 1
  find /backups -maxdepth 1 \( -name 'db_*.dump' -o -name 'media_*.tar.gz' -o -name '*.part' \) -mtime +"$BACKUP_KEEP_DAYS" -delete
  echo "$(date '+%d.%m.%y %H:%M') копия готова: db_$stamp.dump, media_$stamp.tar.gz"
}

seconds_until() {
  h=${1%%:*}; m=${1#*:}
  set -- $(date '+%H %M %S')
  now=$(( ${1#0} * 3600 + ${2#0} * 60 + ${3#0} ))
  wait=$(( ${h#0} * 3600 + ${m#0} * 60 - now ))
  [ "$wait" -le 0 ] && wait=$((wait + 86400))
  echo "$wait"
}

[ "${1:-}" = "--now" ] && backup
while true; do
  sleep "$(seconds_until "$BACKUP_AT")"
  backup || echo "$(date '+%d.%m.%y %H:%M') копия не удалась" >&2
done
