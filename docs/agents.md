# Agent system

The agent layer interprets trusted Gold data; it never replaces ETL, quality checks or statistical
calculation.

## Flow

1. **Data Analyst** maps the question to an approved analytical query and returns structured evidence.
2. **Statistical Analyst** preserves computed metrics and identifies supported comparison structures.
3. **Business Insight** adds bounded interpretation without changing numbers.
4. **Data Quality** blocks empty or insufficient evidence.
5. **Verification/Critic** checks evidence presence and exact number preservation.
6. **Executive Report** runs only after critic approval.

## Safety contract

- Only one `SELECT` statement is allowed.
- Only the five approved Gold aggregation views can be queried.
- Comments, statement chaining, mutations and administrative commands are rejected.
- A maximum of 200 rows and a five-second statement timeout apply.
- Database execution occurs in an explicit read-only transaction.
- Prompt-injection phrases targeting instructions or data mutation are blocked before generation.

The deterministic baseline keeps behavior demonstrable without an external API key. The query
generator is a protocol boundary, so a hosted or local language model can later be added without
weakening SQL validation.

## Evaluation

`tests/fixtures/agents/agent_evaluation.json` is the versioned benchmark. It covers summary, trend,
organization/state/modality rankings and prompt injection. The evaluator reports accuracy,
grounded-answer rate and unexpected failure rate.
