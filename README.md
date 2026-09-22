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
* Catálogo: `http://localhost:8001` (Docs Swagger em `http://localhost:8001/docs`)
* Reservas: `http://localhost:8002` (Docs Swagger em `http://localhost:8002/docs`)
* Frontend: `http://localhost:8080` (Docs Swagger em `http://localhost:8080`)

---

## ☁️ Implantação na Nuvem (AWS)

* **Provedor:** Amazon Web Services (AWS)
* **Serviço de Computação:** AWS EC2 (t3.micro / Ubuntu Server)
* **Endereço Público:** `http://18.231.180.197:8001`, `http://18.231.180.197:8002` e `http://18.231.180.197:8001`

