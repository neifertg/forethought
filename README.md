# capitan

**Plan first, build inside the plan, prove it, remember what you learned.**

capitan keeps AI-assisted projects on course. You stay the captain: you set the goals and approve the plans. Your AI coding agent (Claude Code, Codex, Gemini CLI, Cursor, aider, or a person) is the crew that does the work. capitan sits between the two and makes sure the work stays on course.

## Why you'd want it

AI coding agents are fast, but on bigger projects they tend to:

| Without capitan | With capitan |
|---|---|
| Start coding before the problem is clear | Every piece of work starts with a one-page plan tied to one of your goals |
| Wander into side quests and rabbit holes | The plan lists which files the work may touch; side ideas go to a "parking lot" for later |
| Say "done!" when it isn't | "Done" means every success check passed and a second agent, which didn't write the code, reviewed it |
| Forget what went wrong last time | Lessons are written down and fed into every future plan automatically |
| Leave a mess of branches, half-finished work and undocumented folders | One command shows where you are; another tidies up safely |

It runs on any computer with Python and git, needs nothing else installed, and works with whatever AI tool you use.

## How it works

```
GOALS ─► PLAN ─► CRITIQUE ─► APPROVE ─► START ─► BUILD ─► REVIEW ─► FINISH ─► PR ─► CI
          │         fresh       human              in scope   fresh      lessons        merge gate
          └ lessons pre-filled                     (gate)     per AC     PR text
```

| Step | In plain words | Who |
|---|---|---|
| **Goals** | Write down what the project is for and how you'll know it worked. A short interview does this for you. | You, with the agent |
| **Plan** | Before any code, a one-page plan: what to build, how to tell it works, which files it may touch. | Agent |
| **Critique** | A *fresh* agent, one that didn't write the plan, looks for holes. | Agent |
| **Approve** | You read the page and say yes. Nothing gets built without this. | **You** |
| **Build** | The agent builds on its own branch. capitan blocks code that has no approved plan and flags files outside the plan. | Agent |
| **Review** | Another fresh agent checks the code against each success check in the plan. | Agent |
| **Finish** | capitan confirms the checks passed and a lesson was recorded, then writes the description for your pull request (PR). | Agent |
| **Merge** | You read the PR in the order it suggests and merge it. On GitHub, an automatic check (CI) re-checks everything first. | **You** |

## What you need

