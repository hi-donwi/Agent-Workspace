"""Regression checks against temporary repositories; no network or personal data."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class RegistryGroups(unittest.TestCase):
    """Registry v2 migration, groups, ownership checks, tree, and group-scoped packs."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ws-groups-")
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
        self.ws("client", "new", "beta")
        self.ws("new", "api", "projects/alpha/api", "--client", "alpha")

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

    def migrate(self, force_v1=False):
        registry = self.root / "context/registry.tsv"
        registry.parent.mkdir(parents=True, exist_ok=True)
        if force_v1 and registry.exists():
            rows = registry.read_text().splitlines()[1:]
            registry.write_text("key\tclient\tfolder\tremote\tdescription\n" + "\n".join(rows) + "\n")
        if not registry.read_text().startswith("key\tclient\tgroup\t"):
            self.ws("context", "migrate-v2")
        header = registry.read_text().splitlines()[0].split("\t")
        self.assertEqual(header, ["key", "client", "group", "folder", "remote",
                                  "context_scope", "security_profile", "description"])
        return registry.read_text()

    def test_migration_adds_group_scope_profile_columns_with_defaults(self):
        registry = self.migrate(force_v1=True)
        row = [line.split("\t") for line in registry.splitlines()[1:] if line.strip()][0]
        self.assertEqual(row[0], "api")
        self.assertEqual(row[2], "-")
        self.assertEqual(row[5], "client")
        self.assertEqual(row[6], "-")
        backup = self.root / "context/registry.tsv.bak-v1"
        self.assertTrue(backup.is_file())
        self.assertTrue(backup.read_text().startswith("key\tclient\tfolder"))
        # idempotent: refusing a second run must not damage the file
        before = (self.root / "context/registry.tsv").read_text()
        self.ws("context", "migrate-v2", success=False)
        self.assertEqual((self.root / "context/registry.tsv").read_text(), before)

    def test_group_registration_and_ownership(self):
        self.migrate()
        self.ws("group", "new", "erp", "--client", "alpha")
        groups = (self.root / "context/groups.tsv").read_text().splitlines()
        self.assertIn("erp\talpha\t-", groups)
        # a group belongs to exactly one client
        out = self.ws("group", "new", "erp", "--client", "beta", success=False)
        self.assertNotEqual(out.returncode, 0)
        # a project may reference its own client's group
        self.ws("new", "erp-web", "projects/alpha/erp/web", "--client", "alpha", "--group", "erp")
        # ... and must never reference another client's group
        out = self.ws("new", "beta-site", "projects/beta/site", "--client", "beta", "--group", "erp", success=False)
        self.assertNotEqual(out.returncode, 0)
        self.assertFalse((self.root / "projects/beta/site").exists())
        registry = (self.root / "context/registry.tsv").read_text()
        self.assertNotIn("beta-site", registry)

    def test_tree_renders_client_group_project_hierarchy(self):
        self.migrate()
        self.ws("group", "new", "erp", "--client", "alpha")
        self.ws("new", "erp-web", "projects/alpha/erp/web", "--client", "alpha", "--group", "erp")
        out = self.ws("tree").stdout
        self.assertIn("alpha/", out)
        self.assertIn("erp/", out)
        self.assertIn("erp-web", out)
        self.assertIn("(ungrouped)", out)
        self.assertIn("api", out)
        self.assertIn("beta/", out)

    def test_scope_and_profile_are_validated_and_stored(self):
        self.migrate()
        self.ws("new", "site", "projects/beta/site", "--client", "beta", "--scope", "org", "--profile", "strict")
        row = [line.split("\t") for line in
               (self.root / "context/registry.tsv").read_text().splitlines()[1:] if line.strip()]
        site = [r for r in row if r[0] == "site"][0]
        self.assertEqual(site[5], "org")
        self.assertEqual(site[6], "strict")
        out = self.ws("new", "bad", "projects/beta/bad", "--client", "beta", "--scope", "world", success=False)
        self.assertNotEqual(out.returncode, 0)

    def test_doctor_rejects_cross_client_group(self):
        self.migrate()
        self.ws("group", "new", "erp", "--client", "alpha")
        registry = self.root / "context/registry.tsv"
        rows = registry.read_text().splitlines()
        rows.append("beta-app\tbeta\terp\tprojects/beta/app\t-\tclient\t-\tsynthetic")
        registry.write_text("\n".join(rows) + "\n")
        out = self.ws("doctor", success=False)
        self.assertIn("different client", out.stdout + out.stderr)

    def test_context_pack_includes_own_group_docs_only(self):
        self.migrate()
        self.ws("group", "new", "erp", "--client", "alpha")
        self.ws("new", "erp-web", "projects/alpha/erp/web", "--client", "alpha",
                "--group", "erp", "--scope", "group")
        group_doc = self.root / "context/clients/alpha/groups/erp/client.md"
        group_doc.parent.mkdir(parents=True)
        group_doc.write_text("ERP_GROUP_CANARY")
        other_doc = self.root / "context/clients/beta/client.md"
        other_doc.write_text("BETA_CLIENT_CANARY")
        pack = json.loads(self.ws("context", "pack", "erp-web").stdout)
        self.assertEqual(pack["group"], "erp")
        contents = json.dumps(pack)
        self.assertIn("ERP_GROUP_CANARY", contents)
        self.assertNotIn("BETA_CLIENT_CANARY", contents)
        # a group-scoped pack carries no client-wide material either
        self.assertNotIn("clients/alpha/client.md", [f["path"] for f in pack["files"]])


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
