#!/bin/bash
# Script de Inicialização Automatizada (User Data) na AWS EC2
# Compatível com Ubuntu 22.04 / 24.04 LTS

set -e

# Atualiza pacotes do sistema
apt-get update -y
apt-get upgrade -y

# Instala Git, Docker e Docker Compose v2 (suporta o override docker-compose.aws.yml)
apt-get install -y git docker.io docker-compose-v2 curl

# AWS CLI (usado para validar a IAM Role e provisionar Route 53 / Cloud Map)
snap install aws-cli --classic || true

# Habilita e inicia o serviço do Docker
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

# Diretório da aplicação
mkdir -p /opt/gamerent
cd /opt/gamerent

# Código da aplicação
if [ ! -d .git ]; then
  git clone https://github.com/LucaS4nt0s/GameRent.git .
fi

# Sobe as 2 réplicas do catalog-service + rental-service + frontend usando o DynamoDB gerenciado.
# As credenciais vêm da IAM Role da instância (ver infra/setup_iam.sh) — nada de chaves no disco.
export AWS_REGION=sa-east-1
docker compose -f docker-compose.yml -f docker-compose.aws.yml up -d --build

echo "=== Servidor AWS EC2 configurado com sucesso para o GameRent ==="
