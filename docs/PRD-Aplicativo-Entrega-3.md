# PRD (Product Requirements Document) — Aplicativo GameRent & Entrega 3

**Produto:** GameRent — Plataforma Distribuída de Aluguel de Jogos de Tabuleiro (Estilo iFood/Airbnb)  
**Foco:** Funcionalidades do Aplicativo (Produto) + Integração Prática dos Requisitos da Entrega 3 (Coordenação, Nomeação e Consistência)  
**Provedor de Nuvem:** AWS (`sa-east-1`)  
**Equipe:**
* **Luca Samuel** — Backend, Coordenação, Consistência & Dados
* **Kauan Simão** — Middleware, APIs, Comunicação & Integração
* **Maria Eduarda** — Front-end, Infraestrutura, Nomeação & Nuvem AWS

---

## 1. Contexto: Por que este PRD existe?

O edital do **Trabalho Prático – Sistemas Distribuídos** define os requisitos acadêmicos da **Entrega 3** (*Coordenação, Nomeação e Consistência/Replicação*), mas é genérico quanto ao domínio do aplicativo. Já os relatórios das **Entregas 1 e 2** definem a visão de produto do **GameRent** (conectar **Locadores** donos de jogos de tabuleiro e **Locatários** buscando jogos próximos com privacidade de GPS e sem risco de *double-booking*), porém o código atual possui apenas **endpoints básicos com 5 jogos fixos em memória** e **nenhuma interface de usuário (Front-end)** ou fluxo completo do locador/locatário.

Este PRD especifica **todas as funcionalidades de negócio do aplicativo GameRent** que precisam ser construídas ou evoluídas para que o sistema funcione como um **produto completo** e, ao mesmo tempo, **demonstre na prática todas as técnicas exigidas na Entrega 3**.

---

## 2. Visão Geral das Personas e Jornadas no Aplicativo

```
+-----------------------------------------------------------------------------------+
|                        APLICATIVO GAMERENT (Web UI - Porta 8080)                  |
|                                                                                   |
|  [Aba 1: Visão Locatário]     [Aba 2: Visão Locador]    [Aba 3: Lab Distribuído]  |
|  - Busca por GPS (Raio km)    - Cadastrar Novo Jogo     - Simular Concorrência    |
|  - Filtro Categoria/Status    - Gerenciar Meu Acervo      (10 cliques simultâneos)|
|  - Alugar Jogo (Reserva)      - Ver Jogos Alugados      - Comparar Consistência   |
|  - Meus Aluguéis / Devolver   - Colocar em Manutenção     (Forte vs. Eventual)    |
|                                                         - Mapa de Nós, URNs e     |
|                                                           Relógio de Lamport      |
+-----------------------------------------+-----------------------------------------+
                                          |
                 +------------------------+------------------------+
                 |                                                 |
                 v                                                 v
+----------------------------------------+       +----------------------------------+
|     CATALOG-SERVICE (Porta 8001)       |       |    RENTAL-SERVICE (Porta 8002)   |
|     (2 Réplicas + Cálculo Geo)         |<------|   (Orquestrador de Locações)     |
+-------------------+--------------------+  S2S  +-----------------+----------------+
                    |                                              |
                    +----------------------+-----------------------+
                                           |
                                           v
                    +----------------------------------------------+
                    |   AMAZON DYNAMODB (Persistência & Multi-AZ)  |
                    |   - Tabela: gamerent_games                   |
                    |   - Tabela: gamerent_rentals                 |
                    +----------------------------------------------+
```

---

## 3. O Que Falta no Aplicativo Hoje vs. O Que Será Construído

