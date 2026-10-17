import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".agents/bin"))

from ws_pm import active_alerts, client_dossier, compute_alerts, digest, interactions, log_interaction, snooze, thresholds, today  # noqa: E402

NOW = datetime.fromisoformat("2026-10-17T10:00:00+07:00")


def task_doc(task_id, scope, title, status="backlog", updated="2026-10-17T09:00:00+07:00", extra=""):
    project, client = ("", scope[1:]) if scope.startswith("@") else (scope, "")
    client_line = f"client: {client}\n" if client else ""
    return (
        "---\nschema_version: 2\n"
        f"id: {task_id}\nproject: {project or chr(34) * 2}\ntitle: {title}\nstatus: {status}\npriority: normal\nowner: dw\n"
        "labels:\nacceptance_criteria:\nrelated_plans:\nrelated_runs:\ngit_links:\n"
        'blocked: false\nblocked_reason: ""\n'
        f"{client_line}{extra}created_at: 2026-10-01T09:00:00+07:00\nupdated_at: {updated}\n---\n"
    )


class Alerts(unittest.TestCase):
    """Alerts are computed from the records each time (ADR-0024); only snoozes are stored."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-pm-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = self.root / "context"
        (self.context / "tasks").mkdir(parents=True)
        (self.context / "registry.tsv").write_text("key\tclient\tgroup\tfolder\napi\tacme\t-\tp/api\nweb\tbeta\t-\tp/web\n")

    def task(self, task_id, scope, title, **kwargs):
        folder = self.context / ("clients/" + scope[1:] + "/tasks" if scope.startswith("@") else "tasks/" + scope)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{task_id}.md").write_text(task_doc(task_id, scope, title, **kwargs))

    def kinds(self, alerts):
        return sorted((a.kind, a.ref) for a in alerts)

    def test_dates_and_reminders(self):
        self.task("task_late", "api", "Late", extra="due: 2026-10-15\n")
        self.task("task_today", "web", "Today", extra="due: 2026-10-17\n")
        self.task("task_later", "web", "Later", extra="due: 2026-10-30\n")
        self.task("task_done_late", "api", "Done late", status="done", extra="due: 2026-10-01\n")
        self.task("task_call", "@acme", "Call", extra="kind: reminder\ndue: 2026-10-17\nremind_at: 2026-10-17T10:10+07:00\n")
        self.task("task_call_later", "@acme", "Call later", extra="kind: reminder\ndue: 2026-10-17\nremind_at: 2026-10-17T16:00+07:00\n")
        alerts = compute_alerts(self.context, self.root, NOW)
        # A reminder raises one alert, at its time (15 minutes ahead by default), not a due alert.
        self.assertEqual(self.kinds(alerts), [("due_today", "task_today"), ("overdue", "task_late"), ("reminder", "task_call")])
        late = next(a for a in alerts if a.kind == "overdue")
        self.assertEqual((late.severity, late.scope, late.client, late.id), ("warn", "api", "acme", "overdue:api:task_late"))
        self.assertIn("2 days", late.detail)

    def test_blocked_stale_and_waiting_review_use_the_thresholds(self):
        blocked = 'blocked: true\nblocked_reason: "waits on DB access"\n'
        self.task("task_blocked", "api", "Blocked", updated="2026-10-14T09:00:00+07:00")
        path = self.context / "tasks/api/task_blocked.md"
        path.write_text(path.read_text().replace('blocked: false\nblocked_reason: ""\n', blocked))
        self.task("task_stale", "api", "Stale", status="in_progress", updated="2026-10-10T09:00:00+07:00")
        self.task("task_fresh", "api", "Fresh", status="in_progress", updated="2026-10-16T09:00:00+07:00")
        self.task("task_review", "web", "Review", status="review", updated="2026-10-14T09:00:00+07:00")
        self.assertEqual(self.kinds(compute_alerts(self.context, self.root, NOW)),
                         [("blocked", "task_blocked"), ("review", "task_review"), ("stale", "task_stale")])
        (self.context / "pm.json").write_text(json.dumps({"schema_version": 1, "stale_days": 10, "review_days": 5, "blocked_days": 5}))
        self.assertEqual(thresholds(self.context)["stale_days"], 10)
        self.assertEqual(compute_alerts(self.context, self.root, NOW), [])

    def test_pending_approvals_and_agents_that_raised_a_hand(self):
        approvals = self.root / ".local/agent/approvals/api"
        approvals.mkdir(parents=True)
        events = [
            {"type": "requested", "id": "a1", "project": "api", "action": "run_command", "requestedAt": "2026-10-17T02:50:00Z", "expiresAt": "2026-10-17T03:05:00Z"},
            {"type": "requested", "id": "a2", "project": "api", "action": "write_file", "requestedAt": "2026-10-17T02:00:00Z", "expiresAt": "2026-10-17T02:15:00Z"},
            {"type": "requested", "id": "a3", "project": "api", "action": "edit_file", "requestedAt": "2026-10-17T02:55:00Z", "expiresAt": "2026-10-17T03:10:00Z"},
            {"type": "approved", "id": "a3", "project": "api", "decidedAt": "2026-10-17T02:56:00Z"},
        ]
        (approvals / "2026-10.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        activity = self.root / ".local/agent/activity"
        activity.mkdir(parents=True)
        def record(name, state, at):
            (activity / f"{name}.json").write_text(json.dumps({"version": 1, "session": name, "project": "web", "tool": "claude", "state": state, "detail": "permission for Bash", "at": at}))
        record("s-waiting", "waiting", "2026-10-17T02:58:00Z")
        record("s-old", "waiting", "2026-10-16T20:00:00Z")
        record("s-idle", "idle", "2026-10-17T02:59:00Z")
        alerts = compute_alerts(self.context, self.root, NOW)
        self.assertEqual(self.kinds(alerts), [("agent", "s-waiting"), ("approval", "a1")])
        approval = next(a for a in alerts if a.kind == "approval")
        self.assertEqual((approval.severity, approval.title, approval.client), ("attn", "Approve run_command", "acme"))

    def test_scope_and_client_filters(self):
        self.task("task_a", "api", "A", extra="due: 2026-10-15\n")
        self.task("task_b", "web", "B", extra="due: 2026-10-15\n")
        self.task("task_c", "@acme", "C", extra="due: 2026-10-15\n")
        self.assertEqual([a.ref for a in compute_alerts(self.context, self.root, NOW, scope="api")], ["task_a"])
        self.assertEqual(sorted(a.ref for a in compute_alerts(self.context, self.root, NOW, client="acme")), ["task_a", "task_c"])

    def test_a_snooze_hides_an_alert_until_its_time(self):
        self.task("task_late", "api", "Late", extra="due: 2026-10-15\n")
        snooze(self.root, "overdue:api:task_late", datetime.fromisoformat("2026-10-17T12:00:00+07:00"), NOW)
        self.assertEqual(active_alerts(self.context, self.root, NOW), [])
        self.assertEqual(len(active_alerts(self.context, self.root, datetime.fromisoformat("2026-10-17T12:30:00+07:00"))), 1)
        stored = json.loads((self.root / ".local/pm/snoozes.json").read_text())
        self.assertIn("overdue:api:task_late", stored)

    def test_today_puts_people_waiting_first_then_dates_and_lists_work_in_hand(self):
        self.task("task_late", "api", "Late", extra="due: 2026-10-15\n")
        self.task("task_today", "web", "Today", extra="due: 2026-10-17\n")
        self.task("task_doing", "web", "Doing", status="in_progress", extra="assignee: agent:claude\n")
        approvals = self.root / ".local/agent/approvals/api"
        approvals.mkdir(parents=True)
        (approvals / "2026-10.jsonl").write_text(json.dumps({"type": "requested", "id": "a1", "project": "api", "action": "run_command",
                                                             "requestedAt": "2026-10-17T02:50:00Z", "expiresAt": "2026-10-17T03:05:00Z"}) + "\n")
        day = today(self.context, self.root, NOW)
        self.assertEqual(day["date"], "2026-10-17")
        self.assertEqual(day["signals"]["overdue"], 1)
        self.assertEqual(day["signals"]["due_today"], 1)
        self.assertEqual(day["signals"]["waiting"], 1)
        self.assertEqual([item["kind"] for item in day["items"]], ["approval", "overdue", "due_today"])
        self.assertEqual([t["id"] for t in day["in_progress"]], ["task_doing"])

    def test_the_cli_prints_json_for_the_desk_and_agents(self):
        self.task("task_late", "api", "Late", extra="due: 2026-10-15\n")
        script = str(SOURCE / ".agents/bin/ws_pm.py")
        for command in ("alerts", "today"):
            result = subprocess.run([sys.executable, script, command, str(self.context), str(self.root), "--json", "--now", NOW.isoformat()],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("overdue:api:task_late", result.stdout, command)



class ClientDossier(unittest.TestCase):
    """What may be read about a client, and what never leaves the desk (ADR-0024)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-pm-client-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = self.root / "context"
        acme = self.context / "clients" / "acme"
        (acme / "tasks").mkdir(parents=True)
        (self.context / "tasks" / "api").mkdir(parents=True)
        (self.context / "registry.tsv").write_text("key\tclient\tgroup\tfolder\napi\tacme\t-\tp/api\nweb\tbeta\t-\tp/web\n")
        (acme / "client.md").write_text("# acme — client\n\n- **Full name:** Acme Logistics\n- **Engaged since:** 2025-03-01\n\n"
                                        "## What they are\n\nA logistics firm.\n\n## Working agreement\n\nReports on Friday.\n")
        (acme / "contacts.md").write_text("RESTRICTED_CONTACT_CANARY +62 812 0000 0000\n")
        (acme / "commercial.md").write_text("RESTRICTED_RATE_CANARY 100 per hour\n")
        (self.context / "tasks/api/task_late.md").write_text(task_doc("task_late", "api", "Late", extra="due: 2026-10-15\n"))
        (acme / "tasks/task_report.md").write_text(task_doc("task_report", "@acme", "Send the report", extra="due: 2026-10-20\n"))

    def test_the_dossier_carries_profile_work_and_interactions_but_never_restricted_records(self):
        log_interaction(self.context, "acme", "Call: agreed phase 2 scope", actor="dw-cli")
        dossier = client_dossier(self.context, self.root, "acme", NOW)
        self.assertEqual(dossier["profile"]["fields"]["Full name"], "Acme Logistics")
        self.assertEqual(dossier["profile"]["working_agreement"], "Reports on Friday.")
        self.assertEqual(dossier["projects"], [{"key": "api", "open": 1, "overdue": 1}])
        self.assertEqual([t["id"] for t in dossier["tasks"]], ["task_report"])
        self.assertEqual((dossier["open"], dossier["overdue"]), (2, 1))
        self.assertEqual(dossier["interactions"][0]["text"], "Call: agreed phase 2 scope")
        self.assertEqual(dossier["restricted"], {"contacts": True, "commercial": True})
        dumped = json.dumps(dossier)
        self.assertNotIn("RESTRICTED_CONTACT_CANARY", dumped)
        self.assertNotIn("RESTRICTED_RATE_CANARY", dumped)
        script = str(SOURCE / ".agents/bin/ws_pm.py")
        for extra in ([], ["--json"]):
            out = subprocess.run([sys.executable, script, "client", str(self.context), str(self.root), "acme", *extra, "--now", NOW.isoformat()],
                                 text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertNotIn("CANARY", out.stdout)

    def test_the_interaction_log_is_append_only_and_newest_first(self):
        log_interaction(self.context, "acme", "First", actor="dw")
        log_interaction(self.context, "acme", "Second", actor="dw")
        self.assertEqual([e["text"] for e in interactions(self.context, "acme")], ["Second", "First"])
        with self.assertRaisesRegex(Exception, "no client"):
            log_interaction(self.context, "nosuch", "x", actor="dw")


class Digest(unittest.TestCase):
    """The work digest an agent finds in CONTEXT.md at bind (ADR-0024)."""

    def test_the_bound_project_and_its_client_only(self):
        temp = tempfile.TemporaryDirectory(prefix="ws-pm-digest-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        context = root / "context"
        for folder in ("tasks/api", "tasks/web", "clients/acme/tasks"):
            (context / folder).mkdir(parents=True)
        (context / "registry.tsv").write_text("key\tclient\tgroup\tfolder\napi\tacme\t-\tp/api\nweb\tbeta\t-\tp/web\n")
        (context / "tasks/api/task_doing.md").write_text(task_doc("task_doing", "api", "Fix login", status="in_progress", extra="assignee: agent:claude\ndue: 2026-10-18\n"))
        (context / "tasks/api/task_next.md").write_text(task_doc("task_next", "api", "Push notifications", status="ready"))
        (context / "tasks/api/task_idea.md").write_text(task_doc("task_idea", "api", "Someday idea"))
        (context / "tasks/web/task_other.md").write_text(task_doc("task_other", "web", "OTHER_CLIENT_CANARY", status="in_progress"))
        (context / "clients/acme/tasks/task_report.md").write_text(task_doc("task_report", "@acme", "Send the report", extra="due: 2026-10-20\n"))
        text = digest(context, root, "api", NOW)
        self.assertIn("## Work for api", text)
        self.assertIn("`task_doing` Fix login (agent:claude, due 2026-10-18)", text)
        self.assertIn("Ready:\n- `task_next` Push notifications", text)
        self.assertIn("Client `acme`'s own open work:\n- `task_report` Send the report (due 2026-10-20)", text)
        self.assertIn("Open in api: 3 (1 in backlog).", text)
        self.assertNotIn("OTHER_CLIENT_CANARY", text)

if __name__ == "__main__":
    unittest.main()
