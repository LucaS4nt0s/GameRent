#!/usr/bin/env bash
# Provisiona a IAM Role da EC2 do GameRent (Entrega 3) e a anexa à instância.
#
# Permissões concedidas (infra/iam/gamerent-ec2-policy.json):
#   - dynamodb:*          nas tabelas gamerent_* em sa-east-1 (+ ListTables)
#   - route53:*           Route 53 (hoje em "*"; restringir ao ARN da zona gamerent.internal após criá-la)
#   - servicediscovery:*  AWS Cloud Map
#
# Uso (rodar da sua máquina, com AWS CLI configurado com um usuário administrador):
#   ./infra/setup_iam.sh <EC2_INSTANCE_ID>
#   ./infra/setup_iam.sh i-0123456789abcdef0
#
# Idempotente: pode ser executado mais de uma vez.

set -euo pipefail

INSTANCE_ID="${1:-}"
REGION="${AWS_REGION:-sa-east-1}"
ROLE_NAME="${ROLE_NAME:-GameRentEC2Role}"
PROFILE_NAME="${PROFILE_NAME:-GameRentEC2InstanceProfile}"
POLICY_NAME="GameRentDistributedPolicy"
DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -z "$INSTANCE_ID" ]]; then
  echo "Uso: $0 <EC2_INSTANCE_ID>" >&2
  exit 1
fi

echo "==> Role $ROLE_NAME"
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$DIR/iam/ec2-trust-policy.json" \
    --description "GameRent Entrega 3: DynamoDB, Route 53 e Cloud Map" >/dev/null
fi

echo "==> Política inline $POLICY_NAME"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$DIR/iam/gamerent-ec2-policy.json"

echo "==> Instance Profile $PROFILE_NAME"
if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
fi
# Checado à parte: uma execução anterior pode ter criado o profile e falhado antes de anexar a role
ROLES="$(aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" \
  --query 'InstanceProfile.Roles[].RoleName' --output text)"
if [[ " $ROLES " != *" $ROLE_NAME "* ]]; then
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME"
fi

echo "==> Anexando à instância $INSTANCE_ID ($REGION)"
CURRENT="$(aws ec2 describe-iam-instance-profile-associations \
  --region "$REGION" \
  --filters "Name=instance-id,Values=$INSTANCE_ID" "Name=state,Values=associated" \
  --query 'IamInstanceProfileAssociations[0].AssociationId' --output text)"

if [[ "$CURRENT" == "None" || -z "$CURRENT" ]]; then
  # O Instance Profile recém-criado leva alguns segundos para propagar no IAM
  for attempt in 1 2 3 4 5 6; do
    if aws ec2 associate-iam-instance-profile \
      --region "$REGION" \
      --instance-id "$INSTANCE_ID" \
      --iam-instance-profile "Name=$PROFILE_NAME" >/dev/null; then
      break
    fi
    if [[ $attempt == 6 ]]; then
      echo "Falha ao associar $PROFILE_NAME à instância $INSTANCE_ID" >&2
      exit 1
    fi
    sleep 10
  done
else
  aws ec2 replace-iam-instance-profile-association \
    --region "$REGION" \
    --association-id "$CURRENT" \
    --iam-instance-profile "Name=$PROFILE_NAME" >/dev/null
fi

# Os containers ficam a 2 saltos do IMDS. Com IMDSv2 e hop limit 1, o boto3 dentro do container não
# recebe o token e fica sem as credenciais da role.
echo "==> IMDSv2 com hop limit 2 (credenciais acessíveis de dentro dos containers)"
aws ec2 modify-instance-metadata-options \
  --region "$REGION" \
  --instance-id "$INSTANCE_ID" \
  --http-tokens required \
  --http-put-response-hop-limit 2 >/dev/null

cat <<EOF

IAM pronto. Para validar, dentro da EC2:
  aws sts get-caller-identity          # deve mostrar assumed-role/$ROLE_NAME
  aws dynamodb list-tables --region $REGION
  aws route53 list-hosted-zones
  aws servicediscovery list-namespaces --region $REGION
EOF
