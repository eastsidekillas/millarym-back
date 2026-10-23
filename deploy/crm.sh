#!/usr/bin/env bash
# Обслуживание «Резервов и Заказов» на сервере — меню: bash /opt/millarym/millarym-back/deploy/crm.sh
# Или сразу действие: crm.sh update | status | backup | backups | restore | reset | fabrics | legacy | admin | password | logs
set -uo pipefail
# readlink — чтобы работало и через ярлык /usr/local/bin/crm
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
BACK=$PWD
SETUP="$BACK/../millarym-front/deploy/server-setup.sh"

[ "$(id -u)" = 0 ] || { echo "Запустите от root: sudo bash $0"; exit 1; }
[ -f .env ] || { echo "Программа ещё не установлена — сначала: bash $SETUP <IP или домен>"; exit 1; }
. deploy/compose-cmd.sh

ADDRESS=$(sed -n 's/^DOMAIN=//p' .env | head -1)
URL=$(sed -n 's/^SITE_URL=//p' .env | head -1)
BACKUP_DIR=$(sed -n 's/^BACKUP_DIR=//p' .env | head -1)
BACKUP_DIR=$(realpath -m "${BACKUP_DIR:-./backups}")
CTL="$BACKUP_DIR/.control"

say() { echo; echo "== $*"; }
ask() { local reply; read -r -p "$1" reply; echo "$reply"; }
confirm_word() {
  local answer
  read -r -p "Чтобы продолжить, введите $1: " answer
  [ "$answer" = "$1" ] || { echo "Отменено."; return 1; }
}
pause() { echo; read -r -p "Enter — вернуться в меню " _; }

# --- состояние -----------------------------------------------------------------------------------------------

