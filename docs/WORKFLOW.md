# Using capitan through a project's life

This guide walks a project from an empty folder to a mature codebase with many features, research tracks and contributors, showing who does what at each stage and what capitan checks along the way. Commands are written `capitan <cmd>`, short for `python -m capitan <cmd>` run from the project root.

```
 ┌──────────┐   ┌────────────┐   ┌───────────────────────────────────────────┐   ┌───────────┐
 │ 1 SET UP │ → │ 2 KICKOFF  │ → │ 3 THE CHANGE LOOP  (repeats, many at once) │ → │ 5 MILESTONE│ ─┐
 │  once    │   │ interview  │   │ plan → critique → approve → build → review │   │  review    │  │
 └──────────┘   └────────────┘   │ → finish → PR → merge                       │   └───────────┘  │
                      ▲          └───────────────────────────────────────────┘          │         │
                      │                     4 WEEKLY: tidy · map · prune                 │         │
                      └──────────────── direction changed? re-run kickoff ───────────────┘ ◄───────┘
```

## Who does what

| | You (the human) | The agent (any AI tool, or a teammate) | capitan (the checks) |
|---|---|---|---|
| Direction | Answer the kickoff interview; own the objectives | Interview you; turn answers into files | Refuses plans with no real objective |
| Plans | Approve them (only you) | Write them; get them critiqued | Validates plans; ties a critique to the exact plan version |
| Code | Read the PR; merge | Build inside the plan; get it reviewed | Blocks unplanned code; flags out-of-scope files; ties a review to the exact code |
| Memory | Decide what matters | Record lessons, park ideas, rescue knowledge | Feeds relevant lessons into every plan; keeps knowledge on the base branch |
| Order | Run tidy, decide | Fix what tidy finds | Reports drift; prunes only safe branches |

---

## 1. Set up (once, ~5 minutes)

```sh
python path/to/capitan/capitan/cli.py init path/to/project          # any agent
python path/to/capitan/capitan/cli.py init path/to/project --claude # + Claude Code skills and edit hook
#   add --owner @you to write .github/CODEOWNERS (only you approve changes to the rules)
cd path/to/project
git init                       # if it is not a repo yet
capitan hooks              # pre-commit gate
```

Commit the generated files. The commit prints a *governance files changed* warning, which is expected here. capitan's own files (its config, `.claude/`, `.github/`, `.gitignore`) are **governance**: they set the rules. Adding them is fine, but changing them later needs you: run `capitan allow-governance` first (valid 30 minutes) for a local commit, and add the `governance-approved` label to a PR that changes them. The pre-commit hook judges with the last committed rules and CI with the base branch's rules, so a change can't rewrite the rules it is judged by, with one exception only GitHub can close: a pull request runs its own copy of the workflow file. So on GitHub, run `init` with `--owner @you` (it writes `.github/CODEOWNERS` for the rule files) and protect `main`: require a pull request, require the `capitan` status check, require review from Code Owners, and allow no bypass. Give agents a token that can't approve pull requests or add labels: anyone with triage or write access can add the `governance-approved` label, and that includes an agent with a `gh` token. Also know the local limits: the editor hook sees only an agent's edit tools, so an agent with a shell can still write files or run `allow-governance` itself; restrict its shell or sandbox it if that matters. That makes the rules hold even if someone, or some agent, skips a step locally.

If you use the `scaffold-ai-project` skill, it does this for you and sets up the folder layout.

## 2. Kickoff interview (once, 30-60 minutes)

Start a fresh agent session and ask it to run the kickoff: *"Run the capitan kickoff interview"* (Claude Code: the `capitan-kickoff` skill; any other tool: point it at `capitan/playbooks/kickoff.md`).

The agent interviews you one topic at a time and pushes back on vague answers:

