# CHECKPOINT — Fase 3

```text
CHECKPOINT
--------------------------------
Fase: 3 — RAW Layer
Status: BLOCKED — contrato PNCP ao vivo indisponível por timeout
Data: 2026-08-17
Branch: feat/phase-3-raw-layer-implementation
Arquivos criados: 16
Arquivos alterados: 5
Testes unitários executados: 85
Testes unitários aprovados: 85
Testes de integração executados: 17
Testes de integração aprovados: 16
Testes falharam no gate final: 1
Cobertura: 81,36%
Respostas RAW persistidas no cenário medido: 2
Registros de negócio contidos nas respostas RAW: 3
Registros de negócio persistidos em Silver: 0 — transformação fora do escopo da Fase 3
Respostas RAW duplicadas impedidas: 2
Registros contabilizados como duplicados no replay: 3
Problemas encontrados: 4
Correções realizadas: 3
Riscos restantes: indisponibilidade externa do PNCP; reconciliação futura de run RUNNING quando a própria finalização falhar
Próxima etapa: repetir o gate PNCP; após aprovação da Fase 3, iniciar a Fase 4 — Silver
--------------------------------

STAGE_STATUS = BLOCKED
```

## Objetivo da etapa

Persistir respostas bem-sucedidas do PNCP como texto exato em uma camada Bronze imutável,
idempotente e retomável. A etapa inclui identidades determinísticas, histórico de execuções,
checkpoint por página e transações atômicas, sem antecipar transformação Silver.

## Verificações executadas

| Gate | Evidência fresca | Resultado |
|---|---|---|
| Lint | `ruff check .` | PASS — zero erros |
| Formato | `ruff format --check .` após correção | PASS — 50 arquivos formatados |
| Testes unitários | pytest sem integração | PASS — 85/85 |
| Cobertura | branch coverage | PASS — 81,36%, mínimo 80% |
| PostgreSQL real | conexão, migração, repositórios e serviço | PASS — 16/16 |
| Migração | `alembic current` | PASS — `20260817_0002 (head)` |
| PNCP ao vivo | publicação, 01/08/2025, modalidade 6, página de 10 | BLOCKED — 4/4 tentativas terminaram em `ReadTimeout` em cada uma de duas execuções |
| Docker build | imagem reconstruída a partir do worktree | PASS |
| Containers | API e PostgreSQL em portas 58000/55432 | PASS — 2/2 healthy |
| Endpoint local | `GET http://127.0.0.1:58000/health` | PASS — `ok/reachable` |
| Logs da API | inspeção após rebuild e health checks | PASS — sem `Traceback`, `ERROR` ou `CRITICAL` |

## Medição de persistência e idempotência

O cenário determinístico de duas páginas persistiu 2 respostas RAW contendo 3 registros. O replay
completo processou novamente as 2 páginas, manteve a Bronze em 2 linhas, inseriu 0 registros e
contabilizou 3 registros duplicados. Assim, 2 respostas RAW redundantes foram impedidas pela
restrição de identidade e hash do corpo.

Uma alteração de um único caractere no corpo, acompanhada do novo SHA-256, produziu uma segunda
versão imutável para a mesma identidade de requisição. O teste concorrente com duas transações
independentes mediu um único insert vencedor e uma única linha Bronze.

## BUG HUNT

| Caso inspecionado | Evidência | Resultado |
|---|---|---|
| Corpo HTTP 204 vazio | cliente enriquecido preserva `raw_body == ""` e página solicitada | PASS |
| Unicode e hash UTF-8 | canonicalização preserva `ação`; SHA-256 usa o texto exato em UTF-8 | PASS |
| Duplicatas concorrentes | duas transações retornam `[False, True]` e deixam uma linha | PASS |
| Corpo alterado | mesmo request com hash novo cria versão imutável adicional | PASS |
| Identidade por tamanho de página | escopo remove apenas `pagina`; mudança de `tamanhoPagina` muda o fingerprint | PASS |
| Falha parcial e retomada | página 1 permanece; nova execução retoma na página 2 | PASS |
| Estado terminal | falhas tratadas viram `FAILED`; sucesso vira `SUCCEEDED` | PASS |
| Rollback atômico | RAW, contadores e checkpoint revertem juntos | PASS |
| Vazamento de corpo | somente códigos seguros são persistidos; logs não contêm payload | PASS |
| Watermark | cada teste do serviço confirma `control.etl_watermark` vazio | PASS |
| Logs da API | nenhum `Traceback`, `ERROR` ou `CRITICAL` | PASS |

Nenhum defeito funcional novo foi encontrado. A decisão vinculante da Task 5 permanece: se o
próprio PostgreSQL impedir a transação separada que marcaria a execução como `FAILED`, o erro de
persistência é propagado e a execução pode permanecer `RUNNING`. A reconciliação durável desse
caso excepcional pertence à orquestração futura.

## Problemas encontrados e correções

### 1. Formatação inicial

- **Problema:** o gate encontrou cinco arquivos fora do formato configurado por divergência de
  finais de linha.
- **Correção:** `ruff format .` normalizou os arquivos.
- **Reteste:** lint e formato passaram.

### 2. Cobertura abaixo do limite

- **Problema:** 81 testes passaram, mas a cobertura medida foi 79,90%, abaixo dos 80% exigidos.
- **Correção:** quatro casos unitários cobrem o roteamento dos endpoints de procurement/contract
  em publicação/atualização, sem alterar produção.
- **Reteste:** 85 testes passaram e a cobertura subiu para 81,36%.

### 3. Colisão de portas Docker

- **Problema:** a porta 5432 já estava ocupada pelo PostgreSQL de desenvolvimento.
- **Correção:** a composição foi reconstruída e validada em 55432 (PostgreSQL) e 58000 (API), sem
  interromper o serviço existente.
- **Reteste:** os dois containers ficaram healthy e `/health` retornou `ok/reachable`.

### 4. Timeout no PNCP ao vivo — não corrigido localmente

- **Problema:** o endpoint oficial não respondeu dentro de 30 segundos; o cliente esgotou as
  quatro tentativas. A execução foi repetida com acesso externo autorizado e apresentou o mesmo
  resultado.
- **Classificação:** dependência externa indisponível, sem evidência de regressão local.
- **Ação necessária:** repetir o teste ao vivo quando o PNCP responder. O status não pode ser
  promovido para `PASSED` antes desse gate.

## Riscos restantes

- A promoção da Fase 3 está bloqueada pelo gate externo do PNCP.
- Se a própria transação de finalização de falha for recusada pelo banco, uma execução pode ficar
  `RUNNING`; o erro de persistência é visível e a reconciliação fica para a futura orquestração.
- A Bronze contém dados não confiáveis como texto e não oferece ainda entidades Silver ou regras
  de qualidade de negócio.

## Próxima etapa

Repetir `tests/integration/test_pncp_live.py`. Com o contrato ao vivo aprovado, atualizar este
checkpoint para `STAGE_STATUS = PASSED`, concluir os checkboxes restantes da Task 6 e então seguir
para a Fase 4 — Silver.
