---
name: forethought-critique
description: Get a fresh-context critique of an existing forethought plan (changes/<id>/plan.md or epic.md). Use when asked to review, critique or sanity-check a plan before approval.
---

Never critique a plan written in this same session; the point is fresh eyes.

Spawn a `general-purpose` subagent with this prompt:
"Run `python -m forethought critique <id> --print`. Act exactly as the critic that output describes, using the repository for context if useful. Write your reply, starting with the VERDICT line, to `changes/<id>/critique.md`. Do not edit anything else."

Then summarize the verdict and the top issues for the user.
