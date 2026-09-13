"""Regression checks against temporary repositories; no network or personal data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class WorkspaceSecurity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-security-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        for directory in ["bin", "templates", "standards"]:
            shutil.copytree(SOURCE / ".agents" / directory, self.root / ".agents" / directory)
        for name in ["AGENTS.md", ".gitignore", ".ignore", "workspace.conf.example"]:
            shutil.copy2(SOURCE / name, self.root / name)
        self.env = dict(os.environ, WS_USER="fixture", WS_AGENT="test",
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        self.git(self.root, "init", "-qb", "main")
        self.ws("init", "--org", "Example", "--key", "example", "--group", "git@example.invalid:example")
        self.ws("context", "init")
        self.ws("client", "new", "alpha")
        self.ws("new", "api", "projects/alpha/public/api", "--client", "alpha")
        self.product = self.root / "projects/alpha/public/api"

    def ws(self, *args, success=True):
        result = subprocess.run([str(self.root / ".agents/bin/ws"), *args],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def git(self, root, *args):
        result = subprocess.run(["git", "-C", str(root), *args], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_links_resolve_actual_context(self):
        pointer = (self.product / "AGENTS.md").read_text()
        self.assertIn(str(self.root / "context/memory/projects/api"), pointer)
        self.assertIn(str(self.root / "context/runs/api"), pointer)

    def test_link_and_unlink_preserve_client_instructions(self):
        path = self.product / "AGENTS.md"
        path.write_text("# Client-owned instructions\n")
        self.git(self.product, "add", "-f", "AGENTS.md")
        self.ws("link", "api")
        self.assertEqual(path.read_text(), "# Client-owned instructions\n")
        self.ws("unlink", "api")
        self.assertEqual(path.read_text(), "# Client-owned instructions\n")

    def test_reject_parent_escape_before_mutation(self):
        result = self.ws("new", "escape", "../outside", "--client", "alpha", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "outside").exists())

    def test_reject_symlink_escape(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "projects/escape").symlink_to(outside, target_is_directory=True)
        result = self.ws("new", "escape", "projects/escape/repo", "--client", "alpha", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((outside / "repo").exists())

    def test_reject_pointer_symlink(self):
        pointer = self.product / "AGENTS.md"
        pointer.unlink()
        sentinel = self.base / "sentinel"
        sentinel.write_text("untouched")
        pointer.symlink_to(sentinel)
        self.ws("link", "api", success=False)
        self.assertEqual(sentinel.read_text(), "untouched")

    def test_reject_invalid_key(self):
        result = self.ws("new", "../../escape", "projects/alpha/other", "--client", "alpha", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "projects/alpha/other").exists())

    def test_skills_sync_restores_locked_revision(self):
        source = self.base / "skills"
        skill = source / "skills/example/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: example\npack: core\ndescription: Fixture\n---\none\n")
        (source / "index.json").write_text('{"skills": []}\n')
        self.git(source, "init", "-qb", "main")
        self.git(source, "config", "user.name", "Fixture")
        self.git(source, "config", "user.email", "fixture@example.invalid")
        self.git(source, "add", ".")
        self.git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "one")
        (self.root / ".agents/skills.manifest").write_text(f"source = {source}\nref = main\nskill example\n")
        self.ws("skills", "sync")
        lock = self.root / ".agents/skills.lock"
        before = lock.read_bytes()
        skill.write_text(skill.read_text().replace("one", "two"))
        self.git(source, "add", ".")
        self.git(source, "-c", "commit.gpgsign=false", "commit", "-qm", "two")
        self.ws("skills", "sync")
        self.assertEqual(lock.read_bytes(), before)
        self.assertIn("one", (self.root / ".agents/skills/example/SKILL.md").read_text())
        self.ws("skills", "update")
        self.assertIn("two", (self.root / ".agents/skills/example/SKILL.md").read_text())

    def test_unscoped_route_excludes_client_skills(self):
        skill = self.root / "context/clients/alpha/skills/secret-domain/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: secret-domain\nkeywords: widgets, gizmos\ndescription: Widgets and gizmos\n---\n")
        self.assertNotIn("secret-domain", self.ws("route", "widgets gizmos").stdout)
        self.assertIn("secret-domain", self.ws("route", "--project", "api", "widgets gizmos").stdout)

    def test_clock_serializes_quotes_and_separate_sessions(self):
        self.env["WS_SESSION_ID"] = "one"
        self.ws("agent", "in", "api", 'review "quoted" task')
        self.env["WS_SESSION_ID"] = "two"
        self.ws("agent", "in", "api", "second")
        opened = list((self.root / "context/works").glob(".open-agent-*.json"))
        self.assertEqual(len(opened), 2)
        notes = [json.loads(p.read_text())["note"] for p in opened]
        self.assertIn('review "quoted" task', notes)
        self.ws("agent", "out")
        self.env["WS_SESSION_ID"] = "one"
        self.ws("agent", "out")

    def test_human_hours_count_each_person(self):
        target = self.root / "context/works/human/api/2026-09.jsonl"
        target.parent.mkdir(parents=True)
        target.write_text("".join(json.dumps({"actor": actor, "start": "2026-09-01T09:00:00+07:00",
            "start_ts": 1788228000, "end_ts": 1788231600}, separators=(",", ":")) + "\n" for actor in ["alice", "bob"]))
        self.assertIn("2.00", self.ws("hours", "--month", "2026-09", "--project", "api").stdout)

    def test_linked_worktree_uses_git_paths(self):
        self.git(self.product, "config", "user.name", "Fixture")
        self.git(self.product, "config", "user.email", "fixture@example.invalid")
        self.git(self.product, "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "initial")
        target = self.root / "projects/alpha/public/worktree"
        self.git(self.product, "worktree", "add", "-b", "feature", str(target))
        self.ws("new", "worktree", "projects/alpha/public/worktree", "--client", "alpha")
        self.assertTrue((target / ".workspace").is_file())

    def test_context_pack_excludes_other_client_and_local_notes(self):
        self.ws("client", "new", "beta")
        (self.root / "context/clients/beta/client.md").write_text("PRIVATE_SIBLING_CANARY")
        (self.root / ".local").mkdir()
        (self.root / ".local/notes.md").write_text("PERSONAL_CANARY")
        pack = json.loads(self.ws("context", "pack", "api").stdout)
        self.assertEqual(pack["project"], "api")
        self.assertIn("context/memory/projects/api/project.md", [f["path"] for f in pack["files"]])
        self.assertNotIn("PRIVATE_SIBLING_CANARY", json.dumps(pack))
        self.assertNotIn("PERSONAL_CANARY", json.dumps(pack))


if __name__ == "__main__":
    unittest.main()
