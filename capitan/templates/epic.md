# __TITLE__

```json plan
{
  "id": "__ID__",
  "tier": "epic",
  "status": "draft",
  "created": "__DATE__",
  "objective": "__OBJECTIVE__",
  "children": [
    {"key": "a", "title": "TODO: first standard change", "depends_on": []},
    {"key": "b", "title": "TODO: second standard change", "depends_on": ["a"]}
  ]
}
```

## Why
TODO: the outcome this epic delivers and how it moves the objective.

## Shape
TODO: the overall approach in a few lines: main components, data model changes, key decisions (link ADRs).

## Out of scope
TODO: what this epic deliberately leaves out. Park it.

## Relevant lessons
__LESSONS__

Each child becomes its own standard change (python -m capitan new "<child title>" --tier standard ...).
Children with no unmet depends_on can run in parallel, one branch/worktree each.
