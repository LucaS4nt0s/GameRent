#!/usr/bin/env bash
# Service Discovery na AWS (Entrega 3 — Nomeação): Route 53 Private Hosted Zone "gamerent.internal".
#
# Cria (ou reaproveita) a zona privada associada à VPC da EC2 e publica:
#   catalog.gamerent.internal  A  <IP privado da EC2>
#   rental.gamerent.internal   A  <IP privado da EC2>
#
# Uso (da sua máquina com AWS CLI admin; de dentro da EC2 a role de infra/setup_iam.sh basta se a VPC
# já tiver enableDnsSupport/enableDnsHostnames ligados, pois a role não tem ec2:ModifyVpcAttribute):
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

INFO="$(aws ec2 describe-instances \
  --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].[VpcId,PrivateIpAddress]' --output text)"
read -r VPC_ID PRIVATE_IP <<<"$INFO"
if [[ -z "${VPC_ID:-}" || "$VPC_ID" == "None" || -z "${PRIVATE_IP:-}" ]]; then
  echo "Não encontrei VPC/IP privado da instância $INSTANCE_ID em $REGION" >&2
  exit 1
fi
echo "==> EC2 $INSTANCE_ID: VPC=$VPC_ID IP privado=$PRIVATE_IP"

# A VPC precisa resolver DNS privado; só altera o que estiver desligado
for attr in enableDnsSupport enableDnsHostnames; do
  enabled="$(aws ec2 describe-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" --attribute "$attr" \
    --query "${attr^}.Value" --output text)"
  if [[ "$enabled" != "True" ]]; then
    echo "==> Ligando $attr na VPC $VPC_ID"
    flag="--enable-dns-support"
    [[ "$attr" == enableDnsHostnames ]] && flag="--enable-dns-hostnames"
    aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC_ID" "$flag" '{"Value":true}'
  fi
done

ZONE_IDS="$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME." \
  --query "HostedZones[?Name=='$ZONE_NAME.' && Config.PrivateZone].Id" --output text)"
read -r -a ZONE_LIST <<<"$ZONE_IDS"
if (( ${#ZONE_LIST[@]} > 1 )); then
  echo "Há ${#ZONE_LIST[@]} zonas privadas $ZONE_NAME (${ZONE_LIST[*]}). Remova as extras ou rode com ZONE_ID=<id>." >&2
  exit 1
fi
ZONE_ID="${ZONE_ID:-${ZONE_LIST[0]:-None}}"

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
  ASSOCIATED="$(aws route53 get-hosted-zone --id "$ZONE_ID" \
    --query "VPCs[?VPCId=='$VPC_ID'] | length(@)" --output text)"
  if [[ "$ASSOCIATED" == "0" ]]; then
    aws route53 associate-vpc-with-hosted-zone --hosted-zone-id "$ZONE_ID" \
      --vpc "VPCRegion=$REGION,VPCId=$VPC_ID" >/dev/null
  fi
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
