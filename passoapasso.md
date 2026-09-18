# Guia Passo a Passo — Entrega 2: Primeiros Módulos e Comunicação
**Projeto:** GameRent — Plataforma Distribuída de Aluguel de Jogos de Tabuleiro  
**Disciplina:** Sistemas Distribuídos  
**Provedor de Nuvem:** Amazon Web Services (AWS)  
**Integrantes:**  
- **Luca Samuel** (Backend, Lógica de Negócio e Dados)  
- **Kauan Simão** (Middleware, APIs, Comunicação e Integração)  
- **Maria Eduarda** (Infraestrutura, Nuvem AWS, Resiliência e Front-end)  

---

## 1. Visão Geral da Entrega 2

### O que diz o edital / PDF da disciplina:
* **Foco da Entrega 2:** "Primeiros Módulos e Comunicação"
* **Valor:** 1,5 pontos
* **Requisitos Obrigatórios:**
  1. **Implementação mínima de dois nós/serviços** comunicando-se via **RPC** (ex: gRPC) ou **REST** (HTTP/JSON).
  2. **Configuração inicial em nuvem (AWS)** com pelo menos um serviço rodando e acessível.
  3. **Documentação técnica da comunicação** (contratos de API, endpoints, payloads, diagrama de fluxo de comunicação).
  4. **Código-fonte em repositório Git com README** explicativo.
  5. **Relatório técnico parcial** com evidências (prints de telas, requisições, logs e console da AWS).
  6. **Demonstração prática** funcional (ao vivo ou gravada).

---

## 2. Desenho da Solução para o GameRent na Entrega 2

Para manter 100% de aderência ao planejamento entregue na Entrega 1, definimos os **dois nós/serviços** distribuídos:

```
                  +-----------------------------+
                  |  Cliente / Postman / cURL   |
                  +--------------+--------------+
                                 |
                          (1) POST /rentals
                                 |
                                 v
        +------------------------------------------------+
        |             Nó 1: RENTAL-SERVICE               |
        |          (Serviço de Locações/Reservas)        |
        +------------------------+-----------------------+
                                 |
                     (2) Chamada RPC/REST interna:
                         GET /games/{game_id}
                                 |
                                 v
        +------------------------------------------------+
        |            Nó 2: CATALOG-SERVICE               |
        |       (Serviço de Catálogo e Geolocalização)   |
        +------------------------------------------------+
```

### Detalhamento dos 2 Nós/Serviços:

1. **Nó 1: `catalog-service` (Serviço de Catálogo & Geolocalização Relativa)**
   * **Papel:** Gerencia os jogos de tabuleiro disponíveis, dados dos locadores e implementa o cálculo em memória de distância linear (geolocalização relativa), preservando a privacidade das coordenadas reais dos locadores (conforme definido na Entrega 1).
   * **Porta padrão:** `8001`
   * **Endpoints principais:**
     * `GET /health` — Verificação de integridade (Health Check).
     * `GET /games` — Listagem geral do catálogo.
     * `GET /games/{id}` — Busca dados e status de disponibilidade de um jogo específico (consumido pelo `rental-service`).
     * `GET /games/nearby?lat=...&lon=...&max_km=...` — Filtro de jogos por proximidade geográfica calculada em memória.

2. **Nó 2: `rental-service` (Serviço de Reservas & Locação)**
   * **Papel:** Gerencia solicitações de aluguel feitas pelos locatários. Ao receber um pedido de aluguel, ele **não processa às cegas**: ele realiza uma **chamada de rede síncrona (REST/RPC)** para o `catalog-service` para verificar se o jogo existe e se está livre. Se validado, processa a reserva e retorna confirmação.
   * **Porta padrão:** `8002`
   * **Endpoints principais:**
     * `GET /health` — Health Check.
     * `POST /rentals` — Criação de pedido de reserva (dispara chamada interna para o `catalog-service`).
     * `GET /rentals/{id}` — Consulta de status de uma reserva.

