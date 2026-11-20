# Who can change the rules, and what capitan can't stop

capitan only helps if an AI agent can't quietly switch it off. This page explains how the rules are protected, what you should set up on GitHub, and the limits that remain.

## The rule files

capitan's own files are **governance**: `capitan/` (the tool and its `config.json`), `.claude/`, `.github/` and `.gitignore` (the `governance_paths` setting).

- **Adding them** (when you first install capitan) is allowed, with a warning that lists them.
- **Changing them needs a human.** Locally, run `python -m capitan allow-governance` first (it lasts 30 minutes and is logged). On a pull request, add the `governance-approved` label. `AGENTS.md` tells agents never to do either.
- **A change can't rewrite the rules it is judged by.** The pre-commit hook runs the *last committed* copy of capitan, and CI runs the *base branch's* copy, so editing `capitan/cli.py` or the config inside a change has no effect on how that change is checked.
- **Rule changes are reviewed like code.** They are part of the code fingerprint, so editing the config after a review invalidates the review.
- With the Claude Code adapter, the edit-time hook blocks an agent from editing or creating rule files.

## Set this up on GitHub (recommended for any shared or public repo)

Two things only GitHub can enforce:

1. **A pull request runs its own copy of the workflow file**, so a PR could rewrite the check itself.
2. **Anyone with triage or write access can add a label**, including an agent holding a `gh` token.

The fix for both is code-owner review:

1. Install with `init --owner @you`. It writes `.github/CODEOWNERS` so the rule files need your review.
2. In the repository's branch protection for `main`, turn on: **Require a pull request**, **Require status checks to pass: capitan**, **Require review from Code Owners**, and **do not allow bypassing**.
3. Give agents a GitHub token that cannot approve pull requests or add labels.

## Known limits

- **The editor hook sees only an agent's edit tools.** An agent with a shell can still write files directly or run `allow-governance` itself, and a git-ignored file such as `.claude/settings.local.json` never reaches CI. If that matters, restrict the agent's shell access (for example with your tool's permission deny rules) or run it in a sandbox.
- **Local checks can be bypassed on purpose:** forging the 30-minute token, or `git commit --no-verify`. CI and branch protection are the backstop.
- **capitan can't stop deliberate forgery** of a critique or a fingerprint; local files can't. Approval is a human step for that reason, and CI is the final gate.
