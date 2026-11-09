# GameRent — Relatório Técnico: Entrega 3

**Coordenação, Nomeação, Consistência e Replicação na AWS**

- **Disciplina:** Sistemas Distribuídos
- **Provedor de Nuvem:** Amazon Web Services (AWS) — região `sa-east-1` (São Paulo)
- **Data:** Novembro / 2026

**Integrantes do Grupo:**

- **Luca Samuel** — Backend, Coordenação, Consistência & Dados
- **Kauan Simão** — Middleware, APIs, Comunicação & Integração
- **Maria Eduarda** — Infraestrutura, Nuvem AWS, Resiliência & Front-end

> **Status deste documento:** evidências coletadas em 09/11/2026 (prints em `docs/diagrams/entrega-3/`).
> Ainda marcados como **[EVIDÊNCIA PENDENTE]**: aba Segurança da EC2 e `aws sts get-caller-identity`
> (2.2), logs de Lamport na EC2 (3.4), `curl` do discovery na EC2 (4.4), benchmark com o DynamoDB
> gerenciado (5.3) e persistência após reinício (CA-01, 5.3).

---

## 1. Introdução e Objetivos da Entrega 3

A Entrega 2 validou a comunicação síncrona entre dois nós (`rental-service` → `catalog-service`) e a
primeira implantação na EC2. Nela, o estado do catálogo vivia num dicionário em memória de um único
processo, e a reserva seguia o padrão *check-then-act* (`GET /games/{id}` seguido de `PATCH /status`),
sujeito a condição de corrida.

A Entrega 3 ataca três blocos do conteúdo da disciplina:

| Bloco | Tema                       | Problema no GameRent                                              | Solução adotada                                                          |
|-------|----------------------------|-------------------------------------------------------------------|--------------------------------------------------------------------------|
| 4     | Coordenação                | Duas pessoas alugando o mesmo exemplar ao mesmo tempo             | Exclusão mútua com escrita condicional no DynamoDB + relógio de Lamport  |
| 5     | Nomeação                   | Identificadores ad hoc e endereços IP fixos na configuração       | Esquema formal de URNs + DNS interno (Docker DNS / Route 53)             |
| 6     | Consistência e Replicação  | Réplicas do catálogo precisam enxergar o mesmo estado             | DynamoDB Multi-AZ com leitura forte ou eventual escolhida pelo cliente   |

---

## 2. Arquitetura Distribuída da Entrega 3

```
                         +-----------------------------------------+
                         |   Navegador — Front-end React (8080)    |
                         |   Locatário · Locador · Laboratório     |
                         +--------------------+--------------------+
                                              | HTTP (nginx /api/*)
                    +-------------------------+--------------------------+
                    |                                                    |
                    v                                                    v
  +------------------------------------+          +--------------------------------------+
  |  rental-service (8002)             |  REST    |  catalog-service — réplica 1 (8001)  |
  |  urn:gamerent:node:rental-service: | -------> |  urn:gamerent:node:catalog-service:  |
  |  rental-1                          | X-Lamport|  catalog-1                           |
  |  resolve catalog.gamerent.internal |  -Clock  +--------------------------------------+
  +-----------------+------------------+          |  catalog-service — réplica 2 (8003)  |
                    |                             |  urn:gamerent:node:catalog-service:  |
                    |                             |  catalog-2                           |
                    |                             +------------------+-------------------+
                    |                                                |
                    |      ConditionExpression / ConsistentRead      |
                    v                                                v
  +-------------------------------------------------------------------------------------+
  |  Amazon DynamoDB (sa-east-1, replicado em 3 AZs)  — local: amazon/dynamodb-local    |
  |  gamerent_games  (id, urn, status, version, lamport_clock, current_rental_id, ...)  |
  |  gamerent_rentals (rental_id, urn, game_id, status, lamport_clock, ...)             |
  +-------------------------------------------------------------------------------------+

  Resolução de nomes:  Docker DNS (catalog-service)  |  Route 53 Private Hosted Zone
                                                     |  gamerent.internal (AWS)
```