> **Por que essa escolha é ideal?**  
> Porque comprova comunicação distribuída inter-serviços (**Service-to-Service / S2S communication**). O `rental-service` age como **servidor** para o cliente final e como **cliente HTTP/RPC** para o `catalog-service`.

---

## 3. Estrutura Recomendada do Repositório Git

Organize os arquivos do projeto da seguinte forma:

```text
GameRent/
├── .gitignore
├── README.md                          # Instruções completas de execução local e na AWS
├── docker-compose.yml                 # Orquestração local dos serviços
├── passoapasso.md                     # Este roteiro de execução
│
├── docs/                              # Documentações e relatórios da disciplina
│   ├── relatorio-entrega-1.pdf
│   ├── relatorio-entrega-2.md         # Rascunho/versão final do relatório técnico da Entrega 2
│   ├── relatorio-entrega-2.pdf
│   └── diagrams/                      # Diagramas arquiteturais e de sequência
│       ├── arquitetura_entrega2.png
│       └── fluxo_comunicacao_s2s.png
│
├── services/                          # Código-fonte dos microsserviços
│   ├── catalog-service/               # Serviço de Catálogo e Geolocalização
│   │   ├── Dockerfile
│   │   ├── requirements.txt           # (ou package.json se Node.js)
│   │   ├── src/
│   │   │   ├── app.py                 # Inicialização da API REST (ex: FastAPI/Flask)
│   │   │   ├── models.py              # Modelos de dados do jogo
│   │   │   └── geo_utils.py           # Cálculo em memória de distância relativa
│   │   └── tests/
│   │       └── test_catalog.py
│   │
│   └── rental-service/                # Serviço de Locação / Reservas
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── src/
│       │   ├── app.py                 # API REST de Reservas
│       │   ├── models.py              # Modelos de dados de reservas
│       │   └── catalog_client.py      # Módulo cliente que faz chamadas REST/RPC para o catalog-service
│       └── tests/
│           └── test_rental.py
│
├── scripts/                           # Scripts utilitários e de teste
│   ├── seed_data.py                   # Script para popular dados de teste
│   └── test_communication.py          # Script automatizado que dispara requisições e valida a comunicação
│
└── infra/                             # Scripts de infraestrutura e deploy AWS
    ├── user_data_ec2.sh               # Script de inicialização automática na EC2 (User Data)
    └── nginx.conf                     # (Opcional) Proxy reverso se utilizado
```

---

## 4. Passo a Passo Prático de Execução

### Passo 1: Inicializar o Repositório Git
1. No terminal do diretório `C:\GameRent`:
   ```bash
   git init
   ```
2. Crie o arquivo `.gitignore` ignorando arquivos temporários (`venv/`, `__pycache__/`, `.env`, `.DS_Store`).
3. Faça o commit inicial da estrutura de pastas.

---

### Passo 2: Implementar o `catalog-service` (Nó 1)
* **Tecnologia sugerida:** Python (FastAPI + Uvicorn) ou Node.js (Express/NestJS).  
  *(Recomendamos **FastAPI (Python)** pela rapidez, geração automática de documentação Swagger/OpenAPI e tipagem rigorosa).*
* **Funcionalidades a implementar:**
  1. Modelo de dados em memória (lista/dicionário) para os jogos de tabuleiro:
     * `id`, `title`, `description`, `price_per_day`, `status` (`"AVAILABLE"` ou `"RENTED"`), `owner_id`, `latitude`, `longitude`.
  2. Função de cálculo da distância euclidiana/haversine em `geo_utils.py` (calcula a distância em KM entre o cliente e o jogo sem retornar o GPS do dono).
  3. Endpoint `GET /games/{id}`:
     * Se o jogo existir, retorna HTTP 200 com os dados e status.
     * Se não existir, retorna HTTP 404.
  4. Endpoint `GET /games/nearby`:
     * Recebe `lat`, `lon` e `radius_km`.
     * Retorna os jogos com o campo calculado `distance_km`, ocultando coordenadas reais.
  5. Endpoint `PATCH /games/{id}/status`:
     * Permite alterar status para `"RENTED"` ou `"AVAILABLE"`.

