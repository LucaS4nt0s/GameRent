# GameRent — Relatório Técnico: Entrega 2
## Primeiros Módulos e Comunicação Inter-Serviços na AWS

**Disciplina:** Sistemas Distribuídos  
**Provedor de Nuvem:** Amazon Web Services (AWS)  
**Data:** Setembro / 2026  

### Integrantes do Grupo:
* **Luca Samuel** — Backend, Coordenação, Consistência & Dados
* **Kauan Simão** — Middleware, APIs, Comunicação & Integração
* **Maria Eduarda** — Front-end, Infraestrutura, Segurança & Resiliência

---

## 1. Introdução e Objetivos da Entrega 2

O presente relatório documenta as atividades e resultados práticos da **Entrega 2** do projeto **GameRent**, cujo objetivo principal foi a implementação e validação da camada de comunicação síncrona entre nós distribuídos (**Service-to-Service Communication**), bem como o provisionamento e execução inicial dos serviços em ambiente de computação em nuvem na **Amazon Web Services (AWS)**.

Nesta etapa, validou-se a capacidade de desacoplamento funcional entre o serviço responsável pelo acervo e cálculo de proximidade (`catalog-service`) e o serviço orquestrador de transações de locação (`rental-service`).

---

## 2. Arquitetura Distribuída da Entrega 2

A topologia implementada para esta entrega é composta por dois microsserviços independentes que operam em processos distintos e se comunicam através da rede via protocolo HTTP sobre arquitetura REST (com payloads serializados em JSON):

```
+-----------------------------------------------------------+
|                   Cliente / Aplicação Web                 |
+-----------------------------+-----------------------------+
                              |
                     (1) POST /rentals
                              |
                              v
+-----------------------------------------------------------+
|                   NÓ 1: RENTAL-SERVICE                    |
|                (Processo / Container: Porta 8002)         |
|                                                           |
|  - Recebe o pedido de aluguel                             |
|  - Inicia comunicação cliente-servidor interna            |
+-----------------------------+-----------------------------+
                              |
                 (2) GET /games/{id} (REST síncrono)
                              |
                              v
+-----------------------------------------------------------+
|                  NÓ 2: CATALOG-SERVICE                    |
|                (Processo / Container: Porta 8001)         |
|                                                           |
|  - Valida existência e disponibilidade do jogo            |
|  - Executa cálculo de geolocalização relativa em memória   |
|  - Retorna estado do recurso ou erro HTTP                 |
+-----------------------------------------------------------+
```

---

## 3. Especificação e Documentação da Comunicação

A comunicação entre os serviços segue contratos estritos de API RESTful.

### 3.1. Endpoints do `catalog-service` (Porta 8001)

| Método | Endpoint | Descrição | Status de Resposta |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Health check do serviço | `200 OK` |
| `GET` | `/games` | Lista todos os jogos de tabuleiro cadastrados | `200 OK` |
| `GET` | `/games/{id}` | Retorna detalhes e status do jogo especificado | `200 OK` / `404 Not Found` |
| `GET` | `/games/nearby` | Retorna jogos próximos com base em `lat`, `lon` e `max_km` | `200 OK` |
| `PATCH` | `/games/{id}/status` | Atualiza o estado (`AVAILABLE` / `RENTED`) | `200 OK` / `404 Not Found` |

### 3.2. Endpoints do `rental-service` (Porta 8002)

| Método | Endpoint | Descrição | Chamada Inter-Serviço |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Health check do serviço | Nenhuma |
| `POST` | `/rentals` | Inicia um novo aluguel | Dispara `GET /games/{id}` no `catalog-service` |
| `GET` | `/rentals/{id}`| Consulta status da reserva criada | Nenhuma |

### 3.3. Exemplo de Payload de Requisição e Resposta

**Requisição: `POST /rentals`**
```json
{
  "renter_name": "João da Silva",
  "game_id": 1,
  "rental_days": 3
}
```

**Resposta de Sucesso (`201 Created`):**
```json
{
  "rental_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "game_id": 1,
  "game_title": "Catan",
  "renter_name": "João da Silva",
  "rental_days": 3,
  "total_price": 45.0,
  "status": "CONFIRMED",
  "created_at": "2026-09-18T18:30:00Z"
}
```

---

## 4. Implantação em Nuvem (Amazon Web Services — AWS)

### 4.1. Configuração da Infraestrutura
* **Instância:** AWS EC2 (`t2.micro` / Ubuntu Server 24.04 LTS).
* **Região:** `us-east-1` (N. Virginia).
* **Segurança de Rede (Security Group):**
  * Porta `22` (SSH): Restrita ao IP dos administradores.
  * Portas `8001` e `8002`: Abertas para tráfego TCP inbound, permitindo chamadas públicas e demonstração externa.

*(Inserir Print do Console AWS mostrando a instância EC2 ativa e o Security Group)*

---

## 5. Testes Práticos e Evidências de Comunicação

### Cenário 1: Consulta de Proximidade (Geolocalização Relativa)
* **Objetivo:** Comprovar o cálculo em memória de distância sem vazamento de dados confidenciais de GPS do locador.
* **Resultado:** Requisição `GET /games/nearby?lat=-23.5505&lon=-46.6333&max_km=15` retornou itens filtrados com campo `distance_km` relativo.

*(Inserir Print da requisição no Postman / cURL)*

---

### Cenário 2: Fluxo Completo de Reserva com Comunicação S2S
* **Objetivo:** Comprovar a chamada síncrona do `rental-service` consultando o `catalog-service`.
* **Resultado:** O `rental-service` recebeu a requisição, chamou o `catalog-service`, validou que o jogo estava disponível, confirmou a reserva e retornou HTTP 201.

*(Inserir Print do Postman e Print dos logs de terminal dos dois serviços evidenciando o handshake)*

---

### Cenário 3: Validação de Conflito de Disponibilidade
* **Objetivo:** Testar tentativa de reserva de um jogo já alugado.
* **Resultado:** O `catalog-service` reportou status `RENTED`, fazendo o `rental-service` responder `409 Conflict`.

*(Inserir Print de erro 409)*

---

### Cenário 4: Tratamento de Queda de Serviço (Resiliência Básica)
* **Objetivo:** Testar o comportamento do `rental-service` quando o `catalog-service` está inacessível.
* **Resultado:** O `rental-service` tratou o timeout e retornou `503 Service Unavailable`, sem quebra do processo principal.

*(Inserir Print de simulação de queda e erro 503)*

---

## 6. Conclusão e Próximos Passos (Entrega 3)

A Entrega 2 cumpriu com sucesso todos os critérios estabelecidos pelo edital:
1. Dois serviços independentes operando e comunicando-se via REST síncrono.
2. Implantação e execução na nuvem AWS.
3. Tratamento e documentação clara dos fluxos de comunicação.

Para a **Entrega 3 (Coordenação, Nomeação e Consistência)**, o grupo integrará:
* Controle de concorrência com **Conditional Writes do Amazon DynamoDB** (exclusão mútua distribuída contra double-booking).
* Resolução de nomes dinâmica com **AWS Cloud Map / Route 53**.
* Mecanismo formal de replicação e avaliação do modelo de consistência.
