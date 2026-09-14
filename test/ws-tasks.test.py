import tempfile
from pathlib import Path
import sys
import subprocess
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".agents/bin"))

from ws_tasks import TaskError, load_source, load_tasks, parse_task_document  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
