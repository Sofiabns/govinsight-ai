# CHECKPOINT — Fase 7

```text
CHECKPOINT
--------------------------------
Fase: 7 — Analytics
Status: PASSED
Data: 2026-08-30
Branch: feat/phase-7-analytics
Views analíticas: 6
Operações públicas do serviço: 5
Testes específicos da fase: 9/9
Testes aprovados no gate final: 136/136
Teste PNCP ao vivo: 1 não executado por estar fora do escopo
Cobertura final: 92,81%
Problemas encontrados: 10
Correções realizadas: 10
Próxima etapa: Fase 8 — Orchestration
--------------------------------

STAGE_STATUS = PASSED
```

## Resultado

A Fase 7 centraliza métricas de contratações em seis views PostgreSQL e oferece uma interface Python
tipada para resumo, rankings, tendência mensal, distribuição e outliers. Os cálculos usam
`numeric`/`Decimal`, preservam nulos e distinguem explicitamente valores estimados e homologados.

## Evidências finais

| Gate | Resultado |
|---|---|
| Testes específicos da Fase 7 | PASS — 9/9 |
| Suíte local + PostgreSQL | PASS — 136/136; 1 teste externo não executado |
| Cobertura combinada | PASS — 92,81%, mínimo 80% |
| `ruff check .` | PASS — zero erros |
| `ruff format --check .` | PASS — 101 arquivos formatados |
| Migração atual | PASS — `20260830_0006 (head)` |
| Cabeça do Alembic | PASS — `20260830_0006 (head)` |
| `git diff --check` | PASS — sem erros de whitespace |

## Cenários medidos

1. Contagens, somas, médias e cobertura de valores reconciliaram exatamente com uma amostra Gold
   calculada de forma independente.
2. Filtros de período e UF compuseram resultados sem alterar a semântica financeira.
3. Rankings de órgão e estado mantiveram ordem determinística e participação total igual a 1.
4. Localidade sem UF apareceu no grupo explícito `UNKNOWN`.
5. Crescimento mensal foi calculado apenas para meses consecutivos; lacunas retornaram nulo.
6. Quartis e cercas IQR usaram somente `Decimal`; uma contratação extrema preservou a chave PNCP
   como evidência.
7. Filtros válidos sem correspondência retornaram coleções vazias e métricas financeiras nulas.
8. Limites de ranking acima de 100 foram bloqueados antes da consulta.

## Problemas encontrados e corrigidos

- O fixture de unidade sem UF omitia chaves presentes nas demais linhas do mesmo lote; os nulos
  passaram a ser explícitos para manter o insert consistente.
- A precisão esperada para crescimento mensal excedia a escala retornada pelo PostgreSQL; o teste
  passou a validar exatamente a precisão real do banco.
- O gate de formatação encontrou quatro arquivos novos fora do padrão; o formatador oficial foi
  aplicado antes da suíte final.
- A revisão identificou fallback silencioso de enums, agrupamento duplicável por nome de UF,
  chaves substitutas instáveis, ausência do padrão homologado, logs incompletos e lacunas de teste;
  os contratos, consultas, observabilidade e cenários foram corrigidos antes da integração.
- A segunda revisão encontrou um nome de UF ausente competindo lexicalmente com o nome válido; o
  agregado agora prefere nomes reais e usa o rótulo desconhecido somente quando necessário.

## Limites preservados

- Não existe métrica de valor contratado: homologado não é usado como substituto.
- Fornecedores, categorias e regiões aguardam fontes Silver/Gold confiáveis.
- Outlier IQR é uma observação estatística e não indica fraude ou irregularidade.
- Views materializadas permanecem adiadas até existir evidência de necessidade de performance.
- Distribuição e IQR carregam os valores filtrados em memória; a migração para percentis no banco
  será avaliada quando medições reais indicarem pressão de volume.
