---
name: Tarefa / Requisito (Padrão GameRent)
about: Template padrão para criação de Issues do projeto GameRent (Sistemas Distribuídos)
title: "[RF-XX] "
labels: ""
assignees: ""
---

## 📌 Contexto e Objetivo
<!-- Descreva de forma clara o que precisa ser feito e qual problema de Sistemas Distribuídos esta Issue resolve. -->


---

## 🏷️ Classificação da Tarefa
* **Entrega:** <!-- Ex: Entrega 3 (Coordenação, Nomeação e Consistência) / Entrega 4 -->
* **Épico / Bloco:** <!-- Ex: Coordenação / Nomeação / Consistência e Replicação / Tolerância a Falhas / Infra AWS / Documentação -->
* **Requisito Relacionado:** <!-- Ex: RF-01, RF-02, CA-01 (conforme Sprint.md) -->
* **Componente(s) Afetado(s):**
  - [ ] `catalog-service` (Porta 8001)
  - [ ] `rental-service` (Porta 8002)
  - [ ] `infra` / `docker-compose.yml` / AWS (EC2, DynamoDB, Route 53)
  - [ ] `scripts` (Testes automatizados / Concorrência)
  - [ ] `docs` (Relatório Técnico / Diagramas)

---

## 🛠️ Tarefas Técnicas (To-Do)
<!-- Liste os passos técnicos ou arquivos que devem ser criados/modificados -->
- [ ] Tarefa 1
- [ ] Tarefa 2
- [ ] Tarefa 3

---

## ✅ Critérios de Aceite (Definition of Done)
<!-- Condições obrigatórias para que a Issue seja considerada concluída -->
- [ ] Código implementado e testado localmente via `docker compose up --build`.
- [ ] Validado na instância AWS EC2 (`sa-east-1`) sem quebrar os serviços existentes.
- [ ] Logs estruturados e/ou testes de validação (`scripts/`) funcionando conforme esperado.
- [ ] Evidências (prints de logs, terminal ou console AWS) coletadas para o relatório técnico da entrega.

---

## 📎 Referências e Observações Adicionais
<!-- Links úteis, trechos de código, comandos de teste ou referências ao arquivo Sprint.md -->
- Consulte o arquivo [`Sprint.md`](../Sprint.md) para detalhes da arquitetura e critérios de avaliação.
