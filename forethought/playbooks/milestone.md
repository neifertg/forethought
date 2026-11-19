# Playbook: milestone review

Run this when a milestone is reached (or missed), and at least every few weeks on a long project. It is a short interview plus housekeeping: it keeps the goals honest and the project tidy as it grows.

## 1. Look before talking
Run and read: `python -m forethought status`, `tidy`, `branches`, `map`, and `ROADMAP.md`. Note what was finished, what is still open, what drifted.

## 2. Interview the human (one topic at a time; play back before writing)
1. **Did the milestone deliver its objectives?** Check each objective's signal against reality, not against the plan. What does the evidence say?
2. **What did we learn?** About users, the domain, the data model, the technology. Which assumptions were wrong?
3. **Are the objectives still right?** Keep, sharpen, re-rank, add or retire. A changed objective is a decision: say why in `GOALS.md`.
4. **Non-goals:** still right? Did anything sneak in that should not have?
5. **Next milestone:** smallest valuable next step, its done-definition and date, its riskiest assumption.
6. **Parking lot:** for each parked idea, promote (it becomes a change or epic), keep, or delete. Ideas older than a few months that nobody misses: delete.

## 3. Housekeeping (from what tidy reported)
- Research without a decision: decide (GO, NEEDS-CLARIFICATION or KILL) or kill it.
- Stale changes: finish, revise or drop (rescue knowledge first).
- Branches: `python -m forethought branches --prune` for the safe ones; decide the rest.
- Feature folders without a README: write them (`forethought feature <dir>`).
- Lessons that keep coming back: turn each into a check, then `forethought enforce <L-n> "<check>"`.
- Lessons marked general: if one also showed up in another project, copy it into your personal setup (for example your global agent instructions). Leave project lessons in the project.
- Data model: does `docs/data-model.md` still match reality? Fix it in a change if not.

## 4. Write and commit
Update `GOALS.md` (objectives, milestone, non-goals), create the next epics with `forethought new --tier epic`, run `check` and `map`, and commit to the base branch. Summarize for the human in one screen: what was achieved, what changed and why, what is next.
