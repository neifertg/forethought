#!/usr/bin/env python3
"""forethought: plan-first project harness. Works with any coding agent or none.

Python 3.8+, standard library only. Run from the project root:
    python -m forethought <command> ...

Plan
  new "<title>" --tier T [...]   start a change: quick | standard | epic
  check [<id>]                   validate one plan, or every open plan (exit 1 on errors)
  critique <id> [--print]        fresh-context critique of the plan (runs config agent_cmd, or prints the prompt)
  approve <id>                   human sign-off: the plan becomes buildable
  revise <id>                    send an approved plan back to draft to change it (needs approval again)
Build
  start <id>                     approved -> in progress (then: git switch -c change/<id>)
  park "<idea>" [--from <id>]    send a side idea to the parking lot instead of doing it now
  review <id> [--print]          fresh-context code review, one verdict per acceptance criterion
  finish <id>                    close: criteria pass, review current, lessons recorded -> writes pr.md
  pr <id>                        (re)write the PR description from the plan, review and diff
  drop <id>                      abandon an open change, on purpose (refuses while knowledge would be stranded)
Enforce
  gate [--staged|--ci|--paths] [--base B]   plan gate + scope guard (git hook, CI, agent hooks)
  hooks                          install the git pre-commit gate
  allow-governance               HUMAN ONLY: allow changes to forethought's own rules for 30 minutes
Remember
  learn "<title>" --area a,b --body "..." [--general]   record a lesson (--general: true beyond this project)
  recall <terms...>              search past lessons
  enforce <L-n> "<check>"        retire a lesson into a test/lint rule/hook; plans stop carrying it
  research "<topic>"             start research/<topic>/decision.md (ends GO | NEEDS-CLARIFICATION | KILL)
Stay organized
  status                         where am I: branch, change, other open work, knowledge not on main yet
  branches [--prune [--yes]]     every branch with its change and a verdict; prune only what is merged and closed
  rescue <id|branch>             bring lessons, parked ideas and notes from a branch onto the base branch
  feature <dir>                  create a feature folder's README (purpose, entry point, owns, depends on)
  map                            regenerate docs/map.md: features, folders, open changes
  tidy                           report what is drifting: missing READMEs, unclaimed code, stale work, branches
Setup
  init <dir> [--claude]          install into a project (run from the forethought source repo)
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # <project>/forethought  (or <source repo>/forethought)
# project root. FORETHOUGHT_ROOT lets a copy of the rules from the base branch (CI) or the last commit
# (pre-commit) judge the working tree, so a change can never edit the rules it is judged by.
ROOT = Path(os.environ["FORETHOUGHT_ROOT"]).resolve() if os.environ.get("FORETHOUGHT_ROOT") else HERE.parent
TIERS = ("quick", "standard", "epic")
STATUSES = ("draft", "approved", "in-progress", "done", "dropped")
OPEN = ("draft", "approved", "in-progress")
PLAN_BLOCK = re.compile(r"```json plan[ \t]*\r?\n(.*?)\r?\n```", re.S)
STOP = set("the and for with from into that this then when will should must have add fix make use new "
           "update support allow change remove create".split())

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ---------- small helpers ----------

def today():
    return datetime.date.today().isoformat()  # read the clock at the moment of use


def die(msg, code=1):
    print("forethought: " + msg, file=sys.stderr)
    sys.exit(code)


def read(p):
    return Path(p).read_text(encoding="utf-8")


def write(p, text):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(text, encoding="utf-8", newline="\n")


DEFAULTS = {
    "agent_cmd": "", "base_branch": "", "plan_max_lines": 80,
    "scope_mode": "warn", "quick_max_files": 3, "pr_max_lines": 400, "pr_size_mode": "warn",
    "review_max_chars": 150000, "max_in_progress": 3, "stale_days": 30, "parked_stale_days": 60,
    "feature_dirs": ["src/features/*", "features/*", "apps/*", "packages/*", "services/*", "modules/*"],
    "planning_paths": ["changes/**", "GOALS.md", "ROADMAP.md", "LESSONS.md", "AGENTS.md", "CLAUDE.md",
                       "README.md", "**/README.md", "docs/**", "research/**/*.md"],
    # the rules themselves: no change needed (setup and kickoff commit them), but every change is flagged loudly
    "governance_paths": ["forethought/**", ".claude/**", ".github/**", ".gitignore"],
    # never pruned, never treated as a change branch
    "keep_branches": ["main", "master", "develop", "dev", "staging", "production", "release/*", "hotfix/*"],
    # tidy doesn't ask "which plan claimed this?" about these (tests, scripts, infra usually predate plans)
    "tidy_ignore": ["tests/**", "test/**", "scripts/**", "infra/**", "tools/**", ".github/**"],
    "schema_paths": ["**/migrations/**", "**/schema.prisma", "**/schema.sql", "**/*.sql", "**/models.py",
                     "**/models/**"],
    "test_paths": ["tests/**", "test/**", "**/__tests__/**", "**/*.test.*", "**/*.spec.*", "**/test_*.py",
                   "**/*_test.*"],
}


def config():
    p = HERE / "config.json"
    cfg = dict(DEFAULTS)
    if p.exists():
        cfg.update(json.loads(read(p)))
    return cfg


def slug(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:40].rstrip("-") or "change"


def change_dirs():
    d = ROOT / "changes"
    if not d.exists():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and re.match(r"^\d{3,}-", p.name)
                   and ((p / "plan.md").exists() or (p / "epic.md").exists())),
                  key=lambda p: int(p.name.split("-", 1)[0]))


def find_change(cid, required=True):
    for d in change_dirs():
        num = d.name.split("-", 1)[0]
        if d.name == cid or (cid.isdigit() and int(num) == int(cid)):
            return d
    if required:
        die("no change '%s' in changes/" % cid)
    return None


def plan_file(d):
    for name in ("plan.md", "epic.md"):
        if (d / name).exists():
            return d / name
    die("%s has no plan.md or epic.md" % d.name)


def load_plan(path):
    text = read(path)
    m = PLAN_BLOCK.search(text)
    if not m:
        return text, None, "missing the ```json plan block"
    try:
        return text, json.loads(m.group(1)), None
    except ValueError as e:
        return text, None, "the ```json plan block is not valid JSON (%s)" % e


def save_plan(path, text, data):
    block = "```json plan\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"
    write(path, PLAN_BLOCK.sub(lambda _m: block, text, count=1))


def sections(text):
    """'## Heading' -> body text, outside the json block."""
    body = PLAN_BLOCK.sub("", text)
    out, cur = {}, None
    for line in body.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            cur = h.group(1).strip().lower()
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def goal_ids():
    """Objective IDs from '- **O1**: text' lines in the '## Objectives' section only.
    An objective with no text, or still holding a TODO placeholder, does not count."""
    p = ROOT / "GOALS.md"
    if not p.exists():
        return set()
    section = "\n".join(v for k, v in sections(read(p)).items() if "objective" in k)
    ids = set()
    for m in re.finditer(r"^\s*[-*]\s*\*\*(O\d+):?\*\*\s*:?\s*(.*)$", section, re.M):
        text = m.group(2).strip()
        if text and not re.search(r"\btodo\b", text, re.I):
            ids.add(m.group(1))
    return ids


# ---------- lessons ----------

LESSON_HEAD = re.compile(r"^###\s+(L-\d+)\s+\((\d{4}-\d{2}-\d{2})\)\s+\[([^\]]*)\]\s+(.+)$", re.M)


def lessons_parse(text):
    heads = list(LESSON_HEAD.finditer(text))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end():end].strip()
        enforced = re.search(r"^Enforced by:\s*(.+)$", body, re.M)
        out.append({"id": h.group(1), "date": h.group(2),
                    "areas": [a.strip() for a in h.group(3).split(",") if a.strip()],
                    "title": h.group(4).strip(), "body": body,
                    "raw": text[h.start():end].strip(),
                    "enforced": enforced.group(1).strip() if enforced else None,
                    "general": bool(re.search(r"^Scope:\s*general\b", body, re.M | re.I))})
    return out


def lessons_all():
    p = ROOT / "LESSONS.md"
    return lessons_parse(read(p)) if p.exists() else []


def terms_from(*chunks):
    words = []
    for c in chunks:
        for w in re.findall(r"[a-z0-9]+", (c or "").lower()):
            if len(w) > 2 and w not in STOP and w not in words:
                words.append(w)
    return words


def lessons_search(terms, limit=5, include_enforced=False):
    """Enforced lessons are handled by a check now, so plans and critiques don't need to carry them."""
    scored = []
    for l in lessons_all():
        if l["enforced"] and not include_enforced:
            continue
        hay_head = (l["title"] + " " + " ".join(l["areas"])).lower()
        hay_body = l["body"].lower()
        score = sum(3 * hay_head.count(t) + hay_body.count(t) for t in terms)
        if score:
            scored.append((score, l))
    scored.sort(key=lambda x: (-x[0], x[1]["id"]))
    return [l for _, l in scored[:limit]]


def lessons_block(terms):
    hits = lessons_search(terms)
    if not hits:
        return "- None found for: %s. Add any you know of." % (", ".join(terms) or "(no terms)")
    return "\n".join("- %s %s [%s]" % (l["id"], l["title"], ", ".join(l["areas"])) for l in hits)


# ---------- validation ----------

def check_plan(d):
    """Return (data, errors) for one change folder."""
    path = plan_file(d)
    text, data, err = load_plan(path)
    if err:
        return None, [err]
    errs = []
    tier, status = data.get("tier"), data.get("status")
    if data.get("id") != d.name:
        errs.append("json id '%s' does not match folder '%s'" % (data.get("id"), d.name))
    if tier not in TIERS:
        errs.append("tier must be one of %s" % ", ".join(TIERS))
    if status not in STATUSES:
        errs.append("status must be one of %s" % ", ".join(STATUSES))
    todo = [str(i) for i, l in enumerate(text.splitlines(), 1) if re.search(r"\bTODO:", l)]
    if todo:
        errs.append("still contains TODO placeholders (lines %s)" % ", ".join(todo))

    if tier == "quick":
        for k in ("intent", "done_check"):
            if not str(data.get(k, "")).strip():
                errs.append("quick change needs '%s'" % k)
        return data, errs + drift(d, data)

    goals = goal_ids()
    if data.get("objective") not in goals:
        errs.append("objective '%s' is not an objective in GOALS.md (have: %s)"
                    % (data.get("objective"), ", ".join(sorted(goals)) or "none"))
    secs = sections(text)
    need = ["why", "out of scope", "relevant lessons"]

    if tier == "standard":
        need += ["data impact", "test plan", "risks"]
        if not data.get("areas"):
            errs.append("'areas' must list the paths/globs this change may touch")
        if not str(data.get("timebox", "")).strip():
            errs.append("'timebox' is required (e.g. '1 day')")
        crit = data.get("criteria") or []
        if not crit:
            errs.append("at least one acceptance criterion is required")
        seen = set()
        for n, c in enumerate(crit, 1):
            cid = str(c.get("id", "")).strip()
            if not re.match(r"^AC-\d+$", cid):
                errs.append("criterion #%d needs an id like AC-1" % n)
                cid = "#%d" % n
            if cid in seen:
                errs.append("duplicate criterion id %s" % cid)
            seen.add(cid)
            for k in ("when", "then", "test"):
                if not str(c.get(k, "")).strip():
                    errs.append("criterion %s is missing '%s'" % (cid, k))
            if c.get("status", "pending") not in ("pending", "pass", "fail"):
                errs.append("criterion %s status must be pending|pass|fail" % cid)
        lines = [l for l in PLAN_BLOCK.sub("", text).splitlines() if l.strip()]
        limit = config()["plan_max_lines"]
        if len(lines) > limit:
            errs.append("plan prose is %d lines; keep it to one page (<= %d). Split into an epic if it is bigger."
                        % (len(lines), limit))

    if tier == "epic":
        kids = data.get("children") or []
        if len(kids) < 2:
            errs.append("an epic needs at least 2 children (otherwise make it a standard change)")
        ids = [k.get("key") for k in kids]
        for k in kids:
            if not k.get("key") or not k.get("title"):
                errs.append("each child needs 'key' and 'title'")
            for dep in k.get("depends_on", []):
                if dep not in ids:
                    errs.append("child %s depends on unknown child %s" % (k.get("key"), dep))
        if not errs and has_cycle(kids):
            errs.append("children depends_on has a cycle")

    if data.get("epic"):
        epic_dir = find_change(str(data["epic"]), required=False)
        edata = epic_child = None
        if epic_dir:
            _, edata, _ = load_plan(plan_file(epic_dir))
        if not edata or edata.get("tier") != "epic":
            errs.append("'epic' %s is not an epic in changes/" % data["epic"])
        else:
            epic_child = next((k for k in edata.get("children", []) if k.get("key") == data.get("child")), None)
            if not epic_child:
                errs.append("'child' %s is not a child key of epic %s" % (data.get("child"), data["epic"]))
            if edata.get("status") not in ("approved", "in-progress", "done") or drift(epic_dir, edata):
                errs.append("parent epic %s is not in an approved, unchanged state" % data["epic"])

    for s in need:
        if not secs.get(s):
            errs.append("section '## %s' is missing or empty" % s.title())
    return data, errs + drift(d, data)


