---
name: forethought-kickoff
description: Run the forethought kickoff interview to set a project's objectives, non-goals, first milestone, data model, feature shape, research questions and working agreements, then write GOALS.md, docs/data-model.md, AGENTS.md and the first epics. Use when starting a new forethought project, when GOALS.md still has TODOs, or when asked to set up, plan or re-plan a project's goals. Also use forethought/playbooks/milestone.md when a milestone is reached.
---

This is a thin Claude Code wrapper; the real instructions are tool-neutral.

1. Read `forethought/playbooks/kickoff.md` and follow it exactly.
2. Interview in the conversation, one round at a time. Use the AskUserQuestion tool only for real multiple-choice decisions (ranking objectives, choosing a scope mode); open questions go in plain conversation.
3. Play each round back and get a yes before writing anything.
4. Write the files listed in the playbook, run `python -m forethought check` and `python -m forethought map`, and end with the one-screen summary and the next step (critique and approve the first epic).

For a milestone review, follow `forethought/playbooks/milestone.md` the same way.
