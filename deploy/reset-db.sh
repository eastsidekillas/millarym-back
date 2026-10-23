#!/usr/bin/env bash
# Начать с чистой базы: копия текущей → удалить базу (и фото, если без --keep-photos) → поднять заново.
#   bash deploy/reset-db.sh            — база и фото
#   bash deploy/reset-db.sh --keep-photos — только база, фото тканей и моделей остаются
# Потом: фото тканей (deploy/import-fabrics.sh) и перенос старых данных (deploy/import-legacy.sh).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "СТОП: нет .env — программа ещё не ставилась (deploy/server-setup.sh)"; exit 1; }
. deploy/compose-cmd.sh
KEEP_PHOTOS=0
[ "${1:-}" = "--keep-photos" ] && KEEP_PHOTOS=1
PROJECT=$(basename "$PWD")
BACKUP_DIR=$(sed -n 's/^BACKUP_DIR=//p' .env | head -1)
BACKUP_DIR=${BACKUP_DIR:-./backups}
ADDRESS=$(sed -n 's/^DOMAIN=//p' .env | head -1)

echo "Будут удалены ВСЕ изделия, рекламации, журнал, сотрудники и справочники."
[ "$KEEP_PHOTOS" = 0 ] && echo "Фото тканей, моделей и рекламаций тоже будут удалены (оставить: --keep-photos)."
echo "Перед удалением будет сделана копия — её можно восстановить на странице «Резервные копии»."
read -r -p "Чтобы продолжить, введите УДАЛИТЬ: " answer
[ "$answer" = "УДАЛИТЬ" ] || { echo "Отменено."; exit 1; }

stamp=$(date +%Y-%m-%d_%H%M%S)
mkdir -p "$BACKUP_DIR"
echo "== копия базы: $BACKUP_DIR/db_$stamp.dump"
$DC exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$BACKUP_DIR/db_$stamp.dump.part"
mv "$BACKUP_DIR/db_$stamp.dump.part" "$BACKUP_DIR/db_$stamp.dump"
$DC run --rm -T --no-deps --entrypoint tar backup -czf "/backups/media_$stamp.tar.gz" -C /media .
echo "Перед очисткой базы (deploy/reset-db.sh)" > "$BACKUP_DIR/note_$stamp.txt"

echo "== останавливаю и удаляю данные"
$DC down
docker volume rm "${PROJECT}_postgres_data"
[ "$KEEP_PHOTOS" = 0 ] && docker volume rm "${PROJECT}_media" || true

echo "== поднимаю с чистой базой"
bash ../millarym-front/deploy/server-setup.sh "$ADDRESS"