def drift(d, data):
    """An approved plan is a contract: editing it afterwards needs a revise and a new approval."""
    if data.get("status") in ("approved", "in-progress") and data.get("approved_hash") != plan_hash(d):
        return ["the plan changed after approval. To change it: python -m forethought revise %s "
                "(back to draft, then critique and approve again)" % d.name]
    return []


def epic_children(epic_name):
    """child key -> list of change data built for it."""
    out = {}
    for d in change_dirs():
        _, data, err = load_plan(plan_file(d))
        if not err and data.get("epic") == epic_name:
            out.setdefault(data.get("child"), []).append(data)
    return out


def has_cycle(kids):
    graph = {k["key"]: list(k.get("depends_on", [])) for k in kids}
    state = {}

    def visit(n):
        if state.get(n) == 1:
            return True
        if state.get(n) == 2:
            return False
        state[n] = 1
        if any(visit(m) for m in graph.get(n, [])):
            return True
        state[n] = 2
        return False

    return any(visit(n) for n in graph)


# ---------- roadmap ----------

def refresh_roadmap():
    p = ROOT / "ROADMAP.md"
    if not p.exists():
        return
    head = ["| ID | Title | Tier | Objective | Status |", "|---|---|---|---|---|"]
    open_rows, closed_rows = [], []
    for d in change_dirs():
        try:
            text, data, err = load_plan(plan_file(d))
        except SystemExit:
            continue
        if err:
            open_rows.append("| %s | (unreadable plan) | | | |" % d.name)
            continue
        title = (re.search(r"^#\s+(.+)$", text, re.M) or [None, d.name])[1]
        row = "| %s | %s | %s | %s | %s |" % (d.name, title, data.get("tier", ""),
                                             data.get("objective", "-"), data.get("status", ""))
        (open_rows if data.get("status") in OPEN else closed_rows).append(row)
    keep = 10  # a growing project keeps a readable roadmap: open work in full, recent history, a count of the rest
    rows = ["**Open**", ""] + head + (open_rows or ["| - | nothing open | | | |"])
    if closed_rows:
        rows += ["", "**Recently closed**", ""] + head + closed_rows[-keep:][::-1]
        if len(closed_rows) > keep:
            rows += ["", "%d older closed changes are in `changes/` (and git history)." % (len(closed_rows) - keep)]
    text = read(p)
    new = re.sub(r"(<!-- forethought:changes:start -->).*?(<!-- forethought:changes:end -->)",
                 lambda m: m.group(1) + "\n" + "\n".join(rows) + "\n" + m.group(2), text, flags=re.S)
    if new != text:
        write(p, new)


# ---------- commands ----------

