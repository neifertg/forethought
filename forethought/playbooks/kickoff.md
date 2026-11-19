# Playbook: kickoff interview

Run this once at the start of a project (and again whenever the project's direction changes). An agent interviews the human; the human answers. The output is the project's foundation: `GOALS.md`, a first `docs/data-model.md`, the project section of `AGENTS.md`, research questions, and the first epics.

Everything later in forethought checks work against what this interview produces, so the quality of these answers sets the ceiling for the whole project. Garbage in, garbage out: your job as the interviewer is to keep garbage out.

## How to interview

- **One topic at a time, a few questions at a time.** Never dump the whole questionnaire. Wait for answers.
- **Push back on vague answers.** "Make onboarding better" is a wish. Ask: better for whom, measured how, compared to what? Keep asking until an answer is specific enough that someone could check it.
- **Separate outcomes from tasks.** "Build a dashboard" is a task. "Managers see overdue audits without asking anyone" is an outcome. Objectives must be outcomes.
- **Never invent.** If the human doesn't know, write it down as an open question (it becomes research), not as a guess dressed up as a fact.
- **Play it back.** After each round, summarize in a few lines and ask "is that right?" before moving on. Write files only after the human confirms.
- **Respect their time.** A good kickoff takes 30-60 minutes. If the human wants to stop, write what you have, mark the rest as open, and say what is missing.

## Rounds

### 1. The problem
- What problem does this solve, and for whom? Who feels it most today?
- What do they do now instead? What does that cost them?
- Why now?

### 2. Objectives (becomes `GOALS.md` > Objectives)
- If this project succeeds, what is different in 3, 6 and 12 months?
- Turn the answers into **3 to 5 objectives** (`O1`, `O2`...). Each one: an outcome, plus the signal that shows it is achieved (a number, an observable behavior, a user saying or doing something).
- Test each: could two people disagree about whether it was met? If yes, sharpen it.
- Rank them. When two objectives conflict, which wins?

### 3. Non-goals and constraints (becomes `GOALS.md` > Non-goals)
- What will this project deliberately not do, at least for now? (Ask for at least three. Non-goals prevent more rabbit holes than goals do.)
- Hard constraints: deadline, budget, required stack or vendors, compliance or security requirements, data that must stay in a region, performance limits, who must approve what.

### 4. First milestone (becomes `GOALS.md` > Current milestone)
- What is the smallest version a real user could use and get value from?
- How will you know the milestone is done? By when?
- What is the riskiest assumption in it, and how could we test that first?

### 5. Domain and data (becomes `docs/data-model.md`)
- What are the main things (entities) the system keeps track of? How do they relate (one-to-many, many-to-many, ownership)?
- What must always be true? (Invariants: "every invoice belongs to exactly one customer", "a closed audit can't be edited".) Each becomes a row with a test to enforce it later.
- Where does data come from, who can see what, how long must it be kept, and what happens when it is deleted?
- Sketch it back as a small diagram and a list of invariants; confirm it.

### 6. Shape of the work (becomes feature folders and epics)
- What are the main capabilities? Group them into features: each feature becomes a folder (`src/features/<name>/` or your stack's equivalent) and usually an epic.
- Which features does the first milestone need? In what order, and what depends on what?
- Everything else goes to the parking lot, not the plan.

### 7. Unknowns (becomes `research/`)
- What don't we know yet that could change the plan? (A technology choice, a vendor's limits, a legal question, whether users want X.)
- For each: the one question, which objective it serves, and how much time it deserves. Each becomes `forethought research "<topic>"`.

### 8. How we work (becomes the `## Project` section of `AGENTS.md`)
- Stack: language, framework, database, hosting. Commands to install, run, test, lint, build.
- Testing approach and the done-check for the project (the command CI must pass).
- Review preferences: which agent/model critiques plans and reviews code (`agent_cmd`), how strict the scope guard should be (`scope_mode`), how many changes may run at once (`max_in_progress`).
- Anything an agent must never do here (touch production, add dependencies without asking, etc.).

## Write the results (after the human confirms each part)

1. `GOALS.md`: objectives (`- **O1**: <outcome>. Signal: <how we'll know>`), current milestone, non-goals, constraints.
2. `docs/data-model.md`: entities and relationships diagram, invariants table (`INV-1`...), open data questions.
3. `AGENTS.md`: a `## Project` section at the top with stack, commands, testing approach and project-specific rules.
4. `forethought/config.json`: `agent_cmd`, `scope_mode`, `max_in_progress`, `feature_dirs`, `base_branch` if not detected.
5. For each open question: `python -m forethought research "<topic>"`, with its question and objective filled in.
6. For each first-milestone feature: `python -m forethought new "<feature>" --tier epic --objective O<n>`, with `children` and `depends_on` filled in from round 6. Ideas outside the milestone: `python -m forethought park "<idea>"`.
7. Run `python -m forethought check` and `python -m forethought map`.

## Finish

Show the human a one-screen summary: objectives with signals, milestone and date, non-goals, the epics in order, the research questions, and anything still open. Tell them the next step: critique and approve the first epic (`python -m forethought critique <id>`, then `approve`), and start research that blocks it.

Commit these files to the base branch. They are the project's foundation, not work in progress.

`forethought/config.json` is governance: it sets the rules agents follow, so agents can't change it alone. Before step 4, ask the human to run `python -m forethought allow-governance` (valid 30 minutes), or show them the config values and let them make the edit. The commit then warns that governance files changed; that is expected.
