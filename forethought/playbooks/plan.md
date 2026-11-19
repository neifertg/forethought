# Playbook: plan a change

Any agent (or a person) follows this before writing code. The command is `python -m forethought` (below: `forethought`).

## 1. Pick the tier
| Tier | Use when | What it needs |
|---|---|---|
| quick | Typo, config tweak, one-file bug fix with an obvious check | `forethought new "<title>" --tier quick --intent "..." --done-check "..."` and nothing else |
| standard | Anything that adds or changes behavior, touches data, or takes more than an hour | A one-page plan, a fresh critique, human approval |
| epic | More than ~2 days of work or more than one area of the system | An epic that splits into standard changes with `depends_on` |

When unsure, pick standard. If a standard plan grows past one page, it is an epic.

For an epic: plan and approve the epic first, then create each child as its own standard change with
`forethought new "<child title>" --tier standard --epic <epic-id> --child <key>`. A child cannot start until the children it depends on are done.

## 2. Anchor it to a goal
Read `GOALS.md`. Every standard or epic change names exactly one objective (`O1`, `O2`...). If the work serves no objective, or matches a non-goal, stop and tell the human instead of planning it. That is the rabbit-hole check.

## 3. Create and fill the plan
`forethought new "<title>" --tier standard --objective O1 --areas "src/x/**,db/migrations/**"`

Then fill every TODO in `changes/<id>/plan.md`:
- **criteria**: `WHEN <situation> THEN <observable result>`, each with the test that proves it. A criterion with no possible test is a wish: rewrite it or drop it.
- **areas**: the only paths this change may touch. Narrow is better.
- **timebox**: when to stop and re-plan instead of pushing on.
- **Data impact**: read `docs/data-model.md`. Name every entity, relationship and invariant touched. Data mistakes are the most expensive kind; be specific.
- **Relevant lessons**: forethought pre-filled matches from `LESSONS.md`. Also run `forethought recall <other terms>`. For each lesson listed, say in one line how this plan accounts for it.
- **Out of scope**: list the tempting extras and park each one (`forethought park "..." --from <id>`).

Keep it to one page. The plan is for the reviewer and for future you, not a novel.

## 4. Validate, critique, hand over
1. `forethought check <id>` until it prints `ok`.
2. Get a critique from a FRESH context, not the session that wrote the plan: `forethought critique <id>` (runs `agent_cmd` from `forethought/config.json`), or `forethought critique <id> --print` and give that prompt to a new session; save its reply as `changes/<id>/critique.md`.
3. Fix what the critique finds, re-run check and critique if the plan changed materially.
4. Tell the human it is ready. **Only the human runs `forethought approve <id>`.** No code for this change until then.