def cmd_init(a):
    src_project = HERE.parent / "project"
    if not src_project.exists():
        die("init runs from the forethought source repo, not from an installed copy")
    target = Path(a.dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    made, kept = [], []

    def place(src, dst):
        if dst.exists():
            kept.append(str(dst.relative_to(target)))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            made.append(str(dst.relative_to(target)))

    for f in sorted(HERE.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            place(f, target / "forethought" / f.relative_to(HERE))
    for f in sorted(src_project.rglob("*")):
        if f.is_file():
            place(f, target / f.relative_to(src_project))
    if a.claude:
        adapter = HERE.parent / "adapters" / "claude-code"
        for f in sorted((adapter / "skills").rglob("*")):
            if f.is_file():
                place(f, target / ".claude" / "skills" / f.relative_to(adapter / "skills"))
        place(adapter / "hooks" / "forethought_gate.py", target / ".claude" / "hooks" / "forethought_gate.py")
        st = target / ".claude" / "settings.json"
        if st.exists():
            kept.append(".claude/settings.json (merge the PreToolUse hook from adapters/claude-code/settings.json "
                        "to block code edits before a plan is approved)")
        else:
            place(adapter / "settings.json", st)
        cm = target / "CLAUDE.md"
        if not cm.exists():
            write(cm, "@AGENTS.md\n")
            made.append("CLAUDE.md")
        elif "@AGENTS.md" not in read(cm):
            kept.append("CLAUDE.md (add a line '@AGENTS.md' so Claude Code loads the forethought rules)")
    gi = target / ".gitignore"
    for line in ("forethought/gate-log.jsonl", "forethought/cache.json", "forethought/__pycache__/"):
        if not gi.exists() or line not in read(gi):
            write(gi, (read(gi).rstrip("\n") + "\n" if gi.exists() else "") + line + "\n")
            made.append(".gitignore (+ %s)" % line)
    owners = target / ".github" / "CODEOWNERS"
    if a.owner:
        # GitHub runs a PR's own copy of the workflow, so only code-owner review stops a PR from rewriting the
        # gate. With "Require review from Code Owners" on, only this owner can approve rule changes.
        owner = a.owner if a.owner.startswith("@") else "@" + a.owner
        rules = "".join("%s %s\n" % (p, owner) for p in ("/forethought/", "/.github/", "/.claude/", "/.gitignore"))
        if owners.exists():
            kept.append(".github/CODEOWNERS (add these lines yourself:\n%s)" % rules.rstrip())
        else:
            write(owners, "# Changes to forethought's rules need review from:\n" + rules)
            made.append(".github/CODEOWNERS (rule changes need %s's review)" % owner)
    for m in made:
        print("  created  " + m)
    for k in kept:
        print("  kept     " + k + " (already existed)")
    if not a.owner and not owners.exists():
        print("Tip: init --owner @you writes .github/CODEOWNERS so only you can approve changes to the rules "
              "(then turn on 'Require review from Code Owners' in branch protection).")
    print("Next: in a git repo run: python -m forethought hooks\n"
          "Then start a fresh agent session and ask it to run the kickoff interview "
          "(forethought/playbooks/kickoff.md; Claude Code: the forethought-kickoff skill).\n"
          "Lifecycle guide: docs/WORKFLOW.md in the forethought repo.")


def cmd_new(a):
    if a.tier != "quick" and not goal_ids():
        die("GOALS.md has no objectives yet. Under a '## Objectives' heading, write lines like "
            "'- **O1**: <outcome>'. Every change must say which objective it moves.")
    if (a.epic or a.child) and not (a.epic and a.child and a.tier == "standard"):
        die("--epic and --child go together, on a standard change")
    if a.epic:
        epic_dir = find_change(a.epic)
        _, edata, _ = load_plan(plan_file(epic_dir))
        if not edata or edata.get("tier") != "epic":
            die("%s is not an epic" % a.epic)
        if a.child not in [k.get("key") for k in edata.get("children", [])]:
            die("epic %s has no child '%s'" % (epic_dir.name, a.child))
        if edata.get("status") not in ("approved", "in-progress") or drift(epic_dir, edata):
            die("epic %s is '%s' or changed since approval; approve the epic before starting its children"
                % (epic_dir.name, edata.get("status")))
        a.epic = epic_dir.name
        a.objective = a.objective or edata.get("objective")
    nums = [int(d.name.split("-", 1)[0]) for d in change_dirs()]
    cid = "%03d-%s" % ((max(nums) + 1) if nums else 1, slug(a.title))
    d = ROOT / "changes" / cid
    areas = [x.strip() for x in (a.areas or "").split(",") if x.strip()]
    if a.tier == "quick":
        ok = bool((a.intent or "").strip() and (a.done_check or "").strip())
        data = {"id": cid, "tier": "quick", "status": "draft", "created": today(),
                "intent": a.intent or "", "done_check": a.done_check or ""}
        write(d / "plan.md", "# %s\n\n```json plan\n%s\n```\n" % (a.title, json.dumps(data, indent=2)))
        refresh_roadmap()
        if not ok:
            die("created changes/%s/plan.md as DRAFT. A quick change needs --intent and --done-check; "
                "fill both in the json block, then ask the human to approve it." % cid)
        # Even a quick change needs a human yes (no critique, though), so an agent can never approve its own work.
        print("created changes/%s/plan.md (quick). Ask the human to run: python -m forethought approve %s" % (cid, cid))
    else:
        tpl = read(HERE / "templates" / ("plan.md" if a.tier == "standard" else "epic.md"))
        terms = terms_from(a.title, " ".join(areas))
        text = (tpl.replace("__TITLE__", a.title).replace("__ID__", cid)
                .replace("__DATE__", today()).replace("__OBJECTIVE__", a.objective or "TODO")
                .replace("__LESSONS__", lessons_block(terms)))
        _, data, _ = load_plan_text(text)
        if areas:
            data["areas"] = areas
        if a.epic:
            data["epic"], data["child"] = a.epic, a.child
        name = "plan.md" if a.tier == "standard" else "epic.md"
        write(d / name, text)
        save_plan(d / name, text, data)
        print("created changes/%s/%s" % (cid, name))
        print("Fill every TODO, then: python -m forethought check %s" % cid)
    refresh_roadmap()


def load_plan_text(text):
    m = PLAN_BLOCK.search(text)
    return text, json.loads(m.group(1)), None


def cmd_check(a):
    dirs = [find_change(a.id)] if a.id else change_dirs()
    bad = 0
    for d in dirs:
        data, errs = check_plan(d)
        if not a.id and data and data.get("status") not in OPEN:
            continue
        if errs:
            bad += 1
            print("FAIL %s" % d.name)
            for e in errs:
                print("  - " + e)
        else:
            print("ok   %s" % d.name)
        for w in area_warnings(data or {}):
            print("  warning: " + w)
    if not dirs:
        print("no changes yet")
    sys.exit(1 if bad else 0)


VERDICT_LINE = re.compile(r"^[\s>*_`#-]*VERDICT[\s*_]*:[\s*_]*(READY|REVISE)\b", re.I)
LIFECYCLE_KEYS = ("status", "approved", "in_progress", "done", "dropped", "critique_skipped", "approved_hash",
                  "review_skipped", "no_lessons", "no_model_change", "knowledge_abandoned")


def verdict(text):
    """REVISE if any verdict line says REVISE (so 'REVISE ... READY once fixed' stays REVISE),
    else READY if one says READY. Tolerates bold/quotes/fences; ignores an echoed
    'READY | REVISE' template line."""
    found = set()
    for line in text.splitlines():
        if re.search(r"READY\s*\|\s*REVISE", line, re.I):
            continue
        m = VERDICT_LINE.match(line)
        if m:
            found.add(m.group(1).upper())
    return "REVISE" if "REVISE" in found else ("READY" if found else None)


def plan_hash(d):
    """Fingerprint of what the critic judged: prose + plan json, ignoring lifecycle fields."""
    text, data, _ = load_plan(plan_file(d))
    data = {k: v for k, v in (data or {}).items() if k not in LIFECYCLE_KEYS}
    data["criteria"] = [{k: v for k, v in c.items() if k != "status"} for c in data.get("criteria", [])]
    blob = json.dumps(data, sort_keys=True) + PLAN_BLOCK.sub("", text).strip()
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def critic_prompt(d):
    path = plan_file(d)
    text, data, _ = load_plan(path)
    parts = [read(HERE / "playbooks" / "critique.md"),
             "\n---\n# Project objectives (GOALS.md)\n", read(ROOT / "GOALS.md") if (ROOT / "GOALS.md").exists() else "(none)",
             "\n---\n# Plan under review (%s)\n" % path.relative_to(ROOT).as_posix(), text]
    dm = ROOT / "docs" / "data-model.md"
    if dm.exists():
        parts += ["\n---\n# Data model (docs/data-model.md)\n", read(dm)]
    terms = terms_from(re.search(r"^#\s+(.+)$", text, re.M).group(1) if re.search(r"^#\s+(.+)$", text, re.M) else "",
                       " ".join((data or {}).get("areas", [])))
    hits = lessons_search(terms)
    parts.append("\n---\n# Past lessons that may apply\n")
    parts.append("\n\n".join("### %s %s [%s]\n%s" % (l["id"], l["title"], ", ".join(l["areas"]), l["body"])
                             for l in hits) or "(none matched)")
    return "".join(parts)


def cmd_critique(a):
    d = find_change(a.id)
    prompt = critic_prompt(d)
    old = d / "critique.md"
    if old.exists():  # a critique of an earlier version must not satisfy approval
        old.replace(d / "critique.prev.md")
    write(d / ".critique-hash", plan_hash(d) + "\n")
    cmd = config().get("agent_cmd", "").strip()
    if a.print or not cmd:
        print(prompt)
        if not a.print:
            print("\n[forethought] No agent_cmd in forethought/config.json. Give the prompt above to a FRESH agent session "
                  "and save its reply to changes/%s/critique.md" % d.name, file=sys.stderr)
        return
    r = subprocess.run(cmd, shell=True, input=prompt, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or not r.stdout.strip():
        die("agent_cmd failed (exit %s): %s" % (r.returncode, (r.stderr or "")[-500:]))
    write(d / "critique.md", "# Critique of %s (%s, via `%s`)\n\n%s\n" % (d.name, today(), cmd, r.stdout.strip()))
    print("wrote changes/%s/critique.md  verdict: %s" % (d.name, verdict(r.stdout) or "(none found)"))


def require_clean(d):
    data, errs = check_plan(d)
    if errs:
        print("%s does not pass check:" % d.name)
        for e in errs:
            print("  - " + e)
        sys.exit(1)
    return data


def cmd_approve(a):
    d = find_change(a.id)
    path = plan_file(d)
    data = require_clean(d)
    if data["status"] != "draft":
        die("%s is '%s'; only a draft can be approved" % (d.name, data["status"]))
    if data["tier"] != "quick" and not a.skip_critique:
        crit = d / "critique.md"
        if not crit.exists():
            die("no critique yet. Run: python -m forethought critique %s  (or --skip-critique \"<why>\")" % d.name)
        v = verdict(read(crit))
        if not v:
            die("critique.md has no 'VERDICT: READY' or 'VERDICT: REVISE' line")
        if v == "REVISE":
            die("critique verdict is REVISE. Address it and re-run critique, or approve with --skip-critique \"<why>\"")
        h = d / ".critique-hash"
        if not h.exists() or read(h).strip() != plan_hash(d):
            die("the plan changed after it was critiqued. Re-run: python -m forethought critique %s" % d.name)
    text = read(path)
    data["status"] = "approved"
    data["approved"] = today()
    data["approved_hash"] = plan_hash(d)
    if a.skip_critique:
        data["critique_skipped"] = a.skip_critique
    save_plan(path, text, data)
    refresh_roadmap()
    print("approved %s" % d.name)


def cmd_revise(a):
    d = find_change(a.id)
    path = plan_file(d)
    text, data, err = load_plan(path)
    if err:
        die(err)
    if data.get("status") not in ("approved", "in-progress"):
        die("%s is '%s'; only an approved or in-progress plan can be revised" % (d.name, data.get("status")))
    for k in ("approved", "approved_hash", "in_progress", "critique_skipped"):
        data.pop(k, None)
    for c in data.get("criteria", []):  # a revised plan has to earn its passes again
        c["status"] = "pending"
    data["status"] = "draft"
    data["revised"] = today()
    save_plan(path, text, data)
    refresh_roadmap()
    print("%s is a draft again: revise it, critique it, and get it approved." % d.name)


TRANSITIONS = {"in-progress": ("approved",), "done": ("in-progress",),
               "dropped": ("draft", "approved", "in-progress")}


def cmd_move(a):
    """start / finish / drop: move a change forward in its lifecycle."""
    d = find_change(a.id)
    path = plan_file(d)
    text, data, err = load_plan(path)
    if err:
        die(err)
    if data.get("status") not in TRANSITIONS[a.status]:
        die("%s is '%s'; it can become '%s' only from: %s"
            % (d.name, data.get("status"), a.status, ", ".join(TRANSITIONS[a.status])))
    if a.status != "dropped":
        require_clean(d)
    if a.status == "in-progress" and data.get("tier") != "epic":
        limit = config()["max_in_progress"]
        busy = [x.name for x in change_dirs() if x != d and (load_plan(plan_file(x))[1] or {}).get("status") == "in-progress"
                and (load_plan(plan_file(x))[1] or {}).get("tier") != "epic"]
        if len(busy) >= limit:
            die("%d changes are already in progress (%s); the limit is %d. Finish or drop one first, or raise "
                "max_in_progress in forethought/config.json. Fewer open streams = fewer forgotten branches."
                % (len(busy), ", ".join(busy), limit))
    if a.status == "dropped" and in_git() and not getattr(a, "abandon_knowledge", None):
        at_risk = []
        for b in branches_for_change(d):
            at_risk += ["%s: %s" % (b, item) for item in knowledge_at_risk(b)]
        if at_risk:
            die("these exist only on the change's branch and would be stranded:\n  " + "\n  ".join(at_risk)
                + "\nRescue them onto %s first:  python -m forethought rescue %s\n"
                  "(or drop with --abandon-knowledge \"<why>\")" % (short_branch(base_branch()), d.name))
    if a.status == "dropped" and getattr(a, "abandon_knowledge", None):
        data["knowledge_abandoned"] = a.abandon_knowledge
    if a.status == "in-progress" and data.get("epic"):
        _, edata, _ = load_plan(plan_file(find_change(data["epic"])))
        kid = next(k for k in edata["children"] if k["key"] == data["child"])
        built = epic_children(data["epic"])
        waiting = [dep for dep in kid.get("depends_on", [])
                   if not any(c.get("status") == "done" for c in built.get(dep, []))]
        if waiting:
            dropped = [w for w in waiting if any(c.get("status") == "dropped" for c in built.get(w, []))]
            hint = (" (%s was dropped: revise the epic and re-plan the dependencies)" % ", ".join(dropped)) if dropped else ""
            die("epic %s: child '%s' depends on unfinished child(ren): %s%s"
                % (data["epic"], data["child"], ", ".join(waiting), hint))
    if a.status == "done" and data.get("tier") == "standard":
        open_c = [c["id"] for c in data.get("criteria", []) if c.get("status") != "pass"]
        if open_c:
            die("criteria not passed yet: %s" % ", ".join(open_c))
        probs = close_checks(d, data, a)
        if probs:
            print("Not finished yet:", file=sys.stderr)
            for p in probs:
                print("  - " + p, file=sys.stderr)
            sys.exit(1)
    if a.status == "done" and data.get("tier") == "epic":
        built = epic_children(d.name)
        unfinished = [k["key"] for k in data.get("children", [])  # a dropped child is a decision, not a blocker
                      if not any(c.get("status") in ("done", "dropped") for c in built.get(k["key"], []))]
        if unfinished:
            die("epic children not done yet: %s" % ", ".join(unfinished))
    data["status"] = a.status
    data[a.status.replace("-", "_")] = today()
    save_plan(path, text, data)
    refresh_roadmap()
    print("%s -> %s" % (d.name, a.status))
    if a.status == "in-progress" and in_git() and d.name not in current_branch():
        print("tip: work on its own branch so the gate knows which change this is:  git switch -c change/%s" % d.name)
    if a.status == "done" and data.get("tier") == "standard" and in_git():
        write(d / "pr.md", build_pr(d, data, read(path), getattr(a, "base", None)))
        print("PR description: changes/%s/pr.md  (e.g. gh pr create --body-file changes/%s/pr.md)" % (d.name, d.name))


def cmd_status(a):
    refresh_roadmap()
    dirs = change_dirs()
    if in_git():  # "where am I, and is anything I need somewhere else?"
        branch = current_branch()
        act = active_change()
        act_data = (load_plan(plan_file(act))[1] or {}) if act else {}
        print("branch:  %s" % (branch or "(none)"))
        print("change:  %s" % ("%s (%s)" % (act.name, act_data.get("status")) if act else "none for this branch"))
        others = [x.name for x in dirs if x != act and (load_plan(plan_file(x))[1] or {}).get("status") == "in-progress"]
        if others:
            print("also in progress: %s" % ", ".join(others))
        base_full = base_branch()
        base = short_branch(base_full)
        base_tip = git("rev-parse", base_full).stdout.strip()
        tips = branch_tips()  # one git call for all branches; facts are cached per tip
        risky = []
        for b, _ in local_branches():
            if b in (branch, base) or is_long_lived(b):
                continue
            facts = branch_facts(b, tips.get(b, ""), base_full, base_tip)
            if facts["status"] in ("in-progress", "done"):
                continue  # active or awaiting merge: its knowledge arrives with the merge
            if facts["risk"]:
                risky.append("%s (%d)" % (b, len(facts["risk"])))
        if risky:
            shown = ", ".join(risky[:5]) + (" and %d more" % (len(risky) - 5) if len(risky) > 5 else "")
            print("knowledge not on %s yet: %s   -> forethought branches / rescue" % (base, shown))
        print("")
    if not dirs:
        print("no changes yet")
    for d in dirs:
        _, data, err = load_plan(plan_file(d))
        if err:
            print("%-40s  (unreadable)" % d.name)
        else:
            print("%-40s  %-8s  %-11s  %s" % (d.name, data.get("tier"), data.get("status"), data.get("objective", "")))


def insert_between(path, start, end, line):
    text = read(path)
    if start not in text or end not in text:
        die("%s is missing its %s marker" % (path.name, start))
    i = text.index(end)
    before = text[:i].rstrip("\n")
    write(path, before + "\n" + line + "\n" + text[i:])


def cmd_park(a):
    p = ROOT / "ROADMAP.md"
    if not p.exists():
        die("ROADMAP.md is missing. Restore it from forethought (init does not overwrite) or create it with the markers.")
    src = ""
    if a.source:
        found = find_change(a.source, required=False)
        if not found:
            print("warning: no change '%s' in changes/; recording it as given" % a.source, file=sys.stderr)
        src = " (from %s)" % (found.name if found else a.source)
    insert_between(p, "<!-- forethought:parking:start -->", "<!-- forethought:parking:end -->",
                   "- %s %s%s" % (today(), a.idea, src))
    print("parked. It is out of the current change's scope.")


def cmd_learn(a):
    p = ROOT / "LESSONS.md"
    if not p.exists():
        die("LESSONS.md is missing. Re-run init from the forethought repo to restore it.")
    nums = [int(l["id"][2:]) for l in lessons_all()]
    lid = "L-%03d" % ((max(nums) + 1) if nums else 1)
    areas = ", ".join(x.strip() for x in a.area.split(",") if x.strip())
    src = find_change(a.change) if a.change else active_change()
    text = read(p).rstrip("\n")
    write(p, text + "\n\n### %s (%s) [%s] %s\n%s\n%s%s" % (lid, today(), areas, a.title, a.body.strip(),
                                                           "Source: %s\n" % src.name if src else "",
                                                           "Scope: general\n" if a.general else ""))
    print("recorded %s%s%s" % (lid, " (from %s)" % src.name if src else "",
                               ". Marked general: consider it for your personal harness if it recurs in other "
                               "projects." if a.general else ""))


def cmd_enforce(a):
    """Retire a lesson into a check: it stops being pre-filled into plans, the check carries it now."""
    p = ROOT / "LESSONS.md"
    text = read(p)
    lesson = next((l for l in lessons_parse(text) if l["id"] == a.lesson.upper()), None)
    if not lesson:
        die("no lesson %s in LESSONS.md" % a.lesson)
    if lesson["enforced"]:
        die("%s is already enforced by: %s" % (lesson["id"], lesson["enforced"]))
    new_raw = lesson["raw"] + "\nEnforced by: %s (%s)" % (a.check, today())
    write(p, text.replace(lesson["raw"], new_raw, 1))
    print("%s is now enforced by %s; plans stop carrying it." % (lesson["id"], a.check))


def cmd_recall(a):
    hits = lessons_search(terms_from(" ".join(a.terms)), limit=10, include_enforced=True)
    if not hits:
        print("no lessons match")
    for l in hits:
        tag = " [enforced by %s]" % l["enforced"] if l["enforced"] else (" [general]" if l["general"] else "")
        print("%s (%s) [%s] %s%s\n    %s" % (l["id"], l["date"], ", ".join(l["areas"]), l["title"], tag,
                                             l["body"].splitlines()[0] if l["body"] else ""))


# ---------- git and paths ----------

def git(*args):
    # quotepath=off: non-ASCII file names come back as real names, not "caf\303\251.py"
    return subprocess.run(["git", "-c", "core.quotepath=off"] + list(args), cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def in_git():
    return shutil.which("git") is not None and git("rev-parse", "--is-inside-work-tree").returncode == 0


def current_branch():
    for env in ("FORETHOUGHT_BRANCH", "GITHUB_HEAD_REF", "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"):
        if os.environ.get(env):
            return os.environ[env]
    r = git("rev-parse", "--abbrev-ref", "HEAD")
    name = r.stdout.strip() if r.returncode == 0 else ""
    if name == "HEAD":  # detached: during a rebase, git remembers which branch is being rebased
        for state in ("rebase-merge", "rebase-apply"):
            p = Path(git("rev-parse", "--git-path", "%s/head-name" % state).stdout.strip())
            p = p if p.is_absolute() else ROOT / p
            if p.is_file():
                return short_branch(read(p).strip())
    return name


def base_branch(explicit=None):
    """--base, else FORETHOUGHT_BASE, else config base_branch, else detected: origin's default, main, master."""
    name = explicit or os.environ.get("FORETHOUGHT_BASE") or config()["base_branch"]
    if name:
        return name
    if "base" in _BASE:  # detection costs several git calls; do it once per run
        return _BASE["base"]
    _BASE["base"] = _detect_base()
    return _BASE["base"]


_BASE = {}


def _detect_base():
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()  # e.g. origin/develop
    cands = ([head.split("/", 1)[-1], head] if head else []) + ["main", "master"]
    for cand in cands:
        if git("rev-parse", "--verify", "--quiet", cand).returncode == 0:
            return cand
    return "main"


def short_branch(name):
    return re.sub(r"^(refs/heads/|refs/remotes/[^/]+/|origin/)", "", name or "")


def merge_base(base=None):
    base = base_branch(base)
    r = git("merge-base", base, "HEAD")
    if r.returncode != 0:
        die("cannot find the merge base with '%s'. Pass --base <branch> or set base_branch in "
            "forethought/config.json" % base)
    return r.stdout.strip()


def branch_files(base=None):
    """Files that differ from the merge base: committed, staged, unstaged and untracked."""
    mb = merge_base(base)
    # --no-renames: a move reports both paths, so the old location can't hide from the scope guard
    tracked = git("diff", "--name-only", "--no-renames", "--relative", mb).stdout.splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return mb, sorted(set(f.strip() for f in tracked + untracked if f.strip()))


def staged_files():
    return [f.strip() for f in git("diff", "--cached", "--name-only", "--no-renames", "--relative").stdout.splitlines() if f.strip()]


_GLOBS = {}


def glob_re(pat):
    if pat not in _GLOBS:
        p = pat.replace("\\", "/").strip()
        if p.endswith("/"):
            p += "**"
        out, i = "", 0
        while i < len(p):
            if p.startswith("**/", i):
                out, i = out + "(?:.*/)?", i + 3
            elif p.startswith("**", i):
                out, i = out + ".*", i + 2
            elif p[i] == "*":
                out, i = out + "[^/]*", i + 1
            elif p[i] == "?":
                out, i = out + "[^/]", i + 1
            else:
                out, i = out + re.escape(p[i]), i + 1
        _GLOBS[pat] = re.compile("^" + out + "$")
    return _GLOBS[pat]


def matches(path, patterns):
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    for pat in patterns:
        bare = pat.replace("\\", "/").rstrip("/")
        if glob_re(pat).match(p) or (not re.search(r"[*?]", bare) and p.startswith(bare + "/")):
            return True
    return False


TOOL_NOISE = ("forethought/__pycache__/**", "forethought/gate-log.jsonl", "forethought/cache.json", "**/*.pyc")


def code_only(files):
    cfg = config()
    return [f for f in files if not matches(f, cfg["planning_paths"]) and not matches(f, TOOL_NOISE)
            and not matches(f, cfg["governance_paths"])]


def governance_only(files):
    return [f for f in files if matches(f, config()["governance_paths"]) and not matches(f, TOOL_NOISE)]


GOVERNANCE_WARNING = ("governance files changed (%s). They set the rules every agent follows; make sure a "
                      "human made and reviewed this change.")
GOVERNANCE_MINUTES = 30


def reviewable(files):
    """What a review must cover and fingerprint: code, plus any change to the rules themselves."""
    return code_only(files) + governance_only(files)


def governance_token():
    p = git("rev-parse", "--git-path", "forethought-governance-ok").stdout.strip()
    return (Path(p) if Path(p).is_absolute() else ROOT / p) if p else None


def governance_allowed():
    tok = governance_token()
    if not tok or not tok.exists():
        return False
    try:
        when = datetime.datetime.fromisoformat(read(tok).strip())
    except ValueError:
        return False
    return (datetime.datetime.now() - when).total_seconds() < GOVERNANCE_MINUTES * 60


def cmd_allow_governance(a):
    """Human-only: allow changes to forethought's own rules (config, hooks, CI) for the next 30 minutes, locally."""
    if not in_git():
        die("allow-governance needs a git repository")
    tok = governance_token()
    write(tok, datetime.datetime.now().isoformat(timespec="seconds") + "\n")
    gate_log({"mode": "allow-governance", "ok": True, "errors": [],
              "warnings": ["governance changes allowed for %d minutes" % GOVERNANCE_MINUTES]})
    print("governance changes allowed in this clone for %d minutes (logged). In CI a human still has to add the "
          "'governance-approved' label to the PR." % GOVERNANCE_MINUTES)


def active_change():
    """The change this work belongs to: FORETHOUGHT_CHANGE, else the branch name, else the only one in progress."""
    env = os.environ.get("FORETHOUGHT_CHANGE")
    if env:
        return find_change(env, required=False)
    branch = current_branch()
    dirs = change_dirs()
    for d in dirs:
        if d.name in branch:
            return d
    m = re.search(r"(?:^|[/_-])(\d{3,})(?:-|$)", branch)
    if m:
        hit = find_change(m.group(1), required=False)
        if hit:
            return hit
    started = [d for d in dirs if (load_plan(plan_file(d))[1] or {}).get("status") == "in-progress"]
    return started[0] if len(started) == 1 else None


def code_fingerprint(files):
    """Hash of the current content of the given code files (deleted files count too)."""
    h = hashlib.sha256()
    for f in sorted(files):
        p = ROOT / f
        h.update(f.replace("\\", "/").encode("utf-8") + b"\0")
        # normalize line endings: Windows checkouts (CRLF) and Linux CI (LF) must agree
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.is_file() else b"<deleted>")
        h.update(b"\0")
    return h.hexdigest()[:16]


def gate_log(entry):
    try:
        with open(ROOT / "forethought" / "gate-log.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(dict(entry, ts=datetime.datetime.now().isoformat(timespec="seconds"))) + "\n")
    except OSError:
        pass


# ---------- gate: plan gate + scope guard ----------

def gate_eval(files, ci=False, base=None, statuses=None):
    cfg = config()
    errs, warns = [], []
    gov = governance_only(files)
    if gov:
        statuses = statuses or {}
        rewrites = [f for f in gov if statuses.get(f, "M") != "A"]  # adding the rules (setup) is fine; changing them is not
        if ci and os.environ.get("FORETHOUGHT_ALLOW_GOVERNANCE", "").lower() not in ("1", "true", "yes"):
            errs.append("this PR changes forethought's own rules (%s). A human must review it and add the "
                        "'governance-approved' label (which sets FORETHOUGHT_ALLOW_GOVERNANCE)." % ", ".join(gov))
        elif not ci and rewrites and not governance_allowed():
            errs.append("this changes forethought's own rules (%s). Only a human may: run "
                        "python -m forethought allow-governance (valid %d minutes), then retry."
                        % (", ".join(rewrites), GOVERNANCE_MINUTES))
        else:
            warns.append(GOVERNANCE_WARNING % ", ".join(gov))
    code = code_only(files)
    if not code:
        return None, errs, warns
    shown = ", ".join(code[:5]) + (" ..." if len(code) > 5 else "")
    if not ci and in_git():
        base_name, branch = short_branch(base_branch(base)), current_branch()
        if short_branch(branch) == base_name:
            errs.append("code changes (%s) on '%s' itself. Plan a change, start it, and work on its branch "
                        "(git switch -c change/<id>) so it can be reviewed and merged." % (shown, base_name))
            return None, errs, warns
        if branch == "HEAD":
            errs.append("code changes (%s) on a detached HEAD. Switch to the change's branch "
                        "(git switch change/<id>), or set FORETHOUGHT_BRANCH=change/<id> if you must stay detached."
                        % shown)
            return None, errs, warns
    d = active_change()
    if not d:
        errs.append("code changes (%s) but no active change. Plan one (new -> critique -> approve -> start) and "
                    "work on a branch named change/<id>, or set FORETHOUGHT_CHANGE." % shown)
        return None, errs, warns
    data, perrs = check_plan(d)
    if perrs:
        errs.append("plan %s does not pass check: %s" % (d.name, "; ".join(perrs)))
        return d, errs, warns
    if data.get("tier") == "epic":
        errs.append("%s is an epic; epics carry no code. Build in one of its child changes "
                    "(new ... --epic %s --child <key>)." % (d.name, d.name))
        return d, errs, warns
    need = "done" if ci else "in-progress"
    if data.get("status") != need:
        hint = {"draft": "it needs approval, then start", "approved": "run start first",
                "done": "it is finished; new code needs a new change", "dropped": "it was dropped",
                "in-progress": "run finish first (review, lessons, PR description)"}.get(data.get("status"), "")
        errs.append("change %s is '%s', expected '%s' (%s)" % (d.name, data.get("status"), need, hint))
    if data.get("tier") == "quick":
        if len(code) > cfg["quick_max_files"]:
            errs.append("quick change %s touches %d code files (limit %d). Make it a standard change."
                        % (d.name, len(code), cfg["quick_max_files"]))
    elif data.get("tier") == "standard":
        outside = [f for f in code if not matches(f, data.get("areas", []))]
        if outside:
            msg = ("outside the plan's areas %s: %s. Park the idea, or revise the plan to include it."
                   % (data.get("areas"), ", ".join(outside)))
            (errs if cfg["scope_mode"] == "block" else warns).append(msg)
    if ci and data.get("tier") == "standard" and not data.get("review_skipped"):
        rh = d / ".review-hash"
        if not rh.exists() or read(rh).strip() != code_fingerprint(reviewable(files)):
            errs.append("the code changed after its review (or was never reviewed). Run review and finish again.")
    if ci:
        added = deleted = 0
        mb = merge_base(base)
        for line in git("diff", "--numstat", "--relative", mb, "--", *code).stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].isdigit():
                added, deleted = added + int(parts[0]), deleted + int(parts[1])
        if added + deleted > cfg["pr_max_lines"]:
            msg = ("this PR changes %d lines of code (limit %d). Smaller PRs get better reviews: split it into "
                   "slices or epic children." % (added + deleted, cfg["pr_max_lines"]))
            (errs if cfg["pr_size_mode"] == "block" else warns).append(msg)
    return d, errs, warns


def name_statuses(args):
    out = git("diff", "--name-status", "--no-renames", "--relative", *args).stdout.splitlines()
    return {parts[-1]: parts[0][:1] for parts in (l.split("\t") for l in out) if len(parts) >= 2}


def cmd_gate(a):
    if a.paths:
        files = []
        for p in a.paths:
            full = (Path(p) if Path(p).is_absolute() else ROOT / p).resolve()
            try:
                files.append(full.relative_to(ROOT.resolve()).as_posix())
            except ValueError:
                print("gate: %s is outside the project; not checked" % p, file=sys.stderr)
        mode = "paths"
    else:
        if not in_git():
            die("gate needs a git repository (or use --paths)")
        files = staged_files() if a.staged else branch_files(a.base)[1]
        mode = "staged" if a.staged else ("ci" if a.ci else "branch")
    if a.paths:
        # editor/agent hooks: creating a governance file is changing the rules too (e.g. a git-ignored
        # .claude/settings.local.json that switches hooks off never reaches the pre-commit gate or CI)
        statuses = {f: "M" for f in files}
    elif a.staged:
        statuses = name_statuses(["--cached"])
    else:
        statuses = name_statuses([merge_base(a.base)])
        statuses.update({f: "A" for f in git("ls-files", "--others", "--exclude-standard").stdout.splitlines() if f})
    d, errs, warns = gate_eval(files, ci=a.ci, base=a.base, statuses=statuses)
    gate_log({"mode": mode, "change": d.name if d else None, "ok": not errs, "errors": errs, "warnings": warns,
              "files": len(files)})
    for w in warns:
        print("warning: " + w, file=sys.stderr)
    if errs:
        for e in errs:
            print("blocked: " + e, file=sys.stderr)
        sys.exit(1)
    print("gate: ok" + (" (%s)" % d.name if d else " (planning files only)"))


HOOK_MARK = "# forethought gate"


def cmd_hooks(a):
    if not in_git():
        die("not a git repository")
    line = 'python -m forethought gate --staged   (run from %s)' % ROOT
    custom = git("config", "--get", "core.hooksPath").stdout.strip()
    if custom:
        die("this repo uses core.hooksPath=%s (husky or a shared hooks folder), so forethought will not write "
            "there. Add this line to that folder's pre-commit hook (with husky: .husky/pre-commit):\n  %s"
            % (custom, line))
    hooks = Path(git("rev-parse", "--git-path", "hooks").stdout.strip())
    hooks = hooks if hooks.is_absolute() else ROOT / hooks
    hook = hooks / "pre-commit"
    top = Path(git("rev-parse", "--show-toplevel").stdout.strip()).resolve()
    rel = ROOT.resolve().relative_to(top).as_posix()  # forethought may live in a monorepo subfolder
    # one line per forethought project, in a subshell, so several projects in one monorepo share the hook
    # a project that was removed (folder or cli.py gone) skips itself instead of blocking every commit
    # The hook judges with the LAST COMMITTED rules (git archive HEAD:./forethought), so staging an edit to
    # forethought itself can't switch the gate off. First commit (nothing at HEAD yet): the working copy.
    py = sys.executable.replace("\\", "/")
    gate_line = ('(cd "$(git rev-parse --show-toplevel)/%s" 2>/dev/null && [ -f forethought/cli.py ] || exit 0; '
                 't=$(mktemp -d); mkdir -p "$t/forethought"; '
                 'if git archive HEAD:./forethought 2>/dev/null | tar -x -C "$t/forethought" 2>/dev/null '
                 '&& [ -f "$t/forethought/cli.py" ]; then FORETHOUGHT_ROOT="$PWD" "%s" "$t/forethought/cli.py" gate --staged; '
                 'else "%s" -m forethought gate --staged; fi; r=$?; rm -rf "$t"; exit $r) || exit 1\n'
                 % ("" if rel == "." else rel, py, py))
    if hook.exists() and HOOK_MARK not in read(hook):
        die("%s already exists and is not ours. Add this line to it yourself:\n  python -m forethought gate --staged" % hook)
    existing = read(hook) if hook.exists() else "#!/bin/sh\n%s (installed by: python -m forethought hooks)\n" % HOOK_MARK
    if gate_line not in existing:
        existing = existing.rstrip("\n") + "\n" + gate_line
    write(hook, existing)
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    print("installed %s (blocks commits of code outside an active, approved change)" % hook)


# ---------- code review ----------

REVIEW_VERDICT = re.compile(r"^[\s>*_`#-]*VERDICT[\s*_]*:[\s*_]*(PASS|FAIL)\b", re.I)
REVIEW_AC = re.compile(r"^[\s>*_`#-]*(AC-\d+)\b(.*)$", re.I)
# the status must come right after the id ("AC-1: PASS", "AC-1 - PASS", "**AC-1** — PASS"), so prose such as
# "AC-1: does NOT PASS" can't be read as a pass. Upper case only.
REVIEW_STATUS_NEXT = re.compile(r"^[\s*_:—–-]*(PASS|FAIL|UNVERIFIED)\b")


def review_result(text):
    """(overall, {AC-n: status}). Accepts 'AC-1: PASS', 'AC-1 - PASS', table rows '| AC-1 | ... | PASS |'.
    Any FAIL wins. Template lines ('PASS | FAIL', '<PASS, FAIL or UNVERIFIED>') are ignored."""
    overall, per = set(), {}
    for line in text.splitlines():
        cid = st = None
        if line.strip().startswith("|"):
            # Table row: id in the first cell. Cells are judged whole, so a template cell like
            # "<PASS, FAIL or UNVERIFIED>" never counts. Any FAIL cell wins; otherwise the last status cell.
            cells = [c.strip(" *_`") for c in line.strip().strip("|").split("|")]
            if cells and re.match(r"^AC-\d+$", cells[0], re.I):
                found = [c for c in cells[1:] if c in ("PASS", "FAIL", "UNVERIFIED")]
                cid = cells[0].upper()
                st = "FAIL" if "FAIL" in found else (found[-1] if found else None)
        else:
            if re.search(r"PASS\s*(\||,|or)\s*FAIL|<\s*PASS", line, re.I):  # an echoed template line
                continue
            m = REVIEW_VERDICT.match(line)
            if m:
                overall.add(m.group(1).upper())
                continue
            m = REVIEW_AC.match(line)
            if m:
                nxt = REVIEW_STATUS_NEXT.match(m.group(2))
                cid, st = m.group(1).upper(), (nxt.group(1) if nxt else None)
        if cid and st and per.get(cid) != "FAIL":
            per[cid] = st
    return ("FAIL" if "FAIL" in overall else ("PASS" if overall else None)), per


def diff_text(mb, code, limit):
    tracked = set(git("ls-files", "--", *code).stdout.split("\n")) if code else set()
    parts = [git("diff", "--relative", mb, "--", *[f for f in code if f in tracked]).stdout] if tracked else []
    for f in code:
        if f not in tracked and (ROOT / f).is_file():
            try:
                parts.append("--- /dev/null\n+++ b/%s (new, untracked)\n%s" % (f, read(ROOT / f)))
            except UnicodeDecodeError:
                parts.append("+++ b/%s (new binary file)" % f)
    text = "\n".join(parts)
    if len(text) > limit:
        text = text[:limit] + "\n\n[diff truncated at %d characters: review the remaining files in the repository]" % limit
    return text


def cmd_review(a):
    d = find_change(a.id)
    if not in_git():
        die("review needs a git repository")
    text, data, err = load_plan(plan_file(d))
    if err:
        die(err)
    if data.get("tier") != "standard":
        die("review is for standard changes (quick: the done_check; epic: review each child)")
    if data.get("status") != "in-progress":
        die("%s is '%s'; review an in-progress change" % (d.name, data.get("status")))
    mb, files = branch_files(a.base)
    code = reviewable(files)
    if not code:
        die("no code changes against the base branch to review")
    old = d / "review.md"
    if old.exists():
        old.replace(d / "review.prev.md")
    write(d / ".review-hash", code_fingerprint(code) + "\n")
    parts = [read(HERE / "playbooks" / "review.md"),
             "\n---\n# Plan (%s)\n" % plan_file(d).relative_to(ROOT).as_posix(), text]
    dm = ROOT / "docs" / "data-model.md"
    if dm.exists():
        parts += ["\n---\n# Data model (docs/data-model.md)\n", read(dm)]
    parts += ["\n---\n# Changed files\n", "\n".join("- " + f for f in code),
              "\n\n---\n# Diff against %s\n" % mb[:10], diff_text(mb, code, config()["review_max_chars"])]
    prompt = "".join(parts)
    cmd = config().get("agent_cmd", "").strip()
    if a.print or not cmd:
        print(prompt)
        if not a.print:
            print("\n[forethought] No agent_cmd set. Give the prompt above to a FRESH agent session and save its "
                  "reply to changes/%s/review.md" % d.name, file=sys.stderr)
        return
    r = subprocess.run(cmd, shell=True, input=prompt, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0 or not r.stdout.strip():
        die("agent_cmd failed (exit %s): %s" % (r.returncode, (r.stderr or "")[-500:]))
    write(d / "review.md", "# Code review of %s (%s, via `%s`)\n\n%s\n" % (d.name, today(), cmd, r.stdout.strip()))
    overall, per = review_result(r.stdout)
    print("wrote changes/%s/review.md  verdict: %s  %s" % (
        d.name, overall or "(none found)", " ".join("%s=%s" % kv for kv in sorted(per.items()))))


# ---------- PR description ----------

def objective_text(oid):
    p = ROOT / "GOALS.md"
    if p.exists():
        m = re.search(r"\*\*%s:?\*\*\s*:?\s*(.+)" % re.escape(oid or "-"), read(p))
        if m:
            return m.group(1).strip()
    return ""


def build_pr(d, data, text, base=None):
    cfg = config()
    title = (re.search(r"^#\s+(.+)$", text, re.M) or [None, d.name])[1]
    secs = sections(text)
    mb, files = branch_files(base)
    code = code_only(files)
    review = read(d / "review.md") if (d / "review.md").exists() else ""
    overall, per = review_result(review)

    schema = [f for f in code if matches(f, cfg["schema_paths"])]
    if "docs/data-model.md" in files:
        schema.append("docs/data-model.md")
    tests = [f for f in code if matches(f, cfg["test_paths"]) and f not in schema]
    seen = set(schema + tests)
    by_area = []
    for area in data.get("areas", []):
        grp = [f for f in code if f not in seen and matches(f, [area])]
        seen.update(grp)
        if grp:
            by_area.append((area, grp))
    other = [f for f in code if f not in seen]

    added = deleted = 0
    for line in git("diff", "--numstat", "--relative", mb, "--", *code).stdout.splitlines() if code else []:
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].isdigit():
            added, deleted = added + int(parts[0]), deleted + int(parts[1])

    out = ["# %s" % title, "",
           "Change `%s` · objective **%s**: %s" % (d.name, data.get("objective", "-"), objective_text(data.get("objective"))),
           "", "## Why", secs.get("why", "-"), "", "## Acceptance criteria", "",
           "| ID | When | Then | Test | Builder | Reviewer |", "|---|---|---|---|---|---|"]
    for c in data.get("criteria", []):
        out.append("| %s | %s | %s | `%s` | %s | %s |" % (c.get("id"), c.get("when"), c.get("then"), c.get("test"),
                                                        c.get("status"), per.get(c.get("id"), "-")))
    out += ["", "## Review in this order", ""]
    n = 1
    if schema:
        out.append("%d. **Data model and schema** (most expensive to get wrong): %s" % (n, ", ".join("`%s`" % f for f in schema))); n += 1
    for area, grp in by_area:
        out.append("%d. **%s**: %s" % (n, area, ", ".join("`%s`" % f for f in grp))); n += 1
    if tests:
        out.append("%d. **Tests**: %s" % (n, ", ".join("`%s`" % f for f in tests))); n += 1
    if other:
        out.append("%d. **Outside the plan's areas** (check why): %s" % (n, ", ".join("`%s`" % f for f in other)))
    gov = governance_only(files)
    if gov:
        out += ["", "## Governance files changed (review these first)",
                "These change the rules forethought and the agents follow:"] + ["- `%s`" % f for f in gov]
    out += ["", "## Data impact", secs.get("data impact", "-"), "", "## Risks", secs.get("risks", "-"), ""]
    roadmap = read(ROOT / "ROADMAP.md") if (ROOT / "ROADMAP.md").exists() else ""
    parked = [l for l in roadmap.splitlines() if "(from %s)" % d.name in l]
    out += ["## Deliberately not in this PR", secs.get("out of scope", "-")]
    if parked:
        out += ["", "Parked for later:"] + parked
    learned = [l for l in lessons_all() if ("Source: %s" % d.name) in l["body"]]
    out += ["", "## Lessons recorded"]
    out += ["- %s %s" % (l["id"], l["title"]) for l in learned] or [("- none: " + data["no_lessons"]) if data.get("no_lessons") else "- none"]
    crit_v = verdict(read(d / "critique.md")) if (d / "critique.md").exists() else None
    out += ["", "## Verification",
            "- Plan critique: %s" % ("skipped (%s)" % data["critique_skipped"] if data.get("critique_skipped") else (crit_v or "-")),
            "- Code review: %s" % ("skipped (%s)" % data["review_skipped"] if data.get("review_skipped")
                                    else "%s on code fingerprint `%s`" % (overall or "-", code_fingerprint(reviewable(files)))),
            "- Size: %d code files, +%d / -%d lines" % (len(code), added, deleted), ""]
    return "\n".join(out)


def cmd_pr(a):
    d = find_change(a.id)
    if not in_git():
        die("pr needs a git repository")
    text, data, err = load_plan(plan_file(d))
    if err:
        die(err)
    body = build_pr(d, data, text, a.base)
    write(d / "pr.md", body)
    print(body)
    print("\n[forethought] saved to changes/%s/pr.md  (e.g. gh pr create --body-file changes/%s/pr.md)" % (d.name, d.name),
          file=sys.stderr)


# ---------- finish: the close step ----------

def close_checks(d, data, a):
    """Extra gates for finishing a standard change. Returns a list of problems."""
    probs = []
    learned = any(("Source: %s" % d.name) in l["body"] for l in lessons_all())
    if not learned and not a.no_lessons:
        probs.append("record what this change taught you: python -m forethought learn \"<title>\" --area <a> "
                     "--body \"...\"  (or finish with --no-lessons \"<why>\")")
    if a.no_lessons:
        data["no_lessons"] = a.no_lessons
    if not in_git():
        return probs
    _, files = branch_files(getattr(a, "base", None))
    code = reviewable(files)
    if a.skip_review:
        data["review_skipped"] = a.skip_review
    elif not code:
        probs.append("no code differs from the base branch, so there is nothing to review. Finish from the "
                     "change's branch, or pass --skip-review \"<why>\" if this change truly had no code.")
    else:
        rv = d / "review.md"
        if not rv.exists():
            probs.append("no code review yet: python -m forethought review %s  (or --skip-review \"<why>\")" % d.name)
        else:
            overall, per = review_result(read(rv))
            if overall != "PASS":
                probs.append("code review verdict is %s, not PASS" % (overall or "missing"))
            missing = [c["id"] for c in data.get("criteria", []) if per.get(c["id"]) != "PASS"]
            if missing:
                probs.append("review did not PASS criteria: %s" % ", ".join(missing))
            failed_extra = [k for k, v in per.items() if v == "FAIL" and k not in missing]
            if failed_extra:
                probs.append("review reports FAIL on %s" % ", ".join(sorted(failed_extra)))
            rh = d / ".review-hash"
            if not rh.exists() or read(rh).strip() != code_fingerprint(code):
                probs.append("the code changed after the review. Run review again.")
    for folder, why in new_features_without_readme(code + [f for f in files if f.endswith("README.md")]):
        probs.append("feature folder %s/ %s. People and agents find their way by it." % (folder, why))
    schema = [f for f in code if matches(f, config()["schema_paths"])]
    if schema and "docs/data-model.md" not in files and not a.no_model_change:
        probs.append("schema files changed (%s) but docs/data-model.md did not. Update it, or pass "
                     "--no-model-change \"<why>\"" % ", ".join(schema))
    if a.no_model_change:
        data["no_model_change"] = a.no_model_change
    return probs


# ---------- structure: features, map, research ----------

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target", "coverage"}


def project_files():
    """Every file in the project that git would track (or, without git, a filtered walk)."""
    if in_git():
        out = git("ls-files", "--cached", "--others", "--exclude-standard").stdout.splitlines()
        return sorted(set(f.strip() for f in out if f.strip() and (ROOT / f.strip()).exists()))
    files = []
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and not any(s in SKIP_DIRS or s.startswith(".") for s in rel.split("/")[:-1]):
            files.append(rel)
    return sorted(files)


def dirs_of(files, max_depth=4):
    out = set()
    for f in files:
        parts = f.split("/")[:-1]
        for i in range(1, min(len(parts), max_depth) + 1):
            out.add("/".join(parts[:i]))
    return sorted(out)


def feature_dirs(files=None):
    pats = config()["feature_dirs"]
    return [d for d in dirs_of(files if files is not None else project_files()) if any(glob_re(p).match(d) for p in pats)]


def readme_field(folder, field):
    p = ROOT / folder / "README.md"
    if not p.exists():
        return ""
    m = re.search(r"^%s:\s*(.+)$" % re.escape(field), read(p), re.M | re.I)
    v = m.group(1).strip() if m else ""
    return "" if re.search(r"\bTODO:", v) else v


def cmd_feature(a):
    folder = ROOT / a.path
    readme = folder / "README.md"
    if readme.exists():
        die("%s already has a README.md" % a.path)
    folder.mkdir(parents=True, exist_ok=True)
    write(readme, read(HERE / "templates" / "feature-README.md").replace("__NAME__", folder.name))
    if not any(glob_re(p).match(Path(a.path).as_posix().strip("/")) for p in config()["feature_dirs"]):
        print("note: %s does not match feature_dirs in forethought/config.json, so map and tidy won't list it "
              "as a feature" % a.path, file=sys.stderr)
    print("created %s/README.md: fill in Purpose, Entry point, Owns, Depends on" % a.path)


def cmd_research(a):
    folder = ROOT / "research" / slug(a.topic)
    if (folder / "decision.md").exists():
        die("research/%s already exists" % folder.name)
    write(folder / "decision.md", read(HERE / "templates" / "research-decision.md").replace("__TOPIC__", a.topic))
    print("created research/%s/decision.md. Keep notes beside it; end with Decision: GO | NEEDS-CLARIFICATION | KILL"
          % folder.name)


def research_open():
    """Research folders that have not reached a decision."""
    out = []
    base = ROOT / "research"
    if base.exists():
        for f in sorted(p for p in base.iterdir() if p.is_dir()):
            dm = f / "decision.md"
            m = re.search(r"^Decision:\s*(GO|NEEDS-CLARIFICATION|KILL)\b", read(dm), re.M) if dm.exists() else None
            if not m:
                out.append("research/%s" % f.name)
    return out


def cmd_map(a):
    files = project_files()
    feats = feature_dirs(files)
    lines = ["# Project map", "",
             "Generated by `python -m forethought map` on %s. Do not edit; run it again. "
             "Where things go: see `AGENTS.md`." % today(), ""]
    lines += ["## Features", ""]
    if feats:
        lines += ["| Folder | Purpose | Owns | Entry point |", "|---|---|---|---|"]
        for f in feats:
            purpose = readme_field(f, "Purpose") or (
                "**README has no filled-in Purpose line**" if (ROOT / f / "README.md").exists() else "**no README**")
            lines.append("| `%s/` | %s | %s | %s |" % (f, purpose,
                                                      readme_field(f, "Owns") or "-", readme_field(f, "Entry point") or "-"))
    else:
        lines.append("No feature folders yet (feature_dirs in forethought/config.json: %s)." % ", ".join(config()["feature_dirs"]))
    lines += ["", "## Folders", ""]
    counts = {}
    for f in files:
        for d in dirs_of([f], max_depth=2):
            counts[d] = counts.get(d, 0) + 1
    for d in sorted(counts):
        if any(s in SKIP_DIRS or s.startswith(".") for s in d.split("/")):
            continue
        lines.append("%s- `%s/` (%d files)" % ("  " * d.count("/"), d, counts[d]))
    lines += ["", "## Open changes", ""]
    rows = []
    for d in change_dirs():
        text, data, err = load_plan(plan_file(d))
        if not err and data.get("status") in OPEN:
            rows.append("| %s | %s | %s |" % (d.name, data.get("status"), ", ".join("`%s`" % x for x in data.get("areas", [])) or "-"))
    lines += (["| Change | Status | Areas |", "|---|---|---|"] + rows) if rows else ["None."]
    undecided = research_open()
    if undecided:
        lines += ["", "## Research without a decision", ""] + ["- `%s/`" % r for r in undecided]
    write(ROOT / "docs" / "map.md", "\n".join(lines) + "\n")
    print("wrote docs/map.md (%d features, %d folders)" % (len(feats), len(counts)))


def area_warnings(data):
    """Areas that point nowhere: probably a typo. A new folder under an existing parent is fine."""
    out = []
    for area in data.get("areas", []):
        prefix = re.split(r"[*?]", area.replace("\\", "/"))[0].rstrip("/")
        if prefix and not (ROOT / prefix).exists() and not (ROOT / prefix).parent.exists():
            out.append("area '%s' matches no existing folder, not even its parent (typo?)" % area)
    return out


def new_features_without_readme(files):
    pats = config()["feature_dirs"]
    missing = []
    for d in dirs_of(files):
        if not any(glob_re(p).match(d) for p in pats) or d in [m[0] for m in missing]:
            continue
        readme = ROOT / d / "README.md"
        if not readme.exists():
            missing.append((d, "has no README.md (python -m forethought feature %s)" % d))
        elif re.search(r"\bTODO:", read(readme)):
            missing.append((d, "README.md still has TODO: placeholders; fill in what the folder is for"))
    return missing


# ---------- branches: where the work is, and what would be lost ----------

GENERATED = ("docs/map.md", "ROADMAP.md")  # rebuilt by commands; never "knowledge"


def local_branches():
    out = git("for-each-ref", "--format=%(refname:short)|%(objectname)|%(committerdate:unix)", "refs/heads").stdout
    res = []
    for line in out.splitlines():
        parts = line.rsplit("|", 2)
        if len(parts) == 3 and parts[0]:
            res.append((parts[0], int(parts[2]) if parts[2].isdigit() else 0, parts[1]))
    return [(n, ts) for n, ts, _ in res]


def branch_tips():
    out = git("for-each-ref", "--format=%(refname:short)|%(objectname)", "refs/heads").stdout
    return dict(line.rsplit("|", 1) for line in out.splitlines() if "|" in line)


def change_for_branch(name):
    dirs = change_dirs()
    for d in dirs:
        if d.name in name:
            return d
    m = re.search(r"(?:^|[/_-])(\d{3,})(?:-|$)", name)
    return find_change(m.group(1), required=False) if m else None


def branches_for_change(d):
    return [b for b, _ in local_branches() if change_for_branch(b) == d]


def git_show(ref, rel):
    r = git("show", "%s:./%s" % (ref, rel))
    return r.stdout if r.returncode == 0 else None


def git_show_bytes(ref, rel):
    """Exact bytes (text mode would turn CRLF into LF, so a rescued file would never match the branch)."""
    r = subprocess.run(["git", "show", "%s:./%s" % (ref, rel)], cwd=str(ROOT), capture_output=True)
    return r.stdout if r.returncode == 0 else None


def parking_lines(text):
    m = re.search(r"<!-- forethought:parking:start -->(.*?)<!-- forethought:parking:end -->", text or "", re.S)
    return [l.strip() for l in (m.group(1) if m else "").splitlines() if l.strip().startswith("- ")]


def lesson_key(l):
    """A lesson is the same lesson when title and body match (ignoring the lines forethought adds later)."""
    body = "\n".join(x for x in l["body"].splitlines() if not re.match(r"^(Enforced by|Scope):", x))
    return l["title"].strip().lower() + "\n" + re.sub(r"\s+", " ", body).strip()


def three_way(current, base, other):
    """git merge-file on bytes. Returns (merged_bytes, clean)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for name, data in (("current", current), ("base", base), ("other", other)):
            p = Path(tmp) / name
            p.write_bytes(data or b"")
            paths.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", "--quiet"] + paths, capture_output=True)
        return r.stdout, r.returncode == 0


def _lines(data):
    return [l.rstrip() for l in (data or b"").replace(b"\r\n", b"\n").decode("utf-8", "replace").split("\n")]


def contained(base, mb, branch, f, rescued=(), lenient=False):
    """True when everything `branch` changed in file f since mb is already in `base` (merged, squashed,
    cherry-picked or hand-merged): merging the branch's version into base would change nothing."""
    bb = git_show_bytes(branch, f)
    if bb is None:
        return True  # deleted on the branch: nothing to keep
    if any(r.endswith("/" + f) and git_show_bytes(base, r) == bb for r in rescued):
        return True  # its version was rescued (changes/_rescued/...) and committed on base
    base_b = git_show_bytes(base, f)
    if base_b is None:
        return False
    if base_b == bb:
        return True
    mb_b = git_show_bytes(mb, f) or b""
    merged, clean = three_way(base_b, mb_b, bb)
    if clean and merged == base_b:
        return True
    if not lenient:
        return False  # code: only a clean 3-way merge proves it is on base (a line can appear in many places)
    # Hand-merged notes/docs: every line the branch added since the fork is already in base (both sides appended
    # to the same spot is the common case for notes, goals and docs, and always "conflicts" in a 3-way merge).
    # Each added line must appear in base right after the same preceding line (within a few lines), so a
    # changed value that merely exists elsewhere in base ("Use Redis" under "Rejected") does not count.
    before = set(_lines(mb_b))
    blines, have = _lines(bb), _lines(base_b)
    added = [i for i, l in enumerate(blines) if l.strip() and l not in before]
    if not added:
        return False
    for i in added:
        prev = next((blines[k] for k in range(i - 1, -1, -1) if blines[k].strip()), None)
        spots = [j for j, l in enumerate(have) if l == blines[i]]
        if not any(prev is None or prev in have[max(0, j - 4):j] for j in spots):
            return False
    return True


def branch_new_lessons(branch, mb, base_text_or_ref, base_is_text=False):
    """Lessons the branch added or changed since it forked that the base doesn't have. A lesson that already
    existed at the fork isn't branch knowledge, even if base has since edited it (e.g. a typo fix)."""
    at_fork = {lesson_key(l) for l in lessons_parse(git_show(mb, "LESSONS.md") or "")}
    base_text = base_text_or_ref if base_is_text else (git_show(base_text_or_ref, "LESSONS.md") or "")
    on_base = {lesson_key(l) for l in lessons_parse(base_text)}
    return [l for l in lessons_parse(git_show(branch, "LESSONS.md") or "")
            if lesson_key(l) not in at_fork and lesson_key(l) not in on_base]


_CACHE = {}


def branch_facts(branch, tip, base, base_tip):
    """Status, knowledge at risk, and 'already on base' for one branch. Cached by (branch tip, base tip),
    so status/branches/tidy stay fast on repos with many branches."""
    cfg = config()
    settings = hashlib.sha256(json.dumps([cfg["planning_paths"], cfg["keep_branches"], list(GENERATED)],
                                         sort_keys=True).encode("utf-8")).hexdigest()[:12]
    key = "%s|%s|%s" % (tip, base_tip, settings)  # a config change recomputes everything
    store = _CACHE.setdefault("facts", None)
    if store is None:
        p = ROOT / "forethought" / "cache.json"
        try:
            store = json.loads(read(p)) if p.exists() else {}
        except (ValueError, OSError):
            store = {}
        if not isinstance(store, dict):  # a cache is disposable: anything odd means start over
            store = {}
        _CACHE["facts"] = store
    hit = store.get(branch)
    if isinstance(hit, dict) and hit.get("key") == key and isinstance(hit.get("risk"), list):
        return hit
    d = change_for_branch(branch)
    status = None
    if d:  # read the plan as the branch has it: that is where finish recorded 'done'
        rel = plan_file(d).relative_to(ROOT).as_posix()
        text = git_show(branch, rel)
        data = None
        if text:
            m = PLAN_BLOCK.search(text)
            try:
                data = json.loads(m.group(1)) if m else None
            except ValueError:
                data = None
        status = (data or load_plan(plan_file(d))[1] or {}).get("status")
    mb = git("merge-base", base, branch).stdout.strip()
    risk, all_in = [], True
    if mb:
        touched = [f.strip() for f in git("diff", "--name-only", "--no-renames", "--relative", mb, branch).stdout.splitlines()
                   if f.strip() and not matches(f.strip(), TOOL_NOISE)]
        planning = cfg["planning_paths"]
        rescued = [x for x in git("ls-tree", "-r", "--name-only", base, "--", "changes/_rescued").stdout.splitlines() if x]
        for f in touched:
            is_knowledge = matches(f, planning) and f not in GENERATED and f != "LESSONS.md"
            if f in GENERATED or f == "LESSONS.md":
                continue  # generated files never decide anything; lessons are compared one by one below
            ok = contained(base, mb, branch, f, rescued, lenient=is_knowledge)
            if not ok:
                all_in = False
                if is_knowledge:
                    risk.append("file %s" % f)
        if "LESSONS.md" in touched:
            new_lessons = branch_new_lessons(branch, mb, base)
            if new_lessons:
                all_in = False
            risk += ["lesson %s %s" % (l["id"], l["title"]) for l in new_lessons]
        if "ROADMAP.md" in touched:
            known = set(parking_lines(git_show(base, "ROADMAP.md")))
            risk += ["parked: %s" % l[2:] for l in parking_lines(git_show(branch, "ROADMAP.md")) if l not in known]
    facts = {"key": key, "change": d.name if d else None, "status": status, "risk": risk, "all_on_base": all_in}
    store[branch] = facts
    try:
        write(ROOT / "forethought" / "cache.json", json.dumps(store))
    except OSError:
        pass
    return facts


def knowledge_at_risk(branch, base=None):
    """Planning knowledge (lessons, parked ideas, plans, decisions, research notes, docs) that the branch added
    and the base branch does not have yet. This is what a forgotten or deleted branch would take with it."""
    base = base or base_branch()
    tips = branch_tips()
    base_tip = git("rev-parse", base).stdout.strip()
    tip = tips.get(branch) or git("rev-parse", branch).stdout.strip()
    return branch_facts(branch, tip, base, base_tip)["risk"]


def is_long_lived(b):
    return matches(b, config()["keep_branches"])


def branch_report():
    base_full = base_branch()
    base = short_branch(base_full)
    base_tip = git("rev-parse", base_full).stdout.strip()
    tips = branch_tips()
    merged = set(git("branch", "--merged", base_full, "--format=%(refname:short)").stdout.split())
    in_worktree = set(re.findall(r"^branch refs/heads/(.+)$", git("worktree", "list", "--porcelain").stdout, re.M))
    stale = config()["stale_days"]
    now = datetime.datetime.now().timestamp()
    rows = []
    for b, ts in local_branches():
        if b == base:
            continue
        age = int((now - ts) / 86400) if ts else 0
        if is_long_lived(b):
            rows.append({"branch": b, "change": "-", "status": "-", "age": age, "merged": b in merged,
                         "worktree": b in in_worktree, "verdict": "long-lived branch (never pruned)", "risk": [],
                         "prune": None})
            continue
        f = branch_facts(b, tips.get(b, ""), base_full, base_tip)
        # in progress or finished-but-unmerged: its knowledge arrives with the merge, so don't cry "rescue"
        st, risk, prune = f["status"], ([] if f["status"] in ("in-progress", "done") else f["risk"]), None
        closed = st in ("done", "dropped", None)
        if st == "in-progress":
            verdict = "active" + (" (stale: no commit for %d days)" % age if age > stale else "")
        elif risk:
            verdict = "RESCUE FIRST: %d item(s) not on %s" % (len(risk), base)
        elif closed and b in merged:
            verdict, prune = "safe to delete", "-d"
        elif closed and f["all_on_base"]:
            verdict, prune = "safe to delete (everything it changed is already on %s, e.g. squash-merged)" % base, "-D"
        elif st == "done":
            verdict = "finished, PR not merged yet: merge it (its lessons and notes arrive with it)"
        elif st == "dropped":
            verdict = "dropped, unmerged, nothing to rescue: delete with git branch -D %s" % b
        elif f["change"] is None:
            verdict = "no change: what is this branch for?"
        else:
            verdict = "planned (%s), no work yet" % st
        rows.append({"branch": b, "change": f["change"] or "-", "status": st or "-", "age": age,
                     "merged": b in merged, "worktree": b in in_worktree, "verdict": verdict, "risk": risk,
                     "prune": prune})
    return rows


def cmd_branches(a):
    if not in_git():
        die("branches needs a git repository")
    rows = branch_report()
    if not rows:
        print("no branches besides %s" % short_branch(base_branch()))
        return
    w = max(len(r["branch"]) for r in rows)
    for r in rows:
        print("%-*s  %-28s  %-11s  %4dd  %s%s" % (w, r["branch"], r["change"][:28], r["status"], r["age"],
                                                r["verdict"], "  [worktree]" if r["worktree"] else ""))
        for item in r["risk"]:
            print("%s    - %s" % (" " * w, item))
    if a.prune:
        cur = current_branch()
        doomed = [r for r in rows if r["prune"] and r["branch"] != cur and not r["worktree"]]
        if not doomed:
            print("\nnothing safe to prune")
            return
        if not a.yes:
            print("\nwould delete (closed, and everything they changed is on %s): %s\nrun again with --yes to delete"
                  % (short_branch(base_branch()), ", ".join(r["branch"] for r in doomed)))
            return
        for r in doomed:
            # -d for merged branches (git double-checks); -D only where every file was proven to be on base
            res = git("branch", r["prune"], r["branch"])
            print(("deleted %s" % r["branch"]) if res.returncode == 0 else ("kept %s: %s" % (r["branch"], res.stderr.strip())))


def cmd_rescue(a):
    """Bring knowledge from a branch onto the base branch. Merges, never overwrites: local (even uncommitted)
    edits are kept; a real conflict goes to changes/_rescued/<branch>/ for a human to merge."""
    if not in_git():
        die("rescue needs a git repository")
    base = short_branch(base_branch())
    if short_branch(current_branch()) != base:
        die("switch to %s first: knowledge lives on the base branch (git switch %s)" % (base, base))
    target = find_change(a.target, required=False)
    branches = branches_for_change(target) if target else [a.target]
    branches = [b for b in branches if git("rev-parse", "--verify", "--quiet", b).returncode == 0]
    if not branches:
        die("no branch found for '%s'" % a.target)
    done, manual = [], []
    for b in branches:
        mb = git("merge-base", "HEAD", b).stdout.strip()
        lessons_text = read(ROOT / "LESSONS.md") if (ROOT / "LESSONS.md").exists() else "# Lessons\n"
        have = lessons_parse(lessons_text)
        known = {lesson_key(l) for l in have}
        titles = {l["title"].strip().lower(): l["id"] for l in have}
        nxt = max([int(l["id"][2:]) for l in have] or [0]) + 1
        for l in branch_new_lessons(b, mb, lessons_text, base_is_text=True) if mb else []:
            if lesson_key(l) in known:
                continue
            raw = re.sub(r"^###\s+L-\d+", "### L-%03d" % nxt, l["raw"], count=1)
            lessons_text = lessons_text.rstrip("\n") + "\n\n" + raw + "\n"
            same = titles.get(l["title"].strip().lower())
            done.append("lesson L-%03d %s (was %s on %s)%s" % (
                nxt, l["title"], l["id"], b, "  NOTE: same title as %s with different text; merge the two by hand" % same if same else ""))
            known.add(lesson_key(l))
            nxt += 1
        write(ROOT / "LESSONS.md", lessons_text)
        if (ROOT / "ROADMAP.md").exists():
            have_lines = set(parking_lines(read(ROOT / "ROADMAP.md")))
            for line in parking_lines(git_show(b, "ROADMAP.md")):
                if line not in have_lines:
                    insert_between(ROOT / "ROADMAP.md", "<!-- forethought:parking:start -->",
                                   "<!-- forethought:parking:end -->", line)
                    done.append("parked idea: %s" % line[2:])
        for item in knowledge_at_risk(b):
            if not item.startswith("file "):
                continue
            f = item[5:]
            theirs = git_show_bytes(b, f)
            if theirs is None:
                continue
            local = ROOT / f
            mine = local.read_bytes() if local.is_file() else None
            if mine == theirs:
                continue  # already here (perhaps not committed yet)
            existed_at_fork = mb and git_show_bytes(mb, f) is not None
            if mine is None and not existed_at_fork:
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(theirs)
                done.append("file %s (from %s)" % (f, b))
                continue
            if mine is None:  # it was deleted on the base branch on purpose: don't resurrect it silently
                side = ROOT / "changes" / "_rescued" / slug(b) / f
                side.parent.mkdir(parents=True, exist_ok=True)
                side.write_bytes(theirs)
                manual.append("%s was deleted on %s but changed on %s: its version is in %s; restore it or let it go"
                              % (f, base, b, side.relative_to(ROOT).as_posix()))
                continue
            crlf = b"\r\n" in mine and b"\r\n" not in theirs  # Git for Windows' autocrlf working copy
            mine_n = mine.replace(b"\r\n", b"\n") if crlf else mine
            merged, clean = three_way(mine_n, git_show_bytes(mb, f) or b"", theirs) if mb else (b"", False)
            if clean and crlf:
                merged = merged.replace(b"\n", b"\r\n")
            if clean:
                local.write_bytes(merged)  # includes your local edits and the branch's
                done.append("file %s (merged with %s; your edits kept)" % (f, b))
            else:
                side = ROOT / "changes" / "_rescued" / slug(b) / f
                side.parent.mkdir(parents=True, exist_ok=True)
                side.write_bytes(theirs)
                manual.append("%s conflicts with %s: its version is in %s; merge it by hand, then delete that folder"
                              % (f, b, side.relative_to(ROOT).as_posix()))
    refresh_roadmap()
    for x in done:
        print("rescued " + x)
    for x in manual:
        print("manual: " + x)
    if not done and not manual:
        print("nothing to rescue")
    else:
        print("\nNow commit these on %s (they are all planning files, so the gate allows it), then drop or delete "
              "the branch." % base)


# ---------- tidy: what is drifting ----------

def cmd_tidy(a):
    cfg = config()
    report = []

    def section(title, items):
        if items:
            report.append((title, items))

    files = project_files()
    feats = feature_dirs(files)
    section("Feature folders without a README (python -m forethought feature <dir>)",
            ["%s/" % f for f in feats if not (ROOT / f / "README.md").exists()])

    areas = []
    for d in change_dirs():
        _, data, err = load_plan(plan_file(d))
        if not err:
            areas += data.get("areas", [])
    owners = set()  # each code file belongs to its feature folder, else to its top-level folder
    for f in code_only(files):
        if "/" not in f:
            continue
        owner = next((fd for fd in feats if f.startswith(fd + "/")), f.split("/")[0])
        owners.add(owner)
    unclaimed = []
    ignore = cfg["tidy_ignore"] + cfg["test_paths"]
    for cd in sorted(owners):
        if cd.split("/")[0] in ("forethought",) or cd.startswith(".") or matches(cd + "/x", ignore):
            continue
        if not any(matches(cd + "/x", [ar]) or re.split(r"[*?]", ar)[0].rstrip("/").startswith(cd + "/")
                   or re.split(r"[*?]", ar)[0].rstrip("/") == cd for ar in areas):
            unclaimed.append("%s/" % cd)
    section("Code folders no plan has ever claimed (built outside the process, or dead?)", unclaimed)

    section("Research without a decision (finish it: GO, NEEDS-CLARIFICATION or KILL)", research_open())

    old = []
    if (ROOT / "ROADMAP.md").exists():
        cutoff = datetime.date.today() - datetime.timedelta(days=cfg["parked_stale_days"])
        for line in parking_lines(read(ROOT / "ROADMAP.md")):
            m = re.match(r"- (\d{4}-\d{2}-\d{2})", line)
            if m and datetime.date.fromisoformat(m.group(1)) < cutoff:
                old.append(line[2:])
    section("Parked ideas older than %d days (promote one with new, or delete it)" % cfg["parked_stale_days"], old)

    stale_cut = (datetime.date.today() - datetime.timedelta(days=cfg["stale_days"])).isoformat()
    stale = []
    for d in change_dirs():
        _, data, err = load_plan(plan_file(d))
        if err:
            continue
        st = data.get("status")
        since = data.get("in_progress") if st == "in-progress" else data.get("approved") or data.get("created")
        if st in OPEN and since and since < stale_cut:
            stale.append("%s is '%s' since %s" % (d.name, st, since))
    section("Changes open longer than %d days (finish, revise or drop)" % cfg["stale_days"], stale)

    lessons = [l for l in lessons_all() if not l["enforced"]]
    repeats = []
    for i, l1 in enumerate(lessons):
        for l2 in lessons[i + 1:]:
            shared_area = set(l1["areas"]) & set(l2["areas"])
            shared_words = set(terms_from(l1["title"])) & set(terms_from(l2["title"]))
            if shared_area and len(shared_words) >= 2:
                repeats.append("%s and %s look like the same lesson (%s): turn it into a check, then "
                               "python -m forethought enforce <id> \"<check>\"" % (l1["id"], l2["id"], ", ".join(sorted(shared_words))))
    section("Lessons that keep coming back", repeats)
    section("Lessons marked general (candidates for your personal harness, if they recur elsewhere)",
            ["%s %s" % (l["id"], l["title"]) for l in lessons if l["general"]])

    if in_git():
        brs = [r for r in branch_report() if not r["verdict"].startswith("active") or "stale" in r["verdict"]]
        section("Branches needing a decision (details: python -m forethought branches)",
                ["%s: %s" % (r["branch"], r["verdict"]) for r in brs])

    if not report:
        print("Nothing to tidy.")
        return
    for title, items in report:
        print("## " + title)
        for it in items:
            print("- " + it)
        print("")
    print("Run python -m forethought map to refresh docs/map.md.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="forethought", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("dir"); s.add_argument("--claude", action="store_true")
    s.add_argument("--owner", help="GitHub user or team (e.g. @you) who must approve changes to the rules (writes .github/CODEOWNERS)")
    s.set_defaults(f=cmd_init)
    s = sub.add_parser("new"); s.add_argument("title"); s.add_argument("--tier", choices=TIERS, required=True)
    s.add_argument("--objective"); s.add_argument("--areas", help="comma-separated paths/globs")
    s.add_argument("--intent"); s.add_argument("--done-check", dest="done_check")
    s.add_argument("--epic", help="parent epic id (standard tier)"); s.add_argument("--child", help="child key in that epic")
    s.set_defaults(f=cmd_new)
    s = sub.add_parser("check"); s.add_argument("id", nargs="?"); s.set_defaults(f=cmd_check)
    s = sub.add_parser("critique"); s.add_argument("id"); s.add_argument("--print", action="store_true"); s.set_defaults(f=cmd_critique)
    s = sub.add_parser("approve"); s.add_argument("id"); s.add_argument("--skip-critique", dest="skip_critique"); s.set_defaults(f=cmd_approve)
    s = sub.add_parser("revise"); s.add_argument("id"); s.set_defaults(f=cmd_revise)
    for verb, status in (("start", "in-progress"), ("finish", "done"), ("drop", "dropped")):
        s = sub.add_parser(verb); s.add_argument("id"); s.set_defaults(f=cmd_move, status=status)
        if verb == "drop":
            s.add_argument("--abandon-knowledge", dest="abandon_knowledge",
                           help="drop even though lessons/notes exist only on its branch; reason is recorded")
        if verb == "finish":
            s.add_argument("--base", help="base branch for the diff (default: config base_branch)")
            s.add_argument("--skip-review", dest="skip_review", help="finish without a code review; reason is recorded")
            s.add_argument("--no-lessons", dest="no_lessons", help="nothing worth recording; reason is recorded")
            s.add_argument("--no-model-change", dest="no_model_change",
                           help="schema changed but the data model doc needs no update; reason is recorded")
    s = sub.add_parser("review"); s.add_argument("id"); s.add_argument("--print", action="store_true")
    s.add_argument("--base"); s.set_defaults(f=cmd_review)
    s = sub.add_parser("pr"); s.add_argument("id"); s.add_argument("--base"); s.set_defaults(f=cmd_pr)
    s = sub.add_parser("gate"); s.add_argument("--staged", action="store_true", help="check staged files (pre-commit)")
    s.add_argument("--ci", action="store_true", help="merge check: change must be finished and its review current")
    s.add_argument("--base", help="base branch (default: config base_branch)")
    s.add_argument("--paths", nargs="+", help="check these paths (editor/agent hooks)"); s.set_defaults(f=cmd_gate)
    s = sub.add_parser("hooks"); s.set_defaults(f=cmd_hooks)
    s = sub.add_parser("allow-governance"); s.set_defaults(f=cmd_allow_governance)
    s = sub.add_parser("status"); s.set_defaults(f=cmd_status)
    s = sub.add_parser("park"); s.add_argument("idea"); s.add_argument("--from", dest="source"); s.set_defaults(f=cmd_park)
    s = sub.add_parser("learn"); s.add_argument("title"); s.add_argument("--area", required=True)
    s.add_argument("--body", required=True)
    s.add_argument("--change", help="change it came from (default: the active change)")
    s.add_argument("--general", action="store_true", help="true beyond this project: a candidate for your personal harness")
    s.set_defaults(f=cmd_learn)
    s = sub.add_parser("recall"); s.add_argument("terms", nargs="+"); s.set_defaults(f=cmd_recall)
    s = sub.add_parser("enforce"); s.add_argument("lesson"); s.add_argument("check", help="the test/lint rule/hook that now enforces it")
    s.set_defaults(f=cmd_enforce)
    s = sub.add_parser("feature"); s.add_argument("path"); s.set_defaults(f=cmd_feature)
    s = sub.add_parser("research"); s.add_argument("topic"); s.set_defaults(f=cmd_research)
    s = sub.add_parser("map"); s.set_defaults(f=cmd_map)
    s = sub.add_parser("tidy"); s.set_defaults(f=cmd_tidy)
    s = sub.add_parser("branches"); s.add_argument("--prune", action="store_true"); s.add_argument("--yes", action="store_true")
    s.set_defaults(f=cmd_branches)
    s = sub.add_parser("rescue"); s.add_argument("target", help="change id or branch name"); s.set_defaults(f=cmd_rescue)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
