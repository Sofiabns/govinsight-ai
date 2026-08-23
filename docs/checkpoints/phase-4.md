# CHECKPOINT — Fase 4

```text
CHECKPOINT
--------------------------------
Fase: 4 — Silver / Transformation
Status: PASSED
Data: 2026-08-23
Branch: feat/phase-4-silver-transformation-implementation
Arquivos criados: 15
Arquivos alterados: 1
Testes locais executados: 89
Testes PostgreSQL executados: 24
Testes aprovados no gate final: 113/113
Teste PNCP ao vivo: 1 não executado por estar fora do escopo
Cobertura final: 90,86%
Respostas RAW confirmadas no cenário Silver: 4
Registros inseridos/atualizados/inalterados/rejeitados: 2/1/1/2
Falhas funcionais no gate final: 0
Problemas encontrados: 12
Correções realizadas: 12
Próxima etapa: ampliar a Silver e formalizar qualidade e integridade antes da Gold
--------------------------------

STAGE_STATUS = PASSED
```

## Resultado

A Fase 4 entrega o primeiro fluxo completo Bronze → Silver para contratações. Respostas RAW são
consumidas incrementalmente, registros válidos viram estado atual tipado e registros inválidos são
isolados em quarentena com códigos seguros. A linhagem até a resposta e posição originais é
preservada em ambos os caminhos.

O processamento é atômico por resposta RAW. Dados Silver, quarentena e watermark confirmam juntos;
qualquer erro no banco reverte o conjunto. Versões novas atualizam a entidade, versões antigas não
causam regressão e replays sem novos dados não produzem escrita.

## Evidências finais

| Gate | Resultado |
|---|---|
| `ruff check .` | PASS — zero erros |
| `ruff format --check .` | PASS — 63 arquivos formatados |
| Suíte local isolada | PASS funcional — 89/89; cobertura isolada de 71,32% |
| Suíte combinada local + PostgreSQL | PASS — 113/113; 1 teste externo não executado |
| Cobertura combinada | PASS — 90,86%, mínimo 80% |
| Migração | PASS — `20260823_0003 (head)` |
| PNCP ao vivo | Não repetido — a fase consome Bronze local |

A cobertura isolada não alcança o limite porque repositórios e serviços transacionais são exercidos
com PostgreSQL real. A medição representativa combina 89 testes locais com 24 integrações,
sem criar testes artificiais ou duplicados para inflar o índice.

## Cenário Silver medido

1. Uma resposta com dois registros inseriu uma contratação válida e colocou a irmã inválida em
   quarentena.
2. Um replay imediato processou zero respostas.
3. Uma versão mais nova atualizou a contratação.
4. Uma versão mais antiga foi contabilizada como inalterada e não regrediu o estado atual.
5. Um valor monetário fora do schema foi colocado em quarentena sem impedir a irmã válida.
6. Uma falha de repositório injetada após a escrita provocou rollback real; não criou linha parcial
   nem avançou o watermark.

Contagem confirmada nas quatro respostas concluídas: 2 inseridos, 1 atualizado, 1 inalterado e
2 rejeitados. A quinta resposta deliberadamente falha permaneceu pendente para retomada.

## BUG HUNT compacto

| Caso | Evidência | Resultado |
|---|---|---|
| Valor monetário nulo | fixture real preserva homologado como `None` | PASS |
| Timestamp PNCP sem fuso | valor permanece ingênuo, sem inventar timezone | PASS |
| Irmãos válido e inválido | válido persiste; inválido vai à quarentena | PASS |
| Replay | nenhuma resposta ou escrita adicional | PASS |
| Fonte mais antiga | estado atual mantém a versão mais nova | PASS |
| Rollback | erro real não avança watermark nem deixa linha parcial | PASS |
| Sigilo | valor sentinela não aparece na rejeição | PASS |
| Watermark | avanço monotônico dentro da mesma transação | PASS |

## Problemas encontrados e corrigidos

- O Docker estava parado e as portas inicialmente escolhidas pertenciam a uma faixa reservada do
  Windows; o PostgreSQL isolado foi iniciado em `127.0.0.1:54320`.
- A cópia do ambiente virtual apontava para o código da árvore principal; o vínculo editável local
  foi corrigido para o worktree da Fase 4.
- A inserção da quarentena enviava `error_codes` duas vezes; a montagem dos valores foi centralizada.
- O teste Silver enxergava RAW legítima de execuções anteriores; sua watermark inicial agora parte
  do maior id preexistente, sem apagar dados alheios.
- Nove arquivos precisavam da formatação configurada; o formatador do projeto os normalizou.
- A consulta Alembic usava a porta padrão; host e porta do PostgreSQL isolado foram definidos
  explicitamente e o head foi confirmado.
- Inteiros fracionários ou acima do limite e valores fora de `numeric(19,4)` chegavam ao banco;
  agora são rejeitados individualmente pelo parser com códigos estáveis.
- O primeiro insert concorrente usava leitura seguida de escrita; foi substituído por um único
  UPSERT PostgreSQL condicional e comprovado com dois workers simultâneos.
- Uma chave PNCP malformada podia ser copiada para a quarentena; agora ela gera
  `INVALID_NATURAL_KEY` e a coluna segura permanece nula.
- Watermark SQL nula podia ser confundida com linha ausente; o repositório agora distingue os
  estados e rejeita JSON nulo ou malformado.
- A revisão final encontrou uma métrica local antiga no checkpoint e ausência de regressão direta
  para watermark inválida; a métrica foi corrigida e o cenário passou com três estados inválidos.

## Riscos e limites restantes

- Contratos, itens, resultados e enriquecimento IBGE ainda não foram transformados.
- Uma resposta com JSON ou envelope inválido bloqueia o avanço naquele ponto de forma intencional;
  observabilidade e política operacional de descarte exigem orquestração futura.
- A Silver representa estado operacional atual, ainda sem dimensões, fatos ou agregações Gold.
- Dashboard, API analítica e agentes com evidências permanecem fora desta fase.

## Próxima etapa

Ampliar a Silver com as próximas entidades prioritárias e regras formais de qualidade e integridade.
Só depois desse gate o projeto deve construir o modelo dimensional Gold para API, dashboard e IA.