| Módulo do App | Como está hoje (Pós-Entrega 2) | O que falta de Funcionalidade do Aplicativo | Como se conecta com a Entrega 3 |
| :--- | :--- | :--- | :--- |
| **Jornada do Locador (Dono do Jogo)** | Inexistente. Os 5 jogos estão fixos (*hardcoded*) num dicionário Python `GAMES_DB`. | Permitir **Cadastrar novo jogo** (`POST /games`), **Listar jogos de um locador** e **Alterar status/manutenção**. | Cada jogo cadastrado ganha um **URN único** (`urn:gamerent:game:sa-east-1:{id}`), relógio lógico inicial e é replicado no **DynamoDB**. |
| **Jornada do Locatário (Busca e Aluguel)** | Busca básica e aluguel em duas chamadas separadas (`GET` depois `PATCH`) sem atomicidade. | **Busca geográfica com filtros**, **Reserva Atômica**, **Listagem de "Meus Aluguéis"** (`renter_email`) e **Devolução com liberação imediata**. | A reserva usa **Exclusão Mútua (Conditional Write)** no banco; a busca permite escolher **Consistência Forte ou Eventual**. |
| **Interface Web (Front-end)** | Citada no `README.md` (porta `8080`) e na Entrega 1, mas **não existe no projeto**. | Criar o **Web App GameRent** (`services/frontend`) com as telas de Locatário, Locador e Painel de Telemetria Distribuída. | Permite demonstrar ao vivo na apresentação tanto o uso real do app quanto os testes de concorrência, Lamport, DNS e consistência. |
| **Persistência de Dados** | Dicionários em memória (`GAMES_DB` e `RENTALS_DB`). Se reiniciar o container, perde tudo. | Banco de dados persistente com *seed* inicial automático dos 5 jogos clássicos + suporte a novos cadastros e locações. | **Replicação de Dados** no Amazon DynamoDB (Multi-AZ na AWS e `dynamodb-local` no Docker). |

---

## 4. Requisitos Funcionais do Aplicativo (Backlog de Produto + Técnicas SD)

### Módulo A: Funcionalidades do Catálogo e Jornada do Locador (`catalog-service`)

#### **FA-01: Cadastro de Novo Jogo de Tabuleiro pelo Locador (`POST /games`)**
* **Descrição de Negócio:** Como locador (proprietário de jogos), quero cadastrar um jogo de tabuleiro informando título, descrição, categoria, preço por dia, meus dados (`owner_id`, `owner_name`) e minha localização (`latitude`, `longitude`).
* **Regras de Negócio & Sistemas Distribuídos:**
  * As coordenadas exatas (`latitude` e `longitude`) são salvas no banco de dados (`gamerent_games`), mas **nunca** são retornadas nos payloads públicos de listagem/consulta (Privacidade de Geolocalização Relativa).
  * O sistema gera automaticamente o identificador padronizado de **Nomeação (Entrega 3)**: `urn:gamerent:game:sa-east-1:{id}` e `owner_urn: urn:gamerent:owner:{owner_id}`.
  * O registro nasce com `status = "AVAILABLE"`, `version = 1` e `lamport_clock` sincronizado.

#### **FA-02: Busca Geográfica Inteligente e Listagem do Catálogo (`GET /games` e `GET /games/nearby`)**
* **Descrição de Negócio:** Como locatário, quero buscar jogos disponíveis próximos à minha localização (informando meu `lat`, `lon` e raio `max_km`), podendo filtrar por categoria ou disponibilidade, vendo apenas a distância relativa em km (ex: `1.4 km`).
* **Integração com Consistência (Entrega 3):**
  * Ambos os endpoints (`GET /games`, `GET /games/nearby` e `GET /games/{id}`) devem aceitar o parâmetro opcional `consistency=strong|eventual` (padrão: `strong`).
  * Se `consistency=strong`, a leitura no DynamoDB usa `ConsistentRead=True` (lê da réplica líder atualizada).
  * Se `consistency=eventual`, a leitura usa `ConsistentRead=False` (lê de qualquer réplica, menor latência).
  * A resposta inclui metadados técnicos: `consistency_mode`, `db_read_latency_ms`, `lamport_clock`, `version` e `served_by_node` (URN da réplica que respondeu).

#### **FA-03: Reserva e Liberação Atômica de Jogo (`POST /games/{id}/reserve` e `POST /games/{id}/release`)**
* **Descrição de Negócio:** Quando um locatário confirma um aluguel ou devolve um jogo, o catálogo deve bloquear ou liberar o exemplar físico de forma imediata e segura.
* **Integração com Coordenação / Exclusão Mútua (Entrega 3):**
  * Substitui o antigo fluxo inseguro (`GET` seguido de `PATCH`) por uma operação atômica única no `catalog-service`.
  * Executa `UpdateItem` no DynamoDB com `ConditionExpression: #status = :available`.
  * Se dois usuários tentarem alugar o mesmo jogo no mesmo milissegundo, apenas 1 passa pela trava condicional do DynamoDB (status vira `RENTED`, grava `current_rental_id`, incrementa `version` e `lamport_clock`); o segundo recebe `ConditionalCheckFailedException`, convertido imediatamente para **`HTTP 409 Conflict`**.
  * Na devolução (`POST /games/{id}/release`), valida se está `RENTED`, limpa `current_rental_id` e volta para `AVAILABLE`.

