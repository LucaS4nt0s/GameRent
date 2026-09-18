#!/bin/bash
# Script de Inicialização Automatizada (User Data) na AWS EC2
# Compatível com Ubuntu 22.04 / 24.04 LTS

set -e

# Atualiza pacotes do sistema
apt-get update -y
apt-get upgrade -y

# Instala Git, Docker e Docker Compose
apt-get install -y git docker.io docker-compose curl

# Habilita e inicia o serviço do Docker
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

# Diretório da aplicação
mkdir -p /opt/gamerent
cd /opt/gamerent

# Caso você use repositório Git público ou token:
# git clone <URL_DO_REPOSITORIO_GIT> .
# docker-compose up -d --build

echo "=== Servidor AWS EC2 configurado com sucesso para o GameRent ==="
