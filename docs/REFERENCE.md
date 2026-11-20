# capitan reference

Everything in detail: every command, what each one enforces, the organizing tools, tiers, PR descriptions, configuration and adapters. New here? Start with the [README](../README.md); the full lifecycle is in [WORKFLOW.md](WORKFLOW.md); who can change the rules and the known limits are in [SECURITY.md](SECURITY.md).

`capitan <command>` below is short for `python -m capitan <command>`, run from your project's root folder. `python -m capitan --help` lists every command.

## Commands and what they enforce

```
GOALS ─► PLAN ─► CRITIQUE ─► APPROVE ─► START ─► BUILD ─► REVIEW ─► FINISH ─► PR ─► CI
          │         fresh       human              in scope   fresh      lessons        merge gate
          └ lessons pre-filled                     (gate)     per AC     PR text
```

| Step | Command | What is enforced |
|---|---|---|
| Plan | `new "<title>" --tier quick\|standard\|epic --objective O1 --areas "src/x/**"` | Refuses until `GOALS.md` has real objectives. Past lessons for the area are pre-filled. |
| Validate | `check <id>` | No placeholders, a real objective, every criterion has `when`/`then`/`test`, data impact, test plan, risks, out of scope, one page max, no epic dependency cycles. |
| Critique | `critique <id>` | A fresh-context critic checks goal fit, testability, data impact, scope and lessons. The verdict is tied to this exact plan version. |
| Approve | `approve <id>` | **Human only.** Needs a `READY` critique of the current plan (or `--skip-critique "<why>"`, recorded). The approved plan is fingerprinted. |
| Start | `start <id>` then `git switch -c change/<id>` | Approved plans only. Epic children wait for the children they depend on. |
| Build | (your editor or agent) | **Plan gate:** code can't be committed (or, with the Claude adapter, even edited) without an active, started change. **Scope guard:** files outside the plan's `areas` are flagged. |
| Side idea | `park "<idea>" --from <id>` | Goes to the parking lot in `ROADMAP.md` instead of into this change. |
| Review | `review <id>` | A fresh-context code review with one verdict per acceptance criterion, tied to the exact code it saw. |
| Learn | `learn "<title>" --area a,b --body "..."` | Numbered, searchable, linked to the change. `recall <terms>` searches. |
| Finish | `finish <id>` | Every criterion passes, the review passed **on the current code**, a lesson is recorded (or `--no-lessons "<why>"`), and a schema change came with a `docs/data-model.md` update. Writes `changes/<id>/pr.md`. |
| Merge | CI runs `gate --ci` | The change is finished and its review still matches the code exactly. Scope and PR size are reported (or enforced, with `scope_mode` / `pr_size_mode` set to `block`). |

Also: `revise <id>` (send an approved plan back to draft to change it; editing it in place is caught), `drop <id>`, `pr <id>`, `hooks`, `allow-governance` (human only, see [SECURITY.md](SECURITY.md)), and the organizing commands below.

## Tiers
- **quick**: a trivial fix. An intent and a done check; human approval but no critique or review; at most 3 code files.
- **standard**: one page. Criteria, areas, time box, data impact, test plan, risks, out of scope, lessons.
- **epic**: splits into standard changes with `depends_on` (`new ... --epic <id> --child <key>`). Independent children can run in parallel, one branch each. Epics carry no code themselves.

## Staying organized as the project grows

| Problem | What capitan does |
|---|---|
| "Where does this go?" | A **where-things-go** table in `AGENTS.md` that people and agents both read. |
| Nobody knows what a folder is for | `feature <dir>` writes a 5-line README (purpose, entry point, data it owns, dependencies). `finish` refuses a change that creates a feature folder without one. |
| No overview | `map` regenerates `docs/map.md` (features, folders, open changes, undecided research). Never hand-edited, so it never goes stale. |
| A plan names a folder that doesn't exist | `check` warns about areas that point nowhere. |
| Research that never ends | `research "<topic>"` creates `research/<topic>/decision.md`, which ends in GO, NEEDS-CLARIFICATION or KILL. |
| Too many branches, and knowledge stranded on them | **Knowledge lives on the base branch, code on change branches.** `status` shows where you are and flags lessons, parked ideas and docs that exist only on a branch; `branches` gives every branch a verdict; `branches --prune --yes` deletes only what is merged and closed; `rescue <id>` brings stranded knowledge home; `drop` refuses while knowledge would be lost. |
| Too much in flight | `start` refuses beyond `max_in_progress` (default 3) open changes. |
| Lessons pile up | Lessons are searched, never loaded whole, so size costs little. A lesson that keeps recurring becomes a check: `enforce L-7 "test_totals_are_derived"`, and plans stop carrying it. `learn --general` marks the rare lesson that is about how to work anywhere; project lessons stay in the project. |
| Slow drift | `tidy` reports feature folders without READMEs, code no plan ever claimed, research without a decision, stale parked ideas and changes, repeated lessons, and branches needing a decision. Run it weekly or per milestone. |