#### **FA-04: Gestão de Status pelo Locador (`PATCH /games/{id}/status`)**
* **Descrição de Negócio:** O locador pode colocar seu próprio jogo em `MAINTENANCE` (indisponível temporariamente) ou reativá-lo para `AVAILABLE`, desde que o jogo não esteja atualmente alugado (`RENTED`).

---

### Módulo B: Funcionalidades de Locação e Jornada do Locatário (`rental-service`)

#### **FB-01: Criação de Aluguel com Coordenação e Relógio de Lamport (`POST /rentals`)**
* **Descrição de Negócio:** Como locatário, quero alugar um jogo disponível informando meu nome, e-mail, `game_id` e quantidade de dias (`rental_days`), recebendo o valor total calculado (`price_per_day * rental_days`) e o comprovante da reserva.
* **Integração com Coordenação e Nomeação (Entrega 3):**
  1. O `rental-service` incrementa seu **Relógio Lógico de Lamport** local ($L = L + 1$).
  2. Resolve o endereço do serviço de catálogo via módulo de **Nomeação/Service Discovery** (`catalog.gamerent.internal` no Route 53/Cloud Map ou DNS Docker).
  3. Chama atomicamente `POST /games/{game_id}/reserve` enviando o header `X-Lamport-Clock`.
  4. Atualiza seu relógio com o retorno do catálogo ($L = \max(L_{local}, L_{msg}) + 1$).
  5. Gera o URN da reserva (`urn:gamerent:rental:{rental_id}`), calcula o preço total com base nos dados retornados na reserva atômica e salva na tabela `gamerent_rentals` do DynamoDB.

#### **FB-02: Painel "Meus Aluguéis" e Histórico de Locações (`GET /rentals`)**
* **Descrição de Negócio:**
  * Como **locatário**, quero filtrar minhas locações ativas e passadas (`GET /rentals?renter_email=...`).
  * Como **locador**, quero ver as locações feitas para os meus jogos (`GET /rentals?game_id=...`).
* **Persistência:** Os dados vêm diretamente da tabela `gamerent_rentals` no DynamoDB, sobrevivendo a reinicializações dos containers.

#### **FB-03: Devolução de Jogo Alugado (`POST /rentals/{rental_id}/return`)**
* **Descrição de Negócio:** Como locatário (ou locador confirmando recebimento), quero encerrar uma locação ativa.
* **Fluxo Distribuído:**
  * O `rental-service` incrementa o Relógio de Lamport, chama `POST /games/{game_id}/release` no `catalog-service`, atualiza o status do aluguel para `COMPLETED` com timestamp `returned_at` no DynamoDB e retorna o recibo atualizado.

---

### Módulo C: Observabilidade de Sistemas Distribuídos (Endpoints Técnicos para Entrega 3)

#### **FC-01: Endpoint de Descoberta e Identidade do Nó (`GET /discovery` e `GET /health`)**
* **Descrição:** Presente em ambos os microsserviços (`catalog-service` e `rental-service`).
* **O que retorna:**
  * `node_urn`: ex. `urn:gamerent:node:catalog-service:replica-1`
  * `service_dns`: nome simbólico configurado (`catalog.gamerent.internal`) e IP privado resolvido via DNS (`socket.getaddrinfo`).
  * `current_lamport_clock`: valor atual do contador lógico do nó.
  * `storage_backend`: status da conexão com o DynamoDB (`sa-east-1` ou `dynamodb-local`) e contagem de itens.

---

### Módulo D: Aplicativo Web / Front-end (`services/frontend` — Porta `8080`)

Para que o aplicativo seja visual, navegável pela banca avaliadora e cumpra o papel de Front-end previsto na Entrega 1 e no `README.md`, será construída uma interface web limpa e responsiva (HTML/CSS/JS moderno servido em container na porta `8080`) dividida em **3 visões**:

1. **Visão do Locatário (Explorar & Alugar):**
   * Barra de busca por localização (com botões rápidos de bairros de SP: *Centro, Paulista, Itaim Bibi, Pinheiros* ou coordenadas livres + slider de raio em km).
   * Seletor de **Modo de Consistência de Leitura** (`Forte` vs. `Eventual`) mostrando em tempo real a latência da busca (`ms`).
   * Cards dos jogos mostrando: Título, Categoria, Dono, **Distância em km (sem expor lat/lon)**, Preço/dia, Badge de Status (`AVAILABLE`, `RENTED`, `MAINTENANCE`), URN do recurso e botão **"Alugar Agora"**.
   * Seção **"Minhas Locações"** com botão **"Devolver Jogo"** para liberar o exemplar.