---

### Passo 3: Implementar o `rental-service` (Nó 2)
* **Funcionalidades a implementar:**
  1. Módulo `catalog_client.py`:
     * Configurado via variável de ambiente: `CATALOG_SERVICE_URL` (ex: `http://localhost:8001` ou `http://catalog-service:8001` no Docker ou IP público da AWS).
     * Função `check_game_availability(game_id)` que faz um `requests.get` (ou `httpx.get`) para `{CATALOG_SERVICE_URL}/games/{game_id}` com timeout configurado.
  2. Endpoint `POST /rentals`:
     * Recebe: `{ "renter_name": "...", "game_id": 1, "days": 3 }`.
     * O `rental-service` consulta o `catalog-service`.
     * **Cenário A (Sucesso):** O jogo existe e está `AVAILABLE`. O `rental-service` gera um registro de aluguel com ID único (UUID), calcula o valor total, atualiza o status no catálogo para `RENTED` e devolve HTTP 201 Created com os dados da reserva.
     * **Cenário B (Indisponível):** O jogo já está alugado. Retorna HTTP 409 Conflict: `"Jogo indisponível para locação"`.
     * **Cenário C (Inexistente):** O jogo não existe no catálogo. Retorna HTTP 404 Not Found.
     * **Cenário D (Falha de comunicação/rede):** O catálogo está fora do ar (timeout). Retorna HTTP 503 Service Unavailable: `"Falha ao comunicar com o catálogo de jogos"`.

---

### Passo 4: Containerizar com Docker e Testar Localmente
1. Crie um `Dockerfile` enxuto e reprodutível para cada serviço.
2. Crie o arquivo `docker-compose.yml` que sobe ambos os serviços conectados em uma mesma rede virtual (`gamerent-net`):
   * O `rental-service` aponta para `http://catalog-service:8001` via resolução de nomes interna do Docker DNS.
3. Teste a execução local:
   ```bash
   docker compose up --build
   ```
4. Execute requisições via cURL ou Postman para comprovar a comunicação ponta a ponta.

---

### Passo 5: Implantação na Nuvem (AWS)
O edital exige: *"Configuração inicial em nuvem (AWS) com pelo menos um serviço rodando."*

#### Opção Recomendada: Instância AWS EC2 (Free Tier)
1. **Criar Instância EC2:**
   * Tipo: `t2.micro` ou `t3.micro` (dentro do nível gratuito).
   * Sistema Operacional: **Ubuntu Server 24.04 LTS** ou **Amazon Linux 2023**.
   * Par de chaves: Gerar chave `.pem` para acesso SSH.
2. **Configurar Security Group (Firewall):**
   * Porta 22 (SSH) — Acesso administrativo.
   * Porta 80 / 8080 — HTTP público.
   * Porta 8001 e/ou 8002 — Portas dos microsserviços.
3. **Instalação do Ambiente na EC2:**
   * Conectar via SSH: `ssh -i sua-chave.pem ubuntu@ec2-ip-publico.compute-1.amazonaws.com`
   * Instalar Git e Docker / Docker Compose:
     ```bash
     sudo apt update && sudo apt install -y docker.io docker-compose git
     sudo systemctl start docker
     sudo usermod -aG docker ubuntu
     ```
4. **Deploy dos Serviços na EC2:**
   * Clonar o repositório Git na EC2.
   * Rodar `docker compose up -d`.
   * **Validação:** Acessar via navegador ou cURL no IP público:
     * `http://<IP-PUBLICO-AWS>:8001/health`
     * `http://<IP-PUBLICO-AWS>:8002/health`
     * Fazer requisição de aluguel em `http://<IP-PUBLICO-AWS>:8002/rentals`.

> **Variação Híbrida (Demonstração Distribuída máxima):**  
> Você pode rodar o `catalog-service` na nuvem AWS e rodar o `rental-service` na máquina local apontando para o IP público da AWS! Isso demonstra explicitamente nós distribuídos geograficamente pela internet comunicando-se via REST/RPC.

---

