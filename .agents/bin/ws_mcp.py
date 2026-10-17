"""`ws mcp`: the workspace's project management records over MCP (stdio), for any coding agent.

The same operations as `ws task`, `ws today`, `ws alerts`, and `ws client show`, through the
same code (ADR-0024), so an agent and the operator see one truth. Scope follows the session's
bind (ADR-0011): an agent bound to a project reads and writes that project's tasks and its
client's own tasks, and nothing of any other client. `--project <key>` fixes the scope instead;
`--workspace` opens every scope and is for the operator's own assistant only. Restricted client
records are never returned. Every write is a `change` action (ADR-0014) and is recorded in the
task's activity under WS_TASK_ACTOR. No tool deletes anything.

Transport: newline-delimited JSON-RPC 2.0 on stdin and stdout. Standard library only.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from ws_pm import active_alerts, client_dossier, today
from ws_tasks import (
    TaskError, _task, change_status, check_item, comment_task, create_task, edit_task, list_tasks, load_source,
    load_tasks, parse_scope, registry_clients, set_blocked, task_json,
)

SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Project management records of this workspace (tasks, milestones, reminders, alerts, client profile), "
    "scoped to the bound project and its client. Read before you plan; record what you change. "
    "Pass the revision you read when you change a task, so a concurrent edit is refused rather than lost."
)

SCOPE = {"type": "string", "description": "A project key, or @<client> for the client's own work. Defaults to the bound project."}
TASK = {"type": "string", "description": "A task id, task_<slug>."}
REVISION = {"type": "string", "description": "The revision you read (mtime:<ns>:size:<bytes>); a change is refused if the task changed since."}
STATUSES = ["backlog", "ready", "in_progress", "review", "done"]
STRINGS = {"type": "array", "items": {"type": "string"}}


def _schema(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "pm_today",
     "description": "What needs doing now in this scope: signals, people waiting, overdue and due work, reminders, work in progress.",
     "inputSchema": _schema({"scope": SCOPE})},
    {"name": "pm_alerts",
     "description": "Computed alerts in this scope: overdue, due today, reminders, blocked, stale, waiting reviews, approvals, agents that raised a hand.",
     "inputSchema": _schema({"scope": SCOPE})},
    {"name": "pm_list_tasks", "description": "Tasks in this scope, ranked, with fields, checklist, activity, and revision.",
     "inputSchema": _schema({"scope": SCOPE, "status": {"type": "array", "items": {"type": "string", "enum": STATUSES}},
                             "assignee": {"type": "string"}, "label": {"type": "string"},
                             "kind": {"type": "string", "enum": ["task", "milestone", "reminder"]},
                             "due_before": {"type": "string", "description": "YYYY-MM-DD, inclusive."}})},
    {"name": "pm_get_task", "description": "One task in full, with its revision.",
     "inputSchema": _schema({"task_id": TASK, "scope": SCOPE}, ("task_id",))},
    {"name": "pm_add_task", "description": "Add a task to the backlog of this scope.",
     "inputSchema": _schema({"title": {"type": "string"}, "scope": SCOPE, "description": {"type": "string"},
                             "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
                             "due": {"type": "string", "description": "YYYY-MM-DD"},
                             "assignee": {"type": "string", "description": "A person's key, or agent:<tool>."},
                             "labels": STRINGS, "parent": TASK, "kind": {"type": "string", "enum": ["task", "milestone", "reminder"]}},
                            ("title",))},
    {"name": "pm_update_task",
     "description": "Change a task: status, fields, checklist items, or block it with a reason / unblock it. `none` clears a field.",
     "inputSchema": _schema({"task_id": TASK, "scope": SCOPE, "revision": REVISION, "status": {"type": "string", "enum": STATUSES},
                             "title": {"type": "string"}, "priority": {"type": "string"}, "due": {"type": "string"},
                             "assignee": {"type": "string"}, "parent": {"type": "string"}, "remind_at": {"type": "string"},
                             "recur": {"type": "string"}, "rank": {"type": "integer"}, "labels_add": STRINGS, "labels_rm": STRINGS,
                             "check_add": STRINGS, "accept_add": STRINGS,
                             "blocked_reason": {"type": "string", "description": "Blocks the task with this reason."},
                             "unblock": {"type": "boolean"}}, ("task_id",))},
    {"name": "pm_comment", "description": "Add a comment to a task's activity.",
     "inputSchema": _schema({"task_id": TASK, "text": {"type": "string"}, "scope": SCOPE, "revision": REVISION}, ("task_id", "text"))},
    {"name": "pm_check", "description": "Tick or untick checklist item n (from 1).",
     "inputSchema": _schema({"task_id": TASK, "n": {"type": "integer", "minimum": 1}, "scope": SCOPE, "revision": REVISION},
                            ("task_id", "n"))},
    {"name": "client_profile",
     "description": "The bound client's profile, projects, open work, and interactions. Contacts and commercial terms are never included.",
     "inputSchema": _schema({})},
]

FIELDS = ("title", "priority", "due", "assignee", "parent", "remind_at", "recur", "rank",
          "labels_add", "labels_rm", "check_add", "accept_add")


class Refused(Exception):
    """A call this session may not make; reported to the agent as a tool error."""


class Session:
    def __init__(self, context: Path, root: Path, session_dir: Path | None, project: str | None, workspace: bool):
        self.context, self.root, self.session_dir = context, root, session_dir
        self.project, self.workspace = project, workspace

    def scopes(self) -> tuple[str, set[str]]:
        """The default scope and every scope this session may touch, read from the bind each call."""
        project = self.project
        if not project and self.session_dir and (self.session_dir / "bind").is_file():
            lines = (self.session_dir / "bind").read_text(encoding="utf-8").splitlines()
            project = dict(line.split("=", 1) for line in lines if "=" in line).get("project", "")
        if not project:
            if self.workspace:
                return "", set()
            raise Refused("bind a project first: ws session bind <project-key>, or start the server with --project <key>")
        parse_scope(project)
        client = registry_clients(load_source("context", self.context)).get(project, "")
        return project, {project, *([f"@{client}"] if client and client != "-" else [])}

    def scope(self, requested: str | None) -> str:
        default, allowed = self.scopes()
        scope = requested or default
        if not scope:
            raise Refused("name a scope: a project key or @<client>")
        parse_scope(scope)
        if not self.workspace and scope not in allowed:
            raise Refused(f"'{scope}' is outside this session's scope ({', '.join(sorted(allowed))})")
        return scope

    def task(self, scope: str, task_id: str) -> dict[str, object]:
        source = load_source("context", self.context)
        return task_json(_task(source, scope, task_id, None), registry_clients(source), load_tasks(source)[0])

    def client(self) -> str:
        default, allowed = self.scopes()
        clients = [scope[1:] for scope in allowed if scope.startswith("@")]
        if not clients:
            raise Refused("this session is bound to no client")
        return clients[0]


def _now() -> datetime:
    return datetime.now().astimezone()


def call_tool(session: Session, name: str, args: dict[str, Any]) -> object:
    source = load_source("context", session.context)
    if name in ("pm_today", "pm_alerts"):
        scope = session.scope(args.get("scope")) if (args.get("scope") or not session.workspace) else None
        if name == "pm_today":
            return today(session.context, session.root, _now(), scope=scope)
        return {"alerts": [asdict(a) for a in active_alerts(session.context, session.root, _now(), scope=scope)]}
    if name == "client_profile":
        return client_dossier(session.context, session.root, session.client(), _now())
    scope = session.scope(args.get("scope"))
    if name == "pm_list_tasks":
        found = list_tasks(source, scope, status=args.get("status") or (), assignee=args.get("assignee", ""),
                           label=args.get("label", ""), due_before=args.get("due_before", ""))
        if args.get("kind"):
            found = [task for task in found if task.kind == args["kind"]]
        owners, everything = registry_clients(source), load_tasks(source)[0]
        return {"tasks": [task_json(task, owners, everything) for task in found]}
    if name == "pm_get_task":
        return session.task(scope, args["task_id"])
    if name == "pm_add_task":
        record = create_task(source, scope, args["title"], args.get("priority", "normal"), "", args.get("description", ""),
                             kind=args.get("kind", "task"), due=args.get("due", ""), assignee=args.get("assignee", ""),
                             labels=args.get("labels") or (), parent=args.get("parent", ""))
        return session.task(scope, record.id)
    task_id = args["task_id"]
    revision = args.get("revision")
    if name == "pm_comment":
        comment_task(source, scope, task_id, args["text"], revision)
    elif name == "pm_check":
        check_item(source, scope, task_id, int(args["n"]), revision)
    elif name == "pm_update_task":
        changes = {key: args[key] for key in FIELDS if key in args}
        if not changes and "status" not in args and "blocked_reason" not in args and not args.get("unblock"):
            raise Refused("nothing to change")
        # The revision guards the first write; each later one re-reads the task it follows.
        if changes:
            edit_task(source, scope, task_id, changes, revision)
            revision = None
        if "blocked_reason" in args or args.get("unblock"):
            set_blocked(source, scope, task_id, None if args.get("unblock") else args["blocked_reason"], revision)
            revision = None
        if "status" in args:
            change_status(source, scope, task_id, args["status"], revision)
    else:
        raise Refused(f"unknown tool '{name}'")
    return session.task(scope, task_id)


def handle(session: Session, message: dict[str, Any]) -> dict[str, Any] | None:
    method, request_id = message.get("method"), message.get("id")
    if request_id is None:
        return None  # a notification
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        result: dict[str, Any] = {
            "protocolVersion": asked if asked in SUPPORTED else SUPPORTED[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "workspace", "version": "1"},
            "instructions": INSTRUCTIONS,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            data = call_tool(session, str(params.get("name", "")), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(data, indent=2, sort_keys=True)}], "isError": False}
        except (Refused, TaskError, KeyError, ValueError) as error:
            text = f"missing argument {error}" if isinstance(error, KeyError) else str(error)
            result = {"content": [{"type": "text", "text": text}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws mcp")
    parser.add_argument("context_root")
    parser.add_argument("workspace_root")
    parser.add_argument("--session-dir")
    parser.add_argument("--project")
    parser.add_argument("--workspace", action="store_true")
    opts = parser.parse_args(argv)
    session = Session(Path(opts.context_root), Path(opts.workspace_root),
                      Path(opts.session_dir) if opts.session_dir else None, opts.project, opts.workspace)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(session, message) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
