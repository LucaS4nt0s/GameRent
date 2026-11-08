# PRD — Sprint Entrega 3: Coordenação, Nomeação e Consistência (GameRent)

**Disciplina:** Sistemas Distribuídos  
**Data Limite da Entrega 3:** 03/11/2026 (Valor: 2,0 pontos)  
**Provedor de Nuvem:** Amazon Web Services (AWS) — Região `sa-east-1` (São Paulo)  
**Status Atual (Pós-Entrega 2):** Dois microsserviços (`catalog-service` na porta `8001` e `rental-service` na porta `8002`) comunicando-se via REST síncrono, implantados em AWS EC2 com Docker Compose, porém utilizando armazenamento volátil em memória (`GAMES_DB` e `RENTALS_DB`) e sem controle atômico contra condições de corrida (*race conditions*).

---

## 1. Visão Geral e Objetivos da Sprint

O objetivo da **Entrega 3** é evoluir a plataforma **GameRent** de um protótipo funcional com estado em memória para um **sistema distribuído coordenado, persistente e replicado**, atendendo integralmente aos blocos **4 (Coordenação)**, **5 (Nomeação)** e **6 (Consistência e Replicação)** do *Trabalho Prático – Sistemas Distribuídos*, mantendo total coerência com a arquitetura planejada na **Entrega 1** e com os próximos passos definidos na **Entrega 2**.

### Critérios de Avaliação da Disciplina (Entrega 3)
1. **Algoritmo de Coordenação:** Exclusão mútua distribuída e sincronização lógica/física para impedir reservas simultâneas (*double-booking*).
2. **Esquema de Nomeação:** Identificação padronizada de recursos e descoberta dinâmica de serviços (*Service Discovery* / DNS interno).
3. **Início da Replicação de Dados e Modelo de Consistência:** Persistência replicada substituindo os dicionários em memória e experimentação prática comparando **Consistência Forte** vs. **Consistência Eventual**.
4. **Clareza na Documentação Parcial:** Relatório técnico (`docs/relatorio-entrega-3.md` e `.pdf`) com diagramas atualizados, evidências de código, logs e testes em nuvem AWS.

---

## 2. Diagnóstico do Estado Atual do Aplicativo (Gap Analysis)

Com base na inspeção do código-fonte atual e dos relatórios das Entregas 1 e 2, os seguintes pontos precisam ser desenvolvidos ou refatorados:

| Componente / Arquivo Atual | Estado na Entrega 2 | Problema / Limitação | O que desenvolver na Entrega 3 |
| :--- | :--- | :--- | :--- |
| `services/catalog-service/src/app.py` | Estado salvo no dicionário em memória `GAMES_DB`. | Se o container reiniciar ou escalar para >1 réplica, os dados se perdem ou divergem; `PATCH /games/{id}/status` sofre condição de corrida (*Check-Then-Act* não atômico). | Persistência no **Amazon DynamoDB** (tabela `gamerent-catalog`), atualização atômica com **Conditional Writes** + controle de versão/relógio lógico de Lamport. |
| `services/rental-service/src/app.py` | Faz `GET /games/{id}` e depois `PATCH /games/{id}/status`, salvando reservas em `RENTALS_DB` (memória). | Duas requisições simultâneas no mesmo milissegundo leem `AVAILABLE` no `GET` e ambas confirmam o aluguel (*double-booking*). | Solicitar reserva atômica coordenada pelo catálogo/DynamoDB, persistir locações na tabela `gamerent-rentals` e propagar timestamps lógicos. |
| `services/rental-service/src/catalog_client.py` | Recebe URL estática via variável de ambiente `CATALOG_SERVICE_URL`. | Acoplamento a IP/host fixo sem resolução dinâmica de nomes na nuvem ou registro de serviços. | Resolver endereço via **AWS Cloud Map / Route 53 Private DNS** (`catalog.gamerent.internal`) e suportar cabeçalhos de relógio lógico e modo de consistência. |
| `docker-compose.yml` & `infra/` | Sobe apenas `catalog-service` e `rental-service`. | Não possui banco de dados local para desenvolvimento nem scripts de provisionamento das tabelas/DNS na AWS. | Adicionar **DynamoDB Local** para ambiente dev/teste, múltiplas réplicas de serviço para demonstrar replicação/coordenação e scripts AWS CLI/Terraform em `infra/`. |
| `scripts/test_communication.py` | Testa apenas requisições sequenciais (1 por vez). | Não comprova exclusão mútua sob concorrência real nem avalia modelos de consistência. | Criar bateria de testes de concorrência paralela (`ThreadPoolExecutor`/`asyncio.gather`) e testes comparativos de leitura forte vs. eventual. |

