#!/usr/bin/env bash
# Команда docker compose для этого сервера: с доменом (HTTPS, Caddy) или в сети завода по IP.
# Подключается из других скриптов: . deploy/compose-cmd.sh; $DC ps
DOMAIN_VALUE=$(sed -n 's/^DOMAIN=//p' .env 2>/dev/null | head -1)
if [[ "$DOMAIN_VALUE" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  DC="docker compose -f docker-compose.yml -f deploy/compose.lan.yml"
else
  DC="docker compose -f docker-compose.yml -f deploy/compose.server.yml"
fi
