"""Behavior tests for the git-aware parts: gate, hooks, review, finish (close), PR description, CI, agent hook."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_cli import GOALS, SRC, filled_plan

ADAPTER_HOOK = SRC.parents[1] / "adapters" / "claude-code" / "hooks" / "capitan_gate.py"
REVIEW_PASS = "VERDICT: PASS\nAC-1: PASS - test_checkout_creates_order passed\nFindings: none\nNot checked: nothing\n"


class GateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        r = subprocess.run([sys.executable, str(SRC), "init", str(self.root), "--claude"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.root / "GOALS.md").write_text(GOALS, encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    # --- helpers ---
    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")

    def ft(self, *args):
        return subprocess.run([sys.executable, "-m", "capitan"] + list(args), cwd=str(self.root),
                              capture_output=True, text=True, encoding="utf-8")

    def put(self, rel, text="x = 1\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def config(self, **kw):
        p = self.root / "capitan" / "config.json"
        cfg = json.loads(p.read_text(encoding="utf-8"))
        cfg.update(kw)
        p.write_text(json.dumps(cfg), encoding="utf-8")

    def started_change(self, tier="standard", branch=True):
        if tier == "quick":
            self.ft("new", "Fix footer", "--tier", "quick", "--intent", "fix", "--done-check", "renders")
            d = sorted((self.root / "changes").glob("0*"))[-1]
            self.assertEqual(self.ft("approve", d.name).returncode, 0)
        else:
            self.ft("new", "Order checkout", "--tier", "standard", "--objective", "O1")
            d = sorted((self.root / "changes").glob("0*"))[-1]
            (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
            self.assertEqual(self.ft("approve", d.name, "--skip-critique", "test").returncode, 0)
        self.assertEqual(self.ft("start", d.name).returncode, 0)
        if branch:
            self.git("switch", "-q", "-c", "change/" + d.name)
        return d

    def pass_criteria(self, d):
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")

    def build_and_review(self, d, review=REVIEW_PASS):
        self.put("src/orders/checkout.py", "def checkout(cart):\n    return {'order': cart}\n")
        self.put("tests/test_checkout.py", "def test_checkout_creates_order():\n    assert True\n")
        self.pass_criteria(d)
        r = self.ft("review", d.name, "--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        (d / "review.md").write_text(review, encoding="utf-8")
        return r.stdout

    # --- plan gate ---
    def test_code_without_a_change_is_blocked_planning_files_are_not(self):
        self.put("src/app.py")
        self.git("add", "src/app.py")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("on 'main' itself", r.stderr)
        self.git("reset", "-q")
        self.put("GOALS.md", GOALS + "\n- tweak\n")
        self.git("add", "GOALS.md")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("planning files only", r.stdout)

    def test_approved_but_not_started_is_blocked(self):
        self.ft("new", "Order checkout", "--tier", "standard", "--objective", "O1")
        d = sorted((self.root / "changes").glob("0*"))[-1]
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        self.ft("approve", d.name, "--skip-critique", "t")
        self.git("switch", "-q", "-c", "change/" + d.name)
        self.put("src/orders/a.py")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("run start first", r.stderr)

    def test_pre_commit_hook_blocks_a_real_commit(self):
        self.assertEqual(self.ft("hooks").returncode, 0)
        self.put("src/app.py")
        self.git("add", "src/app.py")
        r = self.git("commit", "-m", "sneaky")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("on 'main' itself", r.stderr + r.stdout)
        self.git("reset", "-q")
        d = self.started_change()
        self.put("src/orders/a.py")
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", "planned work")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def test_hooks_never_overwrite_a_foreign_hook(self):
        hook = self.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
        r = self.ft("hooks")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(hook.read_text(encoding="utf-8"), "#!/bin/sh\necho mine\n")

    # --- scope guard ---
    def test_scope_guard_warns_by_default_and_blocks_when_configured(self):
        self.started_change()
        self.put("src/orders/a.py")
        self.put("src/billing/b.py")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("outside the plan's areas", r.stderr)
        self.assertIn("src/billing/b.py", r.stderr)
        self.assertNotIn("src/orders/a.py", r.stderr)
        self.config(scope_mode="block")
        self.assertEqual(self.ft("gate", "--staged").returncode, 1)
        log = (self.root / "capitan" / "gate-log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(log), 2)
        self.assertIn("outside the plan", json.loads(log[0])["warnings"][0])

    def test_quick_change_has_a_file_limit(self):
        self.started_change(tier="quick")
        for i in range(4):
            self.put("src/f%d.py" % i)
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Make it a standard change", r.stderr)

    # --- review, close, PR ---
    def test_review_prompt_contains_plan_criteria_and_the_diff(self):
        d = self.started_change()
        out = self.build_and_review(d)
        self.assertIn("You are the code reviewer", out)
        self.assertIn("AC-1", out)
        self.assertIn("def checkout(cart)", out)
        self.assertTrue((d / ".review-hash").exists())

    def test_finish_requires_passing_current_review_and_a_lesson(self):
        d = self.started_change()
        self.build_and_review(d, review="VERDICT: FAIL\nAC-1: FAIL - test asserts True\n")
        r = self.ft("finish", d.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("verdict is FAIL", r.stderr)
        self.assertIn("record what this change taught you", r.stderr)

        (d / "review.md").write_text(REVIEW_PASS, encoding="utf-8")
        self.put("src/orders/checkout.py", "def checkout(cart):\n    return None  # changed after review\n")
        self.assertIn("code changed after the review", self.ft("finish", d.name, "--no-lessons", "t").stderr)

        self.ft("review", d.name, "--print")
        (d / "review.md").write_text(REVIEW_PASS, encoding="utf-8")
        r = self.ft("learn", "Checkout needs idempotency", "--area", "orders", "--body", "Use a key.")
        self.assertIn("(from %s)" % d.name, r.stdout)
        r = self.ft("finish", d.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        pr = (d / "pr.md").read_text(encoding="utf-8")
        self.assertIn("## Review in this order", pr)
        self.assertLess(pr.index("src/orders/**"), pr.index("**Tests**"))
        self.assertIn("| AC-1 |", pr)
        self.assertIn("| pass | PASS |", pr)
        self.assertIn("Checkout needs idempotency", pr)
        self.assertIn("Customers can place orders", pr)

    def test_schema_change_requires_data_model_update(self):
        d = self.started_change()
        self.build_and_review(d)
        self.put("db/migrations/001_orders.sql", "create table orders (id int);\n")
        self.ft("review", d.name, "--print")
        (d / "review.md").write_text(REVIEW_PASS, encoding="utf-8")
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertIn("docs/data-model.md did not", r.stderr)
        dm = self.root / "docs" / "data-model.md"
        dm.write_text(dm.read_text(encoding="utf-8") + "\nORDER belongs to CUSTOMER\n", encoding="utf-8")
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("**Data model and schema**", (d / "pr.md").read_text(encoding="utf-8"))

    # --- CI ---
    def test_ci_gate_requires_finished_change_with_current_review(self):
        d = self.started_change()
        self.build_and_review(d)
        self.git("add", "-A"); self.git("commit", "-q", "-m", "work")
        r = self.ft("gate", "--ci", "--base", "main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("expected 'done'", r.stderr)
        self.assertEqual(self.ft("finish", d.name, "--no-lessons", "t").returncode, 0)
        self.git("add", "-A"); self.git("commit", "-q", "-m", "finish")
        r = self.ft("gate", "--ci", "--base", "main")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.config(pr_max_lines=1, pr_size_mode="block")
        self.assertIn("Smaller PRs", self.ft("gate", "--ci", "--base", "main").stderr)
        self.config(pr_max_lines=400)
        self.put("src/orders/checkout.py", "def checkout(cart):\n    return 'pushed after review'\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "late push")
        r = self.ft("gate", "--ci", "--base", "main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed after its review", r.stderr)

    def test_ci_branch_detection_uses_ci_env_var(self):
        d = self.started_change(branch=False)
        self.put("src/orders/a.py")
        r = subprocess.run([sys.executable, "-m", "capitan", "gate", "--base", "main"], cwd=str(self.root),
                           capture_output=True, text=True, env=dict(__import__("os").environ, GITHUB_HEAD_REF="change/" + d.name))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(d.name, r.stdout)

    # --- regression tests for verifier round 1 findings ---
    def test_pycache_is_not_code(self):
        self.started_change(tier="quick")
        self.put("src/one.py")
        self.ft("status")  # running the CLI may create capitan/__pycache__
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("capitan/__pycache__/", (self.root / ".gitignore").read_text(encoding="utf-8"))

    def test_epic_carries_no_code(self):
        self.ft("new", "Billing", "--tier", "epic", "--objective", "O2")
        epic = sorted((self.root / "changes").glob("0*"))[-1]
        (epic / "epic.md").write_text((epic / "epic.md").read_text(encoding="utf-8").replace("TODO: ", ""), encoding="utf-8")
        self.ft("approve", epic.name, "--skip-critique", "t")
        self.ft("start", epic.name)
        self.git("switch", "-q", "-c", "change/" + epic.name)
        self.put("src/anything/huge.py")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("epics carry no code", r.stderr)

    def test_finish_on_base_branch_with_no_diff_is_refused(self):
        d = self.started_change(branch=False)
        self.pass_criteria(d)
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertEqual(r.returncode, 1)
        self.assertIn("nothing to review", r.stderr)

    def test_non_ascii_file_is_fingerprinted_and_reviewed(self):
        d = self.started_change()
        self.put("src/orders/café.py", "PRICE = 1\n")
        self.pass_criteria(d)
        out = self.ft("review", d.name, "--print").stdout
        self.assertIn("PRICE = 1", out)
        (d / "review.md").write_text(REVIEW_PASS, encoding="utf-8")
        self.put("src/orders/café.py", "PRICE = 999\n")
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertIn("code changed after the review", r.stderr)

    def test_review_parsing_accepts_tables_and_dashes_rejects_extra_fail(self):
        d = self.started_change()
        self.build_and_review(d, review="VERDICT: PASS\n| ID | Then | Builder | Reviewer |\n|---|---|---|---|\n"
                                        "| AC-1 | an Order is created | pass | PASS |\n")
        self.assertEqual(self.ft("finish", d.name, "--no-lessons", "t").returncode, 0)

    def test_review_template_echo_and_unplanned_fail_do_not_pass(self):
        d = self.started_change()
        self.build_and_review(d, review="VERDICT: PASS\nAC-1: <PASS, FAIL or UNVERIFIED> - evidence\n")
        self.assertIn("did not PASS criteria: AC-1", self.ft("finish", d.name, "--no-lessons", "t").stderr)
        (d / "review.md").write_text("VERDICT: PASS\nAC-1 — PASS\nAC-9: FAIL - extra check broke\n", encoding="utf-8")
        self.assertIn("review reports FAIL on AC-9", self.ft("finish", d.name, "--no-lessons", "t").stderr)

    def test_review_prose_mentioning_pass_is_not_a_pass(self):
        d = self.started_change()
        self.build_and_review(d, review="VERDICT: PASS\nAC-1: does NOT PASS when the cart is empty\n")
        self.assertIn("did not PASS criteria: AC-1", self.ft("finish", d.name, "--no-lessons", "t").stderr)

    def test_table_row_with_reviewer_fail_is_not_lost(self):
        d = self.started_change()
        self.build_and_review(d, review="VERDICT: PASS\nAC-1: PASS - see table\n| ID | Then | Builder | Reviewer |\n"
                                        "|---|---|---|---|\n| AC-1 | an Order is created | pass | FAIL |\n")
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not PASS criteria: AC-1", r.stderr)

    def test_rebase_conflict_does_not_block_edits(self):
        self.put("src/orders/a.py", "v = 'base'\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "base file")
        d = self.started_change()
        self.put("src/orders/a.py", "v = 'branch'\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "branch edit", "--no-verify")
        self.git("switch", "-q", "main")
        self.put("src/orders/a.py", "v = 'main'\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "main edit", "--no-verify")
        self.git("switch", "-q", "change/" + d.name)
        self.assertNotEqual(self.git("rebase", "main").returncode, 0)  # conflict, HEAD detached
        r = self.ft("gate", "--paths", "src/orders/a.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(d.name, r.stdout)
        self.git("rebase", "--abort")

    def test_hooks_refuse_shared_hooks_path(self):
        self.git("config", "core.hooksPath", str(Path(self._tmp.name) / "shared-hooks"))
        r = self.ft("hooks")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("core.hooksPath", r.stderr)
        self.assertFalse((Path(self._tmp.name) / "shared-hooks" / "pre-commit").exists())

    def test_paths_outside_project_are_reported_not_crashed(self):
        r = self.ft("gate", "--paths", "src/orders/../../../outside/x.py")
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("outside the project", r.stderr)

    def test_claude_hook_fails_open_when_capitan_is_broken(self):
        (self.root / "capitan" / "config.json").write_text("{not json", encoding="utf-8")
        r = self.run_hook("src/app.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("failed unexpectedly", r.stderr)
        self.assertEqual(self.run_hook("capitan/config.json").returncode, 0)

    # --- Claude Code adapter hook ---
    def run_hook(self, rel):
        event = {"tool_name": "Write", "tool_input": {"file_path": str(self.root / rel)}, "cwd": str(self.root)}
        env = dict(__import__("os").environ, CLAUDE_PROJECT_DIR=str(self.root))  # as Claude Code sets it
        return subprocess.run([sys.executable, str(self.root / ".claude" / "hooks" / "capitan_gate.py")],
                              input=json.dumps(event), capture_output=True, text=True, cwd=str(self.root), env=env)

    def test_claude_hook_uses_project_dir_not_the_session_folder(self):
        event = {"tool_name": "Write", "tool_input": {"file_path": str(self.root / ".claude" / "settings.local.json")},
                 "cwd": str(self.root / "src")}  # the session cd'd into a subfolder
        env = dict(__import__("os").environ, CLAUDE_PROJECT_DIR=str(self.root))
        r = subprocess.run([sys.executable, str(self.root / ".claude" / "hooks" / "capitan_gate.py")],
                           input=json.dumps(event), capture_output=True, text=True, cwd=str(self.root), env=env)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_gate_paths_odd_spellings_and_case_are_still_governance(self):
        for p in (".Claude/settings.local.json", ".claude /settings.local.json", "src/../.CLAUDE/x.json"):
            r = self.ft("gate", "--paths", p)
            self.assertEqual(r.returncode, 1, "%s: %s" % (p, r.stderr))
        tok = self.root / ".git" / "capitan-governance-ok"
        tok.write_text("2099-01-01T00:00:00\n", encoding="utf-8")  # a token from the future
        self.assertEqual(self.ft("gate", "--paths", ".claude/x.json").returncode, 1)

    def test_claude_edit_hook_blocks_code_before_a_plan(self):
        self.assertTrue((self.root / ".claude" / "settings.json").exists())
        r = self.run_hook("src/app.py")
        self.assertEqual(r.returncode, 2)
        self.assertIn("blocked:", r.stderr)
        self.assertEqual(self.run_hook("GOALS.md").returncode, 0)
        self.started_change()
        self.assertEqual(self.run_hook("src/orders/new.py").returncode, 0)


if __name__ == "__main__":
    unittest.main()


class MonorepoAndBaseTest(unittest.TestCase):
    """capitan installed in a monorepo subfolder, and repos whose base branch is not 'main'."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.top = Path(self._tmp.name) / "mono"
        self.root = self.top / "apps" / "web"
        r = subprocess.run([sys.executable, str(SRC), "init", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.root / "GOALS.md").write_text(GOALS, encoding="utf-8")
        (self.top / "other").mkdir()
        (self.top / "other" / "y.py").write_text("y = 1\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=str(self.top), capture_output=True, text=True, encoding="utf-8")

    def ft(self, *args):
        return subprocess.run([sys.executable, "-m", "capitan"] + list(args), cwd=str(self.root),
                              capture_output=True, text=True, encoding="utf-8")

    def repo(self, base="main"):
        self.git("init", "-q", "-b", base)
        self.git("config", "user.email", "t@example.com"); self.git("config", "user.name", "t")
        self.git("config", "core.autocrlf", "false")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "init")

    def started(self):
        self.ft("new", "Order checkout", "--tier", "standard", "--objective", "O1")
        d = sorted((self.root / "changes").glob("0*"))[-1]
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        self.ft("approve", d.name, "--skip-critique", "t")
        self.ft("start", d.name)
        self.git("switch", "-q", "-c", "change/" + d.name)
        return d

    def test_monorepo_paths_are_relative_to_the_project(self):
        self.repo()
        (self.root / "GOALS.md").write_text(GOALS + "\n- more\n", encoding="utf-8")
        (self.top / "other" / "y.py").write_text("y = 2\n", encoding="utf-8")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)       # planning file + sibling-project code: not ours to gate
        self.git("commit", "-q", "-m", "goals and sibling")
        d = self.started()
        (self.root / "src" / "orders").mkdir(parents=True)
        (self.root / "src" / "orders" / "a.py").write_text("a = 1\n", encoding="utf-8")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        out = self.ft("review", d.name, "--print").stdout
        self.assertIn("src/orders/a.py", out)
        self.assertIn("a = 1", out)
        (d / "review.md").write_text(REVIEW_PASS, encoding="utf-8")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("outside the plan", r.stderr)
        (self.root / "src" / "orders" / "a.py").write_text("a = 'changed after review'\n", encoding="utf-8")
        self.assertIn("code changed after the review", self.ft("finish", d.name, "--no-lessons", "t").stderr)

    def test_master_base_branch_is_detected_and_protected(self):
        self.repo(base="master")
        self.ft("new", "Order checkout", "--tier", "standard", "--objective", "O1")
        d = sorted((self.root / "changes").glob("0*"))[-1]
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        self.ft("approve", d.name, "--skip-critique", "t")
        self.ft("start", d.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("on 'master' itself", r.stderr)

    def test_detached_head_blocks_code(self):
        self.repo()
        self.git("checkout", "-q", "--detach")
        (self.root / "src").mkdir()
        (self.root / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("detached HEAD", r.stderr)

    def test_two_projects_share_one_hook(self):
        self.repo()
        second = self.top / "apps" / "api"
        r = subprocess.run([sys.executable, str(SRC), "init", str(second)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ft("hooks").returncode, 0)
        r = subprocess.run([sys.executable, "-m", "capitan", "hooks"], cwd=str(second), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        hook = (self.top / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("/apps/web\"", hook)
        self.assertIn("/apps/api\"", hook)
        self.assertEqual(self.ft("hooks").returncode, 0)  # re-running does not duplicate
        self.assertEqual((self.top / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8").count("apps/web"), 1)

    def test_removed_project_hook_line_skips_itself(self):
        self.repo()
        self.assertEqual(self.ft("hooks").returncode, 0)
        import shutil
        shutil.rmtree(self.root)
        (self.top / "README.txt").write_text("hello\n", encoding="utf-8")
        self.git("add", "-A")
        r = self.git("commit", "-q", "-m", "after removing the project")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
