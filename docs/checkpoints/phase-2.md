# CHECKPOINT — Fase 2

```text
CHECKPOINT
--------------------------------
Fase: 2 — Extraction
Status: PASSED
Data: 2026-08-17
Branch: feat/phase-2-pncp-extraction
Arquivos criados: 15
Arquivos alterados: 5
Testes unitários executados: 62
Testes unitários aprovados: 62
Testes de integração executados: 2
Testes de integração aprovados: 2
Testes falharam no gate final: 0
Cobertura: 90,98%
Registros retornados no gate PNCP: 10
Registros persistidos: 0 — persistência RAW inicia na Fase 3
Problemas encontrados: 3
Correções realizadas: 3
Riscos restantes: dependência da disponibilidade e do contrato externo do PNCP; não há quota oficial publicada
Próxima etapa: Fase 3 — RAW Layer
--------------------------------

STAGE_STATUS = PASSED
```

## Objetivo da etapa

Implementar a fronteira de extração do PNCP com parâmetros validados, paginação determinística,
timeout, retries limitados, backoff exponencial, suporte a `Retry-After`, logging seguro e erros
de domínio. A etapa retorna dados em memória e não antecipa a persistência Bronze.

## Verificações executadas

| Gate | Evidência | Resultado |
|---|---|---|
| Lint | `ruff check .` | PASS — zero erros |
| Formato | `ruff format --check .` | PASS — 33 arquivos formatados |
| Testes unitários | pytest sem integração | PASS — 62/62 |
| Cobertura | branch coverage | PASS — 90,98%, mínimo 80% |
| PNCP ao vivo | publicação, 01/08/2025, modalidade 6, página de 10 | PASS — 10 registros válidos |
| PostgreSQL | conexão real via psycopg | PASS — 1/1 |
| Docker build | imagem de produção reconstruída | PASS — `httpx2` instalado como dependência runtime |
| Containers | healthchecks de API e PostgreSQL | PASS — 2/2 healthy |
| Endpoint local | `GET /health` | PASS — `ok/reachable` |
| Logs da API | inspeção dos logs após rebuild | PASS — sem exception, ERROR ou CRITICAL |
| Diff | `git diff --check` | PASS — sem erros de whitespace |

## Contrato implementado

- contratações por publicação e atualização;
- contratos por publicação e atualização;
- detalhe pontual de contratação por CNPJ, ano e sequencial;
- datas no formato oficial `YYYYMMDD`;
- páginas de contratações entre 10 e 50 e de contratos entre 10 e 500;
- HTTP 204 convertido em página vazia explícita;
- retry de falhas de transporte e HTTP 429, 500, 502, 503 e 504;
- `Retry-After` numérico ou em data HTTP, com fallback seguro;
- paginação com validação do número retornado antes de entregar registros;
- erros sem corpo da resposta e logs limitados a endpoint, status, tentativa e duração.

## Problemas encontrados e correções

### 1. Formatação inicial

- **Erro:** Ruff identificou uma linha acima do limite e quatro arquivos que precisavam ser
  normalizados.
- **Causa:** quebras de linha divergentes do formatador configurado.
- **Correção:** formatação automática aplicada.
- **Reteste:** lint e verificação de formato passaram com zero erros.

### 2. Nome do filtro CNPJ de contratações

- **Erro:** o primeiro contrato local emitia `cnpjOrgao` também para contratações.
- **Causa:** o PNCP usa nomes diferentes por recurso: `cnpj` em contratações e `cnpjOrgao` em
  contratos.
- **Correção:** a especificação OpenAPI oficial foi consultada, o modelo foi corrigido no ponto
  de origem e os dois contratos ganharam cobertura independente.
- **Reteste:** o teste de regressão falhou antes da correção e passou depois; 30 testes de modelos
  e cliente passaram em conjunto.

### 3. Valor não finito em Retry-After

- **Erro:** `Retry-After: Infinity` era aceito como número e poderia gerar espera infinita.
- **Causa:** o parser validava sinal, mas não finitude.
- **Correção:** valores não finitos agora são rejeitados e usam o backoff finito do cliente.
- **Reteste:** o caso reproduziu a falha antes da correção e os 16 testes de retry passaram depois.

## Inspeção dos dados retornados

A fixture foi capturada da resposta pública real de contratações de 01/08/2025, modalidade 6.
Ela preserva a estrutura aninhada de órgão e unidade, os identificadores oficiais e
`valorTotalHomologado` nulo. O gate ao vivo confirmou uma página com 10 registros e, em todos,
presença de `numeroControlePNCP`, `orgaoEntidade`, `unidadeOrgao`, `objetoCompra` e
`dataAtualizacaoGlobal`.

## Riscos restantes

- A API externa pode ficar indisponível ou alterar seu contrato; o teste `live_api` detecta essa
  divergência e deve permanecer obrigatório no gate de extração.
- O PNCP não publica quota oficial. O cliente reage a HTTP 429 e respeita `Retry-After`, sem
  atribuir ao serviço um limite não documentado.
- Os payloads ainda não são persistidos, hasheados ou deduplicados. Essas garantias pertencem à
  Fase 3 e não são alegadas neste checkpoint.
