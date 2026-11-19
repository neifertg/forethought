---
name: forethought-plan
description: Plan a change in a forethought project before writing any code - pick the tier, anchor it to a GOALS.md objective, fill changes/<id>/plan.md, validate, get a fresh critique. Use when starting any feature, fix or refactor in a repo that has forethought/cli.py, or when asked to plan work.
---

This is a thin Claude Code wrapper. The real instructions are tool-neutral:

1. Read `forethought/playbooks/plan.md` and follow it exactly.
2. For the critique step, do not critique your own plan. Spawn a fresh `general-purpose` subagent with this prompt:
   "Run `python -m forethought critique <id> --print`. Act exactly as the critic that output describes, using the repository for context if useful. Write your reply, starting with the VERDICT line, to `changes/<id>/critique.md`. Do not edit anything else."
3. Read `changes/<id>/critique.md`, fix the plan, re-run `python -m forethought check <id>`.
4. Tell the user the plan is ready for `python -m forethought approve <id>`, with the verdict and any issues you chose not to fix. Never run approve yourself.