---

## 3. Escopo Funcional e Requisitos Técnicos (Backlog da Entrega 3)

### Épico 1: Coordenação e Exclusão Mútua Distribuída (Requisito 4)
**Objetivo:** Garantir que apenas um locatário consiga reservar um exemplar físico de jogo quando múltiplas requisições concorrentes chegarem simultaneamente a diferentes threads ou réplicas do serviço.

* **RF-01 — Exclusão Mútua com DynamoDB Conditional Writes:**
  * Implementar no `catalog-service` um endpoint atômico de reserva (`POST /games/{game_id}/reserve` ou evolução do `PATCH /games/{game_id}/status`) que execute um `UpdateItem` no DynamoDB com a expressão condicional:
    ```text
    ConditionExpression: #status = :available
    UpdateExpression: SET #status = :rented, current_rental_id = :rental_id, lamport_clock = lamport_clock + :inc, updated_at = :now
    ```
  * Caso o DynamoDB retorne `ConditionalCheckFailedException`, o serviço deve capturar a exceção e retornar imediatamente `HTTP 409 Conflict` (bloqueando o *double-booking* direto na camada de coordenação distribuída).
* **RF-02 — Sincronização com Relógios Lógicos de Lamport:**
  * Implementar um módulo de **Relógio Lógico de Lamport** (`lamport_clock.py`) em ambos os microsserviços:
    * Cada evento local incrementa o contador $L_i = L_i + 1$.
    * Ao enviar uma mensagem REST entre `rental-service` e `catalog-service`, enviar o valor atual no header `X-Lamport-Clock`.
    * Ao receber uma requisição, atualizar o relógio local com $L_j = \max(L_j, L_{msg}) + 1$ e devolver o novo timestamp lógico no header de resposta e no payload da transação.
  * Registrar nos logs estruturados o valor do relógio lógico (`[LAMPORT=14]`) ao lado do timestamp físico UTC para demonstrar a ordenação causal dos eventos no relatório.

---

### Épico 2: Esquema de Nomeação e Descoberta de Serviços (Requisito 5)
**Objetivo:** Eliminar referências a IPs fixos na comunicação entre nós e padronizar a identificação única de todos os recursos distribuídos do ecossistema GameRent.

* **RF-03 — Esquema Formal de Identificadores e URNs de Recursos:**
  * Definir e aplicar um esquema padronizado de nomes (URNs / identificadores compostos) em todos os modelos e respostas da API:
    * **Serviços/Nós:** `urn:gamerent:node:{service_name}:{instance_id}` (ex.: `urn:gamerent:node:catalog-service:i-0a1b2c3d`)
    * **Jogos:** `urn:gamerent:game:{region}:{game_id}` (ex.: `urn:gamerent:game:sa-east-1:0001`)
    * **Reservas:** `urn:gamerent:rental:{uuid_v4}`
    * **Locadores:** `urn:gamerent:owner:{owner_id}`
  * Expor essas informações nos endpoints de negócio e no `/health` (identificando qual réplica/instância respondeu à requisição).
* **RF-04 — Service Discovery e Resolução DNS Interna (AWS Route 53 / Cloud Map):**
  * Na AWS: Configurar uma **Zona Hospedada Privada no Amazon Route 53** (`gamerent.internal`) e/ou namespace no **AWS Cloud Map** associada à VPC da aplicação, mapeando:
    * `catalog.gamerent.internal` $\rightarrow$ Nó(s) do `catalog-service`
    * `rental.gamerent.internal` $\rightarrow$ Nó(s) do `rental-service`
  * No código: Implementar um resolvedor/registro de nomeação (`naming.py`) que consulte e exponha nos logs a resolução DNS (`socket.getaddrinfo`) do nome simbólico para o IP privado antes/durante a comunicação inter-serviços, além de um endpoint `GET /discovery` demonstrando os metadados de nomeação do nó atual.

---

### Épico 3: Consistência e Replicação de Dados (Requisito 6)
**Objetivo:** Substituir o armazenamento volátil em memória por persistência distribuída com replicação de dados e avaliar na prática os modelos de **Consistência Forte (*Strong Consistency*)** e **Consistência Eventual (*Eventual Consistency*)**.

