"""Behavior tests for keeping order as a project grows: structure, map, branches, rescue, lessons, tidy."""
import datetime
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_cli import GOALS, SRC, filled_plan


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        r = subprocess.run([sys.executable, str(SRC), "init", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.root / "GOALS.md").write_text(GOALS, encoding="utf-8")
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t"),
                     ("config", "core.autocrlf", "false"), ("add", "-A"), ("commit", "-q", "-m", "init")):
            self.git(*args)

    def tearDown(self):
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=str(self.root), capture_output=True, text=True, encoding="utf-8")

    def ft(self, *args):
        return subprocess.run([sys.executable, "-m", "capitan"] + list(args), cwd=str(self.root),
                              capture_output=True, text=True, encoding="utf-8")

    def put(self, rel, text="x = 1\n"):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def commit(self, msg):
        self.git("add", "-A")
        return self.git("commit", "-q", "--no-verify", "-m", msg)

    def plan(self, title="Order checkout", areas="src/features/orders/**"):
        self.ft("new", title, "--tier", "standard", "--objective", "O1")
        d = sorted((self.root / "changes").glob("0*"))[-1]
        (d / "plan.md").write_text(filled_plan(d.name, title=title).replace('"src/orders/**"', json.dumps(areas)), encoding="utf-8")
        self.assertEqual(self.ft("approve", d.name, "--skip-critique", "t").returncode, 0)
        return d


