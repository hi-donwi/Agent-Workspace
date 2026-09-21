import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / ".agents/bin"))

from ws_web import (  # noqa: E402
    Conflict,
    NotFound,
    Unauthorized,
    WebError,
    build_state,
    load_projects,
    project_context,
    route,
)


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
            "workspace\texample\t-\tprojects/example/Agent-Workspace\tgit@example.invalid:workspace.git\tclient\t-\tFramework repo\n"
        )
        (self.context / "memory/projects/workspace/project.md").write_text("# Workspace\n")
        (self.context / "memory/projects/workspace/active.md").write_text("Active workspace state\n")
        (self.context / "memory/projects/workspace/decisions.md").write_text("Decisions\n")
        (self.context / "runs/workspace/demo/handoff.md").write_text("Continue here\n")
        (self.context / "runs/workspace/demo/plan.md").write_text("Plan details\n")
        (self.context / "tasks/workspace").mkdir(parents=True)
        (self.context / "tasks/workspace/ready.md").write_text(TASK_READY)
        (self.context / "tasks/workspace/review.md").write_text(TASK_REVIEW)
        (self.context / "tasks/workspace/legacy.md").write_text("- [ ] Adopt old checklist\n")
        self.repo_dir = self.root / "projects/example/Agent-Workspace"
        self.repo_dir.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo_dir)], check=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "config", "user.name", "Test Agent"], check=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "config", "user.email", "test@example.invalid"], check=True)
        (self.repo_dir / "README.md").write_text("# Test Repo\n")
        subprocess.run(["git", "-C", str(self.repo_dir), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.repo_dir), "commit", "-qm", "feat: initial commit"], check=True)
        rev_output = subprocess.run(
            ["git", "-C", str(self.repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.sample_sha = rev_output.stdout.strip()
        self.state = build_state(self.root, token="test-token")

    def test_loads_project_summaries(self):
        projects = load_projects(self.state)

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].key, "workspace")
        self.assertEqual(projects[0].client, "example")
        self.assertEqual(projects[0].description, "Framework repo")

    def test_api_requires_bearer_token(self):
        with self.assertRaises(Unauthorized):
            route(self.state, "GET", "/api/projects", {})

        status, content_type, body = route(self.state, "GET", "/api/projects", {"authorization": "Bearer test-token"})

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["projects"][0]["key"], "workspace")

    def test_head_method_supported_on_root_and_api(self):
        # Root path supports HEAD without token
        status, content_type, body = route(self.state, "HEAD", "/", {})
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertTrue(len(body) > 0)

        # API requires bearer token on HEAD
        with self.assertRaises(Unauthorized):
            route(self.state, "HEAD", "/api/projects", {})

        status, content_type, body = route(
            self.state,
            "HEAD",
            "/api/projects",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")

    def test_options_preflight_supported_without_auth(self):
        status, _content_type, body = route(self.state, "OPTIONS", "/api/projects", {})
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")

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

    def test_task_detail_resolves_plan_run_and_git_links(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        task = payload["task"]
        self.assertEqual(task["id"], "task_board_ready")
        self.assertEqual(task["body"], "Board task body.")
        self.assertEqual(task["acceptance_criteria"], ["Board returns ready task"])
        self.assertTrue(task["related_plans"][0]["resolved"])
        self.assertEqual(task["related_plans"][0]["file"]["path"], "context/runs/workspace/demo/plan.md")
        self.assertTrue(task["related_runs"][0]["resolved"])
        self.assertEqual(task["related_runs"][0]["file"]["path"], "context/runs/workspace/demo/handoff.md")
        self.assertEqual(task["git_links"], [{"repository": "workspace", "sha": "abcdef1"}])

    def test_task_detail_rejects_cross_project_or_unknown_task(self):
        with self.assertRaisesRegex(WebError, "task not found"):
            route(
                self.state,
                "GET",
                "/api/projects/workspace/tasks/task_missing",
                {"authorization": "Bearer test-token"},
            )
        with self.assertRaisesRegex(WebError, "project not found"):
            route(
                self.state,
                "GET",
                "/api/projects/missing/tasks/task_board_ready",
                {"authorization": "Bearer test-token"},
            )

    def test_overview_groups_projects_and_counts_tasks(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/overview",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["counts"]["projects"], 1)
        self.assertEqual(payload["counts"]["clients"], 1)
        self.assertGreaterEqual(payload["counts"]["tasks"], 2)
        self.assertTrue(payload["context_local"])
        self.assertEqual(payload["clients"][0]["key"], "example")

    def test_health_reports_registry_and_local_context(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/health",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        ids = {item["id"]: item for item in payload["checks"]}
        self.assertTrue(ids["registry"]["ok"])
        self.assertIn("private-local", ids["context_remote"]["detail"])

    def test_project_runs_lists_handoff_snippet(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/runs",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["id"], "demo")
        self.assertIn("Continue here", payload["runs"][0]["handoff"])

    def test_clients_lists_registry_clients(self):
        (self.context / "clients/example").mkdir(parents=True)
        (self.context / "clients/example/client.md").write_text("# Example Org\nThey buy software.\n")
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/clients",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["clients"][0]["key"], "example")
        self.assertIn("Example Org", payload["clients"][0]["summary"])
        self.assertEqual(payload["clients"][0]["projects"][0]["key"], "workspace")

    def test_plans_lists_run_plan_markdown(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/plans?project=workspace",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["plans"]), 1)
        self.assertEqual(payload["plans"][0]["run"], "demo")
        self.assertIn("Plan details", payload["plans"][0]["body"])

    def test_settings_returns_allowlisted_identity_only(self):
        status, _content_type, body = route(
            self.state,
            "GET",
            "/api/settings",
            {"authorization": "Bearer test-token"},
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["identity"]["context_dir"], "context")
        self.assertTrue(payload["context_local"])
        self.assertTrue(payload["loopback"])
        self.assertNotIn("test-token", json.dumps(payload))

    def test_rejects_unknown_or_bad_project(self):
        with self.assertRaisesRegex(WebError, "project not found"):
            project_context(self.state, "missing")
        with self.assertRaisesRegex(WebError, "project not found"):
            project_context(self.state, "../workspace")

    def test_index_is_public_but_api_is_not(self):
        status, content_type, body = route(self.state, "GET", "/", {})

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn(b"Workspace", body)
        self.assertIn(b"Overview", body)
        self.assertIn(b"Board", body)
        self.assertIn(b"Backlog", body)
        self.assertIn(b"Search", body)
        self.assertIn(b"Context", body)
        self.assertIn(b"data-tab=\"health\"", body)
        self.assertIn(b"data-tab=\"clients\"", body)
        self.assertIn(b"data-tab=\"plans\"", body)
        self.assertIn(b"data-tab=\"settings\"", body)
        self.assertIn(b"renderMarkdown", body)
        self.assertIn(b"command-palette", body)
        self.assertIn(b"openPalette", body)
        self.assertIn(b"<table>", body)
        self.assertIn(b"modal-create", body)
        self.assertIn(b"modal-detail", body)

    def test_rejects_symlinked_context_files(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "active.md").write_text("leak")
        target = self.context / "memory/projects/workspace/active.md"
        target.unlink()
        target.symlink_to(outside / "active.md")

        with self.assertRaisesRegex(WebError, "symlinks"):
            project_context(self.state, "workspace")

    def test_create_task_saves_task_file_and_returns_201(self):
        payload = json.dumps(
            {
                "id": "task_custom_create",
                "title": "New created task",
                "body": "Detailed task description.",
                "status": "ready",
                "priority": "high",
                "owner": "testuser",
                "labels": ["web", "m5"],
                "acceptance_criteria": ["Criteria 1", "Criteria 2"],
                "related_plans": ["runs/workspace/demo/plan.md"],
                "git_links": [{"repository": "workspace", "sha": "abcdef1"}],
            }
        ).encode("utf-8")

        status, content_type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks",
            {"authorization": "Bearer test-token"},
            body=payload,
        )

        self.assertEqual(status, 201)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        data = json.loads(body)
        task = data["task"]
        self.assertEqual(task["id"], "task_custom_create")
        self.assertEqual(task["title"], "New created task")
        self.assertEqual(task["status"], "ready")
        self.assertEqual(task["priority"], "high")
        self.assertEqual(task["owner"], "testuser")
        self.assertEqual(task["labels"], ["web", "m5"])
        self.assertEqual(task["body"], "Detailed task description.")
        self.assertEqual(task["acceptance_criteria"], ["Criteria 1", "Criteria 2"])
        self.assertEqual(task["git_links"], [{"repository": "workspace", "sha": "abcdef1"}])
        self.assertTrue(task["revision"].startswith("mtime:"))

        # Check file exists on disk
        target = self.context / "tasks/workspace/task_custom_create.md"
        self.assertTrue(target.exists())

        # Check board sees the new task
        _status, _type, board_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/board",
            {"authorization": "Bearer test-token"},
        )
        board = json.loads(board_body)
        ready_ids = [item["id"] for item in board["columns"]["ready"]]
        self.assertIn("task_custom_create", ready_ids)

    def test_create_task_with_generated_id_and_defaults(self):
        payload = json.dumps({"title": "Auto id task"}).encode("utf-8")

        status, _type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks",
            {"authorization": "Bearer test-token"},
            body=payload,
        )

        self.assertEqual(status, 201)
        data = json.loads(body)
        task = data["task"]
        self.assertTrue(task["id"].startswith("task_"))
        self.assertEqual(task["status"], "backlog")
        self.assertEqual(task["priority"], "normal")
        self.assertEqual(task["owner"], "unassigned")
        self.assertEqual(task["blocked"], False)
        self.assertEqual(task["labels"], [])

    def test_create_task_requires_bearer_token(self):
        payload = json.dumps({"title": "No auth task"}).encode("utf-8")
        with self.assertRaises(Unauthorized):
            route(self.state, "POST", "/api/projects/workspace/tasks", {}, body=payload)

    def test_create_task_validation_failures(self):
        # Missing title
        with self.assertRaisesRegex(WebError, "title is required"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": ""}).encode("utf-8"),
            )

        # Invalid status
        with self.assertRaisesRegex(WebError, "invalid task status"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": "Task", "status": "invalid_status"}).encode("utf-8"),
            )

        # Blocked without reason
        with self.assertRaisesRegex(WebError, "blocked tasks require"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": "Task", "blocked": True, "blocked_reason": ""}).encode("utf-8"),
            )

        # Unknown project
        with self.assertRaisesRegex(NotFound, "project not found"):
            route(
                self.state,
                "POST",
                "/api/projects/unknown/tasks",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": "Task"}).encode("utf-8"),
            )

    def test_update_task_updates_metadata_and_body(self):
        payload = json.dumps(
            {
                "title": "Renamed Board Task",
                "status": "in_progress",
                "priority": "urgent",
                "owner": "agent-1",
                "body": "Updated body content.",
                "labels": ["updated"],
            }
        ).encode("utf-8")

        status, content_type, body = route(
            self.state,
            "PUT",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
            body=payload,
        )

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        data = json.loads(body)
        task = data["task"]
        self.assertEqual(task["title"], "Renamed Board Task")
        self.assertEqual(task["status"], "in_progress")
        self.assertEqual(task["priority"], "urgent")
        self.assertEqual(task["owner"], "agent-1")
        self.assertEqual(task["body"], "Updated body content.")
        self.assertEqual(task["labels"], ["updated"])

        # Check detail read API sees updated task
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        read_task = json.loads(detail_body)["task"]
        self.assertEqual(read_task["title"], "Renamed Board Task")
        self.assertEqual(read_task["status"], "in_progress")

    def test_update_task_detects_revision_conflict(self):
        # Stale revision in payload
        payload = json.dumps({"title": "New Title", "expected_revision": "stale-revision-123"}).encode("utf-8")
        with self.assertRaisesRegex(Conflict, "revision mismatch"):
            route(
                self.state,
                "PUT",
                "/api/projects/workspace/tasks/task_board_ready",
                {"authorization": "Bearer test-token"},
                body=payload,
            )

        # Stale revision in If-Match header
        with self.assertRaisesRegex(Conflict, "revision mismatch"):
            route(
                self.state,
                "PUT",
                "/api/projects/workspace/tasks/task_board_ready",
                {"authorization": "Bearer test-token", "if-match": "stale-header-rev"},
                body=json.dumps({"title": "New Title"}).encode("utf-8"),
            )

    def test_update_task_rejects_missing_task_or_project(self):
        with self.assertRaisesRegex(NotFound, "task not found"):
            route(
                self.state,
                "PUT",
                "/api/projects/workspace/tasks/task_nonexistent",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": "New Title"}).encode("utf-8"),
            )

        with self.assertRaisesRegex(NotFound, "project not found"):
            route(
                self.state,
                "PUT",
                "/api/projects/unknown/tasks/task_board_ready",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"title": "New Title"}).encode("utf-8"),
            )

    def test_move_task_updates_status_and_persists(self):
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        task = json.loads(detail_body)["task"]
        rev = task["revision"]

        payload = json.dumps(
            {
                "target_status": "in_progress",
                "expected_revision": rev,
            }
        ).encode("utf-8")

        status, content_type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks/task_board_ready/move",
            {"authorization": "Bearer test-token"},
            body=payload,
        )

        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["target_status"], "in_progress")
        self.assertEqual(data["task"]["status"], "in_progress")

        _s, _t, board_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/board",
            {"authorization": "Bearer test-token"},
        )
        board = json.loads(board_body)
        in_progress_ids = [item["id"] for item in board["columns"]["in_progress"]]
        self.assertIn("task_board_ready", in_progress_ids)
        ready_ids = [item["id"] for item in board["columns"]["ready"]]
        self.assertNotIn("task_board_ready", ready_ids)

    def test_move_task_requires_expected_revision_and_detects_conflict(self):
        with self.assertRaisesRegex(WebError, "expected_revision is required"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks/task_board_ready/move",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"target_status": "in_progress"}).encode("utf-8"),
            )

        with self.assertRaisesRegex(Conflict, "revision mismatch"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks/task_board_ready/move",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"target_status": "in_progress", "expected_revision": "stale_rev"}).encode("utf-8"),
            )

    def test_move_task_handles_blocked_and_unblock(self):
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        rev = json.loads(detail_body)["task"]["revision"]

        with self.assertRaisesRegex(WebError, "blocked tasks require"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks/task_board_ready/move",
                {"authorization": "Bearer test-token"},
                body=json.dumps(
                    {
                        "target_status": "ready",
                        "expected_revision": rev,
                        "blocked": True,
                        "blocked_reason": "",
                    }
                ).encode("utf-8"),
            )

        status, _t, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks/task_board_ready/move",
            {"authorization": "Bearer test-token"},
            body=json.dumps(
                {
                    "target_status": "ready",
                    "expected_revision": rev,
                    "blocked": True,
                    "blocked_reason": "Waiting on dependency",
                }
            ).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["task"]["blocked"])
        self.assertEqual(data["task"]["blocked_reason"], "Waiting on dependency")
        new_rev = data["task"]["revision"]

        status, _t, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks/task_board_ready/move",
            {"authorization": "Bearer test-token"},
            body=json.dumps(
                {
                    "target_status": "ready",
                    "expected_revision": new_rev,
                    "blocked": False,
                }
            ).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["task"]["blocked"])
        self.assertEqual(data["task"]["blocked_reason"], "")

    def test_move_task_reports_wip_warning_when_exceeded(self):
        for i in range(3):
            payload = json.dumps(
                {
                    "id": f"task_wip_{i}",
                    "title": f"WIP task {i}",
                    "status": "in_progress",
                }
            ).encode("utf-8")
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks",
                {"authorization": "Bearer test-token"},
                body=payload,
            )

        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        rev = json.loads(detail_body)["task"]["revision"]

        status, _t, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks/task_board_ready/move",
            {"authorization": "Bearer test-token"},
            body=json.dumps(
                {
                    "target_status": "in_progress",
                    "expected_revision": rev,
                }
            ).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIsNotNone(data["wip_warning"])
        self.assertIn("limit: 3", data["wip_warning"])

        _s, _t, board_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/board",
            {"authorization": "Bearer test-token"},
        )
        board = json.loads(board_body)
        self.assertTrue(len(board["wip_warnings"]) > 0)

    def test_get_project_commits_returns_commits(self):
        status, content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/commits",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        data = json.loads(body)
        self.assertEqual(data["project"]["key"], "workspace")
        commits = data["commits"]
        self.assertTrue(len(commits) >= 1)
        self.assertEqual(commits[0]["sha"], self.sample_sha)
        self.assertEqual(commits[0]["subject"], "feat: initial commit")
        self.assertEqual(commits[0]["author"], "Test Agent")

    def test_add_and_remove_task_git_link(self):
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        task = json.loads(detail_body)["task"]
        rev = task["revision"]

        # Add git link
        status, content_type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/tasks/task_board_ready/git-links",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"sha": self.sample_sha, "expected_revision": rev}).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        shas = [item["sha"] for item in data["task"]["git_links"]]
        self.assertIn(self.sample_sha, shas)
        new_rev = data["task"]["revision"]

        # Verify persistence via detail API
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        reloaded_shas = [item["sha"] for item in json.loads(detail_body)["task"]["git_links"]]
        self.assertIn(self.sample_sha, reloaded_shas)

        # Remove git link
        status, content_type, body = route(
            self.state,
            "DELETE",
            f"/api/projects/workspace/tasks/task_board_ready/git-links/{self.sample_sha}",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"expected_revision": new_rev}).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        remaining_shas = [item["sha"] for item in data["task"]["git_links"]]
        self.assertNotIn(self.sample_sha, remaining_shas)

    def test_add_task_git_link_rejects_unknown_sha_or_conflict(self):
        _s, _t, detail_body = route(
            self.state,
            "GET",
            "/api/projects/workspace/tasks/task_board_ready",
            {"authorization": "Bearer test-token"},
        )
        rev = json.loads(detail_body)["task"]["revision"]

        # Unknown sha
        with self.assertRaisesRegex(WebError, "not found"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks/task_board_ready/git-links",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"sha": "0123456789abcdef0123456789abcdef01234567", "expected_revision": rev}).encode("utf-8"),
            )

        # Stale expected revision
        with self.assertRaisesRegex(Conflict, "revision mismatch"):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/tasks/task_board_ready/git-links",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"sha": self.sample_sha, "expected_revision": "stale_rev"}).encode("utf-8"),
            )

    def test_search_all_project_tasks_and_facets(self):
        status, content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        data = json.loads(body)
        self.assertEqual(data["project"]["key"], "workspace")
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["counts"]["by_status"]["ready"], 1)
        self.assertEqual(data["counts"]["by_status"]["review"], 1)
        self.assertEqual(data["counts"]["by_priority"]["high"], 2)
        self.assertEqual(data["counts"]["by_label"]["web"], 2)
        self.assertEqual(data["counts"]["blocked"], 0)
        self.assertEqual(data["freshness"]["scanned_tasks"], 2)
        self.assertTrue(data["freshness"]["scanned_at"].endswith("Z"))

    def test_search_by_query_string_and_snippets(self):
        # Query matching title
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?q=render",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["task"]["id"], "task_board_ready")
        self.assertIn("title", data["results"][0]["matches"])
        self.assertEqual(data["results"][0]["snippet"], "Render board")

        # Query matching body
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?q=body",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 2)
        for res in data["results"]:
            self.assertIn("body", res["matches"])
            self.assertEqual(res["snippet"], "Board task body.")

        # Query with no matches
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?q=xyznonexistent123",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["total"], 0)
        self.assertEqual(len(data["results"]), 0)

    def test_search_by_status_and_label_filters(self):
        # Status filter
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?status=ready",
            {"authorization": "Bearer test-token"},
        )
        data = json.loads(body)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["results"][0]["task"]["id"], "task_board_ready")

        # Label filter
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?label=web&priority=high",
            {"authorization": "Bearer test-token"},
        )
        data = json.loads(body)
        self.assertEqual(data["total"], 2)

        # Nonexistent label
        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search?label=backend",
            {"authorization": "Bearer test-token"},
        )
        data = json.loads(body)
        self.assertEqual(data["total"], 0)

    def test_search_source_freshness_reflects_external_changes_and_deletions(self):
        # Add third task directly to filesystem
        extra_task = TASK_READY.replace("task_board_ready", "task_board_fresh").replace("Render board", "Fresh external task")
        (self.context / "tasks/workspace/fresh.md").write_text(extra_task)

        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search",
            {"authorization": "Bearer test-token"},
        )
        data = json.loads(body)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["freshness"]["scanned_tasks"], 3)

        # Delete ready.md from filesystem
        (self.context / "tasks/workspace/ready.md").unlink()

        status, _t, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/search",
            {"authorization": "Bearer test-token"},
        )
        data = json.loads(body)
        self.assertEqual(data["total"], 2)
        task_ids = [res["task"]["id"] for res in data["results"]]
        self.assertNotIn("task_board_ready", task_ids)
        self.assertIn("task_board_fresh", task_ids)
        self.assertIn("task_board_review", task_ids)

    def test_search_missing_project_returns_not_found(self):
        with self.assertRaises(NotFound):
            route(
                self.state,
                "GET",
                "/api/projects/nonexistent/search",
                {"authorization": "Bearer test-token"},
            )

    def test_project_activity_calculates_merged_hours_and_clocks(self):
        works_dir = self.context / "works"
        (works_dir / "agent/workspace").mkdir(parents=True, exist_ok=True)
        (works_dir / "human/workspace").mkdir(parents=True, exist_ok=True)

        sess1 = json.dumps({
            "id": "agent-1",
            "kind": "agent",
            "project": "workspace",
            "start": "2026-09-15T10:00:00Z",
            "end": "2026-09-15T11:00:00Z",
            "start_ts": 1789466400,
            "end_ts": 1789470000,
            "tool": "claude-code",
            "note": "first session"
        })
        sess2 = json.dumps({
            "id": "agent-2",
            "kind": "agent",
            "project": "workspace",
            "start": "2026-09-15T10:30:00Z",
            "end": "2026-09-15T11:30:00Z",
            "start_ts": 1789468200,
            "end_ts": 1789471800,
            "tool": "codex",
            "note": "second session"
        })
        (works_dir / "agent/workspace/2026-09.jsonl").write_text(sess1 + "\n" + sess2 + "\n")

        clock_file = works_dir / ".open-agent-test.json"
        clock_file.write_text(json.dumps({
            "id": "clock-1",
            "kind": "agent",
            "project": "workspace",
            "tool": "antigravity",
            "actor": "test-user",
            "start": "2026-09-15T14:00:00Z",
            "note": "in progress task"
        }))

        status, content_type, body = route(
            self.state,
            "GET",
            "/api/projects/workspace/activity?month=2026-09",
            {"authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        data = json.loads(body)
        self.assertEqual(data["project"]["key"], "workspace")
        self.assertEqual(data["month"], "2026-09")
        self.assertEqual(data["hours"]["agent_total"], 1.5)
        self.assertEqual(data["hours"]["human_total"], 0.0)
        self.assertEqual(len(data["hours"]["days"]), 1)
        self.assertEqual(data["hours"]["days"][0]["day"], "2026-09-15")
        self.assertEqual(data["hours"]["days"][0]["agent_hours"], 1.5)
        self.assertEqual(data["hours"]["days"][0]["agent_sessions"], 2)
        self.assertIsNotNone(data["active_clocks"]["agent"])
        self.assertEqual(data["active_clocks"]["agent"]["tool"], "antigravity")

    def test_project_activity_invalid_month_format_rejected(self):
        with self.assertRaises(WebError):
            route(
                self.state,
                "GET",
                "/api/projects/workspace/activity?month=202609",
                {"authorization": "Bearer test-token"},
            )

    def test_clock_in_and_clock_out_human(self):
        # 1. Clock in human
        status, content_type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/clock",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"action": "in", "kind": "human", "actor": "tester", "note": "working on test"}).encode(),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "in")
        self.assertEqual(data["kind"], "human")
        self.assertEqual(data["project"], "workspace")

        # Verify open file exists
        works_dir = self.context / "works"
        open_file = works_dir / ".open-human-tester.json"
        self.assertTrue(open_file.exists())

        # 2. Clock out human
        status, content_type, body = route(
            self.state,
            "POST",
            "/api/projects/workspace/clock",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"action": "out", "kind": "human", "actor": "tester", "note": "finished test"}).encode(),
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertEqual(data["action"], "out")
        self.assertFalse(open_file.exists())

    def test_clock_in_already_clocked_in_raises_conflict(self):
        # Clock in first
        route(
            self.state,
            "POST",
            "/api/projects/workspace/clock",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"action": "in", "kind": "human", "actor": "busy-person"}).encode(),
        )
        # Attempting second clock-in on same actor raises Conflict
        with self.assertRaises(Conflict):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/clock",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"action": "in", "kind": "human", "actor": "busy-person"}).encode(),
            )
        # Clean up
        route(
            self.state,
            "POST",
            "/api/projects/workspace/clock",
            {"authorization": "Bearer test-token"},
            body=json.dumps({"action": "out", "kind": "human", "actor": "busy-person"}).encode(),
        )

    def test_clock_out_not_clocked_in_raises_not_found(self):
        with self.assertRaises(NotFound):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/clock",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"action": "out", "kind": "human", "actor": "ghost-user"}).encode(),
            )

    def test_clock_invalid_action_or_kind_raises_weberror(self):
        with self.assertRaises(WebError):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/clock",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"action": "invalid_action", "kind": "human"}).encode(),
            )
        with self.assertRaises(WebError):
            route(
                self.state,
                "POST",
                "/api/projects/workspace/clock",
                {"authorization": "Bearer test-token"},
                body=json.dumps({"action": "in", "kind": "alien"}).encode(),
            )

    def test_framework_dist_takes_precedence_over_companion(self):
        for folder, label in (("apps/workspace-control/dist", "Framework UI"),
                              ("projects/core/UIDL-Runtime/apps/workspace-control/dist", "Companion UI")):
            dist = self.root / folder
            dist.mkdir(parents=True)
            (dist / "index.html").write_text(f"<html><head></head><body>{label}</body></html>")
        _status, _type, body = route(self.state, "GET", "/", {})
        self.assertIn(b"Framework UI", body)

    def test_settings_reports_effective_fallback_runtime(self):
        _s, _t, body = route(self.state, "GET", "/api/settings", {"authorization": "Bearer test-token"})
        self.assertEqual(json.loads(body)["runtime"], "vanilla")

    def test_activity_rejects_impossible_month(self):
        with self.assertRaises(WebError):
            route(self.state, "GET", "/api/projects/workspace/activity?month=2026-99",
                  {"authorization": "Bearer test-token"})

    def test_clock_out_never_stops_another_actor(self):
        headers = {"authorization": "Bearer test-token"}
        path = "/api/projects/workspace/clock"
        route(self.state, "POST", path, headers,
              json.dumps({"action": "in", "actor": "alice"}).encode())
        with self.assertRaises(NotFound):
            route(self.state, "POST", path, headers,
                  json.dumps({"action": "out", "actor": "bob"}).encode())
        self.assertTrue((self.context / "works/.open-human-alice.json").exists())

    def test_clock_out_never_stops_another_project(self):
        works = self.context / "works"
        works.mkdir()
        clock = works / ".open-human-alice.json"
        clock.write_text(json.dumps({"project": "other", "kind": "human", "start_ts": 1,
                                    "actor": "alice", "note": "other project"}))
        with self.assertRaises(Conflict):
            route(self.state, "POST", "/api/projects/workspace/clock",
                  {"authorization": "Bearer test-token"},
                  json.dumps({"action": "out", "actor": "alice"}).encode())
        self.assertTrue(clock.exists())

    def test_static_uidl_serving(self):
        # Create mock dist directory in state.root
        dist_dir = self.root / "projects/core/UIDL-Runtime/apps/workspace-control/dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text("<!doctype html><html><body>Mock UIDL</body></html>")
        assets_dir = dist_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "mock.js").write_text("console.log('mock');")

        # Test GET /uidl/
        status, content_type, body = route(self.state, "GET", "/uidl/", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"Mock UIDL", body)

        # Test GET /uidl/assets/mock.js
        status, content_type, body = route(self.state, "GET", "/uidl/assets/mock.js", {})
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        self.assertIn(b"console.log", body)

        # Test path traversal prevention
        with self.assertRaises(NotFound):
            route(self.state, "GET", "/uidl/../../secret.txt", {})

    def test_uidl_runtime_mode_serves_uidl_at_root(self):
        dist_dir = self.root / "projects/core/UIDL-Runtime/apps/workspace-control/dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text("<!doctype html><html><body>UIDL Root</body></html>")

        uidl_state = build_state(self.root, token="test-token", runtime="uidl")
        status, content_type, body = route(uidl_state, "GET", "/", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"UIDL Root", body)
        self.assertIn(b"test-token", body)
        self.assertIn(b"searchParams.set('token'", body)

    def test_default_runtime_is_uidl_when_dist_exists(self):
        dist_dir = self.root / "projects/donwi/public/UIDL-Runtime/apps/workspace-control/dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text("<!doctype html><html><body>Preferred UIDL</body></html>")
        default_state = build_state(self.root, token="test-token")
        self.assertEqual(default_state.runtime, "uidl")
        status, _content_type, body = route(default_state, "GET", "/", {})
        self.assertEqual(status, 200)
        self.assertIn(b"Preferred UIDL", body)
        self.assertIn(b"test-token", body)

    def test_uidl_token_inject_skips_assets(self):
        dist_dir = self.root / "projects/core/UIDL-Runtime/apps/workspace-control/dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text("<!doctype html><html><head></head><body>UIDL</body></html>")
        assets = dist_dir / "assets"
        assets.mkdir(parents=True, exist_ok=True)
        (assets / "app.js").write_text("console.log('plain')")
        uidl_state = build_state(self.root, token="secret-token", runtime="uidl")
        _status, _type, js = route(uidl_state, "GET", "/assets/app.js", {})
        self.assertEqual(js, b"console.log('plain')")
        self.assertNotIn(b"secret-token", js)

    def test_uidl_falls_back_to_vanilla_without_dist(self):
        default_state = build_state(self.root, token="test-token", runtime="uidl")
        status, content_type, body = route(default_state, "GET", "/", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        self.assertIn(b"command-palette", body)


if __name__ == "__main__":
    unittest.main()