* **RF-05 — Persistência e Replicação com Amazon DynamoDB (Multi-AZ) + Réplicas de Serviço:**
  * Criar camada de repositório (`repository.py`) no `catalog-service` e no `rental-service` utilizando `boto3` para persistir as tabelas:
    * `gamerent_games`: chave de partição `game_id` (Number/String), atributos de geolocalização (`latitude`, `longitude`), `status`, `lamport_clock`, `version`, `updated_at`.
    * `gamerent_rentals`: chave de partição `rental_id` (String), `game_id`, `renter_name`, `status`, `lamport_clock`, `created_at`.
  * Implementar rotina automática de *Seed* inicial dos 5 jogos de tabuleiro caso a tabela esteja vazia na inicialização.
  * Na AWS, o DynamoDB replica automaticamente os dados de forma síncrona/assíncrona através de **3 Zonas de Disponibilidade (Multi-AZ)** na região `sa-east-1`.
  * No `docker-compose.yml`, permitir subir **2 réplicas do `catalog-service`** conectadas ao mesmo banco para comprovar que o estado é compartilhado, replicado e consistente independentemente de qual nó atenda à requisição.
* **RF-06 — Experimentação de Modelos de Consistência (Forte vs. Eventual):**
  * Adicionar suporte ao parâmetro `consistency: "strong" | "eventual"` nos endpoints de leitura (`GET /games/{id}` e `GET /games`):
    * Quando `consistency=strong`, executar `table.get_item(Key=..., ConsistentRead=True)` no DynamoDB (leitura linearizável da réplica líder/quórum de escrita).
    * Quando `consistency=eventual`, executar `table.get_item(Key=..., ConsistentRead=False)` no DynamoDB (leitura de qualquer réplica de armazenamento, menor latência e metade do custo de RCU, mas sujeita a *stale reads* imediatamente após uma escrita).
  * Retornar nos metadados da resposta o modelo de consistência utilizado, a latência da leitura no banco em milissegundos (`db_read_latency_ms`) e a versão/relógio lógico do registro lido.

---

## 4. Arquitetura Alvo da Entrega 3

```
+-------------------------------------------------------------------------+
|                        Cliente / Script de Testes                       |
+------------------------------------+------------------------------------+
                                     |
                        POST /rentals (Concorrentes)
                                     |
                                     v
+-------------------------------------------------------------------------+
|               NÓ 1: RENTAL-SERVICE (Porta 8002)                         |
|  - Incrementa Relógio Lógico de Lamport (L)                             |
|  - Resolve nome 'catalog.gamerent.internal' (Route 53 / Cloud Map)      |
+------------------------------------+------------------------------------+
                                     |
           POST /games/{id}/reserve (Header: X-Lamport-Clock)
                                     |
                                     v
+-------------------------------------------------------------------------+
|          NÓ 2: CATALOG-SERVICE (Réplicas 1..N - Porta 8001)             |
|  - Sincroniza Relógio de Lamport: L = max(L_local, L_msg) + 1           |
|  - Executa Exclusão Mútua via Conditional Write                         |
+------------------------------------+------------------------------------+
                                     |
       UpdateItem (Condition: status = AVAILABLE) / GetItem (Strong/Eventual)
                                     |
                                     v
+-------------------------------------------------------------------------+
|            CAMADA DE DADOS E REPLICAÇÃO (Amazon DynamoDB)               |
|    [ Zona sa-east-1a ] <=== Replicação Multi-AZ ===> [ Zona sa-east-1b ]|
|                    \======= Replicação Multi-AZ ===> [ Zona sa-east-1c ]|
+-------------------------------------------------------------------------+
```

---

## 5. Divisão de Tarefas por Integrante (Alinhada à Entrega 1)

### 👨‍💻 Luca Samuel — Backend, Coordenação, Consistência & Dados
1. **Modelagem e Repositório DynamoDB (`boto3`):**
   * Criar `services/catalog-service/src/database.py` e `services/rental-service/src/database.py` com suporte transparente à AWS (`sa-east-1`) e ao `dynamodb-local` (via variável `DYNAMODB_ENDPOINT_URL`).
   * Implementar criação automática de tabelas (`gamerent_games` e `gamerent_rentals`) e carga inicial (*seed*) dos jogos.
2. **Algoritmo de Exclusão Mútua Distribuída:**
   * Implementar `reserve_game_atomically(game_id, rental_id, incoming_clock)` usando `UpdateItem` com `ConditionExpression=" attribute_exists(id) AND #st = :avail "` no DynamoDB.
   * Implementar liberação atômica (`release_game_atomically`) na devolução do aluguel.