2. **Visão do Locador (Cadastrar & Gerenciar Acervo):**
   * Formulário **"Cadastrar Novo Jogo de Tabuleiro"** (Título, Categoria, Preço/dia, Nome do Locador, Latitude/Longitude oculta) que envia `POST /games`.
   * Lista dos jogos cadastrados com botão para alternar status (`AVAILABLE` $\leftrightarrow$ `MAINTENANCE`).
3. **Laboratório de Sistemas Distribuídos (Painel Especial Entrega 3):**
   * **Simulador de Concorrência (Teste de Exclusão Mútua ao Vivo):** Botão *"Disparar 10 Reservas Simultâneas no Jogo #1"* que executa `Promise.all` contra `POST /rentals` e exibe na tela o placar: **1 Sucesso (`201 Created`)** e **9 Bloqueios (`409 Conflict`)**, comprovando visualmente o bloqueio de *double-booking*.
   * **Monitor do Relógio Lógico de Lamport & URNs:** Exibe os logs das últimas transações mostrando a evolução causal do contador `[LAMPORT=1] -> [LAMPORT=2] -> [LAMPORT=3]` e qual réplica do serviço atendeu cada chamada.
   * **Benchmark Consistência Forte vs. Eventual:** Botão que executa leituras comparativas e exibe na tela a média de latência de cada modelo.

---

## 5. Modelo de Dados Distribuído (Amazon DynamoDB)

### 5.1. Tabela `gamerent_games` (Catálogo de Jogos)
* **Partition Key:** `id` (`Number`)
* **Atributos:**
  * `urn` (`String`) — ex: `urn:gamerent:game:sa-east-1:0001`
  * `title` (`String`), `description` (`String`), `category` (`String`)
  * `price_per_day` (`Decimal`)
  * `status` (`String`) — `AVAILABLE` | `RENTED` | `MAINTENANCE`
  * `owner_id` (`String`), `owner_urn` (`String`), `owner_name` (`String`)
  * `latitude` (`Decimal`), `longitude` (`Decimal`) *(Privados — nunca expostos na API pública)*
  * `current_rental_id` (`String` | `Null`)
  * `version` (`Number`) — contador incremental de versão do item
  * `lamport_clock` (`Number`) — timestamp lógico da última mutação
  * `updated_at` (`String` ISO-8601 UTC)

### 5.2. Tabela `gamerent_rentals` (Transações de Locação)
* **Partition Key:** `rental_id` (`String` UUID v4)
* **Atributos:**
  * `urn` (`String`) — ex: `urn:gamerent:rental:9b1deb4d-...`
  * `game_id` (`Number`), `game_urn` (`String`), `game_title` (`String`)
  * `renter_name` (`String`), `renter_email` (`String`)
  * `rental_days` (`Number`), `daily_rate` (`Decimal`), `total_price` (`Decimal`)
  * `status` (`String`) — `CONFIRMED` | `COMPLETED` | `CANCELLED`
  * `lamport_clock` (`Number`) — timestamp lógico coordenado na criação/finalização
  * `created_at` (`String` ISO-8601 UTC), `returned_at` (`String` | `Null`)

---

## 6. Matriz de Rastreabilidade: Funcionalidades do App x Rubrica da Entrega 3

