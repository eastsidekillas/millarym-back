#!/usr/bin/env bash
# Перенос из старых баз: bash deploy/import-legacy.sh /root/reserv_db2.sql /root/zakaz.sql --dry-run [--manager "Имя в старой базе=логин"]
# Сначала с --dry-run (только отчёт), потом без него. Повторный запуск дублей не создаёт.
set -euo pipefail
RESERV=$(realpath "${1:?укажите дамп резервов (reserv_db2.sql)}")
ORDERS=$(realpath "${2:?укажите дамп заказов (zakaz.sql)}")
shift 2
cd "$(dirname "$0")/.."
DC="docker compose -f docker-compose.yml -f deploy/compose.server.yml"
REPORT="/root/legacy-report-$(date +%Y%m%d-%H%M).txt"
$DC run --rm -T -v "$RESERV:/import/reserv.sql:ro" -v "$ORDERS:/import/zakaz.sql:ro" app \
  django-admin import_legacy --reserv /import/reserv.sql --orders /import/zakaz.sql "$@" | tee "$REPORT"
echo
echo "Отчёт сохранён: $REPORT"
