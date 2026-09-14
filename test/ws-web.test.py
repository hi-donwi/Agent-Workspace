import json
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".agents/bin"))

from ws_web import Unauthorized, WebError, build_state, load_projects, project_context, route  # noqa: E402


TASK_READY = """---
schema_version: 1
id: task_board_ready
project: workspace
title: Render board
status: ready
priority: high
owner: unassigned
labels:
  - web
acceptance_criteria:
  - Board returns ready task
related_plans:
related_runs:
git_links:
blocked: false
blocked_reason: ""
created_at: 2026-09-14T00:00:00Z
updated_at: 2026-09-14T00:00:00Z
---

Board task body.
"""


TASK_REVIEW = TASK_READY.replace("task_board_ready", "task_board_review").replace("Render board", "Review board").replace("status: ready", "status: review")


class WebControlReadFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-web-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.context = self.root / "context"
        (self.context / "memory/projects/workspace").mkdir(parents=True)
        (self.context / "runs/workspace/demo").mkdir(parents=True)
        (self.root / "workspace.conf").write_text("context_dir = context\n")
        (self.context / "registry.tsv").write_text(
            "key\tclient\tgroup\tfolder\tremote\tcontext_scope\tsecurity_profile\tdescription\n"
            "workspace\tdonwi\t-\tprojects/donwi/public/Agent-Workspace\tgit@example.invalid:workspace.git\tclient\t-\tFramework repo\n"
        )
        (self.context / "memory/projects/workspace/project.md").write_text("# Workspace\n")
        (self.context / "memory/projects/workspace/active.md").write_text("Active workspace state\n")
        (self.context / "memory/projects/workspace/decisions.md").write_text("Decisions\n")
        (self.context / "runs/workspace/demo/handoff.md").write_text("Continue here\n")
        (self.context / "tasks/workspace").mkdir(parents=True)
        (self.context / "tasks/workspace/ready.md").write_text(TASK_READY)
        (self.context / "tasks/workspace/review.md").write_text(TASK_REVIEW)
        (self.context / "tasks/workspace/legacy.md").write_text("- [ ] Adopt old checklist\n")
        self.state = build_state(self.root, token="test-token")

    def test_loads_project_summaries(self):
        projects = load_projects(self.state)

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].key, "workspace")
        self.assertEqual(projects[0].client, "donwi")
        self.assertEqual(projects[0].description, "Framework repo")

    def test_api_requires_bearer_token(self):
        with self.assertRaises(Unauthorized):
            route(self.state, "GET", "/api/projects", {})

        status, content_type, body = route(self.state, "GET", "/api/projects", {"authorization": "Bearer test-token"})

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["projects"][0]["key"], "workspace")

    def test_project_context_returns_context_files_and_handoff(self):
        payload = project_context(self.state, "workspace")

        paths = {item["path"] for item in payload["files"]}
        self.assertIn("context/memory/projects/workspace/project.md", paths)
        self.assertIn("context/memory/projects/workspace/active.md", paths)
        self.assertIn("context/runs/workspace/demo/handoff.md", paths)

    def test_project_board_groups_same_task_records_by_status(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/board",
            {"authorization": "Bearer test-token"},
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["source"]["id"], "context")
        self.assertEqual(payload["columns"]["ready"][0]["id"], "task_board_ready")
        self.assertEqual(payload["columns"]["ready"][0]["source"], "context")
        self.assertEqual(payload["columns"]["review"][0]["id"], "task_board_review")
        self.assertEqual(payload["columns"]["backlog"], [])
        self.assertEqual(payload["legacy_candidates"][0]["title"], "Adopt old checklist")

    def test_rejects_unknown_or_bad_project(self):
        with self.assertRaisesRegex(WebError, "project not found"):
            project_context(self.state, "missing")
        with self.assertRaisesRegex(WebError, "project not found"):
            project_context(self.state, "../workspace")

    def test_index_is_public_but_api_is_not(self):
        status, content_type, body = route(self.state, "GET", "/", {})

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn(b"Agent Workspace Control", body)

    def test_rejects_symlinked_context_files(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "active.md").write_text("leak")
        target = self.context / "memory/projects/workspace/active.md"
        target.unlink()
        target.symlink_to(outside / "active.md")

        with self.assertRaisesRegex(WebError, "symlinks"):
            project_context(self.state, "workspace")


if __name__ == "__main__":
    unittest.main()
