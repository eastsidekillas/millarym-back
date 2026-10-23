#!/usr/bin/env bash
# Фото тканей на сервер: bash deploy/import-fabrics.sh /root/ткани.zip [--dry-run] [--replace] [--no-create]
# Название ткани берётся из имени файла; можно указать zip-архив или папку.
set -euo pipefail
SRC="${1:?укажите zip-архив или папку с картинками}"
shift
SRC=$(realpath "$SRC")
cd "$(dirname "$0")/.."
. deploy/compose-cmd.sh
if [ -d "$SRC" ]; then
  $DC run --rm -T -v "$SRC:/import:ro" app django-admin import_fabrics /import "$@"
else
  $DC run --rm -T -v "$SRC:/import/fabrics.zip:ro" app django-admin import_fabrics /import/fabrics.zip "$@"
fi