class OrganizeTest(_Base):
    # --- structure ---
    def test_feature_readme_and_map(self):
        r = self.ft("feature", "src/features/orders")
        self.assertEqual(r.returncode, 0, r.stderr)
        readme = self.root / "src/features/orders/README.md"
        readme.write_text(readme.read_text(encoding="utf-8").replace(
            "Purpose: TODO: one sentence: what this feature does for the user.", "Purpose: Customers place orders."), encoding="utf-8")
        self.put("src/features/orders/api.py")
        self.put("src/features/billing/api.py")  # no README
        self.assertEqual(self.ft("map").returncode, 0)
        m = (self.root / "docs/map.md").read_text(encoding="utf-8")
        self.assertIn("| `src/features/orders/` | Customers place orders. |", m)
        self.assertIn("| `src/features/billing/` | **no README** |", m)
        self.assertIn("Do not edit", m)

    def test_check_warns_about_areas_that_point_nowhere(self):
        self.put("src/features/orders/a.py")
        d = self.plan(areas="srcc/featurs/orders/**")
        out = self.ft("check", d.name).stdout
        self.assertIn("warning: area 'srcc/featurs/orders/**' matches no existing folder", out)
        d2 = self.plan(title="Billing", areas="src/features/billing/**")  # new folder under an existing parent: fine
        self.assertNotIn("warning", self.ft("check", d2.name).stdout)

    def test_finish_requires_readme_for_a_new_feature_folder(self):
        d = self.plan()
        self.ft("start", d.name)
        self.git("switch", "-q", "-c", "change/" + d.name)
        self.put("src/features/orders/api.py", "def place():\n    return 1\n")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        r = self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t")
        self.assertIn("feature folder src/features/orders/ has no README.md", r.stderr)
        self.ft("feature", "src/features/orders")
        r = self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t")
        self.assertIn("still has TODO: placeholders", r.stderr)
        readme = self.root / "src/features/orders/README.md"
        readme.write_text(re.sub(r"TODO: [^\n]*", "filled in", readme.read_text(encoding="utf-8")), encoding="utf-8")
        self.assertEqual(self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t").returncode, 0)

    def test_research_needs_a_decision(self):
        self.assertEqual(self.ft("research", "Vector store per tenant").returncode, 0)
        dec = self.root / "research/vector-store-per-tenant/decision.md"
        self.assertIn("tidy", "tidy")
        self.assertIn("research/vector-store-per-tenant", self.ft("tidy").stdout)
        dec.write_text(dec.read_text(encoding="utf-8").replace("Decision: TODO: GO | NEEDS-CLARIFICATION | KILL", "Decision: KILL"),
                       encoding="utf-8")
        self.assertNotIn("research/vector-store-per-tenant", self.ft("tidy").stdout)

    # --- work in progress and branches ---
    def test_work_in_progress_limit(self):
        self.put("src/features/orders/README.md", "x\n")
        ids = [self.plan(title="Change %d" % i) for i in range(4)]
        for d in ids[:3]:
            self.assertEqual(self.ft("start", d.name).returncode, 0)
        r = self.ft("start", ids[3].name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("the limit is 3", r.stderr)

    def test_status_header_shows_where_you_are(self):
        d = self.plan()
        self.ft("start", d.name)
        self.commit("plan")
        self.git("switch", "-q", "-c", "change/" + d.name)
        out = self.ft("status").stdout
        self.assertIn("branch:  change/%s" % d.name, out)
        self.assertIn("change:  %s (in-progress)" % d.name, out)

    def test_knowledge_on_a_dropped_branch_must_be_rescued(self):
        d = self.plan()
        self.ft("start", d.name)
        self.commit("plan approved and started")
        self.git("switch", "-q", "-c", "change/" + d.name)
        self.ft("learn", "Payment provider rejects zero totals", "--area", "orders", "--body", "Guard before calling.")
        self.ft("park", "Gift cards", "--from", d.name)
        self.put("docs/decisions/001-idempotency.md", "# Use idempotency keys\n")
        self.commit("work with knowledge")
        self.git("switch", "-q", "main")

        out = self.ft("status").stdout
        self.assertNotIn("knowledge not on main", out)  # the branch is still active (in progress)
        r = self.ft("drop", d.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("lesson L-001 Payment provider rejects zero totals", r.stderr)
        self.assertIn("parked:", r.stderr)
        self.assertIn("docs/decisions/001-idempotency.md", r.stderr)

        r = self.ft("rescue", d.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Payment provider rejects zero totals", (self.root / "LESSONS.md").read_text(encoding="utf-8"))
        self.assertIn("Gift cards", (self.root / "ROADMAP.md").read_text(encoding="utf-8"))
        self.assertTrue((self.root / "docs/decisions/001-idempotency.md").exists())
        self.commit("rescue knowledge")
        r = self.ft("drop", d.name)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rescue_refuses_off_the_base_branch(self):
        self.git("switch", "-q", "-c", "elsewhere")
        r = self.ft("rescue", "elsewhere")
        self.assertIn("switch to main first", r.stderr)

    def test_branches_report_and_safe_prune(self):
        d = self.plan()
        self.ft("start", d.name)
        self.commit("plan")
        self.git("switch", "-q", "-c", "change/" + d.name)
        self.put("src/features/orders/README.md", "Purpose: orders\n")
        self.put("src/features/orders/a.py")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.assertEqual(self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t").returncode, 0)
        self.commit("feature done")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "merge", "change/" + d.name)
        self.git("switch", "-q", "-c", "experiment-x")  # unmerged work with no change behind it
        self.put("scratch.py")
        self.commit("try something")
        self.git("switch", "-q", "main")

        out = self.ft("branches").stdout
        self.assertRegex(out, r"change/%s .*done .*safe to delete" % re.escape(d.name))
        self.assertIn("no change: what is this branch for?", out)
        self.assertIn("would delete", self.ft("branches", "--prune").stdout)
        self.assertEqual(self.git("rev-parse", "--verify", "--quiet", "change/" + d.name).returncode, 0)  # dry run
        self.ft("branches", "--prune", "--yes")
        self.assertNotEqual(self.git("rev-parse", "--verify", "--quiet", "change/" + d.name).returncode, 0)
        self.assertEqual(self.git("rev-parse", "--verify", "--quiet", "experiment-x").returncode, 0)  # never touched

    # --- lessons ---
    def test_enforced_lessons_leave_plans_general_ones_are_flagged(self):
        self.ft("learn", "Order totals drift from line items", "--area", "orders", "--body", "Compute once.")
        self.ft("learn", "Agents guess column names", "--area", "process", "--body", "Read the schema first.", "--general")
        self.assertEqual(self.ft("enforce", "L-001", "test_totals_are_derived").returncode, 0)
        self.ft("new", "Order totals rework", "--tier", "standard", "--objective", "O1")
        d = sorted((self.root / "changes").glob("0*"))[-1]
        self.assertNotIn("L-001", (d / "plan.md").read_text(encoding="utf-8"))
        self.assertIn("[enforced by test_totals_are_derived", self.ft("recall", "totals").stdout)
        self.assertIn("L-002 Agents guess column names", self.ft("tidy").stdout)

    def test_tidy_flags_repeated_lessons_stale_parking_and_unclaimed_code(self):
        self.ft("learn", "Invoice totals drift again", "--area", "billing", "--body", "a")
        self.ft("learn", "Invoice totals drift after refunds", "--area", "billing", "--body", "b")
        old = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()
        rm = self.root / "ROADMAP.md"
        rm.write_text(rm.read_text(encoding="utf-8").replace("<!-- capitan:parking:end -->",
                                                             "- %s Dark mode\n<!-- capitan:parking:end -->" % old), encoding="utf-8")
        self.put("legacy/old.py")
        out = self.ft("tidy").stdout
        self.assertIn("L-001 and L-002 look like the same lesson", out)
        self.assertIn("Dark mode", out)
        self.assertIn("legacy/", out)

    def test_roadmap_collapses_old_closed_changes(self):
        for i in range(12):
            self.ft("new", "Fix %d" % i, "--tier", "quick", "--intent", "x", "--done-check", "y")
            d = sorted((self.root / "changes").glob("0*"))[-1]
            self.ft("drop", d.name, "--abandon-knowledge", "test")
        text = (self.root / "ROADMAP.md").read_text(encoding="utf-8")
        self.assertIn("**Recently closed**", text)
        self.assertIn("2 older closed changes", text)
        self.assertIn("| - | nothing open |", text)


if __name__ == "__main__":
    unittest.main()


class BranchSafetyTest(_Base):
    """Regression tests for the verifier's findings on branches, rescue and knowledge checks."""

    def started_branch(self):
        d = self.plan()
        self.ft("start", d.name)
        self.commit("plan")
        self.git("switch", "-q", "-c", "change/" + d.name)
        return d

    def test_research_code_is_not_planning(self):
        self.put("research/fast-cache/prototype.py")
        self.git("add", "-A")
        r = self.ft("gate", "--staged")
        self.assertEqual(r.returncode, 1)
        self.assertIn("research/fast-cache/prototype.py", r.stderr)

    def test_same_title_different_lesson_is_at_risk_and_rescued_with_a_note(self):
        self.ft("learn", "Cache invalidation", "--area", "cache", "--body", "Old insight.")
        self.commit("lesson on main")
        d = self.started_branch()
        lt = (self.root / "LESSONS.md").read_text(encoding="utf-8")
        (self.root / "LESSONS.md").write_text(lt + "\n### L-009 (2026-11-19) [cache] Cache invalidation\nA genuinely new insight.\n", encoding="utf-8")
        self.commit("variant lesson")
        self.git("switch", "-q", "main")
        self.ft("drop", d.name)  # refused: knowledge at risk
        self.assertIn("lesson L-009 Cache invalidation", self.ft("drop", d.name).stderr)
        out = self.ft("rescue", d.name).stdout
        self.assertIn("same title as L-001", out)
        self.assertIn("A genuinely new insight.", (self.root / "LESSONS.md").read_text(encoding="utf-8"))

    def test_rescue_merges_and_never_overwrites_uncommitted_work(self):
        d = self.started_branch()
        self.put("changes/%s/notes.md" % d.name, "line 1\nbranch addition\n")
        self.commit("branch notes")
        self.git("switch", "-q", "main")
        self.put("changes/%s/notes.md" % d.name, "MY UNCOMMITTED MAIN NOTES\n")
        out = self.ft("rescue", d.name).stdout
        notes = (self.root / ("changes/%s/notes.md" % d.name)).read_text(encoding="utf-8")
        self.assertIn("MY UNCOMMITTED MAIN NOTES", notes)  # never thrown away
        self.assertIn("changes/_rescued/", out)  # the conflict went to a side folder
        self.git("add", "-A")
        r = self.ft("gate", "--staged")  # and the side folder is committable on main
        self.assertEqual(r.returncode, 0, r.stderr)
        again = self.ft("rescue", d.name).stdout  # re-running doesn't invent new differences for done files
        self.assertNotIn("file changes/_rescued", again)

    def test_generated_map_and_squash_merge_are_not_knowledge_at_risk(self):
        d = self.started_branch()
        self.ft("map")
        self.put("src/features/orders/README.md", "Purpose: orders\n")
        self.put("src/features/orders/a.py")
        self.put("docs/decisions/001-keys.md", "# Keys\n")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t")
        self.commit("feature")
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--squash", "change/" + d.name)
        self.commit("squash merge")
        self.ft("map")  # main's map differs from the branch's: still not knowledge
        dm = self.root / "docs/data-model.md"
        dm.write_text(dm.read_text(encoding="utf-8") + "\nlater edit on main\n", encoding="utf-8")
        self.commit("main moves on")
        out = self.ft("branches").stdout
        self.assertIn("already on main", out)
        self.assertNotIn("RESCUE FIRST", out)
        self.ft("branches", "--prune", "--yes")
        self.assertNotEqual(self.git("rev-parse", "--verify", "--quiet", "change/" + d.name).returncode, 0)
        self.assertTrue((self.root / "capitan" / "cache.json").exists())

    def test_long_lived_branches_are_never_pruned(self):
        self.git("branch", "develop")
        out = self.ft("branches").stdout
        self.assertIn("long-lived branch (never pruned)", out)
        self.ft("branches", "--prune", "--yes")
        self.assertEqual(self.git("rev-parse", "--verify", "--quiet", "develop").returncode, 0)

    def test_tidy_ignores_tests_and_scripts(self):
        self.put("tests/test_x.py")
        self.put("scripts/deploy.sh")
        self.put("legacy/old.py")
        out = self.ft("tidy").stdout
        self.assertIn("legacy/", out)
        self.assertNotIn("- tests/", out)
        self.assertNotIn("- scripts/", out)

    # --- round 2 verifier findings ---
    def dropped_branch_setup(self):
        d = self.started_branch()
        return d

    def test_hand_merged_appends_are_not_at_risk(self):
        d = self.started_branch()
        g = self.root / "GOALS.md"
        g.write_text(g.read_text(encoding="utf-8") + "- **O3**: Branch idea.\n", encoding="utf-8")
        self.commit("branch goal")
        self.git("switch", "-q", "main")
        g.write_text(g.read_text(encoding="utf-8") + "- **O4**: Main idea.\n", encoding="utf-8")
        self.commit("main goal")
        self.assertIn("file GOALS.md", self.ft("drop", d.name).stderr)  # really at risk before the merge
        g.write_text(g.read_text(encoding="utf-8") + "- **O3**: Branch idea.\n", encoding="utf-8")  # hand merge
        self.commit("hand merge")
        r = self.ft("drop", d.name)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_lesson_edited_on_main_after_fork_is_not_branch_knowledge(self):
        self.ft("learn", "Cache invalidaton", "--area", "cache", "--body", "Old text.")
        self.commit("lesson")
        d = self.started_branch()
        self.put("docs/x.md", "x\n")
        self.commit("unrelated branch work")
        self.git("switch", "-q", "main")
        lt = self.root / "LESSONS.md"
        lt.write_text(lt.read_text(encoding="utf-8").replace("Cache invalidaton", "Cache invalidation"), encoding="utf-8")
        self.commit("typo fix")
        self.git("switch", "-q", "change/" + d.name)
        self.put("docs/x.md", "x\ny\n")  # touch LESSONS.md on the branch too, so it is compared
        lt.write_text(lt.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.commit("more")
        self.git("switch", "-q", "main")
        out = self.ft("drop", d.name).stderr
        self.assertNotIn("lesson", out)

    def test_cache_of_wrong_shape_is_rebuilt_not_fatal(self):
        self.git("branch", "side")
        for junk in ("[]", "\"x\"", "{\"side\": \"str\"}", "{not json"):
            (self.root / "capitan" / "cache.json").write_text(junk, encoding="utf-8")
            r = self.ft("branches")
            self.assertEqual(r.returncode, 0, "%s: %s" % (junk, r.stderr))
            self.assertNotIn("Traceback", r.stderr)

    def test_config_change_invalidates_the_cache(self):
        self.git("switch", "-q", "-c", "x2")
        self.put("notes/idea.md", "big idea\n")
        self.commit("notes")
        self.git("switch", "-q", "main")
        self.assertIn("no change: what is this branch for?", self.ft("branches").stdout)
        cfg = self.root / "capitan" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["planning_paths"].append("notes/**")
        cfg.write_text(json.dumps(data), encoding="utf-8")
        self.assertIn("RESCUE FIRST", self.ft("branches").stdout)

    def test_rescue_does_not_resurrect_a_file_deleted_on_main(self):
        self.put("docs/guide.md", "v1\n")
        self.commit("guide")
        d = self.started_branch()
        self.put("docs/guide.md", "v1\nbranch edit\n")
        self.commit("edit guide")
        self.git("switch", "-q", "main")
        self.git("rm", "-q", "docs/guide.md")
        self.commit("remove guide")
        out = self.ft("rescue", d.name).stdout
        self.assertFalse((self.root / "docs/guide.md").exists())
        self.assertIn("was deleted on main", out)
        self.commit("keep the rescued copy")
        r = self.ft("drop", d.name)  # its version is now on main (in changes/_rescued): nothing at risk
        self.assertEqual(r.returncode, 0, r.stderr)

    # --- round 3: the documented setup and kickoff flows must work as written ---
    def test_documented_setup_order_commits_cleanly(self):
        fresh = Path(self._tmp.name) / "fresh"
        r = subprocess.run([sys.executable, str(SRC), "init", str(fresh), "--claude"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        g = lambda *a: subprocess.run(["git"] + list(a), cwd=str(fresh), capture_output=True, text=True, encoding="utf-8")
        g("init", "-q", "-b", "main"); g("config", "user.email", "t@e"); g("config", "user.name", "t")
        h = subprocess.run([sys.executable, "-m", "capitan", "hooks"], cwd=str(fresh), capture_output=True, text=True)
        self.assertEqual(h.returncode, 0, h.stderr)
        g("add", "-A")
        c = g("commit", "-q", "-m", "add capitan")  # hooks installed first, as the docs say
        self.assertEqual(c.returncode, 0, c.stderr + c.stdout)
        self.assertIn("governance files changed", c.stderr + c.stdout)

    def test_kickoff_config_change_commits_on_main_with_a_warning(self):
        self.ft("hooks")
        cfg = self.root / "capitan" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["agent_cmd"] = "claude -p"
        cfg.write_text(json.dumps(data), encoding="utf-8")
        self.git("add", "-A")
        c = self.git("commit", "-q", "-m", "kickoff results")
        self.assertNotEqual(c.returncode, 0)  # an agent can't change the rules on its own
        self.assertIn("allow-governance", c.stderr + c.stdout)
        self.assertEqual(self.ft("allow-governance").returncode, 0)  # the human says yes
        c = self.git("commit", "-q", "-m", "kickoff results")
        self.assertEqual(c.returncode, 0, c.stderr + c.stdout)
        self.assertIn("governance files changed (capitan/config.json)", c.stderr + c.stdout)

    def test_changed_value_that_exists_elsewhere_on_main_stays_at_risk(self):
        self.put("docs/db.md", "## Decision\n- Use Postgres\n\n## Rejected\n- Use Mongo\n")
        self.commit("db doc")
        d = self.started_branch()
        self.put("docs/db.md", "## Decision\n- Use Redis\n\n## Rejected\n- Use Mongo\n")
        self.commit("switch decision")
        self.git("switch", "-q", "main")
        self.put("docs/db.md", "## Decision\n- Use Postgres\n\n## Rejected\n- Use Mongo\n- Use Redis\n")
        self.commit("main rejects redis")
        self.assertIn("file docs/db.md", self.ft("drop", d.name).stderr)

    def test_finished_branch_with_open_pr_says_merge_not_rescue(self):
        d = self.started_branch()
        self.put("src/features/orders/README.md", "Purpose: orders\n")
        self.put("src/features/orders/a.py")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.ft("finish", d.name, "--no-lessons", "t", "--skip-review", "t")
        self.commit("finished")
        self.git("switch", "-q", "main")
        out = self.ft("branches").stdout
        self.assertIn("PR not merged yet", out)
        self.assertNotIn("RESCUE FIRST", out)
        self.assertNotIn("knowledge not on main", self.ft("status").stdout)

    # --- round 4: the rules can't be weakened by the change they judge ---
    def test_staged_edit_to_the_gate_cannot_switch_it_off(self):
        self.ft("hooks")
        cli = self.root / "capitan" / "cli.py"
        src = cli.read_text(encoding="utf-8")
        cli.write_text(src.replace("def gate_eval(files, ci=False, base=None, statuses=None):",
                                   "def gate_eval(files, ci=False, base=None, statuses=None):\n    return None, [], []\n\n\n"
                                   "def _old_gate_eval(files, ci=False, base=None, statuses=None):"),
                       encoding="utf-8")
        self.put("src/x.py")
        self.git("add", "-A")
        c = self.git("commit", "-q", "-m", "sneaky")
        self.assertNotEqual(c.returncode, 0, "the edited gate judged itself")
        self.assertIn("blocked", c.stderr + c.stdout)

    def test_ci_blocks_rule_changes_without_the_human_label(self):
        d = self.started_branch()
        cfg = self.root / "capitan" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["planning_paths"].append("src/**")
        cfg.write_text(json.dumps(data), encoding="utf-8")
        self.commit("loosen the rules")
        r = self.ft("gate", "--ci", "--base", "main")
        self.assertEqual(r.returncode, 1)
        self.assertIn("governance-approved", r.stderr)

    def test_config_edit_after_review_invalidates_the_review(self):
        d = self.started_branch()
        self.put("src/features/orders/README.md", "Purpose: orders\n")
        self.put("src/features/orders/a.py")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.ft("review", d.name, "--print")
        (d / "review.md").write_text("VERDICT: PASS\nAC-1: PASS\n", encoding="utf-8")
        cfg = self.root / "capitan" / "config.json"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace('"scope_mode": "warn"', '"scope_mode": "block"'), encoding="utf-8")
        r = self.ft("finish", d.name, "--no-lessons", "t")
        self.assertIn("changed after the review", r.stderr)

    # --- round 5 ---
    def test_agent_cannot_create_new_governance_files_at_edit_time(self):
        r = self.ft("gate", "--paths", ".claude/settings.local.json")  # what the Claude edit hook runs
        self.assertEqual(r.returncode, 1)
        self.assertIn("allow-governance", r.stderr)

    def test_init_owner_writes_codeowners_for_the_rule_files(self):
        fresh = Path(self._tmp.name) / "owned"
        r = subprocess.run([sys.executable, str(SRC), "init", str(fresh), "--owner", "octo-cat"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        owners = (fresh / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for path in ("/capitan/", "/.github/", "/.claude/", "/.gitignore"):
            self.assertIn("%s @octo-cat" % path, owners)
        r = subprocess.run([sys.executable, str(SRC), "init", str(fresh / "plain")], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("--owner", r.stdout)
