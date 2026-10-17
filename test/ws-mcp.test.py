import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
SERVER = SOURCE / ".agents/bin/ws_mcp.py"


def task_doc(task_id, scope, title, status="backlog", extra=""):
    project, client = ("", scope[1:]) if scope.startswith("@") else (scope, "")
    client_line = f"client: {client}\n" if client else ""
    return (
        "---\nschema_version: 2\n"
        f"id: {task_id}\nproject: {project or chr(34) * 2}\ntitle: {title}\nstatus: {status}\npriority: normal\nowner: dw\n"
        "labels:\nacceptance_criteria:\nrelated_plans:\nrelated_runs:\ngit_links:\n"
        'blocked: false\nblocked_reason: ""\n'
        f"{client_line}{extra}created_at: 2026-10-01T09:00:00+07:00\nupdated_at: 2026-10-17T09:00:00+07:00\n---\n"
    )


class Server:
    """One `ws mcp` process, spoken to in newline-delimited JSON-RPC as an MCP client would."""

    def __init__(self, context, root, *args):
        env = {**os.environ, "WS_TASK_ACTOR": "dw-test-agent"}
        self.process = subprocess.Popen([sys.executable, str(SERVER), str(context), str(root), *args],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def call(self, tool, arguments=None):
        result = self.request("tools/call", {"name": tool, "arguments": arguments or {}})["result"]
        return result["isError"], json.loads(result["content"][0]["text"]) if not result["isError"] else result["content"][0]["text"]

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=5)
        self.process.stdout.close()


class McpServer(unittest.TestCase):
    """`ws mcp`: the project management records for any coding agent, within its bind (ADR-0024)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ws-mcp-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.context = self.root / "context"
        for folder in ("tasks/api", "tasks/web", "clients/acme/tasks", "clients/beta"):
            (self.context / folder).mkdir(parents=True)
        (self.context / "registry.tsv").write_text("key\tclient\tgroup\tfolder\napi\tacme\t-\tp/api\nweb\tbeta\t-\tp/web\n")
        (self.context / "clients/acme/client.md").write_text("# acme — client\n\n- **Full name:** Acme Logistics\n")
        (self.context / "clients/beta/client.md").write_text("# beta — client\n")
        (self.context / "clients/acme/contacts.md").write_text("RESTRICTED_CONTACT_CANARY\n")
        (self.context / "tasks/api/task_fix_login.md").write_text(task_doc("task_fix_login", "api", "Fix login", status="ready"))
        (self.context / "tasks/web/task_other.md").write_text(task_doc("task_other", "web", "OTHER_CLIENT_CANARY"))
        (self.context / "clients/acme/tasks/task_report.md").write_text(task_doc("task_report", "@acme", "Send the report"))
        self.session = self.root / ".local/sessions/s1"
        self.session.mkdir(parents=True)
        (self.session / "bind").write_text("project=api\nclient=acme\n")

    def server(self, *args):
        server = Server(self.context, self.root, "--session-dir", str(self.session), *args)
        self.addCleanup(server.close)
        reply = server.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
        self.assertEqual(reply["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(reply["result"]["serverInfo"]["name"], "workspace")
        server.notify("notifications/initialized")
        return server

    def test_lists_its_tools(self):
        server = self.server()
        names = {tool["name"] for tool in server.request("tools/list")["result"]["tools"]}
        self.assertEqual(names, {"pm_today", "pm_alerts", "pm_list_tasks", "pm_get_task", "pm_add_task",
                                 "pm_update_task", "pm_comment", "pm_check", "client_profile"})
        self.assertEqual(server.request("ping")["result"], {})
        self.assertEqual(server.request("no/such")["error"]["code"], -32601)

    def test_reads_and_writes_within_the_bound_project_and_its_client(self):
        server = self.server()
        error, data = server.call("pm_list_tasks")
        self.assertFalse(error)
        self.assertEqual([t["id"] for t in data["tasks"]], ["task_fix_login"])
        error, data = server.call("pm_list_tasks", {"scope": "@acme"})
        self.assertEqual([t["id"] for t in data["tasks"]], ["task_report"])
        error, message = server.call("pm_list_tasks", {"scope": "web"})
        self.assertTrue(error)
        self.assertIn("outside this session's scope", message)
        error, message = server.call("pm_get_task", {"task_id": "task_other"})
        self.assertTrue(error)

        error, created = server.call("pm_add_task", {"title": "From the agent", "due": "2026-10-30", "description": "Found while fixing login."})
        self.assertFalse(error, created)
        self.assertEqual((created["project"], created["due"], created["activity"][0]["actor"]), ("api", "2026-10-30", "dw-test-agent"))
        error, moved = server.call("pm_update_task", {"task_id": "task_fix_login", "status": "in_progress", "check_add": ["Reproduce"]})
        self.assertFalse(error, moved)
        self.assertEqual((moved["status"], moved["checklist"][0]["text"]), ("in_progress", "Reproduce"))
        error, blocked = server.call("pm_update_task", {"task_id": "task_fix_login", "blocked_reason": "needs a test device"})
        self.assertTrue(blocked["blocked"])
        error, checked = server.call("pm_check", {"task_id": "task_fix_login", "n": 1})
        self.assertTrue(checked["checklist"][0]["done"])
        error, commented = server.call("pm_comment", {"task_id": "task_fix_login", "text": "Session TTL was 5 min."})
        self.assertEqual(commented["activity"][-1]["text"], "Session TTL was 5 min.")
        error, stale = server.call("pm_update_task", {"task_id": "task_fix_login", "status": "review", "revision": "mtime:1:size:1"})
        self.assertTrue(error)
        self.assertIn("revision mismatch", stale)

    def test_today_alerts_and_the_client_profile_never_cross_the_boundary(self):
        server = self.server()
        for tool in ("pm_today", "pm_alerts", "client_profile"):
            error, data = server.call(tool)
            self.assertFalse(error, data)
            text = json.dumps(data)
            self.assertNotIn("OTHER_CLIENT_CANARY", text, tool)
            self.assertNotIn("RESTRICTED_CONTACT_CANARY", text, tool)
        error, profile = server.call("client_profile")
        self.assertEqual(profile["client"], "acme")
        self.assertEqual(profile["restricted"]["contacts"], True)

    def test_without_a_bind_it_refuses_and_a_fixed_project_overrides(self):
        (self.session / "bind").unlink()
        error, message = self.server().call("pm_list_tasks")
        self.assertTrue(error)
        self.assertIn("bind a project first", message)
        error, data = self.server("--project", "web").call("pm_list_tasks")
        self.assertFalse(error)
        self.assertEqual([t["id"] for t in data["tasks"]], ["task_other"])


if __name__ == "__main__":
    unittest.main()
