# CHECKPOINT — Fase 3

```text
CHECKPOINT
--------------------------------
Fase: 3 — RAW Layer
Status: PASSED
Data: 2026-08-21
Branch: feat/phase-3-raw-layer-implementation
Arquivos criados: 16
Arquivos alterados: 5
Testes unitários executados: 86
Testes unitários aprovados: 86
Testes de integração distintos executados: 21
Testes de integração distintos aprovados: 21
Testes falharam no gate final: 0
Execuções do teste PNCP ao vivo: 4 — três falharam por timeout; a quarta passou em 1,29 s
Cobertura: 80,41%
Respostas RAW persistidas no cenário medido: 2
Registros de negócio contidos nas respostas RAW: 3
Registros de negócio persistidos em Silver: 0 — transformação fora do escopo da Fase 3
Respostas RAW duplicadas impedidas: 2
Registros contabilizados como duplicados no replay: 3
Problemas encontrados: 11
Correções realizadas: 10; o PNCP externo recuperou-se sem correção local
Riscos restantes: reconciliação futura de run RUNNING quando a própria finalização falhar
Próxima etapa: iniciar a Fase 4 — Silver / Transformation
--------------------------------

STAGE_STATUS = PASSED
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
| Testes unitários | pytest sem integração | PASS — 86/86 |
| Cobertura | branch coverage | PASS — 80,41%, mínimo 80% |
| PostgreSQL real | conexão, migração, repositórios e serviço | PASS — 20/20 |
| Migração | `alembic current` | PASS — `20260817_0002 (head)` |
| PNCP ao vivo | publicação, 01/08/2025, modalidade 6, página de 10 | PASS — quarta execução aprovada em 1,29 s; as três anteriores totalizaram 12 `ReadTimeout` |
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
| Corpo HTTP 204 vazio | cliente força `raw_body == ""` até para resposta 204 não conforme com conteúdo | PASS |
| Unicode e hash UTF-8 | canonicalização preserva `ação`; SHA-256 usa o texto exato em UTF-8 | PASS |
| Duplicatas concorrentes | duas transações retornam `[False, True]` e deixam uma linha | PASS |
| Corpo alterado | mesmo request com hash novo cria versão imutável adicional | PASS |
| Identidade por tamanho de página | escopo remove apenas `pagina`; mudança de `tamanhoPagina` muda o fingerprint | PASS |
| Falha parcial e retomada | página 1 permanece; nova execução retoma na página 2 | PASS |
| Identidade da resposta | endpoint, parâmetros completos e página divergentes falham antes de RAW/checkpoint | PASS |
| Checkpoint concorrente | maior página prevalece; conclusão só avança e nunca regride na mesma página | PASS |
| Estado terminal | falhas tratadas viram `FAILED`; sucesso vira `SUCCEEDED` | PASS |
| Rollback atômico | RAW, contadores e checkpoint revertem juntos | PASS |
| Vazamento de corpo | traceback e cadeia dos erros de JSON/envelope não retêm o payload sentinela | PASS |
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
- **Evidência final após a revisão:** 86 testes passaram e a cobertura ficou em 80,41%.

### 3. Colisão de portas Docker

- **Problema:** a porta 5432 já estava ocupada pelo PostgreSQL de desenvolvimento.
- **Correção:** a composição foi reconstruída e validada em 55432 (PostgreSQL) e 58000 (API), sem
  interromper o serviço existente.
- **Reteste:** os dois containers ficaram healthy e `/health` retornou `ok/reachable`.

### 4. Timeout no PNCP ao vivo — recuperado externamente

- **Problema:** o endpoint oficial não respondeu dentro de 30 segundos; o cliente esgotou quatro
  tentativas por execução. O mesmo teste foi executado três vezes e totalizou 12 tentativas
  encerradas por timeout.
- **Classificação:** indisponibilidade externa transitória, sem evidência de regressão local.
- **Resolução:** em 21/08/2026, a quarta execução recebeu uma resposta compatível e passou
  em 1,29 s, sem alteração no cliente ou relaxamento do teste.

### 5–10. Correções da revisão final

- Erros de JSON e envelope agora são traduzidos sem causa ou contexto implícito que retenha o
  payload; testes sentinela inspecionam o traceback completo e a cadeia da exceção.
- O serviço valida endpoint, parâmetros completos e página contra a requisição efetivamente
  emitida antes de construir ou persistir `RawCapture`.
- O UPSERT PostgreSQL do checkpoint aceita somente página maior ou a transição de conclusão
  `false` para `true` na mesma página, preservando replay concluído e concorrência fora de ordem.
- Respostas HTTP 204 sempre produzem corpo RAW vazio, inclusive quando o servidor envia conteúdo
  não conforme.
- A inspeção da migração confirma as colunas da unicidade, o alvo completo da chave estrangeira e
  a restrição de dataset do watermark.
- A documentação teve espaços finais e evidências obsoletas corrigidos.

### 11. Ambiente Docker parado ao retomar o projeto

- **Problema:** o Docker Desktop e os contêineres estavam parados; a porta 5432 não aceitava
  conexões. O Alembic também aguardava ao resolver `localhost` no ambiente retomado.
- **Correção:** o Docker Desktop foi iniciado, a pilha foi reconstruída nas portas 55432/58000 e
  o gate local do Alembic usou explicitamente `127.0.0.1`.
- **Reteste:** 20/20 integrações PostgreSQL passaram, a migração ficou em
  `20260817_0002 (head)`, os dois contêineres ficaram saudáveis e `/health` retornou
  `ok/reachable`.

## Riscos restantes

- Se a própria transação de finalização de falha for recusada pelo banco, uma execução pode ficar
  `RUNNING`; o erro de persistência é visível e a reconciliação fica para a futura orquestração.
- A Bronze contém dados não confiáveis como texto e não oferece ainda entidades Silver ou regras
  de qualidade de negócio.

## Próxima etapa

Iniciar a Fase 4 — Silver / Transformation, preservando a Bronze imutável como fonte de verdade e
criando normalização, tipagem, deduplicação e regras de qualidade somente a partir dos campos
realmente observados no PNCP.