### 2.1. Componentes

| Componente            | Porta | Responsabilidade                                                              |
|-----------------------|------:|-------------------------------------------------------------------------------|
| `catalog-service` ×2  | 8001 / 8003 | Catálogo, busca geográfica, reserva atômica e leitura forte/eventual   |
| `rental-service`      | 8002  | Orquestra locações e chama o catálogo de forma síncrona                       |
| `dynamodb-local`      | 8000  | DynamoDB em container para desenvolvimento (substituído pelo gerenciado na AWS)|
| `frontend`            | 8080  | Interface web (React + nginx)                                                 |

### 2.2. Infraestrutura (issue #3)

- **Local:** `docker compose up -d --build` sobe o DynamoDB Local (`-sharedDb`), as duas réplicas do
  catálogo apontando para a mesma tabela, o `rental-service` e o front-end. Por enquanto o
  `rental-service` fala só com a réplica 1. A réplica 2 entra no balanceamento quando a escrita de
  status e a geração de IDs passarem a ser feitas no DynamoDB (#4/#7).
- **AWS:** a EC2 recebe a IAM Role `GameRentEC2Role` (`infra/setup_iam.sh`) com `dynamodb:*` nas tabelas
  `gamerent_*`, `route53:*` e `servicediscovery:*`. Nenhuma chave de acesso fica na máquina: o boto3 usa as
  credenciais temporárias do Instance Profile. O override `docker-compose.aws.yml` desliga o endpoint
  local e passa a usar o DynamoDB gerenciado.

**Evidência — IAM Role.** A role `GameRentEC2Role` existe no IAM com o serviço `ec2` como entidade
confiável, e a coluna "Última atividade" mostra que ela foi assumida pela instância durante a coleta:

![IAM — role GameRentEC2Role](diagrams/entrega-3/01-iam-role-gamerentec2role.png)

> **[EVIDÊNCIA PENDENTE]** Print da instância `gamerent-server` (EC2 → aba Segurança → "Função do IAM" =
> `GameRentEC2Role`) e saída de `aws sts get-caller-identity` executado dentro da EC2, mostrando
> `assumed-role/GameRentEC2Role`.

---

## 3. Bloco 4 — Coordenação

### 3.1. Fundamentação

Em um sistema distribuído não existe memória compartilhada nem relógio global. Duas réplicas do catálogo
que recebem pedidos simultâneos para o mesmo jogo não conseguem, sozinhas, decidir quem chegou primeiro.
Um `threading.Lock` só protege as threads de **um** processo e não serve com várias réplicas.

Abordagens clássicas de exclusão mútua distribuída:

| Algoritmo                    | Ideia                                              | Custo / limitação                              |
|------------------------------|----------------------------------------------------|------------------------------------------------|
| Centralizado (coordenador)   | Um nó concede a permissão                          | Ponto único de falha                           |
| Ricart–Agrawala              | Pede permissão a todos, ordenando por Lamport      | 2(N−1) mensagens; todos precisam estar vivos   |
| Token Ring                   | Só quem tem o token entra                          | Perda do token; latência proporcional a N      |
| **Compare-and-set no armazenamento** | O banco aplica a escrita só se a condição ainda vale | Depende de um armazenamento com escrita condicional |

O GameRent usa a última. O DynamoDB funciona como árbitro: a operação `UpdateItem` com
`ConditionExpression` é atômica por item, então a verificação ("está `AVAILABLE`?") e a ação ("vire
`RENTED`") acontecem num único passo indivisível no servidor.

### 3.2. Exclusão mútua (issues #7, #9 e #14 — PR #21)

```text
UpdateItem gamerent_games
  Key:                 { id: <game_id> }
  ConditionExpression: attribute_exists(id) AND #status = :available
  UpdateExpression:    SET #status = :rented, current_rental_id = :rental_id,
                           lamport_clock = :clock, version = version + :one, updated_at = :now
```

- Se a condição falha, o DynamoDB lança `ConditionalCheckFailedException` e o catálogo responde
  **409 Conflict**.
- O `rental-service` deixa de fazer `GET` + `PATCH`: chama direto o endpoint atômico de reserva e repassa
  o 409 ao cliente.
- A devolução faz a operação inversa (`RENTED → AVAILABLE`, limpando `current_rental_id`).

> **Estado atual:** o fluxo atômico entrou em `dev` com o PR #21 (`POST /games/{id}/reserve` e
> `/release`, `ConditionExpression` no DynamoDB e 409 propagado pelo `rental-service`). O `test_issue_14`
> já comprova o 409 em reservas sequenciais. A ausência de *double-booking* sob concorrência real só pode
> ser afirmada depois do CA-02 (seção 3.4).

### 3.3. Relógio lógico de Lamport (issue #6)

Cada nó mantém um contador `L`:

- evento interno ou envio: `L = L + 1`, com o valor enviado no header `X-Lamport-Clock`;
- recebimento: `L = max(L, L_msg) + 1`, devolvido no header de resposta e no JSON (`lamport_clock`).

Assim, se a reserva *a* causou a atualização *b* no catálogo, então `L(a) < L(b)` (relação
*happens-before*). A recíproca não vale: `L(a) < L(b)` não prova que *a* causou *b*, porque eventos
concorrentes também recebem valores ordenados. Ordenando por `(L, id do nó)`, os nós obtêm uma **ordem
total consistente com a causalidade**, suficiente para registrar e auditar as operações. Detectar
concorrência exigiria relógios vetoriais. Os logs registram `[LAMPORT=n]` junto do horário físico
(`asctime` do container, que fica em UTC por padrão nas imagens `python:3.11-slim`).

### 3.4. Evidências

**Exclusão mútua (CA-02) — na AWS.** A bateria foi executada contra a stack da EC2, pelo CloudFront
(`/api/catalog` e `/api/rental`). Dez `POST /rentals` simultâneos para o mesmo jogo resultaram em
**1 × 201 Created** e **9 × 409 Conflict**. Logo depois, uma leitura forte do item mostra
`status=RENTED`, `version=2` e o `lamport_clock` da escrita vencedora. O mesmo teste também confirmou o
cadastro com URN sem expor GPS (FA-01), o relógio de Lamport (entrada 50 → saída 219) e o ciclo
devolução → nova locação (FB-03):

![Bateria de testes na AWS](diagrams/entrega-3/03b-teste-aws.webp)

Como a rota `/reserve` não é exposta publicamente (o nginx responde 403), a disputa **entre as duas
réplicas** do catálogo foi validada no ambiente Docker, com 10 reservas divididas entre `catalog-1` e
`catalog-2`: **1 × 200 e 9 × 409**, com a vencedora decidida pela escrita condicional:

![Bateria de testes local, com disputa entre réplicas](diagrams/entrega-3/03a-teste-local.webp)

**Relógio de Lamport (CA-03).** Linha do tempo de duas locações, juntando os logs do `rental-service` e
das duas réplicas do catálogo e ordenando pelo horário físico. O contador nunca diminui ao longo da
cadeia solicitação → reserva → confirmação → liberação → finalização. O salto de 24 para 33 no
`rental-service` corresponde às outras nove requisições da disputa, que avançaram o relógio no intervalo:

![Logs com LAMPORT crescendo](diagrams/entrega-3/04-lamport-logs-local.webp)

> **[EVIDÊNCIA PENDENTE]** O print acima foi gerado no ambiente Docker local. Repetir na EC2 com
> `sudo docker logs gamerent-rental 2>&1 | grep <rental_id>` (e o mesmo para `gamerent-catalog-1`).

---

## 4. Bloco 5 — Nomeação

### 4.1. Fundamentação

Nomeação separa **o que** um recurso é (nome) de **onde** ele está (endereço). Em sistemas distribuídos
isso é necessário porque réplicas sobem e descem, IPs mudam a cada implantação e o mesmo recurso precisa
ser referenciado de forma estável entre serviços, logs e interface.

O GameRent usa dois tipos de nome:

1. **Nomes estruturados independentes de localização (URNs)** para recursos de negócio e nós.
2. **Nomes simbólicos resolvidos por DNS** para chegar aos serviços.

### 4.2. Esquema formal de URNs (issue #5)

Implementado em `services/*/src/naming.py`:

| Recurso    | Formato                                          | Exemplo                                                    |
|------------|--------------------------------------------------|------------------------------------------------------------|
| Nó         | `urn:gamerent:node:{service_name}:{instance_id}` | `urn:gamerent:node:catalog-service:catalog-2`              |
| Jogo       | `urn:gamerent:game:{region}:{game_id}`           | `urn:gamerent:game:sa-east-1:1`                            |
| Reserva    | `urn:gamerent:rental:{uuid_v4}`                  | `urn:gamerent:rental:4db0ddd6-3f6c-40d7-a62d-eef18e768ce2` |
| Locador    | `urn:gamerent:owner:{owner_id}`                  | `urn:gamerent:owner:locador-001`                           |

O espaço de nomes é hierárquico (`urn:gamerent:<tipo>:...`). A região dentro do URN do jogo prepara o
esquema para particionamento geográfico. O `uuid_v4` das reservas é gerado sem coordenação entre nós e
tem probabilidade de colisão desprezível. Os URNs aparecem em `/health`, `/discovery`, em todos os jogos
(`urn`, `owner_urn`, `served_by_node`) e nas locações (`urn`, `game_urn`).

### 4.3. Service Discovery e DNS interno

| Ambiente | Nome usado pelo `rental-service` | Resolvido por                                  |
|----------|----------------------------------|------------------------------------------------|
| Docker   | `catalog-service`                | DNS embutido do Docker (rede `gamerent-net`)   |
| AWS      | `catalog.gamerent.internal`      | Route 53 Private Hosted Zone `gamerent.internal` |

Uma zona privada só responde dentro das VPCs associadas a ela, e a VPC precisa ter `enableDnsSupport`
e `enableDnsHostnames` ligados (o script verifica isso). O AWS Cloud Map é uma alternativa: um namespace
DNS privado do Cloud Map cria a mesma zona no Route 53 e permite registrar e remover instâncias por API,
com health check. Com uma única EC2, a zona privada direta é suficiente. Por isso a IAM Role já tem
`servicediscovery:*`, mas o Cloud Map não foi usado.

`infra/setup_route53.sh` cria a zona privada associada à VPC e publica `catalog.gamerent.internal` e
`rental.gamerent.internal` (registros A, TTL 60 s) com o IP privado da EC2. Os serviços registram cada
tradução feita com `socket.getaddrinfo`:

```text
[RENTAL-SERVICE] [DNS] catalog.gamerent.internal -> 172.31.x.x
```

`GET /discovery` expõe os metadados de nomeação do nó: URN, `instance_id`, região, hostname, IPs locais,
o esquema de URNs e a resolução de cada nome simbólico.

### 4.4. Evidências

**Route 53.** Zona privada `gamerent.internal` com os registros A `catalog.gamerent.internal` e
`rental.gamerent.internal` apontando para o IP privado da EC2 (`172.31.33.87`):

![Route 53 — zona privada gamerent.internal](diagrams/entrega-3/05-route53-gamerent-internal.webp)

**Resolução na EC2.** O painel de service discovery (seção 6), servido pela EC2, mostra o
`catalog-service` resolvendo `catalog.gamerent.internal` para `172.31.33.87`, o mesmo IP do registro no
Route 53:

![Service discovery na EC2](diagrams/entrega-3/09b-admin-service-discovery.png)

> **Observação.** No mesmo painel, o `rental-service` ainda aponta para `http://catalog-service:8001`
> (DNS do Docker). O nome `catalog.gamerent.internal` só é usado pelo `rental-service` quando a stack sobe
> com o override `docker-compose.aws.yml`, que não estava ativo na coleta.

> **[EVIDÊNCIA PENDENTE]** Saída de `curl http://catalog.gamerent.internal:8001/discovery` executado na EC2
> e trecho de log `[DNS] catalog.gamerent.internal -> 172.31.33.87` (CA-04).

---

## 5. Bloco 6 — Consistência e Replicação

### 5.1. Fundamentação

Replicar dados aumenta a disponibilidade e a tolerância a falhas, mas cria a questão de **quando** uma
escrita fica visível nas outras réplicas.

- O **teorema CAP** trata do caso com **partição** de rede: o sistema precisa escolher entre
  consistência e disponibilidade.
- O **PACELC** completa o CAP com o caso normal (*Else*): **sem** partição, ainda há um compromisso
  entre **latência** e **consistência**.

Pelo PACELC, o DynamoDB fica em PA/EL por padrão (leitura eventual, mais barata e rápida). Quando o
cliente pede `ConsistentRead`, aquela leitura vai para PC/EC: paga latência para ver a última escrita
confirmada.

- **Consistência forte:** toda leitura vê a escrita mais recente já confirmada (linearizável por item).
- **Consistência eventual:** sem novas escritas, todas as réplicas convergem. Até lá, uma leitura pode
  devolver um valor antigo.

### 5.2. Replicação no DynamoDB

O DynamoDB replica cada tabela automaticamente em múltiplas zonas de disponibilidade da região (AWS,
*Developer Guide*). Internamente, cada partição tem um grupo de réplicas com um líder, e a escrita é
confirmada depois de gravada num quórum delas (ELHEMALI et al., USENIX ATC 2022). Na leitura, o
cliente escolhe:

| Parâmetro do GameRent   | Chamada no DynamoDB      | Garantia                      | Custo                       |
|-------------------------|--------------------------|-------------------------------|-----------------------------|
| `consistency=strong`    | `ConsistentRead=True`    | Lê a última escrita confirmada | 1 unidade de leitura / 4 KB, mais latência |
| `consistency=eventual`  | `ConsistentRead=False`   | Pode ler dado antigo          | ½ unidade de leitura / 4 KB, menos latência |

No modo provisionado a unidade é a RCU; no on-demand, a RRU. Num `Scan` (usado por `GET /games`), o
custo é calculado sobre o volume total lido, não por item retornado.

No nível da aplicação, as duas réplicas do `catalog-service` não guardam estado próprio: elas são
réplicas de processamento sobre o mesmo armazenamento replicado. Por isso um jogo cadastrado em
`catalog-1` é lido por `catalog-2`. Os campos `version` e `lamport_clock` de cada item mostram ao
cliente qual versão ele recebeu, e `served_by_node` mostra qual réplica respondeu.

### 5.3. Evidências

**Forte × eventual (CA-05).** Latência de leitura medida dentro do serviço (header
`X-DB-Read-Latency-Ms`), 20 leituras alternadas de `GET /games` em cada modo:

| Ambiente                    | Modo     | Leituras | Latência média (ms) | p95 (ms) |
|-----------------------------|----------|---------:|--------------------:|---------:|
| EC2 (via CloudFront)        | strong   |       20 |                5,30 |     8,79 |
| EC2 (via CloudFront)        | eventual |       20 |                4,97 |     7,73 |
| Docker local                | strong   |       20 |               18,11 |    78,58 |
| Docker local                | eventual |       20 |               15,51 |    65,64 |

No comparador do site (5 leituras por modo), a diferença média foi de 0,09 ms a favor da leitura
eventual (6,29 ms × 6,20 ms):

![Comparador forte × eventual](diagrams/entrega-3/09c-admin-forte-eventual.png)

Em todas as medições a leitura eventual foi um pouco mais rápida, como o PACELC prevê. A diferença é
pequena porque o `Scan` lê poucos itens e o banco está na mesma região dos serviços.

> **Limitação da medição.** O painel de discovery capturado às 18:11 de 09/11 indica
> `LOCAL_DYNAMODB` nos dois serviços: naquele momento a EC2 estava usando o container `dynamodb-local`, e
> não o DynamoDB gerenciado. Os números da EC2 acima refletem esse estado.
>
> **[EVIDÊNCIA PENDENTE]** Subir a stack com `docker compose -f docker-compose.yml -f docker-compose.aws.yml
> up -d --build`, confirmar `DynamoDB = AWS` no painel e repetir o benchmark.

**Tabelas no DynamoDB.** As tabelas `gamerent_games` (chave `id`) e `gamerent_rentals` (chave
`rental_id`) estão ativas em `sa-east-1`. A coluna "Regiões de replicação" é 0 porque o projeto não usa
Global Tables (replicação entre regiões). A replicação usada é a Multi-AZ, que o DynamoDB faz
automaticamente dentro da região e não aparece como configuração no console:

![Tabelas no console do DynamoDB](diagrams/entrega-3/07a-dynamodb-tabelas.png)

Itens de `gamerent_games` com `lamport_clock`, `urn` e `version`. Jogos disputados várias vezes têm
versões mais altas (Terraforming Mars em `version=11`, Dixit em `version=8`):

![gamerent_games — lamport_clock](diagrams/entrega-3/07b-dynamodb-games-lamport.png)

![gamerent_games — urn e version](diagrams/entrega-3/07c-dynamodb-games-urn-version.png)

Itens de `gamerent_rentals` com `game_urn`, `lamport_clock`, `status` e `returned_at`:

![gamerent_rentals — lamport_clock](diagrams/entrega-3/07d-dynamodb-rentals-lamport.webp)

![gamerent_rentals — status](diagrams/entrega-3/07e-dynamodb-rentals-status.png)

> **[EVIDÊNCIA PENDENTE]** CA-01: reiniciar os containers após uma locação e mostrar que o status `RENTED`
> e o registro da locação continuam no DynamoDB.

---

## 6. Interface Web (issues #11, #17, #18 e #19 — PR #28)

O front-end (`frontend/`, React servido por nginx na porta 8080) foi reorganizado em três abas que
servem tanto ao produto quanto à demonstração dos blocos 4, 5 e 6. A interface relê catálogo, locações
e saúde em segundo plano a cada 3 s, então uma reserva ou devolução feita por outro cliente aparece sem
recarregar a página.

**Aba 1 — Locatário (#17).**
- Busca geográfica com atalhos de bairros de São Paulo, latitude/longitude e raio `max_km`. As
  coordenadas do locador nunca saem do servidor; o cliente recebe só a distância relativa.
- Seletor de consistência **Forte** ou **Eventual**, com badges de `db_read_latency_ms` e
  `served_by_node` da resposta (bloco 6).
- Cards com URN do jogo, versão e relógio de Lamport da última escrita.
- Aluguel e "Minhas locações" com devolução (`POST /rentals/{id}/return`).

**Aba 2 — Locador (#18).**
- Cadastro de jogo (`POST /games`), que já mostra o URN gerado (bloco 5), com aviso de privacidade
  geográfica.
- Acervo com alternância `AVAILABLE` ↔ `MAINTENANCE` (`PATCH /games/{id}/status`).

**Aba 3 — Laboratório de Sistemas Distribuídos (#19).**
- **Disputa concorrente (bloco 4):** dispara 10 reservas simultâneas do mesmo jogo e mostra cada
  resposta com seu relógio de Lamport. O resultado esperado é 1 × `201 Created` e 9 × `409 Conflict`.
- **Nomeação e service discovery (bloco 5):** consulta `GET /discovery` dos dois serviços a cada 5 s e
  mostra URN do nó, nome DNS, IP resolvido, modo do DynamoDB e Lamport.
- **Comparador de consistência (bloco 6):** 5 leituras em cada modo, alternando a ordem, com a latência
  média de leitura do banco.

**Disputa concorrente** na EC2: 10 reservas do jogo `urn:gamerent:game:sa-east-1:1` → 1 × 201 (req #5) e
9 × 409, com o Lamport de cada resposta indo de 29 a 39:

![Laboratório — disputa concorrente](diagrams/entrega-3/09a-admin-disputa-concorrente.png)

**Acervo técnico**, com URN, dono, status, versão e Lamport de cada jogo, lido em consistência forte e
indicando a réplica que respondeu (`served_by_node`):

![Laboratório — acervo técnico](diagrams/entrega-3/09d-admin-acervo-tecnico.webp)

Os prints das abas **Service discovery** e **Forte × Eventual** estão nas seções 4.4 e 5.3.

---

## 7. Implantação na AWS

| Item                 | Configuração                                                                  |
|----------------------|-------------------------------------------------------------------------------|
| Computação           | EC2 Ubuntu 24.04 LTS, `sa-east-1`, Docker Compose v2                           |
| Identidade           | IAM Role `GameRentEC2Role` via Instance Profile (`infra/setup_iam.sh`)        |
| Banco                | Amazon DynamoDB on-demand: `gamerent_games`, `gamerent_rentals`               |
| Nomeação             | Route 53 Private Hosted Zone `gamerent.internal` (`infra/setup_route53.sh`)   |
| Inicialização        | `infra/user_data_ec2.sh` + `docker-compose.aws.yml`                           |
| Security Group       | 22 restrita aos administradores; 8001–8003 e 8080 abertas para a demonstração |

---

## 8. Conclusão

A Entrega 3 leva o GameRent de um protótipo com estado em memória para uma arquitetura em que (sujeito
à validação dos critérios de aceite nas seções de evidências):

- várias réplicas do catálogo operam sobre um armazenamento replicado e compartilhado;
- a reserva de um exemplar é decidida por uma escrita condicional atômica, para evitar *double-booking*;
- a ordem causal entre os serviços fica registrada por relógios de Lamport;
- recursos e nós têm nomes formais e estáveis, e os serviços se encontram por DNS, não por IP fixo;
- o cliente escolhe entre consistência forte e eventual, conhecendo o custo em latência de cada uma.

> **[PENDENTE]** Lições aprendidas e próximos passos (Entrega 4), após a coleta das evidências.

---

## 9. Como gerar o PDF

Salve os prints em `docs/diagrams/entrega-3/` (pasta versionada) e referencie-os com caminho relativo,
por exemplo `![Route 53](diagrams/entrega-3/route53-zona-privada.png)`. Depois:

```bash
pandoc docs/relatorio-entrega-3.md -s -o docs/relatorio-entrega-3.html --metadata title="GameRent — Entrega 3"
# Abra o HTML no navegador e use "Imprimir → Salvar como PDF" para docs/relatorio-entrega-3.pdf
```

---

## Referências

- TANENBAUM, A. S.; VAN STEEN, M. *Distributed Systems*. 4. ed. — capítulos 5 (Nomeação),
  6 (Coordenação) e 7 (Consistência e Replicação).
- LAMPORT, L. Time, Clocks, and the Ordering of Events in a Distributed System. *Communications of the
  ACM*, 21(7), 1978.
- AWS. *Amazon DynamoDB Developer Guide* — Read consistency; Condition expressions; Read/write capacity mode.
- ELHEMALI, M. et al. Amazon DynamoDB: A Scalable, Predictably Performant, and Fully Managed NoSQL
  Database Service. *USENIX ATC*, 2022.
- ABADI, D. Consistency Tradeoffs in Modern Distributed Database System Design (PACELC). *IEEE
  Computer*, 45(2), 2012.
- AWS. *Amazon Route 53 Developer Guide* — Working with private hosted zones.
