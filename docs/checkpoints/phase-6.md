# CHECKPOINT — Fase 6

```text
CHECKPOINT
--------------------------------
Fase: 6 — Data Warehouse
Status: PASSED
Data: 2026-08-30
Branch: feat/phase-6-data-warehouse-impl
Arquivos criados: 9
Arquivos alterados: 2
Testes específicos da fase: 8/8
Testes aprovados no gate final: 127/127
Teste PNCP ao vivo: 1 não executado por estar fora do escopo
Cobertura final: 92,08%
Dimensões Gold: 4
Fatos Gold: 1
Grão da fato: 1 contratação por numero_controle_pncp
Problemas encontrados: 13
Correções realizadas: 13
Próxima etapa: Fase 7 — API analítica
--------------------------------

STAGE_STATUS = PASSED
```

## Resultado

A Fase 6 adiciona o primeiro Data Warehouse dimensional confiável do projeto. A camada Gold possui
dimensões de data, órgão, unidade/localidade e modalidade, ligadas a
`gold.fact_procurement`. A fato mantém uma linha por chave de controle PNCP, referências à Bronze e
medidas financeiras exatas em `numeric(19,4)`.

A carga só inicia quando Silver e Qualidade apontam para o mesmo snapshot. Dimensões, fato,
reconciliação e watermark Gold compartilham uma transação `REPEATABLE READ`; qualquer divergência
desfaz todas as alterações.

## Evidências finais

| Gate | Resultado |
|---|---|
| Testes específicos da Fase 6 | PASS — 8/8 |
| Suíte local + PostgreSQL | PASS — 127/127; 1 teste externo não executado |
| Cobertura combinada | PASS — 92,08%, mínimo 80% |
| `ruff check .` | PASS — zero erros |
| `ruff format --check .` | PASS — 88 arquivos formatados |
| Migração atual | PASS — `20260826_0005 (head)` |
| Cabeça do Alembic | PASS — `20260826_0005 (head)` |
| `git diff --check` | PASS — sem erros de whitespace |

O teste PNCP ao vivo não foi repetido porque esta fase consome somente dados locais já existentes
na Silver.

## Cenários medidos

1. A migração criou quatro dimensões e uma fato com PKs, FKs, unicidade, índices e duas medidas
   monetárias nullable `numeric(19,4)`; o downgrade removeu tudo na ordem segura.
2. Duas contratações produziram duas fatos, duas organizações, duas unidades, uma modalidade e
   cinco datas distintas, com todos os joins resolvidos.
3. As somas estimada `350,2500` e homologada `300,0000` coincidiram exatamente entre Silver e Gold,
   incluindo contagens de nulos.
4. O replay do mesmo snapshot retornou `NOOP`, preservou contagens e não regravou o warehouse.
5. Uma Silver à frente da Qualidade foi bloqueada sem criar dimensões, fatos ou watermark Gold.
6. Um snapshot posterior atualizou descrições e valor em Tipo 1, preservando todas as chaves
   substitutas e a data original de criação da fato.
7. Uma reconciliação inválida injetada reverteu dimensões, fato e watermark na mesma transação.
8. Duas cargas concorrentes produziram exatamente uma carga e um `NOOP`, sem erro de serialização.
9. Um snapshot posterior com uma contratação alterada e outra inalterada preservou os timestamps
   da linha que não mudou.
10. Watermarks Silver ou Quality ausentes foram rejeitados como snapshot aprovado indisponível.
11. A carga completou com `pool_size=1` e `max_overflow=0`, sem solicitar uma segunda conexão.

## Garantias analíticas

- `numero_controle_pncp` é único na fato e define o grão atual.
- Todas as referências obrigatórias resolvem para dimensões existentes.
- Datas de publicação, abertura e encerramento reutilizam `gold.dim_date` em papéis diferentes.
- Linhagem RAW e hash normalizado coincidem com a Silver.
- Somas e nulos financeiros são reconciliados separadamente.
- Valor homologado nunca é apresentado como valor contratado.
- Região, fornecedor, contratos, itens e categorias não são inventados sem fontes Silver confiáveis.

## Problemas encontrados e corrigidos

- O cenário de atualização usou inicialmente um timestamp anterior ao registro-base; a Silver o
  rejeitou corretamente como versão antiga. O fixture passou a usar uma atualização realmente
  posterior.
- O gate de formatação encontrou três artefatos fora do padrão; o formatador oficial foi aplicado e
  o gate completo foi repetido.
- A checagem manual do Alembic recebeu somente `GOVINSIGHT_DATABASE_URL`, mas o ambiente de migração
  lê variáveis PostgreSQL individuais. A verificação foi repetida explicitamente na porta isolada
  `54320` e confirmou a revisão correta.
- A primeira trava transacional fixava o snapshot antes de terminar a espera; ela foi substituída
  por uma advisory lock de sessão adquirida antes de abrir `REPEATABLE READ`.
- A limpeza de integração removia dados globais; cada cenário agora usa chaves próprias, remove
  somente suas linhas e restaura os três watermarks que encontrou.
- A ausência de aprovação era confundida com watermark zero; Silver e Quality agora são
  obrigatórias, enquanto apenas a Gold pode estar ausente na primeira carga.
- UPSERTs posteriores atualizavam timestamps de linhas inalteradas; condições `IS DISTINCT FROM`
  agora evitam escrita e WAL desnecessários.
- O desempate dimensional ganhou índice de registro e chave PNCP para permanecer determinístico.
- Os testes passaram a validar publicação, abertura e encerramento separadamente.
- A carga passou a emitir logs estruturados seguros somente com watermarks, status e contagens.
- A primeira correção da trava usava duas conexões e bloqueava um pool unitário; trava e transação
  agora reutilizam a mesma conexão física.
- O teste concorrente liberava a trava antes de comprovar a espera; ele agora observa dois waiters
  PostgreSQL antes da liberação.
- O evento de conclusão era emitido antes da confirmação do commit; agora só é registrado após o
  encerramento bem-sucedido da transação.

## Riscos e limites restantes

- A Gold cobre somente contratações porque essa é a entidade atualmente validada na Silver.
- Dimensões são Tipo 1; o projeto ainda não retém histórico dimensional Tipo 2.
- Não há sinal oficial de exclusão na Silver, portanto a carga não infere deleções por ausência.
- Localidade permanece dentro da dimensão de unidade até o enriquecimento oficial do IBGE.
- Valor contratado será disponibilizado somente após uma fato de contratos baseada em dados reais.

## Próxima etapa

Construir a Fase 7 — API analítica sobre o warehouse Gold, expondo filtros e agregações confiáveis
sem permitir que clientes confundam medidas estimadas, homologadas e contratadas.