status() {
  say "Программа: $URL"
  $DC ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'
  say "Диски"
  df -h / "$BACKUP_DIR" 2>/dev/null | awk 'NR==1 || !seen[$0]++'
  say "Последние копии ($BACKUP_DIR)"
  list_copies 5
  if [ -f "$CTL/heartbeat" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$CTL/heartbeat") ))
    [ "$age" -lt 120 ] && echo "Служба копий работает." || echo "ВНИМАНИЕ: служба копий не отвечает ${age} с — $DC restart backup"
  else
    echo "ВНИМАНИЕ: служба копий ещё не запускалась."
  fi
}

logs() {
  say "Последние строки журналов (вернуться в меню — Ctrl+C)"
  trap 'true' INT  # Ctrl+C останавливает просмотр журналов, а не всё меню
  $DC logs --tail 40 -f app backup scheduler
  trap - INT
}

# --- копии ---------------------------------------------------------------------------------------------------

STAMPS=()
list_copies() {
  local limit=${1:-30} i=0 f stamp note size media
  STAMPS=()
  for f in $(ls -1t "$BACKUP_DIR"/db_*.dump 2>/dev/null); do
    stamp=$(basename "$f" .dump); stamp=${stamp#db_}
    note="По расписанию"
    [ -f "$BACKUP_DIR/note_$stamp.txt" ] && note=$(head -1 "$BACKUP_DIR/note_$stamp.txt")
    size=$(du -h "$f" | cut -f1)
    media="без фото"
    [ -f "$BACKUP_DIR/media_$stamp.tar.gz" ] && media="фото $(du -h "$BACKUP_DIR/media_$stamp.tar.gz" | cut -f1)"
    i=$((i + 1))
    STAMPS+=("$stamp")
    printf '%3d) %s  база %-6s %-12s %s\n' "$i" "$(echo "$stamp" | sed -E 's/^..(..)-(..)-(..)_(..)(..).*/\3.\2.\1 \4:\5/')" "$size" "$media" "$note"
    [ "$i" -ge "$limit" ] && break
  done
  [ "$i" = 0 ] && echo "Копий пока нет."
  return 0
}

queue_task() {  # то же, что кнопки на странице «Резервные копии»: задание службе копий
  [ -d "$CTL/queue" ] || { echo "Служба копий ещё не запускалась: $DC up -d backup"; return 1; }
  local name="$CTL/queue/$(date +%s%N).task"
  printf 'action=%s\nstamp=%s\nby=консоль сервера\n' "$1" "${2:-}" > "$name.part" && mv "$name.part" "$name"
}

wait_service() {  # ждём, пока служба копий выполнит задание
  local lines_before=$1 i
  for i in $(seq 1 600); do
    sleep 2
    state=$(sed -n 's/^text=//p' "$CTL/status" 2>/dev/null)
    [ -n "$state" ] && printf '\r%-90s' "$state"
    if [ "$(wc -l < "$BACKUP_DIR/history.log" 2>/dev/null || echo 0)" -gt "$lines_before" ] && ! ls "$CTL/queue/"*.task >/dev/null 2>&1 \
      && grep -q '^state=idle' "$CTL/status" 2>/dev/null; then
      echo; tail -n +"$((lines_before + 1))" "$BACKUP_DIR/history.log" | cut -f1,2,3,6 | sed 's/\t/  /g'
      return 0
    fi
  done
  echo; echo "Служба копий долго не отвечает — посмотрите: $DC logs --tail 50 backup"
}

history_lines() { wc -l < "$BACKUP_DIR/history.log" 2>/dev/null || echo 0; }

backup_now() {
  say "Копия базы и фото сейчас"
  local before; before=$(history_lines)
  queue_task backup || return
  wait_service "$before"
}

finish_restore() {  # приложение снимает заглушку на первом запросе, после migrate
  local i
  for i in $(seq 1 60); do
    [ -f "$CTL/maintenance" ] || [ -f "$CTL/migrate" ] || return 0
    $DC exec -T frontend wget -q -O /dev/null --header "Host: $ADDRESS" http://app:8000/api/v1/maintenance/ 2>/dev/null || true
    sleep 2
  done
  echo "Заглушка не снялась — откройте программу в браузере или: $DC restart app"
}

restore() {
  say "Восстановить из копии"
  list_copies 30
  [ "${#STAMPS[@]}" -gt 0 ] || return
  local n; n=$(ask "Номер копии (пусто — отмена): ")
  [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "${#STAMPS[@]}" ] || { echo "Отменено."; return; }
  local stamp=${STAMPS[$((n - 1))]}
  echo "Всё, что внесли после этой копии, пропадёт. Перед восстановлением служба сделает копию текущей базы."
  echo "На 1–2 минуты программа будет недоступна у всех."
  confirm_word ВОССТАНОВИТЬ || return
  local before; before=$(history_lines)
  queue_task restore "$stamp" || return
  wait_service "$before"
  finish_restore
}

# --- база ----------------------------------------------------------------------------------------------------

reset_db() {
  say "Начать с чистой базы"
  echo "1) удалить базу и фото"
  echo "2) удалить только базу, фото тканей и моделей оставить"
  case "$(ask "Выбор (пусто — отмена): ")" in
    1) bash deploy/reset-db.sh ;;
    2) bash deploy/reset-db.sh --keep-photos ;;
    *) echo "Отменено." ;;
  esac
}

fabrics() {
  say "Загрузить фото тканей (zip-архив или папка; название ткани — из имени файла)"
  local src; src=$(ask "Путь к архиву или папке на сервере: ")
  [ -e "$src" ] || { echo "Нет такого файла или папки: $src"; return; }
  echo "1) добавить новые ткани и фото к тканям без фото"
  echo "2) то же и заменить фото у тканей, где оно уже есть"
  local mode; mode=$(ask "Выбор: ")
  local extra=()
  [ "$mode" = 2 ] && extra=(--replace)
  bash deploy/import-fabrics.sh "$src" --dry-run "${extra[@]}" | tail -25
  [ "$(ask "Загрузить по-настоящему? (да/нет): ")" = "да" ] || { echo "Отменено."; return; }
  bash deploy/import-fabrics.sh "$src" "${extra[@]}" | tail -15
}

