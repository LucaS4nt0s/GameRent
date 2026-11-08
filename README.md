# GameRent — Plataforma Distribuída de Aluguel de Jogos de Tabuleiro

Trabalho Prático da disciplina de **Sistemas Distribuídos**.

## 👥 Integrantes do Grupo
* **Luca Samuel** (Backend, Coordenação, Consistência & Dados)
* **Kauan Simão** (Middleware, APIs, Comunicação & Integração)
* **Maria Eduarda** (Infraestrutura, Nuvem AWS, Resiliência & Front-end)

---

## 🎯 Entrega 2: Primeiros Módulos e Comunicação

O objetivo desta entrega é demonstrar a comunicação síncrona inter-serviços (**Service-to-Service communication**) entre dois nós distribuídos, além da implantação inicial na nuvem (**AWS**).

### Arquitetura dos Serviços

1. **`catalog-service` (Porta 8001)**
   - Gerencia o catálogo de jogos de tabuleiro e locadores.
   - Implementa o cálculo em memória de distância linear relativa (protegendo as coordenadas reais dos locadores).
   - Endpoints:
     - `GET /health`: Verificação de saúde do nó.
     - `GET /games`: Listagem completa do catálogo.
     - `GET /games/{id}`: Consulta dados e disponibilidade do jogo.
     - `GET /games/nearby?lat={lat}&lon={lon}&max_km={km}`: Busca por proximidade.
     - `PATCH /games/{id}/status`: Atualização do status de disponibilidade.

2. **`rental-service` (Porta 8002)**
   - Orquestra os pedidos de aluguel solicitados pelos locatários.
   - Realiza chamada de rede síncrona (REST/RPC) para o `catalog-service` para verificar a existência e a disponibilidade do jogo antes de autorizar o aluguel.
   - Endpoints:
     - `GET /health`: Verificação de saúde do nó.
     - `POST /rentals`: Inicia um aluguel (consulta o catálogo via HTTP).
     - `GET /rentals/{id}`: Detalhes do aluguel.

---

## 🚀 Como Executar Localmente

### Pré-requisitos
* Docker e Docker Compose instalados.

### Execução via Docker Compose
```bash
# Na raiz do projeto:
docker compose up --build
```

Os serviços estarão disponíveis em:
* Catálogo — réplica 1: `http://localhost:8001` (Docs Swagger em `http://localhost:8001/docs`)
* Catálogo — réplica 2: `http://localhost:8003`
* Reservas: `http://localhost:8002` (Docs Swagger em `http://localhost:8002/docs`)
* Front-end: `http://localhost:8080`
* DynamoDB Local: `http://localhost:8000`

As duas réplicas do catálogo compartilham a mesma tabela no DynamoDB Local. Detalhes da infraestrutura
local e da IAM Role na AWS em [`infra/README.md`](infra/README.md).

### Front-end (marca Jogaí)

O site em `frontend/` (React + Vite) separa a visão do cliente da área técnica:

* **Início** (`#/`): animação da caixa guiada pela rolagem, busca por GPS do aparelho ou por cidade
  (tabela fixa em `frontend/src/data/cities.js`, convertida em lat/lon para `GET /games/nearby`) e catálogo.
* **Minha conta** (`#/conta`, `#/conta/jogos`, `#/conta/dados`): locações do usuário, anúncio de jogos
  (com link opcional de foto, campo `image_url` do catálogo) e dados da conta.
* **Área do administrador** (`#/admin`): Laboratório de Sistemas Distribuídos (disputa concorrente,
  service discovery, comparador forte × eventual e acervo com URN/Lamport/versão). Só aparece para admins.

Login, escolhido por `VITE_AUTH_PROVIDER` no build do front:

| Variável | Uso |
|---|---|
| `VITE_AUTH_PROVIDER` | `local` (padrão, login de demonstração no navegador) ou `cognito` |
| `VITE_ADMIN_EMAILS` | e-mails tratados como admin no modo local (padrão `admin@jogai.test`) |
| `VITE_COGNITO_DOMAIN` | domínio do Hosted UI do User Pool (ex.: `jogai.auth.sa-east-1.amazoncognito.com`) |
| `VITE_COGNITO_CLIENT_ID` | App client público (sem segredo), com Authorization Code + PKCE |
| `VITE_COGNITO_REDIRECT_URI` | URL de retorno cadastrada no App client (padrão: origem do site) |

No modo `cognito`, admin é quem está no grupo `admin` do User Pool. O front já envia o `id_token`
no cabeçalho `Authorization`; a validação do JWT nos serviços FastAPI ainda é um próximo passo.

Para desenvolver só o front contra outra stack: `CATALOG_TARGET=http://localhost:8011 RENTAL_TARGET=http://localhost:8012 npm run dev`.

---

## ☁️ Implantação na Nuvem (AWS)

* **Provedor:** Amazon Web Services (AWS)
* **Serviço de Computação:** AWS EC2 (t3.micro / Ubuntu Server)
* **Endereço Público:** `http://18.231.180.197:8001` e `http://18.231.180.197:8002`

