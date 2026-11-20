#!/usr/bin/env python3
"""Claude Code PreToolUse hook: run the capitan gate on a file before Claude edits it.

Blocks (exit 2, reason on stderr) only when the gate itself says "blocked:" - code with no active, started
change, code on the base branch, or (with scope_mode 'block') a file outside the plan's areas.
Anything unexpected - a crash, a broken config, a missing module - lets the edit through with a warning:
the git pre-commit hook and CI are the backstop, and a broken hook must never lock you out of fixing it.
"""
import json
import os
import subprocess
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    # the project root, not the session's current folder (which follows `cd`)
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    if not path or not os.path.isdir(os.path.join(root, "capitan")):
        return 0
    try:
        rel = os.path.relpath(os.path.abspath(path), root)
    except ValueError:  # another drive on Windows
        return 0
    if rel.startswith(".."):
        return 0
    try:
        r = subprocess.run([sys.executable, "-m", "capitan", "gate", "--paths", rel], cwd=root,
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        sys.stderr.write("capitan hook could not run the gate (%s); edit allowed\n" % e)
        return 0
    blocked = [l for l in r.stderr.splitlines() if l.startswith("blocked: ")]
    if r.returncode == 1 and blocked:
        sys.stderr.write("\n".join(blocked) + "\nPlan first: see capitan/playbooks/plan.md\n")
        return 2
    if r.returncode != 0:
        sys.stderr.write("capitan gate failed unexpectedly; edit allowed. Fix it:\n%s\n" % r.stderr.strip()[-800:])
        return 0
    if r.stderr.strip():  # warnings, e.g. outside the plan's areas
        sys.stderr.write(r.stderr.strip() + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
