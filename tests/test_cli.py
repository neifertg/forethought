"""Behavior tests: install capitan into a temp project and drive the CLI like a user or agent would."""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "capitan" / "cli.py"

GOALS = """# Goals
## Objectives
- **O1**: Customers can place orders without calling support.
- **O2**: Monthly invoicing runs with zero manual steps.
## Current milestone
Ordering MVP by March.
## Non-goals
- Mobile app.
"""

FAKE_AGENT = 'import sys\nsys.stdin.read()\nprint("VERDICT: %s\\n1. [minor] tighten AC-1 -> name the test")\n'


def filled_plan(cid, objective="O1", criteria=None, extra_lines=0, title="Order checkout"):
    data = {"id": cid, "tier": "standard", "status": "draft", "created": "2026-11-18",
            "objective": objective, "areas": ["src/orders/**"], "timebox": "1 day",
            "criteria": criteria if criteria is not None else [
                {"id": "AC-1", "when": "a customer submits a valid cart", "then": "an Order is created",
                 "test": "test_checkout_creates_order", "status": "pending"}]}
    body = "\n".join("filler line %d" % i for i in range(extra_lines))
    return ("# %s\n\n```json plan\n%s\n```\n\n## Why\nCustomers order themselves.\n\n## Data impact\n"
            "Creates Order rows linked to Customer.\n\n## Test plan\nUnit + one e2e checkout.\n\n## Risks\n"
            "Double submit.\n\n## Out of scope\nCoupons (parked).\n\n## Relevant lessons\n- None found.\n%s\n"
            % (title, json.dumps(data, indent=2), body))


class CapitanTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "proj"
        r = subprocess.run([sys.executable, str(SRC), "init", str(self.root), "--claude"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.cmd = [sys.executable, "-m", "capitan"]

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run(self.cmd + list(args), capture_output=True,
                              text=True, encoding="utf-8", cwd=str(self.root))

    def goals(self):
        (self.root / "GOALS.md").write_text(GOALS, encoding="utf-8")

    def new_standard(self, title="Order checkout", *extra):
        r = self.run_cli("new", title, "--tier", "standard", "--objective", "O1", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return sorted((self.root / "changes").glob("0*"))[-1]

    def set_agent(self, verdict):
        fake = self.root / ("fake_%s.py" % verdict)
        fake.write_text(FAKE_AGENT % verdict, encoding="utf-8")
        (self.root / "capitan" / "config.json").write_text(json.dumps(
            {"plan_max_lines": 80, "agent_cmd": '"%s" "%s"' % (sys.executable, fake)}), encoding="utf-8")

    # --- install ---
    def test_init_installs_files_and_never_overwrites(self):
        for f in ("AGENTS.md", "GOALS.md", "ROADMAP.md", "LESSONS.md", "docs/data-model.md",
                  "capitan/cli.py", "capitan/playbooks/critique.md", ".claude/skills/capitan-plan/SKILL.md"):
            self.assertTrue((self.root / f).exists(), f)
        self.assertIn("@AGENTS.md", (self.root / "CLAUDE.md").read_text(encoding="utf-8"))
        self.goals()
        r = subprocess.run([sys.executable, str(SRC), "init", str(self.root)], capture_output=True, text=True, encoding="utf-8")
        self.assertIn("kept     GOALS.md", r.stdout)
        self.assertIn("Customers can place orders", (self.root / "GOALS.md").read_text(encoding="utf-8"))

    # --- goals anchor ---
    def test_new_refuses_until_goals_are_real(self):
        r = self.run_cli("new", "Anything", "--tier", "standard")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("GOALS.md has no objectives", r.stderr)

    def test_unknown_objective_fails_check(self):
        self.goals()
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name, objective="O9"), encoding="utf-8")
        r = self.run_cli("check", d.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("objective 'O9'", r.stdout)

    # --- plan quality ---
    def test_fresh_template_fails_then_filled_plan_passes(self):
        self.goals()
        d = self.new_standard()
        r = self.run_cli("check", d.name)
        self.assertEqual(r.returncode, 1)
        self.assertIn("TODO", r.stdout)
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        r = self.run_cli("check", d.name)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_criterion_without_test_and_overlong_plan_fail(self):
        self.goals()
        d = self.new_standard()
        bad = [{"id": "AC-1", "when": "x", "then": "y", "test": "", "status": "pending"}]
        (d / "plan.md").write_text(filled_plan(d.name, criteria=bad, extra_lines=90), encoding="utf-8")
        out = self.run_cli("check", d.name).stdout
        self.assertIn("criterion AC-1 is missing 'test'", out)
        self.assertIn("keep it to one page", out)

    def test_areas_flag_is_stored(self):
        self.goals()
        d = self.new_standard("Invoices", "--areas", "src/billing/**, db/migrations/**")
        text = (d / "plan.md").read_text(encoding="utf-8")
        self.assertIn('"src/billing/**"', text)
        self.assertIn('"db/migrations/**"', text)

    # --- critique and approval ---
    def test_approve_requires_a_ready_critique(self):
        self.goals()
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        r = self.run_cli("approve", d.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no critique yet", r.stderr)

        self.set_agent("REVISE")
        self.assertEqual(self.run_cli("critique", d.name).returncode, 0)
        self.assertIn("VERDICT: REVISE", (d / "critique.md").read_text(encoding="utf-8"))
        r = self.run_cli("approve", d.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REVISE", r.stderr)

        self.set_agent("READY")
        self.run_cli("critique", d.name)
        r = self.run_cli("approve", d.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"status": "approved"', (d / "plan.md").read_text(encoding="utf-8"))
        self.assertRegex((self.root / "ROADMAP.md").read_text(encoding="utf-8"), r"\| %s \| Order checkout \| standard \| O1 \| approved \|" % d.name)

    def test_skip_critique_is_recorded(self):
        self.goals()
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        r = self.run_cli("approve", d.name, "--skip-critique", "spike, throwaway")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"critique_skipped": "spike, throwaway"', (d / "plan.md").read_text(encoding="utf-8"))

    def test_critique_print_bundles_goals_plan_and_matching_lessons(self):
        self.goals()
        self.run_cli("learn", "Checkout double-submit created duplicate orders", "--area", "orders",
                      "--body", "Use an idempotency key on order creation.")
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        out = self.run_cli("critique", d.name, "--print").stdout
        self.assertIn("You are the plan critic", out)
        self.assertIn("Monthly invoicing", out)
        self.assertIn("test_checkout_creates_order", out)
        self.assertIn("idempotency key", out)

    # --- lifecycle ---
    def test_cannot_start_unapproved_or_finish_with_open_criteria(self):
        self.goals()
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        r = self.run_cli("start", d.name)
        self.assertIn("'in-progress' only from: approved", r.stderr)
        self.run_cli("approve", d.name, "--skip-critique", "test")
        self.assertEqual(self.run_cli("start", d.name).returncode, 0)
        r = self.run_cli("finish", d.name)
        self.assertIn("criteria not passed yet: AC-1", r.stderr)
        text = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(text, encoding="utf-8")
        self.assertEqual(self.run_cli("finish", d.name, "--no-lessons", "t").returncode, 0)

    def test_quick_tier_needs_only_intent_and_done_check(self):
        r = self.run_cli("new", "Fix typo in footer", "--tier", "quick", "--intent", "fix 'recieve'",
                          "--done-check", "footer renders 'receive'")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Ask the human to run", r.stdout)
        self.assertIn('"status": "draft"', sorted((self.root / "changes").glob("0*"))[-1].joinpath("plan.md").read_text(encoding="utf-8"))
        r = self.run_cli("new", "Vague", "--tier", "quick")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("as DRAFT", r.stderr)
        d = sorted((self.root / "changes").glob("0*"))[-1]
        self.assertIn("only from: approved", self.run_cli("start", d.name).stderr)
        self.assertIn("quick change needs 'intent'", self.run_cli("approve", d.name).stdout)
        text = (d / "plan.md").read_text(encoding="utf-8")
        text = text.replace('"intent": ""', '"intent": "x"').replace('"done_check": ""', '"done_check": "y"')
        (d / "plan.md").write_text(text, encoding="utf-8")
        self.assertEqual(self.run_cli("approve", d.name).returncode, 0)

    def test_epic_dependencies_are_validated(self):
        self.goals()
        r = self.run_cli("new", "Billing", "--tier", "epic", "--objective", "O2")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = sorted((self.root / "changes").glob("0*"))[-1]
        text = (d / "epic.md").read_text(encoding="utf-8").replace("TODO: ", "")
        block = re.search(r"```json plan\n(.*?)\n```", text, re.S)
        data = json.loads(block.group(1))

        def with_deps(a_deps, b_deps):
            data["children"][0]["depends_on"], data["children"][1]["depends_on"] = a_deps, b_deps
            return text.replace(block.group(1), json.dumps(data, indent=2))

        (d / "epic.md").write_text(with_deps(["b"], ["a"]), encoding="utf-8")
        self.assertIn("cycle", self.run_cli("check", d.name).stdout)
        (d / "epic.md").write_text(with_deps([], ["zzz"]), encoding="utf-8")
        self.assertIn("unknown child zzz", self.run_cli("check", d.name).stdout)
        (d / "epic.md").write_text(with_deps([], ["a"]), encoding="utf-8")
        self.assertEqual(self.run_cli("check", d.name).returncode, 0, self.run_cli("check", d.name).stdout)

    # --- lessons and parking ---
    def test_new_plan_prefills_matching_lessons(self):
        self.goals()
        self.run_cli("learn", "Invoice totals drifted from line items", "--area", "billing, invoices",
                      "--body", "Compute totals in one place.")
        self.run_cli("learn", "Unrelated CSS lesson", "--area", "ui", "--body", "n/a")
        d = self.new_standard("Monthly invoices batch")
        text = (d / "plan.md").read_text(encoding="utf-8")
        self.assertIn("L-001 Invoice totals drifted", text)
        self.assertNotIn("CSS", text)
        out = self.run_cli("recall", "totals").stdout
        self.assertIn("L-001", out)

    # --- regression tests for reviewer findings ---
    def ready_plan(self):
        self.goals()
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        return d

    def manual_critique(self, d, reply):
        self.assertEqual(self.run_cli("critique", d.name, "--print").returncode, 0)
        (d / "critique.md").write_text(reply, encoding="utf-8")

    def test_status_order_cannot_be_skipped_or_reversed(self):
        d = self.ready_plan()
        text = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(text, encoding="utf-8")
        self.assertIn("only from: in-progress", self.run_cli("finish", d.name).stderr)
        self.run_cli("approve", d.name, "--skip-critique", "t")
        self.assertIn("only from: in-progress", self.run_cli("finish", d.name).stderr)
        self.run_cli("start", d.name)
        self.assertEqual(self.run_cli("finish", d.name, "--no-lessons", "t").returncode, 0)
        r = self.run_cli("approve", d.name, "--skip-critique", "t")
        self.assertIn("only a draft can be approved", r.stderr)
        self.assertIn("only from: draft, approved, in-progress", self.run_cli("drop", d.name).stderr)

    def test_echoed_template_verdict_does_not_count(self):
        d = self.ready_plan()
        self.manual_critique(d, "```\nVERDICT: READY | REVISE\n```\nVERDICT: READY\n1. ok\n```\nVERDICT: READY\n```\nVERDICT: REVISE\n")
        self.assertIn("verdict is REVISE", self.run_cli("approve", d.name).stderr)
        self.manual_critique(d, "VERDICT: READY | REVISE\n1. ok\n")
        self.assertIn("no 'VERDICT: READY'", self.run_cli("approve", d.name).stderr)

    def test_fenced_or_bold_ready_reply_is_accepted(self):
        for reply in ("```\nVERDICT: READY\n1. [minor] x -> y\n```\n", "**VERDICT: READY**\n1. fine\n",
                      "VERDICT: READY - no blockers\n"):
            d = self.ready_plan()
            self.manual_critique(d, reply)
            r = self.run_cli("approve", d.name)
            self.assertEqual(r.returncode, 0, "%r -> %s" % (reply, r.stderr))

    def test_plan_edited_after_approval_cannot_proceed_until_revised(self):
        d = self.ready_plan()
        self.run_cli("approve", d.name, "--skip-critique", "t")
        self.assertEqual(self.run_cli("start", d.name).returncode, 0)
        text = (d / "plan.md").read_text(encoding="utf-8")
        loosened = (text.replace('"src/orders/**"', '"**"').replace("test_checkout_creates_order", "eyeballed it")
                    .replace('"status": "pending"', '"status": "pass"'))
        (d / "plan.md").write_text(loosened, encoding="utf-8")
        r = self.run_cli("finish", d.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("changed after approval", r.stdout)
        self.assertEqual(self.run_cli("check", d.name).returncode, 1)
        self.assertEqual(self.run_cli("revise", d.name).returncode, 0)
        self.assertIn('"status": "draft"', (d / "plan.md").read_text(encoding="utf-8"))
        self.assertEqual(self.run_cli("approve", d.name, "--skip-critique", "re-scoped").returncode, 0)

    def test_deleting_approved_hash_does_not_disable_drift_check(self):
        d = self.ready_plan()
        self.run_cli("approve", d.name, "--skip-critique", "t")
        self.run_cli("start", d.name)
        text = (d / "plan.md").read_text(encoding="utf-8")
        text = re.sub(r'\s*"approved_hash": "[0-9a-f]+",?', "", text)
        text = text.replace("test_checkout_creates_order", "eyeballed").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(text, encoding="utf-8")
        r = self.run_cli("finish", d.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("changed after approval", r.stdout)

    def test_conditional_ready_after_revise_is_still_revise(self):
        d = self.ready_plan()
        self.manual_critique(d, "VERDICT: REVISE\n1. [blocker] AC-1 untestable -> name the test\nVERDICT: READY once AC-1 is fixed\n")
        self.assertIn("verdict is REVISE", self.run_cli("approve", d.name).stderr)

    def test_revise_resets_criteria_to_pending(self):
        d = self.ready_plan()
        self.run_cli("approve", d.name, "--skip-critique", "t")
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.run_cli("revise", d.name)
        text = (d / "plan.md").read_text(encoding="utf-8")
        self.assertIn('"status": "pending"', text)
        self.assertNotIn('"status": "pass"', text)

    def test_marking_criteria_pass_does_not_count_as_a_plan_change(self):
        d = self.ready_plan()
        self.run_cli("approve", d.name, "--skip-critique", "t")
        self.run_cli("start", d.name)
        t = (d / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
        (d / "plan.md").write_text(t, encoding="utf-8")
        self.assertEqual(self.run_cli("finish", d.name, "--no-lessons", "t").returncode, 0)

    def test_bold_colon_objective_style_counts(self):
        (self.root / "GOALS.md").write_text("# Goals\n## Objectives\n- **O1:** Ship it.\n", encoding="utf-8")
        d = self.new_standard()
        (d / "plan.md").write_text(filled_plan(d.name), encoding="utf-8")
        self.assertEqual(self.run_cli("check", d.name).returncode, 0)

    def test_plan_edited_after_critique_needs_new_critique(self):
        d = self.ready_plan()
        self.manual_critique(d, "VERDICT: READY\nNot checked: nothing\n")
        text = (d / "plan.md").read_text(encoding="utf-8").replace("Double submit.", "Double submit. Also payments.")
        (d / "plan.md").write_text(text, encoding="utf-8")
        self.assertIn("plan changed after it was critiqued", self.run_cli("approve", d.name).stderr)
        self.manual_critique(d, "VERDICT: READY\n")
        self.assertEqual(self.run_cli("approve", d.name).returncode, 0)
        self.assertTrue((d / "critique.prev.md").exists())

    def test_criterion_without_id_fails_check(self):
        self.goals()
        d = self.new_standard()
        crit = [{"when": "x", "then": "y", "test": "t", "status": "pending"}]
        (d / "plan.md").write_text(filled_plan(d.name, criteria=crit), encoding="utf-8")
        self.assertIn("criterion #1 needs an id like AC-1", self.run_cli("check", d.name).stdout)

    def test_only_real_objectives_in_objectives_section_count(self):
        (self.root / "GOALS.md").write_text(
            "# Goals\n## Objectives\n- **O1**: todo later\n- **O2**: Ship invoices.\n- **O3**:\n"
            "## Non-goals\n- Do not chase **O4** style metrics.\n", encoding="utf-8")
        d = self.new_standard("Invoices", "--objective", "O2")
        for bad in ("O1", "O3", "O4"):
            (d / "plan.md").write_text(filled_plan(d.name, objective=bad), encoding="utf-8")
            self.assertIn("(have: O2)", self.run_cli("check", d.name).stdout, bad)

    def test_todo_word_in_prose_is_allowed(self):
        d = self.ready_plan()
        text = (d / "plan.md").read_text(encoding="utf-8").replace("Double submit.", "Remove old TODO comments.")
        (d / "plan.md").write_text(text, encoding="utf-8")
        self.assertEqual(self.run_cli("check", d.name).returncode, 0)

    def test_epic_children_respect_dependencies(self):
        self.goals()
        self.run_cli("new", "Billing", "--tier", "epic", "--objective", "O2")
        epic = sorted((self.root / "changes").glob("0*"))[-1]
        text = (epic / "epic.md").read_text(encoding="utf-8").replace("TODO: ", "")
        (epic / "epic.md").write_text(text, encoding="utf-8")
        r = self.run_cli("new", "Invoice model", "--tier", "standard", "--epic", "1", "--child", "a")
        self.assertIn("approve the epic before", r.stderr)
        self.run_cli("approve", epic.name, "--skip-critique", "t")
        self.assertIn("no child 'z'", self.run_cli("new", "X", "--tier", "standard", "--epic", "1", "--child", "z").stderr)

        kids = {}
        for key in ("a", "b"):
            r = self.run_cli("new", "Child %s" % key, "--tier", "standard", "--epic", "1", "--child", key)
            self.assertEqual(r.returncode, 0, r.stderr)
            kd = sorted((self.root / "changes").glob("0*"))[-1]
            plan = filled_plan(kd.name, objective="O2", title="Child %s" % key)
            plan = plan.replace('"timebox": "1 day"', '"timebox": "1 day", "epic": "%s", "child": "%s"' % (epic.name, key))
            (kd / "plan.md").write_text(plan, encoding="utf-8")
            self.assertEqual(self.run_cli("approve", kd.name, "--skip-critique", "t").returncode, 0)
            kids[key] = kd
        self.assertIn("depends on unfinished child(ren): a", self.run_cli("start", kids["b"].name).stderr)
        self.run_cli("start", epic.name)
        self.assertIn("epic children not done yet: a, b", self.run_cli("finish", epic.name).stderr)
        for key in ("a", "b"):
            kd = kids[key]
            self.assertEqual(self.run_cli("start", kd.name).returncode, 0)
            t = (kd / "plan.md").read_text(encoding="utf-8").replace('"status": "pending"', '"status": "pass"')
            (kd / "plan.md").write_text(t, encoding="utf-8")
            self.assertEqual(self.run_cli("finish", kd.name, "--no-lessons", "t").returncode, 0)
        self.assertEqual(self.run_cli("finish", epic.name).returncode, 0)

    def test_park_from_short_id_and_missing_files_fail_cleanly(self):
        d = self.ready_plan()
        self.run_cli("park", "Coupons", "--from", "1")
        self.assertIn("Coupons (from %s)" % d.name, (self.root / "ROADMAP.md").read_text(encoding="utf-8"))
        (self.root / "LESSONS.md").unlink()
        r = self.run_cli("learn", "x", "--area", "a", "--body", "b")
        self.assertIn("LESSONS.md is missing", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_park_goes_to_parking_lot(self):
        r = self.run_cli("park", "Add coupon codes", "--from", "001-order-checkout")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.root / "ROADMAP.md").read_text(encoding="utf-8")
        lot = text.split("<!-- capitan:parking:start -->")[1].split("<!-- capitan:parking:end -->")[0]
        self.assertIn("Add coupon codes (from 001-order-checkout)", lot)


if __name__ == "__main__":
    unittest.main()
