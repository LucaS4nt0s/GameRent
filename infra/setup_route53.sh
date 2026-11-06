#!/usr/bin/env bash
# Service Discovery na AWS (Entrega 3 — Nomeação): Route 53 Private Hosted Zone "gamerent.internal".
#
# Cria (ou reaproveita) a zona privada associada à VPC da EC2 e publica:
#   catalog.gamerent.internal  A  <IP privado da EC2>
#   rental.gamerent.internal   A  <IP privado da EC2>
#
# Uso (da sua máquina com AWS CLI admin, ou de dentro da EC2 com a role de infra/setup_iam.sh):
#   ./infra/setup_route53.sh <EC2_INSTANCE_ID>
#
# Idempotente (UPSERT). TTL baixo (60 s) para a troca de IP refletir rápido.

set -euo pipefail

INSTANCE_ID="${1:-}"
REGION="${AWS_REGION:-sa-east-1}"
ZONE_NAME="${ZONE_NAME:-gamerent.internal}"
TTL="${TTL:-60}"
RECORDS=(catalog rental)

if [[ -z "$INSTANCE_ID" ]]; then
  echo "Uso: $0 <EC2_INSTANCE_ID>" >&2
  exit 1
fi

read -r VPC_ID PRIVATE_IP < <(aws ec2 describe-instances \
  --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].[VpcId,PrivateIpAddress]' --output text)
echo "==> EC2 $INSTANCE_ID: VPC=$VPC_ID IP privado=$PRIVATE_IP"

# A VPC precisa resolver DNS privado
aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" --enable-dns-support '{"Value":true}'
aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}'

ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME." \
  --query "HostedZones[?Name=='$ZONE_NAME.' && Config.PrivateZone].Id | [0]" --output text)"

if [[ "$ZONE_ID" == "None" || -z "$ZONE_ID" ]]; then
  echo "==> Criando zona privada $ZONE_NAME"
  ZONE_ID="$(aws route53 create-hosted-zone \
    --name "$ZONE_NAME" \
    --caller-reference "gamerent-$(date +%s)" \
    --vpc "VPCRegion=$REGION,VPCId=$VPC_ID" \
    --hosted-zone-config "Comment=GameRent Entrega 3 - service discovery,PrivateZone=true" \
    --query 'HostedZone.Id' --output text)"
else
  echo "==> Zona privada $ZONE_NAME já existe ($ZONE_ID)"
  aws route53 associate-vpc-with-hosted-zone --hosted-zone-id "$ZONE_ID" \
    --vpc "VPCRegion=$REGION,VPCId=$VPC_ID" >/dev/null 2>&1 || true
fi
ZONE_ID="${ZONE_ID##*/}"

CHANGES=""
for name in "${RECORDS[@]}"; do
  CHANGES+="{\"Action\":\"UPSERT\",\"ResourceRecordSet\":{\"Name\":\"$name.$ZONE_NAME\",\"Type\":\"A\",\"TTL\":$TTL,\"ResourceRecords\":[{\"Value\":\"$PRIVATE_IP\"}]}},"
done
aws route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --change-batch "{\"Comment\":\"GameRent service discovery\",\"Changes\":[${CHANGES%,}]}" >/dev/null

echo "==> Registros publicados:"
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --query "ResourceRecordSets[?Type=='A'].[Name,ResourceRecords[0].Value]" --output table

cat <<EOF

Validação dentro da EC2:
  getent hosts catalog.$ZONE_NAME rental.$ZONE_NAME
  curl -s http://catalog.$ZONE_NAME:8001/discovery

Os containers usam o resolvedor da VPC (via Docker DNS), então para o rental-service falar com o
catálogo pelo nome simbólico basta subir com:
  CATALOG_SERVICE_URL=http://catalog.$ZONE_NAME:8001
EOF
