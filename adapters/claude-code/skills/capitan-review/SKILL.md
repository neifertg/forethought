---
name: capitan-review
description: Get a fresh-context code review of an in-progress capitan change, with one PASS/FAIL/UNVERIFIED verdict per acceptance criterion. Use before finishing a change, or when asked to review the code for a change.
---

Never review code written in this same session; the point is fresh eyes.

1. Make sure the criteria in `changes/<id>/plan.md` reflect real test results.
2. Spawn a `general-purpose` subagent with this prompt:
   "Run `python -m capitan review <id> --print`. Act exactly as the code reviewer that output describes; run the project's tests if you can. Write your reply, starting with the VERDICT line, to `changes/<id>/review.md`. Do not edit anything else."
3. Summarize the verdict and per-criterion results for the user. On FAIL, fix the findings and review again (the code fingerprint changes, so an old review never counts).
4. When it passes: record what the change taught you (`python -m capitan learn ...`), then `python -m capitan finish <id>`.