1. **The problem.** Who has it, what they do today, why now.
2. **Objectives.** 3-5 outcomes, each with a signal that proves it, ranked.
3. **Non-goals and constraints.** What you will deliberately not do; deadlines, budget, compliance, required stack.
4. **First milestone.** The smallest version a real user gets value from, and when.
5. **Domain and data.** Entities, relationships, and the invariants that must always hold.
6. **Shape of the work.** Features (each becomes a folder and usually an epic), their order and dependencies.
7. **Unknowns.** Questions that could change the plan; each becomes a research track.
8. **How we work.** Stack, commands, testing, who reviews, how strict the gates are.

It plays each round back for your confirmation, then writes `GOALS.md`, `docs/data-model.md`, the `## Project` section of `AGENTS.md`, `capitan/config.json`, one `research/<topic>/` per unknown, and the first epics as drafts. Ideas outside the first milestone go to the parking lot.

Commit the results to `main`. The interview's settings go in `capitan/config.json`, which is governance, so you run `capitan allow-governance` first (the agent will ask).

**What you have afterwards:** a project whose every later decision can be checked against written objectives. `capitan new` refuses to plan work until `GOALS.md` has real objectives, which is why this step comes first.

**Then:** critique and approve the first epic (below), and start whatever research blocks it.

## 3. The change loop (every piece of work)

Each piece of work is a **change**: a folder in `changes/<id>/` holding its plan, critique, review and PR description. Big things are **epics** that split into standard changes; trivial fixes are **quick** changes.

### Start of every session
`capitan status` shows the branch you are on, the change it belongs to, what else is open, and any knowledge sitting on a branch that is not on `main` yet. The agent reads `GOALS.md`, `docs/map.md` and the README of the feature folder it is about to touch, not the whole codebase.

### a. Plan
```sh
capitan new "Customer can check out" --tier standard --objective O1 --areas "src/features/orders/**"
```
The agent fills in `changes/<id>/plan.md` (`capitan/playbooks/plan.md`): criteria as `WHEN ... THEN ...` with the test that proves each, the areas it may touch, a time box, data impact, test plan, risks, and what is out of scope. Past lessons for the area are already filled in. `capitan check <id>` until it passes; one page max.

**Children of an epic:** `capitan new "<child>" --tier standard --epic <epic-id> --child <key>`. A child can't start before the children it depends on are done.

### b. Critique
`capitan critique <id>` gives the plan to a fresh agent that did not write it. It checks goal fit, testability, data impact, scope and lessons, and answers READY or REVISE. Fix and re-critique until READY. The critique only counts for the exact plan it saw.

### c. Approve (you)
`capitan approve <id>`. Only you run this. From now on the plan is a contract; to change it, `capitan revise <id>` sends it back through critique and approval.

### d. Build
```sh
capitan start <id>
git switch -c change/<id>
```
At most `max_in_progress` changes (default 3) run at once. While building:
- Code commits without a started change, on `main`, or for an epic are refused by the pre-commit gate (and in Claude Code, edits are refused before they happen).
- Files outside the plan's areas are flagged. Side ideas: `capitan park "<idea>" --from <id>`, then carry on.
- Something surprising or painful: `capitan learn "<title>" --area <a> --body "<what happened; what to do next time>"`.
- A new feature folder gets a README: `capitan feature src/features/<name>`.
- Schema changes come with a `docs/data-model.md` update.
- Each criterion is marked `pass`/`fail` in the plan from real test output only.

### e. Review
`capitan review <id>` gives the plan and the diff to a fresh reviewer. It returns PASS, FAIL or UNVERIFIED for every criterion, plus findings. Fix every FAIL and review again; the review only counts for the exact code it saw.

### f. Finish and merge
`capitan finish <id>` closes the change only if every criterion passed, the review passed on the current code, a lesson was recorded (or you said why not), new feature folders have READMEs, and schema changes updated the data model. It writes `changes/<id>/pr.md`:

- why, and which objective it serves
- a criteria table with the builder's and the reviewer's verdicts side by side
- **review in this order**: data model and schema first, then each planned area, then tests, then anything outside the plan
- data impact, risks, what was deliberately left out, lessons, size