| Requisito do Trabalho Prático (Entrega 3) | Funcionalidade do Aplicativo GameRent onde é aplicado | Arquivos / Componentes no Projeto |
| :--- | :--- | :--- |
| **4.1 Sincronização com Relógios Lógicos/Físicos** | Propagação do header `X-Lamport-Clock` em toda busca, cadastro, reserva e devolução entre Front-end $\rightarrow$ `rental-service` $\rightarrow$ `catalog-service`, gravado junto ao registro no banco. | `common/lamport.py` (ou `lamport_clock.py`), `app.py` (ambos serviços), `catalog_client.py` |
| **4.2 Algoritmo de Exclusão Mútua** | Reserva atômica de jogo de tabuleiro (`POST /games/{id}/reserve`) usando *DynamoDB Conditional Writes* (`#status = :available`), impedindo que 2 locatários aluguem o mesmo jogo simultaneamente. | `services/catalog-service/src/database.py`, `services/catalog-service/src/app.py` |
| **5.1 Esquema de Nomeação e Identificadores** | URNs padronizadas em todos os jogos (`urn:gamerent:game:...`), aluguéis (`urn:gamerent:rental:...`), locadores (`urn:gamerent:owner:...`) e réplicas de nós (`urn:gamerent:node:...`), além de resolução DNS via Route 53 / Cloud Map (`catalog.gamerent.internal`). | `naming.py`, `models.py`, `GET /discovery`, `infra/` |
| **6.1 Implementação de Replicação de Dados** | Persistência das tabelas `gamerent_games` e `gamerent_rentals` no Amazon DynamoDB (replicação Multi-AZ em 3 zonas na AWS `sa-east-1`) + execução de **2 réplicas do `catalog-service`** compartilhando o mesmo estado. | `database.py`, `docker-compose.yml` |
| **6.2 Teste de Diferentes Modelos de Consistência** | Seletor `consistency=strong|eventual` na busca de jogos do catálogo (`ConsistentRead=True` vs `False`), exibindo latência (`db_read_latency_ms`) e versão no App e no script de benchmark. | `services/catalog-service/src/app.py`, `scripts/test_entrega3.py`, Front-end |

---

## 7. Roteiro de Implementação Passo a Passo (Checklist de Execução)

### Fase 1: Camada de Dados, Nomeação e Relógio Lógico (Base Distribuída)
- [ ] **1.1.** Criar módulo de Relógio Lógico de Lamport (`lamport_clock.py`) e módulo de Nomeação/URNs + Resolução DNS (`naming.py`) nos dois serviços.
- [ ] **1.2.** Criar camada de persistência DynamoDB (`database.py`) no `catalog-service` e no `rental-service` com criação automática das tabelas `gamerent_games` e `gamerent_rentals` e *seed* inicial dos 5 jogos.
- [ ] **1.3.** Adicionar `boto3` aos `requirements.txt` de ambos os serviços.

### Fase 2: Funcionalidades do Aplicativo nos Microsserviços (Backend)
- [ ] **2.1. No `catalog-service`:**
  - Implementar `POST /games` (cadastro de novo jogo pelo locador com geração de URN).
  - Atualizar `GET /games`, `GET /games/nearby` e `GET /games/{id}` com suporte a `consistency=strong|eventual` (`ConsistentRead`) e medição de latência.
  - Implementar `POST /games/{id}/reserve` (Exclusão Mútua com *Conditional Write*) e `POST /games/{id}/release` (Devolução atômica).
  - Implementar `GET /discovery` e atualizar `GET /health` com identidade da réplica e relógio lógico.
- [ ] **2.2. No `rental-service`:**
  - Atualizar `catalog_client.py` para enviar/receber `X-Lamport-Clock`, resolver DNS do catálogo e chamar os endpoints atômicos `/reserve` e `/release`.
  - Atualizar `POST /rentals`, `GET /rentals` (com filtros `renter_email` e `game_id`), `GET /rentals/{id}` e `POST /rentals/{id}/return` persistindo tudo em `gamerent_rentals` no DynamoDB.
  - Implementar `GET /discovery` e atualizar `GET /health`.

### Fase 3: Aplicativo Web Front-end & Orquestração Multi-Réplica
- [ ] **3.1.** Criar `services/frontend/` (Interface Web completa na porta `8080`) com as 3 abas: **Locatário**, **Locador** e **Laboratório Distribuído (Entrega 3)**.
- [ ] **3.2.** Atualizar `docker-compose.yml` incluindo:
  - `dynamodb-local` (porta `8000`) para persistência local imediata;
  - `catalog-service` (com suporte a múltiplas réplicas / identificação de instância);
  - `rental-service`;
  - `frontend` (porta `8080`).

### Fase 4: Testes Automatizados de Concorrência, Consistência e Relatório
- [ ] **4.1.** Criar `scripts/test_entrega3.py` testando:
  1. Cadastro de jogo pelo locador e verificação de URN + persistência;
  2. Disputa concorrente com 10 threads simultâneas tentando alugar o mesmo jogo (1 `201 Created`, 9 `409 Conflict`);
  3. Verificação da sequência monotônica do Relógio de Lamport;
  4. Benchmark de 20 leituras com `consistency=strong` vs. 20 leituras com `consistency=eventual`;
  5. Devolução do jogo e nova locação.
- [ ] **4.2.** Consolidar resultados e evidências em `docs/relatorio-entrega-3.md`.
