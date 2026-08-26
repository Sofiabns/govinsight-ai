# CHECKPOINT — Fase 5

```text
CHECKPOINT
--------------------------------
Fase: 5 — Data Quality
Status: PASSED
Data: 2026-08-26
Branch: feat/phase-5-data-quality-implementation
Arquivos criados: 14
Arquivos alterados: 1
Testes locais executados: 91
Testes PostgreSQL executados: 28
Testes aprovados no gate final: 119/119
Teste PNCP ao vivo: 1 não executado por estar fora do escopo
Cobertura final: 91,39%
Regras bloqueantes: 12
Dimensões pontuadas: 5
Score do snapshot limpo: 100,00
Falhas detectadas no cenário inválido: 3
Alerta de volume detectado: 1, sem bloqueio
Problemas encontrados: 11
Correções realizadas: 11
Próxima etapa: Fase 6 — Data Warehouse dimensional
--------------------------------

STAGE_STATUS = PASSED
```

## Resultado

A Fase 5 adiciona um gate determinístico entre Silver e o futuro Data Warehouse. Doze regras SQL
avaliam completude, validade, unicidade, consistência e integridade de linhagem. Cada execução salva
contagens por regra, score ponderado, status e watermark da origem sem persistir valores livres do
PNCP.

Uma falha de dados permanece como evidência auditável e não avança a watermark de qualidade. Uma
falha técnica gera somente código seguro. O replay devolve a execução existente sem duplicar
resultados ou reclassificar evidência terminal.

## Evidências finais

| Gate | Resultado |
|---|---|
| `ruff check .` | PASS — zero erros |
| `ruff format --check .` | PASS — 77 arquivos formatados |
| Suíte local + PostgreSQL | PASS — 119/119; 1 teste externo não executado |
| Cobertura combinada | PASS — 91,39%, mínimo 80% |
| Migração | PASS — `20260826_0004 (head)` |
| PNCP ao vivo | Não repetido — a fase consome Silver local |

Os 119 testes correspondem a 91 cenários locais e 28 integrações com serviços externos locais,
principalmente PostgreSQL. O teste ao vivo do PNCP permaneceu excluído para evitar dependência de
rede sem relação com o gate de qualidade.

## Cenários medidos

1. Um snapshot limpo com uma contratação aprovou as 12 regras bloqueantes e obteve score 100,00.
2. O replay reutilizou a mesma execução e manteve 13 resultados, incluindo volume ainda não
   avaliado por falta de histórico.
3. Um snapshot com texto obrigatório vazio, UF `ZZ` e chave PNCP corrompida falhou em três regras e
   não avançou a watermark de qualidade.
4. Um snapshot posterior corrigido passou e avançou a watermark para o novo RAW confirmado.
5. Após histórico suficiente, quatro linhas contra mediana de uma produziram desvio de 300% e
   `ROW_VOLUME_ANOMALY`, sem bloquear o snapshot.
6. Uma falha injetada durante leitura de replay gerou erro seguro e preservou a execução `PASSED`.
7. Uma contratação Silver confirmada durante a avaliação ficou invisível ao snapshot atual e foi
   avaliada somente na execução seguinte, comprovando `REPEATABLE READ`.

## BUG HUNT compacto

| Caso | Evidência | Resultado |
|---|---|---|
| Dataset vazio | regra bloqueante produz score 0,00 | PASS |
| Texto obrigatório vazio | `REQUIRED_TEXT_PRESENT` falha | PASS |
| UF fora do domínio | `UF_DOMAIN_VALID` falha | PASS |
| Chave PNCP malformada | falha de consistência, sem erro de cast | PASS |
| Replay | execução e resultados existentes são reutilizados | PASS |
| Evidência terminal | falha de leitura não altera `PASSED` para `FAILED` | PASS |
| Concorrência Silver | todas as regras enxergam o mesmo snapshot | PASS |
| Watermark bloqueada | snapshot inválido não avança qualidade | PASS |
| Watermark corrigida | snapshot posterior válido avança exatamente | PASS |
| Score e arredondamento | cálculo usa `Decimal` e duas casas | PASS |
| Volume | baseline exige três runs; desvio acima de 50% gera warning | PASS |
| Sigilo | detalhes contêm apenas contagens e parâmetros agregados | PASS |

## Problemas encontrados e corrigidos

- O primeiro comando de baseline usou um caminho PowerShell com espaços sem operador de execução;
  a chamada foi corrigida sem alterar o projeto.
- O Docker Desktop estava parado e a porta PostgreSQL não respondia; o serviço isolado foi
  reativado em `127.0.0.1:54320`.
- O formatador normalizou exemplos do plano e pequenos trechos de quatro arquivos de produção/teste.
- Um import não utilizado foi removido antes do gate.
- Uma falha transitória ao carregar replay poderia rebaixar uma execução terminal para `FAILED`;
  a transição de erro agora aceita somente runs `RUNNING` e informa se alterou uma linha.
- As consultas usavam o isolamento padrão `READ COMMITTED`, permitindo mistura de estados; a
  avaliação completa agora usa uma transação `REPEATABLE READ`.
- A regra de ano fazia cast direto dos quatro últimos caracteres da chave; `CASE` e regex agora
  transformam chave malformada em falha de qualidade.
- O teste de correção não confirmava a watermark posterior; a asserção foi adicionada.
- Os nomes de primary key divergiam entre metadata e Alembic; ambos agora usam
  `pk_quality_run` e `pk_quality_result`.
- A concorrência entre conclusão e tratamento de erro não tinha regressão direta; o teste confirma
  que evidência concluída é imutável.
- A consistência de snapshot não tinha prova concorrente; um teste realiza commit Silver durante a
  avaliação e confirma visibilidade somente na execução seguinte.

## Riscos e limites restantes

- As regras cobrem apenas `silver.procurement`; contratos, itens e resultados ainda não participam.
- A validação de CNPJ confirma formato de 14 dígitos, mas não calcula dígitos verificadores.
- O limite de 50% para volume é inicial e poderá ser calibrado após histórico operacional real.
- Indisponibilidade completa do PostgreSQL impede o próprio banco de registrar a falha.
- A Silver ainda não oferece dimensões, fatos ou métricas analíticas Gold.

## Próxima etapa

Construir a Fase 6 — Data Warehouse com dimensões e fato baseados somente nos campos realmente
disponíveis e validados. O primeiro modelo deve preservar contagens e valores financeiros sem usar
valor homologado como substituto de contrato.