Open the PR with it (`gh pr create --body-file changes/<id>/pr.md`). CI runs `capitan gate --ci`: the change must be finished and its review must still match the code exactly. You read the PR in the suggested order and merge. Then `capitan branches --prune --yes` deletes the merged branch.

**If a change is abandoned:** `capitan drop <id>`. If its branch holds lessons, parked ideas or docs that are not on `main`, drop refuses until you `capitan rescue <id>` (from `main`) and commit, so nothing learned is lost.

## 4. Weekly (10 minutes)

```sh
capitan tidy      # what is drifting
capitan map       # refresh docs/map.md
capitan branches  # every branch with a verdict; --prune --yes removes the safe ones
```

`tidy` lists feature folders without a README, code no plan ever claimed, research without a decision, parked ideas and changes that went stale, lessons that keep coming back, and branches that need a decision. Each item has an obvious next action; most take a minute.

## 5. Milestone review (each milestone)

Ask the agent to run the milestone review (`capitan/playbooks/milestone.md`; Claude Code: the `capitan-kickoff` skill covers it). It reads the state of the project first, then asks you:

1. Did the milestone deliver its objectives? Check each signal against reality.
2. What did we learn? Which assumptions were wrong?
3. Are the objectives still right? Keep, sharpen, re-rank, add, retire.
4. Are the non-goals still right?
5. What is the next milestone, its done-definition and date?
6. For each parked idea: promote, keep or delete.

Then it does the housekeeping `tidy` points to: decide open research, close stale changes, prune branches, write missing READMEs, turn recurring lessons into checks (`capitan enforce <L-n> "<check>"`), and update the data model. It updates `GOALS.md`, creates the next epics, and commits.

**Lessons, two levels.** Project lessons stay in the project's `LESSONS.md`; they are searched, never loaded whole, so they don't weigh anything down. The rare lesson about *how you work*, true in any project, is recorded with `--general`; at milestone reviews, if it has also shown up elsewhere, copy it into your personal setup.

## 6. As the project grows

| Growth | How it stays orderly |
|---|---|
| New feature | Its own folder and README (`capitan feature`), an epic, children planned against it. |
| New research question | `capitan research "<topic>"`; it ends in GO, NEEDS-CLARIFICATION or KILL. |
| Parallel work | Up to `max_in_progress` changes, one branch each; epic dependencies decide what can run side by side. |
| New person or agent joins | They read `AGENTS.md`, run `capitan status`, and read `docs/map.md`; no tribal knowledge needed. |
| Direction changes | Re-run the kickoff interview; revise affected plans (`capitan revise`); drop what no longer serves an objective. |
| A rule keeps being broken | Make it a check: a test, a lint rule, a stricter setting (`scope_mode: block`, `pr_size_mode: block`), then `enforce` the lesson. |

## 7. Winding down or handing over

1. `capitan branches` and `rescue` anything stranded; `drop` or finish every open change.
2. `capitan tidy` until it is quiet; `capitan map`.
3. A last milestone review: record what the project achieved against each objective, and promote any general lessons.
4. The repository now explains itself: goals, decisions, data model, lessons, and the history of every change with its plan, critique, review and PR.

---

## Cheat sheet

| When | Command |
|---|---|
| Every session | `capitan status` |
| New work | `new` → fill plan → `check` → `critique` → (you) `approve` |
| Building | `start` → `git switch -c change/<id>` → build → `park` / `learn` / `feature` |
| Done building | `review` → fix → `finish` → PR from `pr.md` → merge → `branches --prune --yes` |
| Change of plan | `revise <id>` (approved plans), `drop <id>` (abandon; `rescue` first if asked) |
| Weekly | `tidy`, `map`, `branches` |
| Milestone | milestone review interview, `enforce` recurring lessons |
| Lost? | `capitan --help`, `AGENTS.md`, `docs/map.md` |