## PR descriptions built for reviewers
`finish` writes `changes/<id>/pr.md` from the plan, the review and the diff: why, the objective, a criteria table (builder and reviewer verdicts side by side), a **"review in this order"** list (data model and schema first, then each planned area, then tests, then anything outside the plan), data impact, risks, what was deliberately left out, lessons, and the size. Use it with `gh pr create --body-file changes/<id>/pr.md`.

## Using an agent for critiques and reviews
Set `agent_cmd` in `capitan/config.json` to any command that reads a prompt on stdin and prints a reply: `claude -p`, `codex exec -`, `gemini -p`, `llm`, ... Without it, `critique <id> --print` and `review <id> --print` print the prompt to give to a fresh session; save the reply as `critique.md` / `review.md` in the change folder. (In Claude Code, the `capitan-critique` and `capitan-review` skills do this for you with a fresh subagent.)

## Configuration (`capitan/config.json`)

`capitan/config.json` is one of the rule files: changing it needs a human (see [SECURITY.md](SECURITY.md)).

| Key | Default | Meaning |
|---|---|---|
| `agent_cmd` | `""` | Command for critiques and reviews |
| `base_branch` | `""` (detect) | What branches are compared against. Empty: origin's default branch, else `main`, else `master` |
| `scope_mode` | `warn` | `block` to refuse files outside the plan's areas |
| `quick_max_files` | `3` | Code files a quick change may touch |
| `pr_max_lines`, `pr_size_mode` | `400`, `warn` | PR size budget; `block` to enforce |
| `planning_paths` | changes, GOALS, ROADMAP, LESSONS, AGENTS, docs, ... | Always allowed without a change |
| `schema_paths` | migrations, `*.sql`, `schema.prisma`, models | Changing these requires a `docs/data-model.md` update |
| `test_paths` | `tests/**`, `*.test.*`, ... | Grouped last in the PR review order |
| `feature_dirs` | `src/features/*`, `apps/*`, `packages/*`, ... | Folders that count as features (README required, listed in the map) |
| `max_in_progress` | `3` | Open changes allowed at once |
| `stale_days`, `parked_stale_days` | `30`, `60` | When `tidy` calls a change or a parked idea stale |
| `governance_paths` | `capitan/**`, `.claude/**`, `.github/**`, `.gitignore` | The rules themselves; see [SECURITY.md](SECURITY.md) |
| `keep_branches` | `main`, `master`, `develop`, `staging`, `release/*`, ... | Long-lived branches: never pruned |
| `tidy_ignore` | `tests/**`, `scripts/**`, `infra/**`, ... | Not reported as "code no plan ever claimed" |

Every gate decision is logged to `capitan/gate-log.jsonl` (git-ignored), so you can see which checks earn their keep and retire the ones that don't.

Environment variables (mainly for CI): `CAPITAN_BRANCH` (the branch name when the checkout is detached; `GITHUB_HEAD_REF` and GitLab's `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME` are read too), `CAPITAN_BASE` (base branch), `CAPITAN_CHANGE` (force the active change).

Monorepos: install capitan in the project's subfolder; it only looks at files under that folder.

## Adapters
- **Claude Code** (`init --claude`): skills `capitan-kickoff` (the kickoff and milestone interviews), `capitan-plan`, `capitan-critique`, `capitan-review` (critic and reviewer run in fresh subagents), a PreToolUse hook that blocks edits to code before a plan is approved and started, and `CLAUDE.md` → `@AGENTS.md`.
- **Anything else**: point it at `AGENTS.md`. The git hook and CI enforce the same rules for every tool.
