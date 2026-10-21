#!/bin/sh
# Служба копий. Каждую ночь — дамп базы и архив фото в $BACKUPS; копии старше BACKUP_KEEP_DAYS удаляются.
# Задания из приложения (страница «Резервные копии»): «сделать копию сейчас» и «восстановить» — файлы
# в $BACKUPS/.control/queue. Там же статус, отметка «жив» и флаг заглушки на время восстановления.
set -u

: "${BACKUP_AT:=02:30}"
: "${BACKUP_KEEP_DAYS:=14}"
: "${BACKUPS:=/backups}"
: "${MEDIA:=/media}"
: "${PGHOST:=postgres}"
export PGHOST PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGDATABASE="$POSTGRES_DB"

CTL="$BACKUPS/.control"
mkdir -p "$CTL/queue"
# приложение работает не от root: ставит задания и снимает заглушку
chmod 777 "$CTL" "$CTL/queue"
# восстановление прервали (перезапуск контейнера) — база откатилась целиком, открываем доступ
rm -f "$CTL/maintenance" "$CTL/queue/"*.part "$CTL/restore.sql"

now() { date '+%d.%m.%y %H:%M'; }

status() {
  printf 'state=%s\nsince=%s\ntext=%s\n' "$1" "$(now)" "$2" > "$CTL/status.part" && mv "$CTL/status.part" "$CTL/status"
}

history() {  # действие, ok|err, копия, кто, текст
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(now)" "$1" "$2" "$3" "$4" "$5" >> "$BACKUPS/history.log"
}

label() {  # 2026-10-20_0230 → 20.10.26 02:30
  echo "$1" | sed -E 's/^..(..)-(..)-(..)_(..)(..).*/\3.\2.\1 \4:\5/'
}

prune() {
  find "$BACKUPS" -maxdepth 1 \( -name 'db_*.dump' -o -name 'media_*.tar.gz' -o -name 'note_*.txt' -o -name '*.part' \) \
    -mtime +"$BACKUP_KEEP_DAYS" -delete
}

backup() {  # кто, заметка (пусто — ночная по расписанию)
  local stamp db media err
  stamp=$(date +%Y-%m-%d_%H%M%S)
  db="$BACKUPS/db_$stamp.dump"
  media="$BACKUPS/media_$stamp.tar.gz"
  if ! err=$(pg_dump -Fc -f "$db.part" 2>&1) || ! mv "$db.part" "$db" \
    || ! err=$(tar -czf "$media.part" -C "$MEDIA" . 2>&1) || ! mv "$media.part" "$media"; then
    rm -f "$db.part" "$db" "$media.part"
    history backup err "" "$1" "$(echo "$err" | tail -1)"
    echo "$(now) копия не удалась: $err" >&2
    return 1
  fi
  [ -n "$2" ] && printf '%s\n' "$2" > "$BACKUPS/note_$stamp.txt"
  prune
  history backup ok "$stamp" "$1" "$2"
  echo "$(now) копия готова: db_$stamp.dump, media_$stamp.tar.gz"
}

restore() {  # копия, кто
  local db media name err text
  case "$1" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9] | \
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
    *) history restore err "$1" "$2" "неверное имя копии"; return 1 ;;
  esac
  db="$BACKUPS/db_$1.dump"
  media="$BACKUPS/media_$1.tar.gz"
  name=$(label "$1")
  [ -f "$db" ] || { history restore err "$1" "$2" "копия не найдена"; return 1; }

  touch "$CTL/maintenance"
  status restore "Идёт восстановление базы из копии $name. Подождите пару минут — страница обновится сама."
  sleep 3  # дать закончиться запросам, начатым до заглушки

  if ! backup "$2" "Перед восстановлением из копии $name"; then
    rm -f "$CTL/maintenance"
    history restore err "$1" "$2" "не удалось сделать копию текущей базы — восстановление отменено"
    return 1
  fi
  # сначала весь SQL из копии, потом одной транзакцией: при любой ошибке база остаётся как была
  if ! err=$(pg_restore --no-owner --no-privileges -f "$CTL/restore.sql" "$db" 2>&1) \
    || ! err=$( { echo "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"; cat "$CTL/restore.sql"; } \
      | psql -q -X -v ON_ERROR_STOP=1 --single-transaction -o /dev/null 2>&1); then
    rm -f "$CTL/restore.sql" "$CTL/maintenance"
    history restore err "$1" "$2" "база не изменилась: $(echo "$err" | tail -1)"
    return 1
  fi
  rm -f "$CTL/restore.sql"
  text="база восстановлена"
  if [ -f "$media" ]; then
    if err=$(tar -xzf "$media" -C "$MEDIA" 2>&1); then text="база и фото восстановлены"
    else text="база восстановлена, фото — нет: $(echo "$err" | tail -1)"; fi
  fi
  # заглушку снимет приложение, когда догонит структуру базы до своей версии (migrate)
  touch "$CTL/migrate"
  history restore ok "$1" "$2" "$text"
}

seconds_until() {
  h=${1%%:*}; m=${1#*:}
  set -- $(date '+%H %M %S')
  now=$(( ${1#0} * 3600 + ${2#0} * 60 + ${3#0} ))
  wait=$(( ${h#0} * 3600 + ${m#0} * 60 - now ))
  [ "$wait" -le 0 ] && wait=$((wait + 86400))
  echo "$wait"
}

field() { sed -n "s/^$1=//p" "$2" | head -1; }

status idle ""
[ "${1:-}" = "--now" ] && backup "консоль сервера" "Вручную с сервера"
next=$(( $(date +%s) + $(seconds_until "$BACKUP_AT") ))
while true; do
  touch "$CTL/heartbeat"
  task=$(ls "$CTL/queue/"*.task 2>/dev/null | head -1)
  if [ -n "$task" ]; then
    action=$(field action "$task"); stamp=$(field stamp "$task"); by=$(field by "$task")
    status "$action" "Задание: $action"
    rm -f "$task"
    case "$action" in
      backup) status backup "Делается копия…"; backup "$by" "Вручную: $by" ;;
      restore) restore "$stamp" "$by" ;;
    esac
    status idle ""
  elif [ "$(date +%s)" -ge "$next" ]; then
    status backup "Делается ночная копия…"
    backup "по расписанию" ""
    status idle ""
    next=$(( $(date +%s) + $(seconds_until "$BACKUP_AT") ))
  else
    sleep 5
  fi
done
