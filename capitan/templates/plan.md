# __TITLE__

```json plan
{
  "id": "__ID__",
  "tier": "standard",
  "status": "draft",
  "created": "__DATE__",
  "objective": "__OBJECTIVE__",
  "areas": ["TODO: paths/globs this change may touch, e.g. src/billing/**"],
  "timebox": "TODO: e.g. 1 day. Past this, stop and re-plan or split.",
  "criteria": [
    {"id": "AC-1", "when": "TODO: situation", "then": "TODO: observable result", "test": "TODO: test name or check that proves it", "status": "pending"}
  ]
}
```

## Why
TODO: 1-3 sentences. What problem, for whom, and how it moves the objective above.

## Data impact
TODO: entities and relationships created, changed or removed; invariants from docs/data-model.md that this touches; migrations. Write "None" if truly none.

## Test plan
TODO: beyond the per-criterion tests above: integration/end-to-end checks, how the running app will be checked, what will NOT be tested and why.

## Risks
TODO: what could go wrong or be harder than it looks, and the cheapest early signal for each.

## Out of scope
TODO: tempting related work that is NOT part of this change. Each item goes to the parking lot (python -m capitan park "...").

## Relevant lessons
__LESSONS__

## Slices
Optional. If this takes more than one session, list the order of small, separately testable steps.
