import tempfile
from pathlib import Path
import sys
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".agents/bin"))

from ws_tasks import (  # noqa: E402
    TaskConflict,
    TaskError,
    check_item,
    comment_task,
    create_reminder,
    create_task,
    edit_task,
    list_tasks,
    load_source,
    load_tasks,
    parse_task_document,
    serialize_task_document,
    set_status,
    task_json,
    write_task_document,
)


VALID_TASK = """---
schema_version: 1
id: task_demo_1
project: workspace
title: Build local board reader
status: ready
priority: high
owner: unassigned
labels:
  - web
  - context
acceptance_criteria:
  - Backlog and Kanban read the same task record
related_plans:
  - runs/workspace/demo/plan.md
related_runs:
  - runs/workspace/demo
git_links:
  - workspace@abcdef1
blocked: false
blocked_reason: ""
created_at: 2026-09-14T00:00:00Z
updated_at: 2026-09-14T00:00:00Z
---

Human-readable task body.
"""


class TaskSourceParsing(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-tasks-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "source"
        self.root.mkdir()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_loads_valid_tasks_with_source_identity(self):
        self.write("tasks/workspace/task_demo_1.md", VALID_TASK)

        tasks, legacy = load_tasks(load_source("shared", self.root))

        self.assertEqual(len(tasks), 1)
        self.assertEqual(legacy, [])
        task = tasks[0]
        self.assertEqual(task.source, "shared")
        self.assertEqual(task.path, "tasks/workspace/task_demo_1.md")
        self.assertEqual(task.id, "task_demo_1")
        self.assertEqual(task.status, "ready")
        self.assertEqual(task.labels, ("web", "context"))
        self.assertEqual(task.git_links[0].repository, "workspace")
        self.assertEqual(task.git_links[0].sha, "abcdef1")
        self.assertIn("Human-readable", task.body)

    def test_detects_legacy_checklist_candidates_without_converting(self):
        self.write("tasks/workspace/notes.md", "# Notes\n\n- [ ] Extract parser\n- [x] Review security\n")

        tasks, legacy = load_tasks(load_source("personal", self.root))

        self.assertEqual(tasks, [])
        self.assertEqual([item.title for item in legacy], ["Extract parser", "Review security"])
        self.assertEqual({item.project for item in legacy}, {"workspace"})
        self.assertEqual({item.source for item in legacy}, {"personal"})

    def test_rejects_invalid_status_and_blocker_rules(self):
        invalid_status = VALID_TASK.replace("status: ready", "status: shipped")
        with self.assertRaisesRegex(TaskError, "invalid task status"):
            parse_task_document("shared", "tasks/workspace/bad.md", "rev", invalid_status)

        missing_reason = VALID_TASK.replace("blocked: false", "blocked: true")
        with self.assertRaisesRegex(TaskError, "blocked tasks require"):
            parse_task_document("shared", "tasks/workspace/bad.md", "rev", missing_reason)

    def test_rejects_unsafe_references(self):
        unsafe = VALID_TASK.replace("runs/workspace/demo/plan.md", "../private.md")
        with self.assertRaisesRegex(TaskError, "unsafe reference"):
            parse_task_document("shared", "tasks/workspace/bad.md", "rev", unsafe)

    def test_rejects_duplicate_ids_within_one_source(self):
        self.write("tasks/workspace/one.md", VALID_TASK)
        self.write("tasks/workspace/two.md", VALID_TASK.replace("Build local board reader", "Duplicate"))

        with self.assertRaisesRegex(TaskError, "duplicate task id"):
            load_tasks(load_source("shared", self.root))

    def test_rejects_symlinked_task_source_paths(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "task.md").write_text(VALID_TASK)
        tasks = self.root / "tasks"
        tasks.mkdir()
        (tasks / "workspace").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(TaskError, "symlinks"):
            load_tasks(load_source("shared", self.root))

    def test_rejects_missing_or_invalid_source_root(self):
        with self.assertRaisesRegex(TaskError, "invalid source id"):
            load_source("Bad Source", self.root)
        with self.assertRaisesRegex(TaskError, "does not exist"):
            load_source("shared", self.root / "missing")

    def test_scan_cli_outputs_tasks_and_legacy_candidates(self):
        self.write("tasks/workspace/task_demo_1.md", VALID_TASK)
        self.write("tasks/workspace/notes.md", "- [ ] Adopt legacy item\n")

        result = subprocess.run(
            [sys.executable, str(SOURCE / ".agents/bin/ws_tasks.py"), "scan", "shared", str(self.root)],
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"id": "task_demo_1"', result.stdout)
        self.assertIn('"title": "Adopt legacy item"', result.stdout)

    def test_serialize_task_document_roundtrip(self):
        original = parse_task_document("shared", "tasks/workspace/task_demo_1.md", "rev1", VALID_TASK)
        serialized = serialize_task_document(original)
        parsed = parse_task_document("shared", "tasks/workspace/task_demo_1.md", "rev2", serialized)

        self.assertEqual(parsed.id, original.id)
        self.assertEqual(parsed.project, original.project)
        self.assertEqual(parsed.title, original.title)
        self.assertEqual(parsed.status, original.status)
        self.assertEqual(parsed.priority, original.priority)
        self.assertEqual(parsed.owner, original.owner)
        self.assertEqual(parsed.labels, original.labels)
        self.assertEqual(parsed.acceptance_criteria, original.acceptance_criteria)
        self.assertEqual(parsed.related_plans, original.related_plans)
        self.assertEqual(parsed.related_runs, original.related_runs)
        self.assertEqual(parsed.git_links, original.git_links)
        self.assertEqual(parsed.blocked, original.blocked)
        self.assertEqual(parsed.blocked_reason, original.blocked_reason)
        self.assertEqual(parsed.body, original.body)

    def test_write_task_document_creates_file_atomically(self):
        source = load_source("shared", self.root, writable=True)
        task = parse_task_document("shared", "tasks/workspace/task_demo_1.md", "init", VALID_TASK)

        saved = write_task_document(source, "workspace", task)

        target = self.root / "tasks/workspace/task_demo_1.md"
        self.assertTrue(target.exists())
        self.assertEqual(saved.path, "tasks/workspace/task_demo_1.md")
        self.assertTrue(saved.revision.startswith("mtime:"))

        tasks, _ = load_tasks(source)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, "task_demo_1")

    def test_write_task_document_detects_revision_conflict(self):
        source = load_source("shared", self.root, writable=True)
        task = parse_task_document("shared", "tasks/workspace/task_demo_1.md", "init", VALID_TASK)
        saved = write_task_document(source, "workspace", task)

        # Mismatched expected revision fails
        with self.assertRaisesRegex(TaskConflict, "revision mismatch"):
            write_task_document(source, "workspace", task, expected_revision="stale_revision")

        # Correct expected revision succeeds
        updated_task = parse_task_document(
            "shared",
            "tasks/workspace/task_demo_1.md",
            saved.revision,
            serialize_task_document(saved).replace("Build local board reader", "Updated Title"),
        )
        saved_again = write_task_document(source, "workspace", updated_task, expected_revision=saved.revision)
        self.assertEqual(saved_again.title, "Updated Title")

    def test_write_task_document_rejects_duplicate_on_create(self):
        source = load_source("shared", self.root, writable=True)
        task = parse_task_document("shared", "tasks/workspace/task_demo_1.md", "init", VALID_TASK)
        write_task_document(source, "workspace", task)

        with self.assertRaisesRegex(TaskConflict, "already exists"):
            write_task_document(source, "workspace", task)

    def test_write_task_document_rejects_non_writable_source(self):
        source = load_source("readonly", self.root, writable=False)
        task = parse_task_document("readonly", "tasks/workspace/task_demo_1.md", "init", VALID_TASK)

        with self.assertRaisesRegex(TaskError, "not writable"):
            write_task_document(source, "workspace", task)



V2_FIELDS = """kind: milestone
due: 2026-10-31
remind_at: 2026-10-30T09:00+07:00
recur: weekly
assignee: agent:claude-code
rank: 3
parent: task_parent
depends_on:
  - task_other
"""


class TaskSchemaVersion2(unittest.TestCase):
    """Project management fields (ADR-0024): dates, reminders, ownership, order, structure."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-tasks-v2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "context"
        (self.root / "tasks" / "api").mkdir(parents=True)
        self.source = load_source("context", self.root)

    def v2(self, extra=V2_FIELDS):
        return VALID_TASK.replace("schema_version: 1", "schema_version: 2").replace("blocked: false", extra + "blocked: false")

    def test_parses_the_new_fields_and_keeps_them_through_a_round_trip(self):
        task = parse_task_document("context", "tasks/workspace/task_demo_1.md", "r", self.v2())
        self.assertEqual((task.kind, task.due, task.recur, task.assignee, task.rank, task.parent),
                         ("milestone", "2026-10-31", "weekly", "agent:claude-code", 3, "task_parent"))
        self.assertEqual(task.remind_at, "2026-10-30T09:00+07:00")
        self.assertEqual(task.depends_on, ("task_other",))
        again = parse_task_document("context", task.path, "r2", serialize_task_document(task))
        for field in ("kind", "due", "remind_at", "recur", "assignee", "rank", "parent", "depends_on"):
            self.assertEqual(getattr(again, field), getattr(task, field), field)

    def test_a_version_1_task_is_read_and_written_back_as_version_2(self):
        task = parse_task_document("context", "tasks/workspace/task_demo_1.md", "r", VALID_TASK)
        self.assertEqual((task.kind, task.due, task.rank, task.depends_on), ("task", "", 0, ()))
        self.assertIn("schema_version: 2", serialize_task_document(task))

    def test_rejects_bad_values_for_the_new_fields(self):
        cases = {
            "due: 2026-02-30\n": "invalid due",
            "kind: epic\n": "invalid kind",
            "recur: hourly\n": "invalid recur",
            "assignee: Some One\n": "invalid assignee",
            "remind_at: 2026-10-30T09:00\n": "remind_at needs a time zone offset",
            "parent: not-a-task\n": "invalid parent",
        }
        for extra, message in cases.items():
            with self.assertRaisesRegex(TaskError, message, msg=extra):
                parse_task_document("context", "tasks/workspace/x.md", "r", self.v2(extra))

    def test_creates_a_task_with_fields_and_an_activity_line(self):
        parent = create_task(self.source, "api", "Release 1", "normal", "dw-cli", kind="milestone", due="2026-11-01", actor="dw-cli")
        task = create_task(self.source, "api", "Export CSV", "high", "dw-cli", due="2026-10-20",
                           assignee="agent:claude-code", labels=("export",), parent=parent.id, actor="dw-cli")
        self.assertEqual((task.due, task.assignee, task.labels, task.parent, task.schema_version),
                         ("2026-10-20", "agent:claude-code", ("export",), parent.id, 2))
        activity = task_json(task)["activity"]
        self.assertEqual([(a["actor"], a["text"]) for a in activity], [("dw-cli", "created")])
        with self.assertRaisesRegex(TaskError, "no task 'task_missing'"):
            create_task(self.source, "api", "Orphan", "normal", "dw-cli", parent="task_missing", actor="dw-cli")

    def test_edits_fields_with_the_revision_it_read_and_records_what_changed(self):
        task = create_task(self.source, "api", "Export CSV", "normal", "dw-cli", actor="dw-cli")
        edited = edit_task(self.source, "api", task.id, {"due": "2026-10-21", "priority": "urgent", "labels_add": ["export"],
                                                          "check_add": ["Write the parser", "Stream rows"]},
                           expected_revision=task.revision, actor="agent-claude")
        self.assertEqual((edited.due, edited.priority, edited.labels), ("2026-10-21", "urgent", ("export",)))
        data = task_json(edited)
        self.assertEqual([c["text"] for c in data["checklist"]], ["Write the parser", "Stream rows"])
        self.assertEqual(data["activity"][-1]["actor"], "agent-claude")
        self.assertIn("due 2026-10-21", data["activity"][-1]["text"])
        with self.assertRaisesRegex(TaskConflict, "revision mismatch"):
            edit_task(self.source, "api", task.id, {"due": "none"}, expected_revision=task.revision, actor="x")
        cleared = edit_task(self.source, "api", task.id, {"due": "none"}, actor="x")
        self.assertEqual(cleared.due, "")

    def test_comments_and_checklist_items_go_through_the_activity(self):
        task = create_task(self.source, "api", "Export CSV", "normal", "dw-cli", actor="dw-cli")
        task = edit_task(self.source, "api", task.id, {"check_add": ["Parser", "Rows"]}, actor="dw-cli")
        task = check_item(self.source, "api", task.id, 2, actor="agent-claude")
        task = comment_task(self.source, "api", task.id, "Rows stream in batches of 500.", actor="agent-claude")
        data = task_json(task)
        self.assertEqual([c["done"] for c in data["checklist"]], [False, True])
        self.assertEqual([a["text"] for a in data["activity"]][-2:], ["checked: Rows", "Rows stream in batches of 500."])
        with self.assertRaisesRegex(TaskError, "no checklist item 3"):
            check_item(self.source, "api", task.id, 3, actor="x")

    def test_a_status_change_is_recorded_in_the_activity(self):
        task = create_task(self.source, "api", "Export CSV", "normal", "dw-cli", actor="dw-cli")
        moved = set_status(self.source, "api", task.id, "in_progress", actor="agent-claude")
        self.assertEqual(task_json(moved)["activity"][-1]["text"], "status backlog -> in_progress")

    def test_lists_across_projects_with_filters(self):
        (self.root / "tasks" / "web").mkdir()
        create_task(self.source, "api", "Export CSV", "high", "dw-cli", due="2026-10-20", assignee="dw", actor="x")
        create_task(self.source, "web", "Landing copy", "normal", "dw-cli", labels=("copy",), actor="x")
        self.assertEqual([t.title for t in list_tasks(self.source)], ["Export CSV", "Landing copy"])
        self.assertEqual([t.title for t in list_tasks(self.source, project="web")], ["Landing copy"])
        self.assertEqual([t.title for t in list_tasks(self.source, assignee="dw")], ["Export CSV"])
        self.assertEqual([t.title for t in list_tasks(self.source, label="copy")], ["Landing copy"])
        self.assertEqual([t.title for t in list_tasks(self.source, due_before="2026-10-25")], ["Export CSV"])

    def test_show_and_list_print_json_for_agents(self):
        task = create_task(self.source, "api", "Export CSV", "high", "dw-cli", due="2026-10-20", actor="x")
        script = str(SOURCE / ".agents/bin/ws_tasks.py")
        shown = subprocess.run([sys.executable, script, "show", str(self.root), "api", task.id, "--json"], text=True, capture_output=True)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn('"due": "2026-10-20"', shown.stdout)
        listed = subprocess.run([sys.executable, script, "list", str(self.root), "--all", "--json"], text=True, capture_output=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn(f'"id": "{task.id}"', listed.stdout)


class ClientTasksAndReminders(unittest.TestCase):
    """Work that belongs to a client, reminders, and recurring work (ADR-0024)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-tasks-client-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "context"
        for path in ("tasks/api", "tasks/web", "clients/acme", "clients/beta"):
            (self.root / path).mkdir(parents=True)
        (self.root / "registry.tsv").write_text("key\tclient\tgroup\tfolder\napi\tacme\t-\tprojects/acme/api\nweb\tbeta\t-\tprojects/beta/web\n")
        self.source = load_source("context", self.root)

    def test_a_client_task_lives_with_the_client_and_moves_like_any_task(self):
        task = create_task(self.source, "@acme", "Send the monthly report", "normal", "dw-cli", due="2026-10-31", actor="x")
        self.assertEqual((task.project, task.client), ("", "acme"))
        self.assertEqual(task.path, f"clients/acme/tasks/{task.id}.md")
        moved = set_status(self.source, "@acme", task.id, "in_progress", actor="x")
        self.assertEqual(moved.status, "in_progress")
        self.assertEqual([t.id for t in list_tasks(self.source, "@acme")], [task.id])
        self.assertIn(task.id, [t.id for t in list_tasks(self.source)])
        with self.assertRaisesRegex(TaskError, "no task"):
            set_status(self.source, "@beta", task.id, "done", actor="x")

    def test_a_task_belongs_to_a_project_or_a_client(self):
        neither = VALID_TASK.replace("project: workspace", 'project: ""').replace("schema_version: 1", "schema_version: 2")
        with self.assertRaisesRegex(TaskError, "a project or a client"):
            parse_task_document("context", "clients/acme/tasks/x.md", "r", neither)
        both = VALID_TASK.replace("blocked: false", "client: acme\nblocked: false").replace("schema_version: 1", "schema_version: 2")
        with self.assertRaisesRegex(TaskError, "a project or a client"):
            parse_task_document("context", "tasks/workspace/x.md", "r", both)

    def test_the_client_filter_includes_the_client_tasks_and_its_projects_tasks(self):
        create_task(self.source, "api", "Export CSV", "normal", "dw-cli", actor="x")
        create_task(self.source, "web", "Landing copy", "normal", "dw-cli", actor="x")
        create_task(self.source, "@acme", "Invoice pack", "normal", "dw-cli", actor="x")
        self.assertEqual(sorted(t.title for t in list_tasks(self.source, client="acme")), ["Export CSV", "Invoice pack"])
        script = str(SOURCE / ".agents/bin/ws_tasks.py")
        listed = subprocess.run([sys.executable, script, "list", str(self.root), "--all", "--json"], text=True, capture_output=True)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        import json as _json
        clients = {t["title"]: t["client"] for t in _json.loads(listed.stdout)["tasks"]}
        self.assertEqual(clients, {"Export CSV": "acme", "Landing copy": "beta", "Invoice pack": "acme"})

    def test_a_reminder_is_a_task_with_a_time(self):
        reminder = create_reminder(self.source, "@beta", "Call about phase 2", "2026-10-20 14:00", actor="x")
        self.assertEqual((reminder.kind, reminder.due), ("reminder", "2026-10-20"))
        self.assertTrue(reminder.remind_at.startswith("2026-10-20T14:00"))
        self.assertRegex(reminder.remind_at, r"[+-]\d{2}:\d{2}$")

    def test_finishing_recurring_work_creates_the_next_occurrence(self):
        weekly = create_reminder(self.source, "api", "Weekly report", "2026-10-20 09:00+07:00", recur="weekly", actor="x")
        set_status(self.source, "api", weekly.id, "done", actor="x")
        upcoming = [t for t in list_tasks(self.source, "api") if t.status == "backlog"]
        self.assertEqual(len(upcoming), 1)
        self.assertEqual((upcoming[0].due, upcoming[0].remind_at, upcoming[0].recur), ("2026-10-27", "2026-10-27T09:00+07:00", "weekly"))
        self.assertIn(f"repeats {weekly.id}", task_json(upcoming[0])["activity"][0]["text"])

        monthly = create_task(self.source, "@acme", "Invoice", "normal", "dw-cli", due="2026-01-31", recur="monthly", actor="x")
        set_status(self.source, "@acme", monthly.id, "done", actor="x")
        nxt = [t for t in list_tasks(self.source, "@acme") if t.status == "backlog"]
        self.assertEqual([t.due for t in nxt], ["2026-02-28"])

if __name__ == "__main__":
    unittest.main()
