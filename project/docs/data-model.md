# Data model

The schema (migrations, ORM models) is the source of truth for fields. This file holds what the schema cannot say on its own.

## Entities and relationships
Prefer a diagram generated from the schema (paste the generator command here) over a hand-drawn one; hand-drawn diagrams drift.

```mermaid
erDiagram
  %% generated or hand-kept: ENTITY_A ||--o{ ENTITY_B : has
```

## Invariants
Rules that must always hold. Each has an ID and a test that enforces it.

| ID | Invariant | Enforced by |
|---|---|---|
| INV-1 | TODO: e.g. every Order belongs to exactly one Customer | TODO: test name / DB constraint |

## Decisions
Why the model is shaped this way (or links to ADRs), so nobody "fixes" it back.