### Passo 6: Coleta de Evidências e Testes de Comunicação
Tire prints de alta qualidade para o relatório:
1. **Print do Console da AWS:** Mostrando a instância EC2 em estado *Running* com IP público.
2. **Print dos Logs de Execução:** Mostrando no terminal da EC2 a chegada da requisição no `rental-service` e a chamada subsequente no `catalog-service`.
3. **Prints do Postman / cURL:**
   * Teste 1: Listagem de jogos e cálculo de distância relativa (`GET /games/nearby`).
   * Teste 2: Criação de aluguel com sucesso (`POST /rentals`) -> HTTP 201.
   * Teste 3: Tentativa de alugar o mesmo jogo novamente -> HTTP 409 (validando consistência básica).
   * Teste 4: Tentativa de aluguel quando o `catalog-service` é desligado temporariamente -> HTTP 503 (demonstrando tratamento de falhas de comunicação).

---

### Passo 7: Elaboração do Relatório Técnico da Entrega 2
O relatório deve seguir o padrão acadêmico e conter:
1. **Identificação e Introdução:** Contextualização do projeto GameRent e objetivo da Entrega 2.
2. **Arquitetura da Entrega 2:** Diagrama da comunicação entre os dois nós e o cliente.
3. **Especificação da Comunicação (REST/RPC):**
   * Tabela com método HTTP, rota, parâmetros, payload de entrada e respostas de saída.
   * Explicação dos cabeçalhos, códigos de status e formatos de serialização (JSON).
4. **Implantação na Nuvem (AWS):**
   * Detalhamento da infraestrutura provisionada (EC2, VPC, Security Group, IP elástico/público).
5. **Testes e Resultados:** Prints comentados de cada cenário de teste com logs.
6. **Autoavaliação e Próximos Passos:** Conexão com os requisitos da Entrega 3 (Coordenação, Exclusão Mútua com DynamoDB e Replicação).

---

### Passo 8: Preparação da Demonstração Prática
Prepare um roteiro curto (3 a 5 minutos) caso seja ao vivo ou gravação em vídeo:
1. Apresentação rápida da arquitetura (30s).
2. Mostrar a AWS EC2 rodando no console da AWS (30s).
3. Mostrar os logs ao vivo (`docker compose logs -f`) (1 min).
4. Disparar as requisições no Postman demonstrando o fluxo completo de reserva (1.5 min).
5. Conclusão pontuando o atendimento de todos os requisitos (30s).

---

## 5. Divisão de Tarefas entre os Integrantes (Entrega 2)

| Integrante | Atribuições na Entrega 2 |
| :--- | :--- |
| **Luca Samuel** | Implementar as regras de negócio dos serviços, modelos de dados, cálculo de geolocalização relativa em memória e tratamento dos cenários de validação de reserva. |
| **Kauan Simão** | Desenhar os contratos de API (OpenAPI/Swagger), implementar o cliente HTTP de comunicação inter-serviços (`catalog_client.py`), testes de integração com Postman/cURL e documentação detalhada da comunicação. |
| **Maria Eduarda** | Criar os `Dockerfiles` e `docker-compose.yml`, provisionar a instância na AWS (EC2/Security Groups), configurar ambiente em nuvem, realizar o deploy e redigir a seção de infraestrutura do relatório. |

---

## 6. Checklist Final Pré-Submissão

- [ ] Código-fonte versionado em repositório Git com histórico de commits.
- [ ] `README.md` claro com instruções de execução local e endereço/IP da nuvem.
- [ ] Dois serviços distintos implementados e comunicando-se via REST ou RPC.
- [ ] Pelo menos um serviço rodando e acessível na AWS.
- [ ] Diagrama de comunicação entre os serviços gerado e inserido no relatório.
- [ ] Documentação dos endpoints, contratos de payload e status HTTP.
- [ ] Prints de evidências (AWS Console, requisições Postman, logs de comunicação).
- [ ] Relatório técnico exportado em PDF formatado conforme as normas da disciplina.
- [ ] Roteiro de demonstração prática ensaiado ou gravado.