3. **Modelos de Consistência:**
   * Implementar o seletor `consistency=strong|eventual` (`ConsistentRead=True/False`) no `catalog-service`, medindo o tempo de resposta e expondo a versão do item.

### 👨‍💻 Kauan Simão — Middleware, APIs, Comunicação & Integração
1. **Sincronização com Relógios Lógicos (Lamport):**
   * Criar o gerenciador de relógio lógico thread-safe e integrar nos middlewares/endpoints FastAPI do `rental-service` e `catalog-service` (propagação via header `X-Lamport-Clock`).
2. **Refatoração do Fluxo S2S (`catalog_client.py`):**
   * Substituir o fluxo antigo em duas etapas (`GET` + `PATCH` separados) pela chamada atômica de reserva coordenada, evitando janelas de condição de corrida entre serviços.
3. **Scripts de Teste de Concorrência e Consistência (`scripts/test_entrega3.py`):**
   * Criar teste de estresse disparando **10 requisições simultâneas em paralelo** para reservar o mesmo jogo (`game_id=1`), comprovando que exatamente **1 retorna `201 Created`** e **9 retornam `409 Conflict`**.
   * Criar teste comparativo de **Consistência Forte vs. Consistência Eventual**, registrando latências e comportamento de leitura imediatamente após escrita (*Read-After-Write*).

### 👩‍💻 Maria Eduarda — Infraestrutura, Nomeação, Nuvem AWS & Front-end
1. **Esquema de Nomeação e Service Discovery:**
   * Implementar o módulo de nomeação (`URN` de recursos e identificação de réplicas `INSTANCE_ID`) nos serviços.
   * Configurar **Amazon Route 53 Private Hosted Zone** (`gamerent.internal`) / **AWS Cloud Map** na VPC da AWS para resolução de nomes entre containers/instâncias.
2. **Infraestrutura Docker & AWS (`docker-compose.yml` e `infra/`):**
   * Adicionar o container `amazon/dynamodb-local` ao `docker-compose.yml` para execução local imediata sem custos.
   * Configurar IAM Role / credenciais na instância EC2 da AWS com permissões para `dynamodb:*`, `route53:*` e `servicediscovery:*`.
3. **Front-end e Relatório Técnico (`docs/relatorio-entrega-3.md`):**
   * Atualizar a interface web (se aplicável) para exibir o URN do jogo, o contador do relógio lógico e o status de bloqueio em tempo real.
   * Consolidar prints do console AWS (tabelas DynamoDB, Route 53/Cloud Map, logs de concorrência) no relatório da Entrega 3.

---

## 6. Plano de Testes e Critérios de Aceite (Definition of Done)

Para que a **Entrega 3** seja considerada pronta e receba nota máxima (2,0 pontos), todos os cenários abaixo devem passar localmente e na instância AWS EC2:

- [ ] **CA-01 (Persistência e Replicação):** Reiniciar os containers `catalog-service` e `rental-service` após realizar uma locação e verificar que o status `RENTED` e o registro da locação permanecem salvos no DynamoDB.
- [ ] **CA-02 (Exclusão Mútua sob Concorrência Real):** Executar o script de concorrência com $N \ge 10$ threads simultâneas tentando alugar o mesmo jogo disponível; exatamente 1 requisição deve obter sucesso (`201 Created`) e $N-1$ devem receber rejeição imediata (`409 Conflict`).
- [ ] **CA-03 (Relógio Lógico de Lamport):** Verificar nos logs de ambos os serviços e no JSON de resposta que o contador `lamport_clock` cresce monotonicamente e reflete a relação de causalidade (*happens-before*) entre o pedido no `rental-service` e a gravação condicional no `catalog-service`.
- [ ] **CA-04 (Esquema de Nomeação e Descoberta):** Verificar que todos os recursos retornam URNs padronizados (`urn:gamerent:...`) e que o `rental-service` resolve o endereço do `catalog-service` via nome DNS interno configurável (`catalog.gamerent.internal` na AWS / `catalog-service` no Docker DNS).
- [ ] **CA-05 (Comparativo de Consistência Forte vs. Eventual):** Executar o benchmark de leitura com `consistency=strong` (`ConsistentRead=True`) e `consistency=eventual` (`ConsistentRead=False`), gerando tabela comparativa de latência e consistência para o relatório técnico.
- [ ] **CA-06 (Documentação Parcial — Entrega 3):** Gerar `docs/relatorio-entrega-3.md` (e exportar para PDF) contendo diagrama atualizado, explicação teórica e prática de coordenação, nomeação e consistência, além dos prints/logs da execução na AWS.
