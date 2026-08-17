# CHECKPOINT — Fase 1

```text
CHECKPOINT
--------------------------------
Fase: 1 — Project Setup
Status: PASSED
Data: 2026-08-17
Branch: feat/phase-1-project-setup
Arquivos rastreados no repositório: 30
Testes unitários executados: 6
Testes unitários aprovados: 6
Testes de integração executados: 1
Testes de integração aprovados: 1
Testes falharam no gate final: 0
Cobertura: 85,37%
Containers saudáveis: 2/2
Schemas verificados: bronze, control, gold, silver
Alembic revision: 20260817_0001
Registros processados: 0 — extração inicia na Fase 2
Problemas encontrados: 4
Correções realizadas: 4
Riscos restantes: dependência do daemon Docker e credenciais locais devem ser substituídas fora de desenvolvimento
Próxima etapa: Fase 2 — Extraction
--------------------------------

STAGE_STATUS = PASSED
```

## Objetivo da etapa

Estabelecer uma fundação reproduzível para desenvolvimento e execução do GovInsight AI com
Python 3.12, PostgreSQL, migrações, configuração tipada, logging estruturado, FastAPI, testes e
Docker Compose.

## Verificações executadas

| Gate | Evidência | Resultado |
|---|---|---|
| Lint | `ruff check .` | PASS — zero erros |
| Formato | `ruff format --check .` | PASS — 19 arquivos formatados |
| Testes unitários | pytest sem integração | PASS — 6/6 |
| Cobertura | branch coverage | PASS — 85,37%, mínimo 80% |
| Teste PostgreSQL | conexão real via psycopg | PASS — 1/1 |
| Compose | `docker compose config --quiet` | PASS |
| PostgreSQL | container healthcheck | PASS — healthy |
| FastAPI | container healthcheck | PASS — healthy |
| Endpoint | `GET /health` | PASS — `ok/reachable` |
| Migração | tabela `alembic_version` | PASS — `20260817_0001` |
| Schemas | `information_schema.schemata` | PASS — quatro schemas |
| Logs da API | busca por Traceback/ERROR/CRITICAL | PASS — zero ocorrências recentes |

## Problemas encontrados e correções

### 1. Parâmetros Git sem identidade

- **Erro:** Git recusou o primeiro commit.
- **Causa:** `user.name` e `user.email` não estavam definidos.
- **Correção:** identidade fornecida por Sofia e configurada somente neste repositório.
- **Reteste:** commit criado com autor `Sofia <sofiabns06@gmail.com>`.

### 2. Sandbox e propriedade do Git

- **Erro:** bloqueio de `.git/index.lock` e aviso de propriedade duvidosa.
- **Causa:** separação entre o usuário do sandbox e o usuário do Windows.
- **Correção:** operações Git autorizadas e `safe.directory` aplicado por comando, sem modificar a
  configuração global.
- **Reteste:** commits locais criados na branch de feature.

### 3. Cliente de testes depreciado

- **Erro:** Starlette emitiu warning ao usar `httpx` no `TestClient`.
- **Causa:** Starlette 1.6 migrou o cliente suportado para `httpx2`.
- **Correção:** dependência de desenvolvimento substituída por `httpx2`.
- **Reteste:** testes da API passaram sem warnings.

### 4. Qualidade de build e código

- **Erro:** Ruff encontrou imports fora de ordem e arquivos não formatados; o primeiro build
  também avisou sobre `pip` executado como root.
- **Causa:** formatação inicial e instalação direta no Python global da imagem.
- **Correção:** Ruff aplicado; Dockerfile passou a instalar em `/opt/venv` e a produção usa wheel
  não editável.
- **Reteste:** lint/formato passaram e o novo build não emitiu o warning de root.

## Decisões mantidas

- O setup cria somente schemas; tabelas de negócio aguardam validação das entidades na Fase 2.
- A imagem roda como usuário não privilegiado.
- `.env` e dados locais permanecem fora do Git.
- A aplicação não registra a senha do PostgreSQL.
- O endpoint `/health` retorna 503 quando o banco não está alcançável.
- Testes de integração exigem uma URL explícita e possuem timeout de conexão.

## Riscos restantes

- Docker Desktop precisa estar ativo para o stack local.
- As credenciais default do Compose servem somente para desenvolvimento local.
- Não existe extração PNCP nesta fase; nenhuma afirmação de pipeline de dados foi feita.
