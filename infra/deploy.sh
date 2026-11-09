#!/bin/bash
# Atualiza o Jogaí/GameRent na EC2 com a última versão da branch main.
#
#   cd /opt/gamerent && sudo bash infra/deploy.sh            # usa a main
#   cd /opt/gamerent && sudo bash infra/deploy.sh dev        # outra branch, para testar
#
# Pré-requisitos: /opt/gamerent/.env preenchido (modelo em .env.example) e a IAM Role na instância.
set -euo pipefail

BRANCH="${1:-main}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.aws.yml)

cd "$APP_DIR"

if [ ! -f .env ]; then
  echo "ERRO: falta $APP_DIR/.env. Copie .env.example para .env e preencha." >&2
  exit 1
fi

echo "==> Baixando a branch $BRANCH"
git fetch --prune origin
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

echo "==> Construindo e subindo os containers"
set -a
. ./.env
set +a
"${COMPOSE[@]}" up -d --build --remove-orphans

echo "==> Esperando os serviços ficarem saudáveis (até 3 min)"
for _ in $(seq 1 36); do
  unhealthy=$("${COMPOSE[@]}" ps --format '{{.Name}} {{.Health}}' | awk '$2 != "" && $2 != "healthy"')
  if [ -z "$unhealthy" ]; then
    "${COMPOSE[@]}" ps
    echo "==> Deploy concluído: $(git rev-parse --short HEAD) da branch $BRANCH"
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 5
done

echo "ERRO: serviços sem ficar saudáveis:" >&2
echo "$unhealthy" >&2
"${COMPOSE[@]}" logs --tail=40 >&2
exit 1