- **Python 3.8 or newer** ([python.org](https://www.python.org/downloads/)) and **git** ([git-scm.com](https://git-scm.com/downloads)).
- **An AI coding tool** you already use, such as Claude Code, Codex, Gemini CLI, Cursor or aider. capitan works with any of them.
- Optional: a GitHub repository, if you want the automatic check on pull requests.

## Get started (about 5 minutes)

**1. Download capitan** (once, anywhere on your computer):

```sh
git clone https://github.com/neifertg/capitan
```

**2. Add it to your project.** Use the second line instead if you use Claude Code:

```sh
python capitan/capitan/cli.py init path/to/your-project
python capitan/capitan/cli.py init path/to/your-project --claude
```

This adds a `capitan/` folder and a few planning files (`AGENTS.md`, `GOALS.md`, `ROADMAP.md`, `LESSONS.md`) to your project. It never overwrites anything you already have.

**3. Turn on the safety net and save the setup.** From your project folder (if it isn't a git repository yet, run `git init` first):

```sh
cd path/to/your-project
python -m capitan hooks
git add -A
git commit -m "Add capitan"
```

The commit prints a warning that "governance files changed". That's expected: capitan points out every change to its own rule files.

**4. Run the kickoff interview.** Open your AI tool in the project folder and say:

> Run the capitan kickoff interview.

The agent asks you about the problem, your goals and how you'll measure them, what's out of scope, your first milestone, your data, and the open questions, one topic at a time. Then it writes your project's foundation: goals, a data model, and the first big pieces of work. This is the most important step. Answer it carefully; everything later is checked against it. Near the end, the agent will ask you to run `python -m capitan allow-governance`: only you can change capitan's settings, so it needs your go-ahead to save them.

## Your first change, step by step

Most of the time you just talk to your agent. You run two commands yourself: one to approve and one to check where you are.

1. **Ask for something:** *"Plan a change: customers can reset their password."* The agent creates a plan in `changes/001-.../plan.md`, checks it, and gets a fresh critique.
2. **Read the one-page plan and approve it:**
   ```sh
   python -m capitan approve 001
   ```
3. **Let the agent build it.** It starts the change, works on its own branch, and runs the tests. If it wants to wander off-plan, capitan flags it, and new ideas get parked for later.
4. **The agent gets a review and finishes.** A fresh reviewer checks each success check, the agent records what it learned, and capitan writes `changes/001-.../pr.md`.
5. **Open the pull request** with that file as the description, read it in the suggested order, and merge.

Lost at any point? Run:

```sh
python -m capitan status
```

It tells you which branch you're on, what you're working on, what else is open, and whether anything important is sitting on another branch.

## Everyday commands

You'll mostly see your agent run these. `capitan` is short for `python -m capitan`, run from your project folder.

| Command | What it does |
|---|---|
| `capitan status` | Where am I? Branch, current work, anything forgotten elsewhere |
| `capitan new "<title>" --tier standard` | Start planning a piece of work (`quick` for a typo-sized fix) |
| `capitan approve <id>` | **You only:** approve a plan |
| `capitan park "<idea>"` | Save a side idea for later instead of doing it now |
| `capitan learn "<lesson>" --area <topic> --body "..."` | Write down something learned |
| `capitan finish <id>` | Close a piece of work and write its PR description |
| `capitan tidy` | Weekly check-up: what's drifting or forgotten |
| `capitan branches --prune` | Show branches, and safely remove finished ones (add `--yes`) |
| `capitan --help` | Every command |

## Words you'll see

| Word | Meaning |
|---|---|
| **Change** | One piece of work, with its own folder in `changes/` (plan, critique, review, PR text) |
| **Tier** | How big a change is: **quick** (a tiny fix), **standard** (one page of plan), **epic** (a big feature split into standard changes) |
| **Success checks** | The plan's "WHEN this happens, THEN that should be true" lines, each with a test that proves it |
| **Areas** | The folders a change is allowed to touch |
| **Critique / review** | A second agent with fresh eyes checking the plan (critique) or the code (review) |
| **Parking lot** | The list of good ideas saved for later, in `ROADMAP.md` |
| **Lesson** | Something learned, in `LESSONS.md`; future plans are reminded of the relevant ones |
| **Gate** | The automatic check that blocks unplanned code, when you commit and when a PR is checked |
| **PR / CI** | Pull request (a proposed change on GitHub) and continuous integration (the automatic check that runs on it) |

## Keeping a big project in order

As a project grows, capitan helps it stay navigable for you and for your agents:

- **`AGENTS.md` has a "where things go" table,** so people and agents put things in the same places.
- **Each feature folder gets a 5-line README.** `capitan map` builds a one-page overview from those READMEs.
- **Research questions end in a decision:** GO, NEEDS-CLARIFICATION or KILL.
- **Lessons and decisions live on your main branch, never stranded on a forgotten one.** `capitan rescue` brings them home.
- **`capitan tidy` lists what's drifting,** such as undocumented folders, stale work and branches to clean up.

## Learn more

- **[The full lifecycle](docs/WORKFLOW.md):** from setup through milestones, growth and handover.
- **[Reference](docs/REFERENCE.md):** every command and what it enforces, tiers, configuration, adapters.
- **[Who can change the rules](docs/SECURITY.md):** how capitan stops agents from switching it off, the GitHub settings to turn on, and the known limits.

## FAQ

**Do I need Claude Code?** No. Any AI coding tool works: they all read `AGENTS.md`, and the git hook enforces the same rules for everyone. Claude Code just gets a few extra conveniences (`init --claude`).

**Isn't this a lot of process for small fixes?** Use the **quick** tier: one line of intent, one line of "how I'll know it's fixed", your approval, done. The full plan is for real features.

**What if the plan turns out wrong halfway?** `capitan revise <id>` sends it back for a new plan and approval. Changing an approved plan quietly is caught.

**Can my agent just turn capitan off?** It's built not to let it: changing capitan's own rules needs you. See [SECURITY.md](docs/SECURITY.md) for how, and for the limits.

## For contributors

```sh
python -m unittest discover -s tests
```

## License

MIT