legacy() {
  say "Перенос из старой базы (дампы .sql из phpMyAdmin)"
  local reserv orders
  reserv=$(ask "Дамп резервов (reserv_db2.sql): ")
  orders=$(ask "Дамп заказов (zakaz.sql): ")
  [ -f "$reserv" ] && [ -f "$orders" ] || { echo "Файл не найден."; return; }
  echo "Сначала проверка — в базу ничего не записывается:"
  bash deploy/import-legacy.sh "$reserv" "$orders" --dry-run | tail -40
  [ "$(ask "Перенести по-настоящему? (да/нет): ")" = "да" ] || { echo "Отменено."; return; }
  bash deploy/import-legacy.sh "$reserv" "$orders" | tail -25
}

admin() {
  say "Новый администратор (вход в программу и в /admin/, все права)"
  $DC exec app django-admin createsuperuser
}

password() {
  say "Новый пароль сотруднику"
  $DC exec -T app django-admin shell -v 0 -c "
from app_auth.models import User
for u in User.objects.filter(is_active=True).order_by('last_name'):
    print(f'  {u.username:16} {u.short_name}')"
  local login; login=$(ask "Логин (пусто — отмена): ")
  [ -n "$login" ] || return
  $DC exec app django-admin changepassword "$login"
}

update() {
  say "Обновить программу (код из GitHub, сборка, перезапуск)"
  bash "$SETUP" "$ADDRESS"
}

change_address() {
  say "Сменить адрес программы (сейчас: $ADDRESS)"
  echo "IP в сети завода (например 192.168.18.121) — без HTTPS; домен — с HTTPS."
  local new; new=$(ask "Новый адрес (пусто — отмена): ")
  [ -n "$new" ] || return
  echo "Паспорта, напечатанные раньше, ведут QR-кодом на старый адрес."
  [ "$(ask "Сменить на $new? (да/нет): ")" = "да" ] || { echo "Отменено."; return; }
  bash "$SETUP" "$new"
}

# --- меню ----------------------------------------------------------------------------------------------------

run() {
  case "$1" in
    status) status ;;
    update) update ;;
    address) change_address ;;
    backup) backup_now ;;
    backups) say "Копии ($BACKUP_DIR)"; list_copies 30 ;;
    restore) restore ;;
    reset) reset_db ;;
    fabrics) fabrics ;;
    legacy) legacy ;;
    admin) admin ;;
    password) password ;;
    logs) logs ;;
    *) echo "Не знаю «$1». Можно: status update address backup backups restore reset fabrics legacy admin password logs"; return 1 ;;
  esac
}

if [ $# -gt 0 ]; then
  run "$1"
  exit $?
fi

while true; do
  clear 2>/dev/null || true
  echo "Резервы и Заказы — обслуживание сервера ($URL)"
  echo
  echo "  1) Состояние: контейнеры, диски, последние копии"
  echo "  2) Обновить программу"
  echo "  3) Сделать резервную копию сейчас"
  echo "  4) Список копий"
  echo "  5) Восстановить из копии"
  echo "  6) Загрузить фото тканей"
  echo "  7) Перенос из старой базы"
  echo "  8) Новый администратор"
  echo "  9) Новый пароль сотруднику"
  echo " 10) Сменить адрес программы (IP / домен)"
  echo " 11) Начать с чистой базы (удалить всё)"
  echo " 12) Журналы (логи)"
  echo "  0) Выход"
  echo
  choice=$(ask "Что сделать: ")
  case "$choice" in
    1) status ;;
    2) update ;;
    3) backup_now ;;
    4) say "Копии ($BACKUP_DIR)"; list_copies 30 ;;
    5) restore ;;
    6) fabrics ;;
    7) legacy ;;
    8) admin ;;
    9) password ;;
    10) change_address ;;
    11) reset_db ;;
    12) logs ;;
    0|q|"") exit 0 ;;
    *) echo "Нет такого пункта." ;;
  esac
  pause
done
