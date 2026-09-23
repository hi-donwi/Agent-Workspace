"""Local web-control shell for Agent Workspace.

M2 is intentionally small: a read-only local HTTP shell that exposes project and context
summaries from the configured workspace. It requires a per-process bearer token so another
local page cannot read context by guessing the port.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse

import ws_state
from ws_tasks import GitLink, TaskConflict, TaskError, TaskRecord, load_source, load_tasks, write_task_document


PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
MAX_CONTEXT_BYTES = 32768
DEFAULT_WIP_LIMITS = {"in_progress": 3, "review": 5}


class WebError(ValueError):
    status = HTTPStatus.BAD_REQUEST


class NotFound(WebError):
    status = HTTPStatus.NOT_FOUND


class Unauthorized(WebError):
    status = HTTPStatus.UNAUTHORIZED


class Conflict(WebError):
    status = HTTPStatus.CONFLICT


class Forbidden(WebError):
    status = HTTPStatus.FORBIDDEN


@dataclass(frozen=True)
class ProjectSummary:
    key: str
    client: str
    group: str
    folder: str
    context_scope: str
    security_profile: str
    description: str


@dataclass(frozen=True)
class WorkspaceWebState:
    root: Path
    context: Path
    token: str
    runtime: str = "uidl"


def build_state(
    root: str | Path,
    *,
    token: str | None = None,
    runtime: str = "uidl",
) -> WorkspaceWebState:
    base = Path(root).resolve()
    context = base / _context_dir(base)
    if not (context / "registry.tsv").is_file():
        raise WebError("context registry not found")
    return WorkspaceWebState(base, context.resolve(), token or secrets.token_urlsafe(32), runtime=runtime)


def _locate_uidl_dist(root: Path) -> Path:
    env_override = os.environ.get("WS_UIDL_DIST")
    if env_override:
        return Path(env_override).resolve()

    preferred = [
        root / "apps/workspace-control/dist",
        root / "projects/core/UIDL-Runtime/apps/workspace-control/dist",
    ]
    for candidate in preferred:
        if (candidate / "index.html").is_file():
            return candidate.resolve()

    matches = sorted(p for p in root.glob("projects/**/apps/workspace-control/dist") if (p / "index.html").is_file())
    if matches:
        return matches[0].resolve()

    return preferred[0].resolve()


def _uidl_available(root: Path) -> bool:
    return (_locate_uidl_dist(root) / "index.html").is_file()


def _serve_static_uidl(state: WorkspaceWebState, subpath: str) -> tuple[int, str, bytes]:
    dist_dir = _locate_uidl_dist(state.root)
    if not dist_dir.is_dir():
        raise NotFound("UIDL UI build not found. Run 'npm ci && npm run build' in apps/workspace-control.")

    clean_subpath = subpath.lstrip("/")
    if not clean_subpath:
        clean_subpath = "index.html"

    target_path = (dist_dir / clean_subpath).resolve()
    try:
        target_path.relative_to(dist_dir)
    except ValueError:
        raise NotFound(f"invalid static path: {subpath}")

    if not target_path.is_file():
        raise NotFound(f"static file not found: {subpath}")

    mime, _ = mimetypes.guess_type(str(target_path))
    content_type = mime or "application/octet-stream"
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
        content_type += "; charset=utf-8"

    payload = target_path.read_bytes()
    if clean_subpath == "index.html":
        payload = _inject_uidl_token(payload, state.token)
    return HTTPStatus.OK, content_type, payload


def _inject_uidl_token(html: bytes, token: str) -> bytes:
    """Put the process token into the companion URL without editing UIDL-Runtime.

    The companion already reads `?token=` on boot. This script runs before the
    module bundle so a bare `/` becomes `/?token=...` in the same origin.
    """
    token_js = json.dumps(token)
    snippet = (
        "<script>(function(){var t="
        + token_js
        + ";var u=new URL(location.href);if(!u.searchParams.get('token'))"
        + "{u.searchParams.set('token',t);location.replace(u.toString());}})();</script>"
    )
    text = html.decode("utf-8", errors="replace")
    if "</head>" in text:
        text = text.replace("</head>", snippet + "</head>", 1)
    elif "<body>" in text:
        text = text.replace("<body>", "<body>" + snippet, 1)
    else:
        text = snippet + text
    return text.encode("utf-8")


def route(
    state: WorkspaceWebState,
    method: str,
    raw_path: str,
    headers: dict[str, str],
    body: bytes = b"",
) -> tuple[int, str, bytes]:
    parsed = urlparse(raw_path)
    path = parsed.path
    if method not in ("GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS"):
        raise WebError(f"unsupported method: {method}")
    if method == "OPTIONS":
        return HTTPStatus.NO_CONTENT, "text/plain", b""
    if method in ("GET", "HEAD"):
        if path.startswith("/uidl"):
            rel = path[len("/uidl") :]
            return _serve_static_uidl(state, rel)
        uidl_ok = state.runtime == "uidl" and _uidl_available(state.root)
        if uidl_ok and (path == "/" or path.startswith("/assets/")):
            return _serve_static_uidl(state, "index.html" if path == "/" else path)
        if path == "/":
            return HTTPStatus.OK, "text/html; charset=utf-8", index_html().encode()
    _require_token(state, headers)
    if method in ("GET", "HEAD"):
        if path == "/api/overview":
            return _json(workspace_overview(state))
        if path == "/api/health":
            return _json(workspace_health(state))
        if path == "/api/clients":
            return _json(list_clients(state))
        if path == "/api/plans":
            query_params = parse_qs(parsed.query)
            project_filter = query_params.get("project", [None])[0]
            return _json(list_plans(state, project_filter))
        if path == "/api/settings":
            return _json(workspace_settings(state))
        if path == "/api/projects":
            return _json({"projects": [_project_to_dict(project) for project in load_projects(state)]})
        prefix = "/api/projects/"
        suffix = "/context"
        if path.startswith(prefix) and path.endswith(suffix):
            key = unquote(path[len(prefix) : -len(suffix)])
            return _json(project_context(state, key))
        board_suffix = "/board"
        if path.startswith(prefix) and path.endswith(board_suffix):
            key = unquote(path[len(prefix) : -len(board_suffix)])
            return _json(project_board(state, key))
        commits_suffix = "/commits"
        if path.startswith(prefix) and path.endswith(commits_suffix):
            key = unquote(path[len(prefix) : -len(commits_suffix)])
            summary = _project_summary(state, key)
            return _json({"project": _project_to_dict(summary), "commits": get_project_commits(state, key)})
        search_suffix = "/search"
        if path.startswith(prefix) and path.endswith(search_suffix):
            key = unquote(path[len(prefix) : -len(search_suffix)])
            query_params = parse_qs(parsed.query)
            return _json(search_project_tasks(state, key, query_params))
        task_marker = "/tasks/"
        if path.startswith(prefix) and task_marker in path[len(prefix) :]:
            tail = path[len(prefix) :]
            key, task_id = tail.split(task_marker, 1)
            return _json(task_detail(state, unquote(key), unquote(task_id)))
        activity_suffix = "/activity"
        if path.startswith(prefix) and path.endswith(activity_suffix):
            key = unquote(path[len(prefix) : -len(activity_suffix)])
            query_params = parse_qs(parsed.query)
            month = query_params.get("month", [None])[0]
            return _json(get_project_activity(state, key, month=month))
        runs_suffix = "/runs"
        if path.startswith(prefix) and path.endswith(runs_suffix):
            key = unquote(path[len(prefix) : -len(runs_suffix)])
            return _json(project_runs(state, key))
    elif method == "POST":
        prefix = "/api/projects/"
        clock_suffix = "/clock"
        if path.startswith(prefix) and path.endswith(clock_suffix):
            key = unquote(path[len(prefix) : -len(clock_suffix)])
            payload = _parse_json_body(body)
            return handle_project_clock(state, key, payload)
        suffix = "/tasks"
        if path.startswith(prefix) and path.endswith(suffix):
            key = unquote(path[len(prefix) : -len(suffix)])
            payload = _parse_json_body(body)
            return create_task(state, key, payload)
        move_suffix = "/move"
        task_marker = "/tasks/"
        if path.startswith(prefix) and path.endswith(move_suffix):
            mid = path[len(prefix) : -len(move_suffix)]
            if task_marker in mid:
                key, task_id = mid.split(task_marker, 1)
                payload = _parse_json_body(body)
                return move_task(state, unquote(key), unquote(task_id), payload, headers)
        git_links_suffix = "/git-links"
        if path.startswith(prefix) and path.endswith(git_links_suffix):
            mid = path[len(prefix) : -len(git_links_suffix)]
            if task_marker in mid:
                key, task_id = mid.split(task_marker, 1)
                payload = _parse_json_body(body)
                return add_task_git_link(state, unquote(key), unquote(task_id), payload, headers)
    elif method == "PUT":
        prefix = "/api/projects/"
        task_marker = "/tasks/"
        if path.startswith(prefix) and task_marker in path[len(prefix) :]:
            tail = path[len(prefix) :]
            key, task_id = tail.split(task_marker, 1)
            payload = _parse_json_body(body)
            return update_task(state, unquote(key), unquote(task_id), payload, headers)
    elif method == "DELETE":
        prefix = "/api/projects/"
        git_links_marker = "/git-links/"
        task_marker = "/tasks/"
        if path.startswith(prefix) and git_links_marker in path[len(prefix) :]:
            tail = path[len(prefix) :]
            task_part, sha = tail.rsplit(git_links_marker, 1)
            if task_marker in task_part:
                key, task_id = task_part.split(task_marker, 1)
                payload = _parse_json_body(body)
                return remove_task_git_link(state, unquote(key), unquote(task_id), unquote(sha), payload, headers)
    raise NotFound("route not found")


def load_projects(state: WorkspaceWebState) -> list[ProjectSummary]:
    rows = _registry_rows(state.context / "registry.tsv")
    projects = []
    for row in rows:
        key = row.get("key", "")
        if not PROJECT_RE.fullmatch(key):
            raise WebError("invalid project key in registry")
        projects.append(
            ProjectSummary(
                key=key,
                client=row.get("client", "-"),
                group=row.get("group", "-"),
                folder=row.get("folder", "-"),
                context_scope=row.get("context_scope", "client") or "client",
                security_profile=row.get("security_profile", "-"),
                description=row.get("description", ""),
            )
        )
    return projects


def project_context(state: WorkspaceWebState, project: str) -> dict[str, object]:
    if not PROJECT_RE.fullmatch(project):
        raise NotFound("project not found")
    projects = {item.key: item for item in load_projects(state)}
    summary = projects.get(project)
    if summary is None:
        raise NotFound("project not found")
    files = []
    for name in ("project", "active", "decisions"):
        path = _contained(state.context, f"memory/projects/{project}/{name}.md")
        if path.exists():
            files.append(_file_payload(state.root, path))
    for run in sorted(_contained(state.context, f"runs/{project}").glob("*/handoff.md")) if _contained(state.context, f"runs/{project}").exists() else []:
        files.append(_file_payload(state.root, run))
    return {"project": _project_to_dict(summary), "files": files}


def project_board(state: WorkspaceWebState, project: str) -> dict[str, object]:
    summary = _project_summary(state, project)
    tasks, legacy = _load_context_tasks(state)
    project_tasks = [task for task in tasks if task.project == project]
    columns = {status: [] for status in ["backlog", "ready", "in_progress", "review", "done"]}
    for task in sorted(project_tasks, key=lambda item: (item.status, item.updated_at, item.id)):
        columns[task.status].append(_task_card(task))
    project_legacy = [candidate.__dict__ for candidate in legacy if candidate.project == project]
    wip_warnings = []
    for col, limit in DEFAULT_WIP_LIMITS.items():
        count = len(columns.get(col, []))
        if count > limit:
            wip_warnings.append(f"Column '{col}' has {count} tasks, exceeding limit of {limit}")
    return {
        "project": _project_to_dict(summary),
        "source": {"id": "context", "root": state.context.relative_to(state.root).as_posix(), "writable": True},
        "columns": columns,
        "legacy_candidates": project_legacy,
        "wip_limits": DEFAULT_WIP_LIMITS,
        "wip_warnings": wip_warnings,
    }


def _param_list(query_params: dict[str, list[str]], *keys: str) -> list[str]:
    result = []
    for key in keys:
        for val in query_params.get(key, []):
            for part in val.split(","):
                cleaned = part.strip()
                if cleaned:
                    result.append(cleaned)
    return result


def search_project_tasks(
    state: WorkspaceWebState,
    project: str,
    query_params: dict[str, list[str]],
) -> dict[str, object]:
    summary = _project_summary(state, project)
    tasks, _legacy = _load_context_tasks(state)
    project_tasks = [task for task in tasks if task.project == project]

    q = (query_params.get("q", [""])[0]).strip().lower()
    status_filter = _param_list(query_params, "status")
    priority_filter = _param_list(query_params, "priority")
    owner_filter = _param_list(query_params, "owner")
    label_filter = _param_list(query_params, "label", "tag")
    source_filter = _param_list(query_params, "source")
    blocked_vals = _param_list(query_params, "blocked")
    blocked_param = blocked_vals[0].lower() if blocked_vals else None

    results = []
    filtered_tasks = []

    for task in sorted(project_tasks, key=lambda item: (item.status, item.updated_at, item.id)):
        if status_filter and task.status not in status_filter:
            continue
        if priority_filter and task.priority not in priority_filter:
            continue
        if owner_filter and task.owner not in owner_filter:
            continue
        if label_filter and not any(lbl in task.labels for lbl in label_filter):
            continue
        if source_filter and task.source not in source_filter:
            continue
        if blocked_param in ("true", "1", "yes") and not task.blocked:
            continue
        if blocked_param in ("false", "0", "no") and task.blocked:
            continue

        matches = []
        snippet = ""

        if q:
            if q in task.id.lower():
                matches.append("id")
            if q in task.title.lower():
                matches.append("title")
                if not snippet:
                    snippet = task.title
            if q in task.owner.lower():
                matches.append("owner")
            if any(q in lbl.lower() for lbl in task.labels):
                matches.append("labels")
            for crit in task.acceptance_criteria:
                if q in crit.lower():
                    matches.append("acceptance_criteria")
                    if not snippet:
                        snippet = crit
            if task.blocked and q in task.blocked_reason.lower():
                matches.append("blocked_reason")
                if not snippet:
                    snippet = task.blocked_reason
            if task.body and q in task.body.lower():
                matches.append("body")
                if not snippet:
                    for line in task.body.splitlines():
                        if q in line.lower():
                            snippet = line.strip()
                            break
                    if not snippet:
                        idx = task.body.lower().find(q)
                        start = max(0, idx - 40)
                        end = min(len(task.body), idx + len(q) + 40)
                        snippet = task.body[start:end].strip()

            if not matches:
                continue

        filtered_tasks.append(task)
        results.append(
            {
                "task": _task_card(task),
                "matches": matches,
                "snippet": snippet,
            }
        )

    by_status = {s: 0 for s in ["backlog", "ready", "in_progress", "review", "done"]}
    for t in filtered_tasks:
        if t.status in by_status:
            by_status[t.status] += 1
        else:
            by_status[t.status] = 1

    by_priority = {p: 0 for p in ["low", "normal", "high", "urgent"]}
    for t in filtered_tasks:
        if t.priority in by_priority:
            by_priority[t.priority] += 1
        else:
            by_priority[t.priority] = 1

    by_owner = dict(Counter(t.owner for t in filtered_tasks))
    by_label = dict(Counter(lbl for t in filtered_tasks for lbl in t.labels))
    blocked_count = sum(1 for t in filtered_tasks if t.blocked)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "project": _project_to_dict(summary),
        "total": len(results),
        "results": results,
        "counts": {
            "by_status": by_status,
            "by_priority": by_priority,
            "by_owner": by_owner,
            "by_label": by_label,
            "blocked": blocked_count,
        },
        "freshness": {
            "scanned_at": now,
            "scanned_tasks": len(project_tasks),
        },
    }


def task_detail(state: WorkspaceWebState, project: str, task_id: str) -> dict[str, object]:
    summary = _project_summary(state, project)
    if not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise NotFound("task not found")
    tasks, _legacy = _load_context_tasks(state)
    matches = [task for task in tasks if task.project == project and task.id == task_id]
    if not matches:
        raise NotFound("task not found")
    task = matches[0]
    return {
        "project": _project_to_dict(summary),
        "task": _task_detail_payload(state, task),
    }


def create_task(state: WorkspaceWebState, project: str, payload: dict[str, object]) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project)
    if not isinstance(payload, dict):
        raise WebError("request body must be a JSON object")

    title = payload.get("title")
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise WebError("title is required")

    task_id = payload.get("id")
    if task_id is None or task_id == "":
        task_id = f"task_{secrets.token_hex(6)}"
    elif not isinstance(task_id, str) or not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise WebError("invalid task id")

    status = payload.get("status", "backlog")
    if not isinstance(status, str) or status not in ("backlog", "ready", "in_progress", "review", "done"):
        raise WebError("invalid task status")

    priority = payload.get("priority", "normal")
    if not isinstance(priority, str) or priority not in ("low", "normal", "high", "urgent"):
        raise WebError("invalid task priority")

    owner = payload.get("owner", "unassigned")
    if not isinstance(owner, str):
        raise WebError("owner must be a string")

    body = payload.get("body", "")
    if not isinstance(body, str):
        raise WebError("body must be a string")

    blocked = payload.get("blocked", False)
    if not isinstance(blocked, bool):
        raise WebError("blocked must be a boolean")

    blocked_reason = payload.get("blocked_reason", "")
    if not isinstance(blocked_reason, str):
        raise WebError("blocked_reason must be a string")

    if blocked and not blocked_reason.strip():
        raise WebError("blocked tasks require blocked_reason")
    if not blocked and blocked_reason.strip():
        raise WebError("blocked_reason requires blocked=true")

    labels = _extract_string_list(payload, "labels")
    acceptance_criteria = _extract_string_list(payload, "acceptance_criteria")
    related_plans = _extract_string_list(payload, "related_plans")
    related_runs = _extract_string_list(payload, "related_runs")
    git_links = _extract_git_links(payload.get("git_links", []))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = TaskRecord(
        source="context",
        path=f"tasks/{project}/{task_id}.md",
        revision="new",
        schema_version=1,
        id=task_id,
        project=project,
        title=title.strip(),
        status=status,
        priority=priority,
        owner=owner,
        labels=tuple(labels),
        acceptance_criteria=tuple(acceptance_criteria),
        related_plans=tuple(related_plans),
        related_runs=tuple(related_runs),
        git_links=tuple(git_links),
        blocked=blocked,
        blocked_reason=blocked_reason.strip() if blocked else "",
        created_at=now,
        updated_at=now,
        body=body,
    )

    source = load_source("context", state.context, writable=True)
    try:
        saved = write_task_document(source, project, record)
    except TaskConflict as error:
        raise Conflict(str(error)) from error
    except TaskError as error:
        raise WebError(str(error)) from error

    return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, saved)}, status=HTTPStatus.CREATED)


def update_task(
    state: WorkspaceWebState,
    project: str,
    task_id: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project)
    if not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise NotFound("task not found")
    if not isinstance(payload, dict):
        raise WebError("request body must be a JSON object")

    tasks, _legacy = _load_context_tasks(state)
    matches = [t for t in tasks if t.project == project and t.id == task_id]
    if not matches:
        raise NotFound("task not found")
    current = matches[0]

    expected_rev = headers.get("if-match") or payload.get("expected_revision")
    if expected_rev is not None:
        expected_rev = str(expected_rev)
        if expected_rev != current.revision:
            raise Conflict(f"revision mismatch: expected '{expected_rev}', found '{current.revision}'")
    else:
        expected_rev = current.revision

    title = payload.get("title", current.title)
    if not isinstance(title, str) or not title.strip() or "\n" in title or "\r" in title:
        raise WebError("title is required")

    status = payload.get("status", current.status)
    if not isinstance(status, str) or status not in ("backlog", "ready", "in_progress", "review", "done"):
        raise WebError("invalid task status")

    priority = payload.get("priority", current.priority)
    if not isinstance(priority, str) or priority not in ("low", "normal", "high", "urgent"):
        raise WebError("invalid task priority")

    owner = payload.get("owner", current.owner)
    if not isinstance(owner, str):
        raise WebError("owner must be a string")

    body = payload.get("body", current.body)
    if not isinstance(body, str):
        raise WebError("body must be a string")

    blocked = payload.get("blocked", current.blocked)
    if not isinstance(blocked, bool):
        raise WebError("blocked must be a boolean")

    blocked_reason = payload.get("blocked_reason", current.blocked_reason)
    if not isinstance(blocked_reason, str):
        raise WebError("blocked_reason must be a string")

    if blocked and not blocked_reason.strip():
        raise WebError("blocked tasks require blocked_reason")
    if not blocked and blocked_reason.strip():
        raise WebError("blocked_reason requires blocked=true")

    labels = _extract_string_list(payload, "labels") if "labels" in payload else list(current.labels)
    acceptance_criteria = _extract_string_list(payload, "acceptance_criteria") if "acceptance_criteria" in payload else list(current.acceptance_criteria)
    related_plans = _extract_string_list(payload, "related_plans") if "related_plans" in payload else list(current.related_plans)
    related_runs = _extract_string_list(payload, "related_runs") if "related_runs" in payload else list(current.related_runs)
    git_links = _extract_git_links(payload["git_links"]) if "git_links" in payload else list(current.git_links)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = TaskRecord(
        source=current.source,
        path=current.path,
        revision=current.revision,
        schema_version=current.schema_version,
        id=current.id,
        project=current.project,
        title=title.strip(),
        status=status,
        priority=priority,
        owner=owner,
        labels=tuple(labels),
        acceptance_criteria=tuple(acceptance_criteria),
        related_plans=tuple(related_plans),
        related_runs=tuple(related_runs),
        git_links=tuple(git_links),
        blocked=blocked,
        blocked_reason=blocked_reason.strip() if blocked else "",
        created_at=current.created_at,
        updated_at=now,
        body=body,
    )

    source = load_source("context", state.context, writable=True)
    try:
        saved = write_task_document(source, project, updated, expected_revision=current.revision)
    except TaskConflict as error:
        raise Conflict(str(error)) from error
    except TaskError as error:
        raise WebError(str(error)) from error

    return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, saved)}, status=HTTPStatus.OK)


def move_task(
    state: WorkspaceWebState,
    project: str,
    task_id: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project)
    if not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise NotFound("task not found")
    if not isinstance(payload, dict):
        raise WebError("request body must be a JSON object")

    tasks, _legacy = _load_context_tasks(state)
    matches = [t for t in tasks if t.project == project and t.id == task_id]
    if not matches:
        raise NotFound("task not found")
    current = matches[0]

    target_status = payload.get("target_status")
    if not isinstance(target_status, str) or target_status not in ("backlog", "ready", "in_progress", "review", "done"):
        raise WebError("valid target_status is required")

    expected_rev = headers.get("if-match") or payload.get("expected_revision")
    if expected_rev is None or not str(expected_rev).strip():
        raise WebError("expected_revision is required for board movement")
    if str(expected_rev) != current.revision:
        raise Conflict(f"revision mismatch: expected '{expected_rev}', found '{current.revision}'")

    blocked = payload.get("blocked", current.blocked)
    if not isinstance(blocked, bool):
        raise WebError("blocked must be a boolean")

    if "blocked" in payload and not blocked and "blocked_reason" not in payload:
        blocked_reason = ""
    else:
        blocked_reason = payload.get("blocked_reason", current.blocked_reason)
    if not isinstance(blocked_reason, str):
        raise WebError("blocked_reason must be a string")

    if blocked and not blocked_reason.strip():
        raise WebError("blocked tasks require blocked_reason")
    if not blocked and blocked_reason.strip():
        raise WebError("blocked_reason requires blocked=true")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = TaskRecord(
        source=current.source,
        path=current.path,
        revision=current.revision,
        schema_version=current.schema_version,
        id=current.id,
        project=current.project,
        title=current.title,
        status=target_status,
        priority=current.priority,
        owner=current.owner,
        labels=current.labels,
        acceptance_criteria=current.acceptance_criteria,
        related_plans=current.related_plans,
        related_runs=current.related_runs,
        git_links=current.git_links,
        blocked=blocked,
        blocked_reason=blocked_reason.strip() if blocked else "",
        created_at=current.created_at,
        updated_at=now,
        body=current.body,
    )

    source = load_source("context", state.context, writable=True)
    try:
        saved = write_task_document(source, project, updated, expected_revision=current.revision)
    except TaskConflict as error:
        raise Conflict(str(error)) from error
    except TaskError as error:
        raise WebError(str(error)) from error

    wip_warning = None
    limit = DEFAULT_WIP_LIMITS.get(target_status)
    if limit is not None:
        target_count = len([t for t in tasks if t.project == project and t.status == target_status and t.id != task_id]) + 1
        if target_count > limit:
            wip_warning = f"Column '{target_status}' has {target_count} tasks (limit: {limit})"

    return _json(
        {
            "project": _project_to_dict(summary),
            "task": _task_detail_payload(state, saved),
            "target_status": target_status,
            "wip_warning": wip_warning,
        },
        status=HTTPStatus.OK,
    )


def _calculate_merged_seconds(intervals: list[tuple[int, int]]) -> int:
    seconds = 0
    start = end = None
    for first, last in sorted(intervals):
        if last < first:
            continue
        if start is None:
            start, end = first, last
        elif first <= end:
            end = max(end, last)
        else:
            seconds += end - start
            start, end = first, last
    if start is not None:
        seconds += end - start
    return seconds


def _get_usage_data(
    state: WorkspaceWebState, summary: ProjectSummary, month: str
) -> dict[str, object]:
    source_dir = None
    config_file = state.root / "workspace.conf"
    if config_file.is_file():
        for line in config_file.read_text().splitlines():
            s = line.strip()
            if s.startswith("usage_source") and "=" in s:
                val = s.split("=", 1)[1].strip()
                if val:
                    source_dir = Path(os.path.expanduser(val))
    if not source_dir:
        default_dir = Path(os.path.expanduser("~/.agent-ops"))
        if default_dir.is_dir():
            source_dir = default_dir

    if not source_dir or not source_dir.is_dir():
        return {
            "available": False,
            "source": None,
            "total_sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "by_tool": {},
            "days": [],
        }

    usage_file = source_dir / "ops" / "usage" / f"{month}.jsonl"
    if not usage_file.is_file():
        return {
            "available": True,
            "source": str(source_dir),
            "total_sessions": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "by_tool": {},
            "days": [],
        }

    project_folder = str((state.root / summary.folder).resolve()) if summary.folder and summary.folder != "-" else ""
    total_sessions = 0
    total_input = 0
    total_output = 0
    by_tool: dict[str, int] = {}
    day_stats: dict[str, dict[str, int]] = {}

    try:
        for line in usage_file.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            rec_proj = rec.get("projectKey")
            rec_root = rec.get("projectRoot")
            matches = False
            if rec_proj and rec_proj == summary.key:
                matches = True
            elif rec_root and project_folder:
                res_root = os.path.realpath(os.path.expanduser(rec_root))
                if res_root == project_folder or project_folder.startswith(res_root + "/"):
                    matches = True
            if not matches:
                continue

            total_sessions += 1
            tool = rec.get("tool") or "unknown"
            by_tool[tool] = by_tool.get(tool, 0) + 1

            tokens = rec.get("tokens") or {}
            inp = int(tokens.get("input") or 0)
            out = int(tokens.get("output") or 0)
            total_input += inp
            total_output += out

            day = (rec.get("start") or "")[:10]
            if day:
                st = day_stats.setdefault(day, {"sessions": 0, "input": 0, "output": 0})
                st["sessions"] += 1
                st["input"] += inp
                st["output"] += out
    except (json.JSONDecodeError, OSError):
        pass

    days_list = [
        {"day": d, "sessions": day_stats[d]["sessions"], "input_tokens": day_stats[d]["input"], "output_tokens": day_stats[d]["output"]}
        for d in sorted(day_stats.keys())
    ]

    return {
        "available": True,
        "source": str(source_dir),
        "total_sessions": total_sessions,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "by_tool": by_tool,
        "days": days_list,
    }


def get_project_activity(
    state: WorkspaceWebState, project: str, month: str | None = None
) -> dict[str, object]:
    summary = _project_summary(state, project)
    if not month:
        month = datetime.now().strftime("%Y-%m")
    elif not re.fullmatch(r"^[0-9]{4}-(0[1-9]|1[0-2])$", month):
        raise WebError("invalid month format (expected YYYY-MM)")

    works_dir = state.context / "works"

    active_clocks: dict[str, object] = {"human": None, "agent": None}
    if works_dir.is_dir():
        for item in works_dir.glob(".open-*.json"):
            if item.is_file() and not item.is_symlink():
                try:
                    data = json.loads(item.read_text())
                    if data.get("project") == project:
                        kind = data.get("kind", "human" if "human" in item.name else "agent")
                        active_clocks[kind] = {
                            "actor": data.get("actor"),
                            "tool": data.get("tool"),
                            "start": data.get("start"),
                            "note": data.get("note"),
                        }
                except (json.JSONDecodeError, OSError):
                    pass

    human_file = works_dir / "human" / project / f"{month}.jsonl"
    human_groups: dict[tuple[str, str], list[tuple[int, int]]] = {}
    human_session_count: dict[str, int] = {}
    if human_file.is_file() and not human_file.is_symlink():
        try:
            for line in human_file.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                day = rec.get("start", "")[:10]
                actor = rec.get("actor", "legacy")
                start_ts = int(rec.get("start_ts", 0))
                end_ts = int(rec.get("end_ts", 0))
                human_groups.setdefault((day, actor), []).append((start_ts, end_ts))
                human_session_count[day] = human_session_count.get(day, 0) + 1
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    agent_file = works_dir / "agent" / project / f"{month}.jsonl"
    agent_groups: dict[tuple[str, str], list[tuple[int, int]]] = {}
    agent_session_count: dict[str, int] = {}
    if agent_file.is_file() and not agent_file.is_symlink():
        try:
            for line in agent_file.read_text().splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                day = rec.get("start", "")[:10]
                actor = "elapsed"
                start_ts = int(rec.get("start_ts", 0))
                end_ts = int(rec.get("end_ts", 0))
                agent_groups.setdefault((day, actor), []).append((start_ts, end_ts))
                agent_session_count[day] = agent_session_count.get(day, 0) + 1
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    human_days: dict[str, float] = {}
    for (day, _), intervals in human_groups.items():
        human_days[day] = human_days.get(day, 0.0) + (_calculate_merged_seconds(intervals) / 3600.0)

    agent_days: dict[str, float] = {}
    for (day, _), intervals in agent_groups.items():
        agent_days[day] = agent_days.get(day, 0.0) + (_calculate_merged_seconds(intervals) / 3600.0)

    all_days = sorted(set(human_days.keys()) | set(agent_days.keys()))
    days_breakdown = []
    for d in all_days:
        days_breakdown.append(
            {
                "day": d,
                "human_hours": round(human_days.get(d, 0.0), 2),
                "agent_hours": round(agent_days.get(d, 0.0), 2),
                "human_sessions": human_session_count.get(d, 0),
                "agent_sessions": agent_session_count.get(d, 0),
            }
        )

    usage_info = _get_usage_data(state, summary, month)

    return {
        "project": _project_to_dict(summary),
        "month": month,
        "active_clocks": active_clocks,
        "hours": {
            "human_total": round(sum(human_days.values()), 2),
            "agent_total": round(sum(agent_days.values()), 2),
            "days": days_breakdown,
        },
        "usage": usage_info,
    }


def handle_project_clock(
    state: WorkspaceWebState,
    project_key: str,
    payload: dict[str, object],
) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project_key)
    action = str(payload.get("action") or "").strip().lower()
    kind = str(payload.get("kind") or "human").strip().lower()
    if kind not in ("human", "agent"):
        raise WebError("kind must be 'human' or 'agent'")
    if action not in ("in", "out"):
        raise WebError("action must be 'in' or 'out'")

    note = str(payload.get("note") or "").strip()
    works_dir = state.context / "works"
    works_dir.mkdir(parents=True, exist_ok=True)

    actor = str(payload.get("actor") or "").strip()
    if not actor:
        try:
            actor = subprocess.check_output(
                ["git", "config", "--get", "user.email"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            actor = os.environ.get("USER", "web-user")
        if not actor:
            actor = "web-user"
    actor_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", actor).strip("-") or "web-user"

    tool = str(payload.get("tool") or ("web-control" if kind == "human" else "agent")).strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", tool):
        raise WebError("invalid clock tool")
    session = str(payload.get("session") or "default").strip()
    session_slug = re.sub(r"[^a-zA-Z0-9_-]", "-", session).strip("-") or "default"

    if kind == "human":
        open_filename = works_dir / f".open-human-{actor_slug}.json"
    else:
        open_filename = works_dir / f".open-agent-{actor_slug}-{tool}-{session_slug}.json"

    if action == "in":
        if open_filename.exists():
            try:
                rec = json.loads(open_filename.read_text())
                active_proj = rec.get("project", "")
                raise Conflict(f"already clocked in on project '{active_proj}' since {rec.get('start')}")
            except (json.JSONDecodeError, OSError):
                pass
        try:
            ws_state.clock_in(open_filename, summary.key, actor, tool, note)
        except Exception as exc:
            raise WebError(f"failed to clock in: {exc}")

        return _json({
            "ok": True,
            "action": "in",
            "kind": kind,
            "project": summary.key,
            "actor": actor,
            "tool": tool,
            "message": f"Clocked in {kind} on {summary.key}",
        })
    else:
        target_file = open_filename
        if not target_file.is_file() or target_file.is_symlink():
            raise NotFound(f"not currently clocked in for {kind} as '{actor}' on project '{summary.key}'")
        try:
            record = json.loads(target_file.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise WebError("cannot read clock session") from exc
        if record.get("project") != summary.key:
            raise Conflict("clock session belongs to another project")

        try:
            ws_state.clock_out(target_file, note)
        except Exception as exc:
            raise WebError(f"failed to clock out: {exc}")

        return _json({
            "ok": True,
            "action": "out",
            "kind": kind,
            "project": summary.key,
            "message": f"Clocked out {kind} on {summary.key}; session recorded",
        })



def get_project_commits(state: WorkspaceWebState, project: str, limit: int = 20) -> list[dict[str, str]]:
    summary = _project_summary(state, project)
    if not summary.folder or summary.folder == "-":
        return []
    repo_path = (state.root / summary.folder).resolve()
    if not repo_path.exists() or not (repo_path / ".git").exists():
        return []

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "log",
                f"-n{max(1, min(limit, 100))}",
                "--format=%H%x09%h%x09%s%x09%an%x09%cI",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
    except Exception:
        return []

    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 4)
        if len(parts) == 5:
            commits.append(
                {
                    "sha": parts[0],
                    "short_sha": parts[1],
                    "subject": parts[2],
                    "author": parts[3],
                    "date": parts[4],
                }
            )
    return commits


def _verify_commit_sha(repo_path: Path, sha: str) -> str:
    cleaned = sha.strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", cleaned):
        raise WebError("invalid commit sha format")
    if not repo_path.exists() or not (repo_path / ".git").exists():
        raise WebError("project repository does not exist on local disk")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--verify", f"{cleaned}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise WebError(f"commit '{cleaned}' not found in project repository")
        return result.stdout.strip()
    except WebError:
        raise
    except Exception as error:
        raise WebError(f"error verifying commit sha: {error}") from error


def add_task_git_link(
    state: WorkspaceWebState,
    project: str,
    task_id: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project)
    if not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise NotFound("task not found")
    if not isinstance(payload, dict):
        raise WebError("request body must be a JSON object")

    raw_sha = payload.get("sha")
    if not isinstance(raw_sha, str) or not raw_sha.strip():
        raise WebError("sha is required")

    repo_path = (state.root / summary.folder).resolve()
    full_sha = _verify_commit_sha(repo_path, raw_sha)

    tasks, _legacy = _load_context_tasks(state)
    matches = [t for t in tasks if t.project == project and t.id == task_id]
    if not matches:
        raise NotFound("task not found")
    current = matches[0]

    expected_rev = headers.get("if-match") or payload.get("expected_revision")
    if expected_rev is not None and str(expected_rev) != current.revision:
        raise Conflict(f"revision mismatch: expected '{expected_rev}', found '{current.revision}'")

    existing_shas = {link.sha for link in current.git_links}
    if full_sha in existing_shas:
        return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, current)}, status=HTTPStatus.OK)

    new_link = GitLink(repository=project, sha=full_sha)
    updated_links = (*current.git_links, new_link)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = TaskRecord(
        source=current.source,
        path=current.path,
        revision=current.revision,
        schema_version=current.schema_version,
        id=current.id,
        project=current.project,
        title=current.title,
        status=current.status,
        priority=current.priority,
        owner=current.owner,
        labels=current.labels,
        acceptance_criteria=current.acceptance_criteria,
        related_plans=current.related_plans,
        related_runs=current.related_runs,
        git_links=updated_links,
        blocked=current.blocked,
        blocked_reason=current.blocked_reason,
        created_at=current.created_at,
        updated_at=now,
        body=current.body,
    )

    source = load_source("context", state.context, writable=True)
    try:
        saved = write_task_document(source, project, updated, expected_revision=current.revision)
    except TaskConflict as error:
        raise Conflict(str(error)) from error
    except TaskError as error:
        raise WebError(str(error)) from error

    return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, saved)}, status=HTTPStatus.OK)


def remove_task_git_link(
    state: WorkspaceWebState,
    project: str,
    task_id: str,
    sha: str,
    payload: dict[str, object],
    headers: dict[str, str],
) -> tuple[int, str, bytes]:
    summary = _project_summary(state, project)
    if not re.fullmatch(r"task_[a-z0-9][a-z0-9_-]*", task_id):
        raise NotFound("task not found")

    tasks, _legacy = _load_context_tasks(state)
    matches = [t for t in tasks if t.project == project and t.id == task_id]
    if not matches:
        raise NotFound("task not found")
    current = matches[0]

    expected_rev = headers.get("if-match") or payload.get("expected_revision")
    if expected_rev is not None and str(expected_rev) != current.revision:
        raise Conflict(f"revision mismatch: expected '{expected_rev}', found '{current.revision}'")

    cleaned_sha = sha.strip()
    updated_links = tuple(link for link in current.git_links if not (link.sha == cleaned_sha or link.sha.startswith(cleaned_sha)))
    if len(updated_links) == len(current.git_links):
        return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, current)}, status=HTTPStatus.OK)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    updated = TaskRecord(
        source=current.source,
        path=current.path,
        revision=current.revision,
        schema_version=current.schema_version,
        id=current.id,
        project=current.project,
        title=current.title,
        status=current.status,
        priority=current.priority,
        owner=current.owner,
        labels=current.labels,
        acceptance_criteria=current.acceptance_criteria,
        related_plans=current.related_plans,
        related_runs=current.related_runs,
        git_links=updated_links,
        blocked=current.blocked,
        blocked_reason=current.blocked_reason,
        created_at=current.created_at,
        updated_at=now,
        body=current.body,
    )

    source = load_source("context", state.context, writable=True)
    try:
        saved = write_task_document(source, project, updated, expected_revision=current.revision)
    except TaskConflict as error:
        raise Conflict(str(error)) from error
    except TaskError as error:
        raise WebError(str(error)) from error

    return _json({"project": _project_to_dict(summary), "task": _task_detail_payload(state, saved)}, status=HTTPStatus.OK)


def _parse_conf(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _first_heading(text: str, fallback: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or fallback
    return fallback


def list_clients(state: WorkspaceWebState) -> dict[str, object]:
    projects = load_projects(state)
    grouped: dict[str, list[dict[str, str]]] = {}
    for project in projects:
        grouped.setdefault(project.client or "(none)", []).append(_project_to_dict(project))
    clients_dir = state.context / "clients"
    keys = set(grouped)
    if clients_dir.is_dir():
        keys.update(path.name for path in clients_dir.iterdir() if path.is_dir() and not path.name.startswith("."))
    clients = []
    for key in sorted(keys):
        summary = ""
        client_md = clients_dir / key / "client.md"
        if client_md.is_file():
            text = client_md.read_text(encoding="utf-8", errors="replace")
            summary = text[:600]
        clients.append({"key": key, "summary": summary, "projects": grouped.get(key, [])})
    return {"clients": clients}


def list_plans(state: WorkspaceWebState, project: str | None = None) -> dict[str, object]:
    if project and not PROJECT_RE.fullmatch(project):
        raise NotFound("project not found")
    runs_root = state.context / "runs"
    plans: list[dict[str, object]] = []
    if not runs_root.is_dir():
        return {"plans": plans}
    for proj_dir in sorted(runs_root.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        if project and proj_dir.name != project:
            continue
        for run_dir in sorted(proj_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            plan = run_dir / "plan.md"
            if not plan.is_file():
                continue
            text = plan.read_text(encoding="utf-8", errors="replace")
            plans.append(
                {
                    "project": proj_dir.name,
                    "run": run_dir.name,
                    "path": str(plan.relative_to(state.context)),
                    "title": _first_heading(text, run_dir.name),
                    "body": text[:8000],
                    "updated": datetime.fromtimestamp(plan.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return {"plans": plans}


def workspace_settings(state: WorkspaceWebState) -> dict[str, object]:
    conf = _parse_conf(state.root / "workspace.conf")
    allowed = ("packs", "context_dir", "context_remote", "default_project")
    identity = {key: conf.get(key, "") for key in allowed}
    return {
        "identity": identity,
        "root_name": state.root.name,
        "context_local": not bool(_git_origin(state.context)),
        "runtime": "uidl" if state.runtime == "uidl" and _uidl_available(state.root) else "vanilla",
        "loopback": True,
    }


def _git_origin(path: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return completed.stdout.strip()


def workspace_overview(state: WorkspaceWebState) -> dict[str, object]:
    projects = load_projects(state)
    grouped: dict[str, list[dict[str, str]]] = {}
    for project in projects:
        grouped.setdefault(project.client or "(none)", []).append(_project_to_dict(project))
    tasks, _errors = _load_context_tasks(state)
    blocked = sum(1 for task in tasks if task.blocked)
    return {
        "context_local": not bool(_git_origin(state.context)),
        "counts": {
            "projects": len(projects),
            "clients": len(grouped),
            "blocked_tasks": blocked,
            "tasks": len(tasks),
        },
        "clients": [
            {"key": client, "projects": items}
            for client, items in sorted(grouped.items())
        ],
    }


def workspace_health(state: WorkspaceWebState) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    registry = state.context / "registry.tsv"
    checks.append(
        {
            "id": "registry",
            "ok": registry.is_file(),
            "detail": "context/registry.tsv" if registry.is_file() else "registry missing",
        }
    )
    origin = _git_origin(state.context)
    checks.append(
        {
            "id": "context_remote",
            "ok": True,
            "detail": origin or "private-local (no remote)",
        }
    )
    missing: list[str] = []
    for project in load_projects(state):
        folder = (state.root / project.folder).resolve()
        if not folder.exists():
            missing.append(project.key)
    checks.append(
        {
            "id": "checkouts",
            "ok": not missing,
            "detail": "all cloned" if not missing else "uncloned: " + ", ".join(missing),
        }
    )
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def project_runs(state: WorkspaceWebState, project: str) -> dict[str, object]:
    summary = _project_summary(state, project)
    root = state.context / "runs" / project
    runs: list[dict[str, object]] = []
    if root.is_dir():
        for path in sorted(root.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_dir() or path.name.startswith("."):
                continue
            handoff = path / "handoff.md"
            snippet = ""
            if handoff.is_file():
                snippet = handoff.read_text(encoding="utf-8", errors="replace")[:480]
            runs.append(
                {
                    "id": path.name,
                    "path": str(path.relative_to(state.context)),
                    "handoff": snippet,
                    "updated": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return {"project": _project_to_dict(summary), "runs": runs}


def index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Workspace Control</title>
  <style>
    :root {
      --bg-base: #0d1117;
      --bg-surface: #161b22;
      --bg-surface-elevated: #21262d;
      --bg-surface-hover: #30363d;
      --bg-input: #0d1117;
      --border: #30363d;
      --border-subtle: #21262d;
      --border-focus: #58a6ff;
      --text-primary: #f0f6fc;
      --text-secondary: #8b949e;
      --text-muted: #6e7681;
      --accent-blue: #58a6ff;
      --accent-blue-bg: rgba(56, 139, 253, 0.15);
      --accent-green: #2ea043;
      --accent-green-bg: rgba(46, 160, 67, 0.15);
      --accent-amber: #d29922;
      --accent-amber-bg: rgba(210, 153, 34, 0.15);
      --accent-red: #f85149;
      --accent-red-bg: rgba(248, 81, 73, 0.15);
      --accent-purple: #bc8cff;
      --accent-purple-bg: rgba(188, 140, 255, 0.15);
      --radius-sm: 4px;
      --radius-md: 6px;
      --radius-lg: 10px;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif;
      font-size: 13px;
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 10px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
    }
    .brand-mark {
      background: var(--accent-blue-bg);
      border: 1px solid var(--accent-blue);
      color: var(--accent-blue);
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: var(--radius-sm);
      letter-spacing: 0.5px;
    }
    .brand-title {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
      letter-spacing: -0.2px;
    }
    .brand-subtitle {
      font-size: 11px;
      color: var(--text-secondary);
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border-subtle);
      padding: 1px 6px;
      border-radius: var(--radius-sm);
    }
    .nav-tabs {
      display: flex;
      align-items: center;
      gap: 2px;
      background: var(--bg-base);
      padding: 3px;
      border-radius: var(--radius-md);
      border: 1px solid var(--border);
    }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-secondary);
      padding: 5px 12px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      transition: all 0.12s ease;
    }
    .tab-btn:hover { color: var(--text-primary); background: rgba(255,255,255,0.04); }
    .tab-btn.active {
      background: var(--bg-surface-elevated);
      color: var(--accent-blue);
      font-weight: 600;
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    select, input, textarea {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text-primary);
      padding: 5px 10px;
      border-radius: var(--radius-md);
      font-size: 12px;
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    select:focus, input:focus, textarea:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
    }
    .btn {
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border);
      color: var(--text-primary);
      padding: 5px 12px;
      border-radius: var(--radius-md);
      cursor: pointer;
      font-size: 12px;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.12s ease;
      user-select: none;
    }
    .btn:hover {
      background: var(--bg-surface-hover);
      border-color: var(--text-muted);
    }
    .btn-primary {
      background: #1f6feb;
      border-color: #388bfd;
      color: #ffffff;
    }
    .btn-primary:hover {
      background: #388bfd;
      border-color: #58a6ff;
    }
    .btn-success {
      background: #238636;
      border-color: #2ea043;
      color: #ffffff;
    }
    .btn-success:hover {
      background: #2ea043;
      border-color: #3fb950;
    }
    .btn-danger {
      background: rgba(248, 81, 73, 0.15);
      border-color: rgba(248, 81, 73, 0.4);
      color: #f85149;
    }
    .btn-danger:hover {
      background: #da3633;
      border-color: #f85149;
      color: #ffffff;
    }
    .btn-sm { padding: 3px 8px; font-size: 11px; }
    .btn-icon { padding: 2px 6px; font-family: monospace; font-size: 11px; }
    .auth-cluster {
      display: flex;
      align-items: center;
      gap: 6px;
      border-left: 1px solid var(--border);
      padding-left: 12px;
    }
    .status-indicator {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent-red);
      display: inline-block;
    }
    .status-indicator.connected {
      background: var(--accent-green);
      box-shadow: 0 0 6px var(--accent-green);
    }
    #banner {
      padding: 8px 24px;
      font-size: 12px;
      display: none;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid transparent;
    }
    #banner.warning {
      background: rgba(210, 153, 34, 0.15);
      color: #e3b341;
      border-color: rgba(210, 153, 34, 0.3);
      display: flex;
    }
    #banner.error {
      background: var(--accent-red-bg);
      color: #ff7b72;
      border-color: rgba(248, 81, 73, 0.3);
      display: flex;
    }
    #banner.info {
      background: var(--accent-blue-bg);
      color: #79c0ff;
      border-color: rgba(56, 139, 253, 0.3);
      display: flex;
    }
    main {
      flex: 1;
      padding: 24px;
      max-width: 1680px;
      margin: 0 auto;
      width: 100%;
    }
    .view-panel { display: none; }
    .view-panel.active { display: block; }
    /* Board View */
    .board-container {
      display: grid;
      grid-template-columns: repeat(5, minmax(280px, 1fr));
      gap: 14px;
      align-items: start;
      overflow-x: auto;
      padding-bottom: 24px;
    }
    .board-col {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - 160px);
    }
    .col-header {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(22, 27, 34, 0.8);
      border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    }
    .col-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 12px;
      text-transform: capitalize;
    }
    .col-count {
      background: var(--bg-base);
      border: 1px solid var(--border);
      padding: 1px 6px;
      border-radius: 10px;
      font-size: 11px;
      color: var(--text-secondary);
      font-family: monospace;
    }
    .col-limit {
      font-size: 11px;
      color: var(--text-muted);
    }
    .col-limit.exceeded {
      color: var(--accent-red);
      font-weight: 700;
    }
    .card-list {
      padding: 10px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: 140px;
    }
    .card {
      background: var(--bg-surface-elevated);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
      transition: border-color 0.12s ease, transform 0.12s ease;
      display: flex;
      flex-direction: column;
      gap: 8px;
      cursor: pointer;
    }
    .card:hover {
      border-color: var(--accent-blue);
      transform: translateY(-1px);
    }
    .card.is-blocked {
      border-left: 3px solid var(--accent-red);
    }
    .card-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
    }
    .badge {
      padding: 1px 6px;
      border-radius: var(--radius-sm);
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-family: monospace;
    }
    .badge-urgent { background: var(--accent-red-bg); color: #ff7b72; border: 1px solid rgba(248,81,73,0.4); }
    .badge-high { background: var(--accent-amber-bg); color: #d29922; border: 1px solid rgba(210,153,34,0.4); }
    .badge-normal { background: var(--accent-blue-bg); color: #79c0ff; border: 1px solid rgba(56,139,253,0.4); }
    .badge-low { background: rgba(110,118,129,0.15); color: #8b949e; border: 1px solid var(--border); }
    .badge-blocked {
      background: var(--accent-red-bg);
      color: #ff7b72;
      border: 1px solid rgba(248,81,73,0.4);
      font-size: 10px;
      padding: 2px 6px;
      border-radius: var(--radius-sm);
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 500;
    }
    .badge-blocked-tag {
      font-weight: 700;
      font-family: monospace;
      font-size: 9px;
      background: #da3633;
      color: #ffffff;
      padding: 0 4px;
      border-radius: 2px;
    }
    .card-id {
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 11px;
      color: var(--text-muted);
    }
    .card-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text-primary);
      line-height: 1.4;
    }
    .card-labels {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .pill {
      background: var(--bg-base);
      border: 1px solid var(--border);
      padding: 1px 6px;
      border-radius: var(--radius-sm);
      font-size: 11px;
      color: var(--text-secondary);
    }
    .pill-git {
      font-family: monospace;
      font-size: 10px;
      color: var(--accent-purple);
      border-color: rgba(188, 140, 255, 0.3);
      background: var(--accent-purple-bg);
    }
    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      margin-top: 4px;
      padding-top: 8px;
      border-top: 1px solid var(--border-subtle);
      font-size: 11px;
      color: var(--text-muted);
    }
    .card-actions {
      display: flex;
      gap: 3px;
    }
    /* Backlog & Table Views */
    .table-container {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }
    th, td {
      padding: 9px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 12px;
    }
    th {
      background: var(--bg-surface-elevated);
      color: var(--text-secondary);
      font-weight: 600;
    }
    tr:hover td { background: var(--bg-surface-hover); cursor: pointer; }
    /* Search View */
    .search-layout {
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 20px;
    }
    .facet-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px;
      margin-bottom: 14px;
    }
    .facet-card h4 {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 8px;
      font-weight: 600;
    }
    .facet-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 4px 6px;
      border-radius: var(--radius-sm);
      font-size: 12px;
      color: var(--text-secondary);
      cursor: pointer;
    }
    .facet-item:hover {
      background: var(--bg-surface-elevated);
      color: var(--accent-blue);
    }
    .snippet-box {
      background: var(--bg-base);
      border-left: 2px solid var(--accent-blue);
      padding: 6px 10px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 11px;
      color: #c9d1d9;
      margin-top: 6px;
      border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    }
    /* Context View */
    .context-layout {
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 20px;
    }
    .file-tree {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 3px;
    }
    .file-item {
      padding: 7px 10px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      color: var(--text-secondary);
      font-size: 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .file-item:hover { background: var(--bg-surface-elevated); color: var(--text-primary); }
    .file-item.active { background: #1f6feb; color: #ffffff; }
    .doc-tag {
      font-family: monospace;
      font-size: 10px;
      padding: 1px 4px;
      border-radius: 2px;
      background: var(--border);
      color: var(--text-secondary);
    }
    .file-preview {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .file-content {
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
      color: #e6edf3;
      white-space: pre-wrap;
      max-height: 620px;
      overflow-y: auto;
    }
    /* Modal */
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(1, 4, 9, 0.75);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 200;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      width: 680px;
      max-width: 95vw;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 24px 48px rgba(0,0,0,0.6);
    }
    .modal-header {
      padding: 14px 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .modal-body {
      padding: 20px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .modal-footer {
      padding: 12px 20px;
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-group label {
      font-size: 11px;
      font-weight: 600;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .form-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
    }
    .conflict-alert {
      background: var(--accent-red-bg);
      border: 1px solid rgba(248, 81, 73, 0.4);
      color: #ff7b72;
      padding: 10px 14px;
      border-radius: var(--radius-md);
      font-size: 12px;
      display: none;
      align-items: center;
      justify-content: space-between;
    }
    .conflict-label {
      font-weight: 700;
      font-family: monospace;
      background: #da3633;
      color: #ffffff;
      padding: 1px 4px;
      border-radius: 2px;
      margin-right: 6px;
    }
    .app-shell { display: flex; min-height: 100vh; }
    .sidebar {
      width: 220px;
      flex-shrink: 0;
      background: var(--bg-surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      padding: 16px 12px;
      gap: 18px;
    }
    .sidebar nav { display: flex; flex-direction: column; gap: 2px; }
    .nav-item {
      background: transparent;
      border: none;
      color: var(--text-secondary);
      text-align: left;
      padding: 8px 10px;
      border-radius: var(--radius-md);
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
    }
    .nav-item:hover { background: var(--bg-surface-elevated); color: var(--text-primary); }
    .nav-item.active { background: var(--accent-blue-bg); color: var(--accent-blue); }
    .nav-item kbd {
      float: right;
      font-size: 10px;
      color: var(--text-muted);
      border: 1px solid var(--border);
      padding: 0 5px;
      border-radius: 3px;
    }
    .sidebar-foot { margin-top: auto; font-size: 11px; color: var(--text-muted); line-height: 1.6; }
    .app-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
    .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
    .stat-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px 16px;
    }
    .stat-card .label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--text-muted); font-weight: 600; }
    .stat-card .value { font-size: 22px; font-weight: 700; margin-top: 6px; }
    .client-block { margin-bottom: 18px; }
    .client-block h3 { font-size: 12px; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.4px; }
    .project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
    .project-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 12px;
      cursor: pointer;
    }
    .project-card:hover { border-color: var(--accent-blue); }
    .project-card h4 { font-size: 13px; margin-bottom: 4px; }
    .empty-state { color: var(--text-muted); padding: 32px; text-align: center; }
    .health-row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--border); }
    .health-ok { color: var(--accent-green); font-weight: 600; }
    .health-bad { color: var(--accent-red); font-weight: 600; }
    .run-card { background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px 14px; margin-bottom: 10px; }
    .run-card h4 { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--accent-blue); }
    .run-card pre { margin-top: 8px; white-space: pre-wrap; color: var(--text-secondary); font-size: 12px; }
    .md-body { font-size: 13px; line-height: 1.55; color: var(--text-primary); }
    .md-body h1, .md-body h2, .md-body h3 { margin: 0.8em 0 0.4em; }
    .md-body h1 { font-size: 18px; }
    .md-body h2 { font-size: 15px; }
    .md-body h3 { font-size: 13px; color: var(--text-secondary); }
    .md-body p { margin: 0.5em 0; }
    .md-body ul, .md-body ol { margin: 0.4em 0 0.4em 1.3em; }
    .md-body code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; background: var(--bg-base); padding: 1px 4px; border-radius: 3px; }
    .md-body pre { background: var(--bg-base); border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; overflow: auto; }
    .md-body pre code { background: none; padding: 0; }
    .md-body a { color: var(--accent-blue); }
    .settings-row { display: grid; grid-template-columns: 160px 1fr; gap: 10px; padding: 10px 12px; border-bottom: 1px solid var(--border); font-size: 13px; }
    .settings-row dt { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.3px; }
    .md-body table { width: 100%; border-collapse: collapse; margin: 0.6em 0; }
    .md-body th, .md-body td { border: 1px solid var(--border); padding: 6px 8px; text-align: left; }
    .md-body th { background: var(--bg-surface-elevated); }
    .md-body blockquote { border-left: 3px solid var(--accent-blue); margin: 0.6em 0; padding: 4px 12px; color: var(--text-secondary); }
    .md-body hr { border: none; border-top: 1px solid var(--border); margin: 1em 0; }
    .md-body del { color: var(--text-muted); }
    .palette {
      display: none;
      position: fixed; inset: 0;
      background: rgba(1, 4, 9, 0.72);
      z-index: 300;
      align-items: flex-start;
      justify-content: center;
      padding-top: 12vh;
    }
    .palette.open { display: flex; }
    .palette-panel {
      width: min(560px, 92vw);
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: 0 24px 48px rgba(0,0,0,0.55);
      overflow: hidden;
    }
    .palette-panel input {
      width: 100%;
      border: none;
      border-bottom: 1px solid var(--border);
      border-radius: 0;
      padding: 12px 14px;
      font-size: 14px;
    }
    .palette-list { max-height: 360px; overflow: auto; }
    .palette-item {
      padding: 8px 14px;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--text-secondary);
      font-size: 13px;
    }
    .palette-item:hover, .palette-item.active { background: var(--bg-surface-elevated); color: var(--text-primary); }
    .palette-item kbd { font-size: 10px; color: var(--text-muted); }
    @media (max-width: 860px) {
      .app-shell { flex-direction: column; }
      .sidebar { width: 100%; flex-direction: row; flex-wrap: wrap; align-items: center; }
      .sidebar nav { flex-direction: row; flex-wrap: wrap; }
      .sidebar-foot { display: none; }
      .board-container { grid-template-columns: minmax(260px, 1fr); }
      .search-layout, .context-layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app-shell">
  <aside class="sidebar">
    <a href="#" class="brand" onclick="switchTab('overview'); return false;">
      <span class="brand-mark">WS</span>
      <span class="brand-title">Workspace</span>
    </a>
    <nav>
      <button class="nav-item active" data-tab="overview" onclick="switchTab('overview')">Overview <kbd>1</kbd></button>
      <button class="nav-item" data-tab="clients" onclick="switchTab('clients')">Clients</button>
      <button class="nav-item" data-tab="board" onclick="switchTab('board')">Board <kbd>2</kbd></button>
      <button class="nav-item" data-tab="backlog" onclick="switchTab('backlog')">Backlog <kbd>3</kbd></button>
      <button class="nav-item" data-tab="search" onclick="switchTab('search')">Search <kbd>4</kbd></button>
      <button class="nav-item" data-tab="context" onclick="switchTab('context')">Context <kbd>5</kbd></button>
      <button class="nav-item" data-tab="plans" onclick="switchTab('plans')">Plans</button>
      <button class="nav-item" data-tab="runs" onclick="switchTab('runs')">Runs <kbd>6</kbd></button>
      <button class="nav-item" data-tab="commits" onclick="switchTab('commits')">Commits <kbd>7</kbd></button>
      <button class="nav-item" data-tab="activity" onclick="switchTab('activity')">Activity <kbd>8</kbd></button>
      <button class="nav-item" data-tab="health" onclick="switchTab('health')">Health <kbd>9</kbd></button>
      <button class="nav-item" data-tab="settings" onclick="switchTab('settings')">Settings</button>
    </nav>
    <div class="sidebar-foot">
      Local loopback control. <kbd>Ctrl/Cmd+K</kbd> command palette,
      <kbd>n</kbd> new task, <kbd>/</kbd> search. Token stays in this session.
    </div>
  </aside>
  <div class="app-main">
  <header>
    <div class="header-actions" style="width:100%; justify-content:flex-end;">
      <select id="project-select" onchange="onProjectChanged()">
        <option value="">Loading projects...</option>
      </select>
      <button class="btn btn-primary" onclick="openCreateTaskModal()">+ New Task</button>
      <div class="auth-cluster">
        <span id="status-indicator" class="status-indicator" title="Disconnected"></span>
        <input id="token-input" type="password" placeholder="Bearer token..." style="width: 130px;" autocomplete="off">
        <button class="btn btn-sm" onclick="saveToken()">Connect</button>
      </div>
    </div>
  </header>

  <div id="banner">
    <span id="banner-text"></span>
    <button class="btn btn-sm" onclick="hideBanner()">Dismiss</button>
  </div>

  <main>
    <section id="view-overview" class="view-panel active">
      <div class="stat-grid" id="overview-stats"></div>
      <div id="overview-clients"></div>
    </section>
    <!-- Board View -->
    <section id="view-board" class="view-panel">
      <div class="board-container" id="board-columns"></div>
    </section>

    <!-- Backlog View -->
    <section id="view-backlog" class="view-panel">
      <div style="display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;">
        <input id="backlog-filter" type="text" placeholder="Filter backlog tasks..." style="width: 280px;" oninput="renderBacklog()">
        <select id="backlog-status" onchange="renderBacklog()">
          <option value="">All Statuses</option>
          <option value="backlog">Backlog</option>
          <option value="ready">Ready</option>
          <option value="in_progress">In Progress</option>
          <option value="review">Review</option>
          <option value="done">Done</option>
        </select>
        <select id="backlog-priority" onchange="renderBacklog()">
          <option value="">All Priorities</option>
          <option value="urgent">Urgent</option>
          <option value="high">High</option>
          <option value="normal">Normal</option>
          <option value="low">Low</option>
        </select>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Status</th>
              <th>Priority</th>
              <th>Owner</th>
              <th>Labels</th>
              <th>Blocked</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody id="backlog-rows"></tbody>
        </table>
      </div>
    </section>

    <!-- Search View -->
    <section id="view-search" class="view-panel">
      <div style="display: flex; gap: 10px; margin-bottom: 14px;">
        <input id="search-q" type="text" placeholder="Search tasks by title, description, criteria, tags, owner..." style="flex: 1;" onkeydown="if(event.key==='Enter') executeSearch()">
        <button class="btn btn-primary" onclick="executeSearch()">Search</button>
      </div>
      <div class="search-layout">
        <aside id="search-facets">
          <div class="facet-card">
            <h4>Status</h4>
            <div id="facet-status"></div>
          </div>
          <div class="facet-card">
            <h4>Priority</h4>
            <div id="facet-priority"></div>
          </div>
          <div class="facet-card">
            <h4>Owner</h4>
            <div id="facet-owner"></div>
          </div>
        </aside>
        <div>
          <div id="search-meta" style="color: var(--text-secondary); font-size: 12px; margin-bottom: 12px;"></div>
          <div id="search-results" style="display: flex; flex-direction: column; gap: 10px;"></div>
        </div>
      </div>
    </section>

    <!-- Context View -->
    <section id="view-context" class="view-panel">
      <div class="context-layout">
        <div class="file-tree" id="context-file-list"></div>
        <div class="file-preview">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h3 id="context-file-path" style="font-size: 13px; color: var(--accent-blue);">Select a file</h3>
            <span id="context-file-size" style="font-size: 11px; color: var(--text-muted); font-family: monospace;"></span>
          </div>
          <div id="context-file-body" class="file-content md-body">Select a context file from the list to view its contents.</div>
        </div>
      </div>
    </section>

    <!-- Commits View -->
    <section id="view-commits" class="view-panel">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Commit</th>
              <th>Subject</th>
              <th>Author</th>
              <th>Date</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="commit-rows"></tbody>
        </table>
      </div>
    </section>

    <!-- Activity & Metrics View -->
    <section id="view-activity" class="view-panel">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 12px;">
        <div style="display: flex; gap: 12px; align-items: center;">
          <h2 style="font-size: 15px; font-weight: 600;">Activity & Metrics</h2>
          <span id="activity-clock-pill" class="badge" style="display: none;"></span>
          <button id="btn-clock-in" class="btn btn-sm btn-primary" onclick="clockAction('in')">Clock In</button>
          <button id="btn-clock-out" class="btn btn-sm" onclick="clockAction('out')" style="display: none;">Clock Out</button>
        </div>
        <div style="display: flex; gap: 8px; align-items: center;">
          <label for="activity-month" style="font-size: 12px; color: var(--text-secondary);">Month:</label>
          <input type="month" id="activity-month" onchange="loadActivity()" style="padding: 4px 8px; font-size: 12px; background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); border-radius: var(--radius-sm);">
        </div>
      </div>

      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px;">
        <div class="card" style="padding: 16px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);">
          <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px;">Human Hours (Payroll)</div>
          <div id="stat-human-hours" style="font-size: 24px; font-weight: 700; color: var(--accent-blue); margin: 8px 0 4px 0;">0.00 h</div>
          <div style="font-size: 11px; color: var(--text-secondary);">Single-threaded human focus</div>
        </div>
        <div class="card" style="padding: 16px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);">
          <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px;">Agent Hours (Machine)</div>
          <div id="stat-agent-hours" style="font-size: 24px; font-weight: 700; color: var(--accent-green); margin: 8px 0 4px 0;">0.00 h</div>
          <div style="font-size: 11px; color: var(--text-secondary);">Autonomous agent execution</div>
        </div>
        <div class="card" style="padding: 16px; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-md);">
          <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600; letter-spacing: 0.5px;">Token Usage (Sessions)</div>
          <div id="stat-token-sessions" style="font-size: 24px; font-weight: 700; color: var(--accent-purple); margin: 8px 0 4px 0;">0</div>
          <div id="stat-token-counts" style="font-size: 11px; color: var(--text-secondary);">0 in / 0 out</div>
        </div>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Human Hours</th>
              <th>Agent Hours</th>
              <th>Distribution</th>
              <th>Token Sessions</th>
            </tr>
          </thead>
          <tbody id="activity-rows"></tbody>
        </table>
      </div>
    </section>

    <section id="view-runs" class="view-panel">
      <div id="runs-list" class="empty-state">Select a project to load runs.</div>
    </section>
    <section id="view-health" class="view-panel">
      <div class="table-container" id="health-list"></div>
    </section>
    <section id="view-clients" class="view-panel">
      <div id="clients-list" class="empty-state">Connect to load clients.</div>
    </section>
    <section id="view-plans" class="view-panel">
      <div id="plans-list" class="empty-state">Connect to load plans.</div>
    </section>
    <section id="view-settings" class="view-panel">
      <div class="table-container" id="settings-list"></div>
    </section>
  <div id="command-palette" class="palette" onclick="if(event.target===this) closePalette()">
    <div class="palette-panel">
      <input id="palette-q" type="text" placeholder="Jump to a view, project, or action…" oninput="filterPalette()" onkeydown="paletteKey(event)">
      <div id="palette-list" class="palette-list"></div>
    </div>
  </div>
  </main>
  </div>
  </div>

  <!-- Create Task Modal -->
  <div id="modal-create" class="modal-backdrop">
    <div class="modal">
      <div class="modal-header">
        <h3 style="font-size: 14px;">Create New Task</h3>
        <button class="btn btn-sm" onclick="closeModal('modal-create')">Close</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label>Title *</label>
          <input id="create-title" type="text" placeholder="Concise task title...">
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Status</label>
            <select id="create-status">
              <option value="backlog">Backlog</option>
              <option value="ready">Ready</option>
              <option value="in_progress">In Progress</option>
              <option value="review">Review</option>
              <option value="done">Done</option>
            </select>
          </div>
          <div class="form-group">
            <label>Priority</label>
            <select id="create-priority">
              <option value="low">Low</option>
              <option value="normal" selected>Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div class="form-group">
            <label>Owner</label>
            <input id="create-owner" type="text" value="unassigned">
          </div>
        </div>
        <div class="form-group">
          <label>Labels (comma-separated)</label>
          <input id="create-labels" type="text" placeholder="e.g. web, api, core">
        </div>
        <div class="form-group">
          <label>Acceptance Criteria (one per line)</label>
          <textarea id="create-criteria" rows="3" placeholder="- Feature is verified&#10;- Standards are checked"></textarea>
        </div>
        <div class="form-group">
          <label>Description (Markdown)</label>
          <textarea id="create-body" rows="4" placeholder="Task description and context..."></textarea>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" onclick="closeModal('modal-create')">Cancel</button>
        <button class="btn btn-primary" onclick="submitCreateTask()">Create Task</button>
      </div>
    </div>
  </div>

  <!-- Detail / Edit Task Modal -->
  <div id="modal-detail" class="modal-backdrop">
    <div class="modal">
      <div class="modal-header">
        <div style="display: flex; align-items: center; gap: 8px;">
          <h3 id="detail-task-id" style="font-family: monospace; font-size: 13px; color: var(--accent-blue);">task_id</h3>
          <span id="detail-task-source" class="pill">context</span>
        </div>
        <button class="btn btn-sm" onclick="closeModal('modal-detail')">Close</button>
      </div>
      <div class="modal-body">
        <div id="detail-conflict" class="conflict-alert">
          <div>
            <span class="conflict-label">CONFLICT</span>
            <span>This task was modified concurrently by another writer.</span>
          </div>
          <button class="btn btn-sm" onclick="reloadCurrentTask()">Reload Latest</button>
        </div>
        <div class="form-group">
          <label>Title</label>
          <input id="detail-title" type="text">
        </div>
        <div class="form-row">
          <div class="form-group">
            <label>Status</label>
            <select id="detail-status">
              <option value="backlog">Backlog</option>
              <option value="ready">Ready</option>
              <option value="in_progress">In Progress</option>
              <option value="review">Review</option>
              <option value="done">Done</option>
            </select>
          </div>
          <div class="form-group">
            <label>Priority</label>
            <select id="detail-priority">
              <option value="low">Low</option>
              <option value="normal">Normal</option>
              <option value="high">High</option>
              <option value="urgent">Urgent</option>
            </select>
          </div>
          <div class="form-group">
            <label>Owner</label>
            <input id="detail-owner" type="text">
          </div>
        </div>
        <div class="form-group">
          <label>Labels (comma-separated)</label>
          <input id="detail-labels" type="text">
        </div>
        <div class="form-row" style="align-items: center;">
          <label style="display: flex; align-items: center; gap: 6px; cursor: pointer;">
            <input id="detail-blocked" type="checkbox" onchange="toggleBlockedReason()">
            <span style="font-size: 12px; font-weight: 600; color: var(--accent-red);">Task is Blocked</span>
          </label>
          <input id="detail-blocked-reason" type="text" placeholder="Blocker reason..." style="display: none; flex: 1;">
        </div>
        <div class="form-group">
          <label>Acceptance Criteria (one per line)</label>
          <textarea id="detail-criteria" rows="3"></textarea>
        </div>
        <div class="form-group">
          <label>Description (Markdown)</label>
          <textarea id="detail-body" rows="4"></textarea>
        </div>
        <!-- Git Evidence Links -->
        <div class="form-group" style="background: var(--bg-base); padding: 12px; border-radius: var(--radius-md); border: 1px solid var(--border);">
          <label style="color: var(--accent-purple);">Local Git Evidence Links</label>
          <div id="detail-git-links" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
          <div style="display: flex; gap: 8px; margin-top: 8px;">
            <input id="attach-commit-sha" type="text" placeholder="Commit SHA (7-40 hex chars)..." style="flex: 1; font-family: monospace;">
            <button class="btn btn-sm btn-success" onclick="attachCommitToDetail()">Attach Link</button>
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" onclick="closeModal('modal-detail')">Cancel</button>
        <button class="btn btn-primary" onclick="saveTaskDetail()">Save Changes</button>
      </div>
    </div>
  </div>

  <script>
    const state = {
      token: sessionStorage.getItem("ws_token") || "",
      project: sessionStorage.getItem("ws_project") || "",
      projects: [],
      boardData: null,
      currentTask: null,
      contextFiles: []
    };

    const STATUSES = ["backlog", "ready", "in_progress", "review", "done"];

    function init() {
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.has("token")) {
        state.token = urlParams.get("token");
        sessionStorage.setItem("ws_token", state.token);
      }
      if (state.token) {
        document.getElementById("token-input").value = state.token;
        setConnected(true);
      }
      loadProjects();
    }

    function setConnected(connected) {
      const el = document.getElementById("status-indicator");
      el.className = "status-indicator " + (connected ? "connected" : "");
      el.title = connected ? "Connected" : "Disconnected";
    }

    function saveToken() {
      const val = document.getElementById("token-input").value.trim();
      state.token = val;
      sessionStorage.setItem("ws_token", val);
      setConnected(!!val);
      loadProjects();
    }

    async function api(path, options = {}) {
      const headers = Object.assign({}, options.headers || {});
      if (state.token) {
        headers["Authorization"] = "Bearer " + state.token;
      }
      if (options.body && typeof options.body === "string" && !headers["Content-Type"]) {
        headers["Content-Type"] = "application/json";
      }
      try {
        const res = await fetch(path, {
          method: options.method || "GET",
          headers: headers,
          body: options.body
        });
        const contentType = res.headers.get("Content-Type") || "";
        let data = null;
        if (contentType.includes("application/json")) {
          data = await res.json();
        } else {
          data = await res.text();
        }
        if (res.status === 401) {
          setConnected(false);
          showBanner("Authentication required. Please enter the Bearer token.", "warning");
        } else if (res.status === 200 || res.status === 201) {
          setConnected(true);
        }
        return { ok: res.ok, status: res.status, data: data };
      } catch (err) {
        showBanner("Network error: " + err.message, "error");
        return { ok: false, status: 0, error: err };
      }
    }

    function showBanner(msg, type = "info") {
      const b = document.getElementById("banner");
      b.className = type;
      document.getElementById("banner-text").textContent = msg;
    }
    function hideBanner() {
      document.getElementById("banner").style.display = "none";
    }

    function switchTab(tabId) {
      document.querySelectorAll(".nav-item").forEach(btn => {
        btn.classList.toggle("active", btn.getAttribute("data-tab") === tabId);
      });
      document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
      const target = document.getElementById("view-" + tabId);
      if (target) target.classList.add("active");
      location.hash = tabId;

      if (tabId === "overview") loadOverview();
      else if (tabId === "board") loadBoard();
      else if (tabId === "backlog") renderBacklog();
      else if (tabId === "context") loadContext();
      else if (tabId === "commits") loadCommits();
      else if (tabId === "search") executeSearch();
      else if (tabId === "activity") loadActivity();
      else if (tabId === "runs") loadRuns();
      else if (tabId === "health") loadHealth();
      else if (tabId === "clients") loadClients();
      else if (tabId === "plans") loadPlans();
      else if (tabId === "settings") loadSettings();
    }

    async function loadProjects() {
      const res = await api("/api/projects");
      if (!res.ok) return;
      state.projects = res.data.projects || [];
      const sel = document.getElementById("project-select");
      sel.innerHTML = "";
      state.projects.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.key;
        opt.textContent = p.key + " (" + p.client + ")";
        sel.appendChild(opt);
      });
      if (state.projects.length > 0) {
        if (!state.project || !state.projects.some(p => p.key === state.project)) {
          state.project = state.projects[0].key;
        }
        sel.value = state.project;
        sessionStorage.setItem("ws_project", state.project);
        const initial = (location.hash || "#overview").slice(1);
        switchTab(initial || "overview");
      }
    }

    function onProjectChanged() {
      state.project = document.getElementById("project-select").value;
      sessionStorage.setItem("ws_project", state.project);
      const active = document.querySelector(".nav-item.active");
      switchTab(active ? active.getAttribute("data-tab") : "overview");
    }

    async function loadOverview() {
      const res = await api("/api/overview");
      if (!res.ok) return;
      const data = res.data;
      const counts = data.counts || {};
      document.getElementById("overview-stats").innerHTML = `
        <div class="stat-card"><div class="label">Projects</div><div class="value">${counts.projects || 0}</div></div>
        <div class="stat-card"><div class="label">Clients</div><div class="value">${counts.clients || 0}</div></div>
        <div class="stat-card"><div class="label">Tasks</div><div class="value">${counts.tasks || 0}</div></div>
        <div class="stat-card"><div class="label">Blocked</div><div class="value" style="color:var(--accent-amber)">${counts.blocked_tasks || 0}</div></div>
        <div class="stat-card"><div class="label">Context</div><div class="value" style="font-size:16px">${data.context_local ? "local" : "shared"}</div></div>
      `;
      const host = document.getElementById("overview-clients");
      host.innerHTML = "";
      (data.clients || []).forEach(client => {
        const block = document.createElement("div");
        block.className = "client-block";
        const cards = (client.projects || []).map(p => `
          <div class="project-card" onclick="selectProject('${escapeHtml(p.key)}')">
            <h4>${escapeHtml(p.key)}</h4>
            <div style="font-size:12px;color:var(--text-secondary)">${escapeHtml(p.description || p.folder || "")}</div>
          </div>`).join("");
        block.innerHTML = `<h3>${escapeHtml(client.key)}</h3><div class="project-grid">${cards}</div>`;
        host.appendChild(block);
      });
    }

    function selectProject(key) {
      state.project = key;
      document.getElementById("project-select").value = key;
      sessionStorage.setItem("ws_project", key);
      switchTab("board");
    }

    async function loadRuns() {
      const host = document.getElementById("runs-list");
      if (!state.project) {
        host.innerHTML = `<div class="empty-state">Select a project to load runs.</div>`;
        return;
      }
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/runs");
      if (!res.ok) return;
      const runs = res.data.runs || [];
      if (!runs.length) {
        host.innerHTML = `<div class="empty-state">No runs recorded for ${escapeHtml(state.project)}.</div>`;
        return;
      }
      host.innerHTML = runs.map(run => `
        <article class="run-card">
          <h4>${escapeHtml(run.id)}</h4>
          <div style="font-size:11px;color:var(--text-muted)">${escapeHtml(run.path)} · ${escapeHtml((run.updated || "").slice(0,19))}</div>
          <div class="md-body">${renderMarkdown(run.handoff || "No handoff.md")}</div>
        </article>`).join("");
    }

    async function loadHealth() {
      const res = await api("/api/health");
      if (!res.ok) return;
      const rows = (res.data.checks || []).map(check => `
        <div class="health-row">
          <span>${escapeHtml(check.id)}</span>
          <span class="${check.ok ? "health-ok" : "health-bad"}">${check.ok ? "ok" : "fail"} — ${escapeHtml(check.detail || "")}</span>
        </div>`).join("");
      document.getElementById("health-list").innerHTML = rows || `<div class="empty-state">No checks.</div>`;
    }

    // --- Board ---
    async function loadBoard() {
      if (!state.project) return;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/board");
      if (!res.ok) return;
      state.boardData = res.data;

      if (res.data.wip_warnings && res.data.wip_warnings.length > 0) {
        showBanner("WIP Limit Warning: " + res.data.wip_warnings.join("; "), "warning");
      } else {
        hideBanner();
      }

      const container = document.getElementById("board-columns");
      container.innerHTML = "";

      STATUSES.forEach(status => {
        const tasks = res.data.columns[status] || [];
        const limit = res.data.wip_limits[status];
        const isExceeded = limit !== undefined && tasks.length > limit;

        const col = document.createElement("div");
        col.className = "board-col";
        col.innerHTML = `
          <div class="col-header">
            <div class="col-title">
              <span>${status.replace("_", " ")}</span>
              <span class="col-count">${tasks.length}</span>
            </div>
            ${limit ? `<span class="col-limit ${isExceeded ? 'exceeded' : ''}">${tasks.length}/${limit} max</span>` : ''}
          </div>
          <div class="card-list" id="col-list-${status}"></div>
        `;
        container.appendChild(col);

        const list = col.querySelector(".card-list");
        tasks.forEach(task => {
          const card = createCardElement(task);
          list.appendChild(card);
        });
      });
    }

    function createCardElement(task) {
      const el = document.createElement("div");
      el.className = "card" + (task.blocked ? " is-blocked" : "");
      const currIdx = STATUSES.indexOf(task.status);

      const labelsHtml = (task.labels || []).map(l => `<span class="pill">${escapeHtml(l)}</span>`).join("");
      const gitBadge = task.git_links && task.git_links.length > 0 ? `<span class="pill pill-git">${task.git_links.length} ${task.git_links.length === 1 ? 'commit' : 'commits'}</span>` : "";

      el.innerHTML = `
        <div class="card-top">
          <span class="badge badge-${task.priority}">${task.priority}</span>
          <span class="card-id">${task.id}</span>
        </div>
        <div class="card-title">${escapeHtml(task.title)}</div>
        ${task.blocked ? `<div class="badge-blocked"><span class="badge-blocked-tag">BLOCKED</span> <span>${escapeHtml(task.blocked_reason || "")}</span></div>` : ''}
        ${labelsHtml ? `<div class="card-labels">${labelsHtml}</div>` : ''}
        <div class="card-footer">
          <span>@${escapeHtml(task.owner || "unassigned")}</span>
          <div style="display:flex; gap:6px; align-items:center;">
            ${gitBadge}
            <div class="card-actions">
              ${currIdx > 0 ? `<button class="btn btn-icon btn-sm" title="Move to ${STATUSES[currIdx - 1]}" onclick="event.stopPropagation(); quickMove('${task.id}', '${STATUSES[currIdx - 1]}')">&larr;</button>` : ''}
              ${currIdx < STATUSES.length - 1 ? `<button class="btn btn-icon btn-sm" title="Move to ${STATUSES[currIdx + 1]}" onclick="event.stopPropagation(); quickMove('${task.id}', '${STATUSES[currIdx + 1]}')">&rarr;</button>` : ''}
            </div>
          </div>
        </div>
      `;
      el.onclick = () => openTaskDetail(task.id);
      return el;
    }

    async function quickMove(taskId, targetStatus) {
      const detailRes = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(taskId));
      if (!detailRes.ok) return;
      const rev = detailRes.data.task.revision;

      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(taskId) + "/move", {
        method: "POST",
        body: JSON.stringify({
          target_status: targetStatus,
          expected_revision: rev
        })
      });
      if (res.status === 409) {
        showBanner("Conflict: task was updated concurrently. Board reloaded.", "warning");
      }
      loadBoard();
    }

    // --- Task Creation ---
    function openCreateTaskModal() {
      document.getElementById("create-title").value = "";
      document.getElementById("create-status").value = "backlog";
      document.getElementById("create-priority").value = "normal";
      document.getElementById("create-owner").value = "unassigned";
      document.getElementById("create-labels").value = "";
      document.getElementById("create-criteria").value = "";
      document.getElementById("create-body").value = "";
      openModal("modal-create");
    }

    async function submitCreateTask() {
      const title = document.getElementById("create-title").value.trim();
      if (!title) {
        alert("Title is required");
        return;
      }
      const rawLabels = document.getElementById("create-labels").value;
      const labels = rawLabels.split(",").map(s => s.trim()).filter(Boolean);
      const rawCriteria = document.getElementById("create-criteria").value;
      const criteria = rawCriteria.split("\\n").map(s => s.trim().replace(/^[-*]\\s*/, "")).filter(Boolean);

      const payload = {
        title: title,
        status: document.getElementById("create-status").value,
        priority: document.getElementById("create-priority").value,
        owner: document.getElementById("create-owner").value.trim(),
        labels: labels,
        acceptance_criteria: criteria,
        body: document.getElementById("create-body").value
      };

      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        closeModal("modal-create");
        loadBoard();
      } else {
        alert("Error creating task: " + (res.data && res.data.error ? res.data.error : res.status));
      }
    }

    // --- Task Detail & Edit ---
    async function openTaskDetail(taskId) {
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(taskId));
      if (!res.ok) return;
      const t = res.data.task;
      state.currentTask = t;

      document.getElementById("detail-conflict").style.display = "none";
      document.getElementById("detail-task-id").textContent = t.id;
      document.getElementById("detail-task-source").textContent = t.source;
      document.getElementById("detail-title").value = t.title;
      document.getElementById("detail-status").value = t.status;
      document.getElementById("detail-priority").value = t.priority;
      document.getElementById("detail-owner").value = t.owner;
      document.getElementById("detail-labels").value = (t.labels || []).join(", ");
      document.getElementById("detail-blocked").checked = !!t.blocked;
      const reasonEl = document.getElementById("detail-blocked-reason");
      reasonEl.value = t.blocked_reason || "";
      reasonEl.style.display = t.blocked ? "block" : "none";
      document.getElementById("detail-criteria").value = (t.acceptance_criteria || []).join("\\n");
      document.getElementById("detail-body").value = t.body || "";

      renderDetailGitLinks(t.git_links || []);
      openModal("modal-detail");
    }

    function toggleBlockedReason() {
      const chk = document.getElementById("detail-blocked").checked;
      document.getElementById("detail-blocked-reason").style.display = chk ? "block" : "none";
    }

    function renderDetailGitLinks(links) {
      const container = document.getElementById("detail-git-links");
      container.innerHTML = "";
      if (links.length === 0) {
        container.innerHTML = `<span style="font-size:11px; color:var(--text-muted);">No commits linked.</span>`;
        return;
      }
      links.forEach(link => {
        const item = document.createElement("div");
        item.style.display = "flex";
        item.style.alignItems = "center";
        item.style.justifyContent = "space-between";
        item.style.fontSize = "11px";
        item.innerHTML = `
          <code>${link.repository}@${link.sha.substring(0, 8)}</code>
          <button class="btn btn-sm btn-danger" onclick="detachCommitFromDetail('${link.sha}')">Detach</button>
        `;
        container.appendChild(item);
      });
    }

    async function attachCommitToDetail() {
      if (!state.currentTask) return;
      const sha = document.getElementById("attach-commit-sha").value.trim();
      if (!sha) return;

      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(state.currentTask.id) + "/git-links", {
        method: "POST",
        body: JSON.stringify({
          sha: sha,
          expected_revision: state.currentTask.revision
        })
      });
      if (res.ok) {
        state.currentTask = res.data.task;
        document.getElementById("attach-commit-sha").value = "";
        renderDetailGitLinks(state.currentTask.git_links || []);
        loadBoard();
      } else if (res.status === 409) {
        document.getElementById("detail-conflict").style.display = "flex";
      } else {
        alert("Error attaching commit: " + (res.data && res.data.error ? res.data.error : res.status));
      }
    }

    async function detachCommitFromDetail(sha) {
      if (!state.currentTask) return;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(state.currentTask.id) + "/git-links/" + encodeURIComponent(sha), {
        method: "DELETE",
        body: JSON.stringify({
          expected_revision: state.currentTask.revision
        })
      });
      if (res.ok) {
        state.currentTask = res.data.task;
        renderDetailGitLinks(state.currentTask.git_links || []);
        loadBoard();
      } else if (res.status === 409) {
        document.getElementById("detail-conflict").style.display = "flex";
      } else {
        alert("Error detaching commit: " + (res.data && res.data.error ? res.data.error : res.status));
      }
    }

    async function saveTaskDetail() {
      if (!state.currentTask) return;
      const blocked = document.getElementById("detail-blocked").checked;
      const blockedReason = document.getElementById("detail-blocked-reason").value.trim();
      if (blocked && !blockedReason) {
        alert("Blocked tasks require a blocked reason");
        return;
      }
      const rawLabels = document.getElementById("detail-labels").value;
      const labels = rawLabels.split(",").map(s => s.trim()).filter(Boolean);
      const rawCriteria = document.getElementById("detail-criteria").value;
      const criteria = rawCriteria.split("\\n").map(s => s.trim().replace(/^[-*]\\s*/, "")).filter(Boolean);

      const payload = {
        title: document.getElementById("detail-title").value.trim(),
        status: document.getElementById("detail-status").value,
        priority: document.getElementById("detail-priority").value,
        owner: document.getElementById("detail-owner").value.trim(),
        labels: labels,
        blocked: blocked,
        blocked_reason: blocked ? blockedReason : "",
        acceptance_criteria: criteria,
        body: document.getElementById("detail-body").value,
        expected_revision: state.currentTask.revision
      };

      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/tasks/" + encodeURIComponent(state.currentTask.id), {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        closeModal("modal-detail");
        loadBoard();
      } else if (res.status === 409) {
        document.getElementById("detail-conflict").style.display = "flex";
      } else {
        alert("Error saving task: " + (res.data && res.data.error ? res.data.error : res.status));
      }
    }

    function reloadCurrentTask() {
      if (state.currentTask) {
        openTaskDetail(state.currentTask.id);
      }
    }

    // --- Backlog View ---
    function renderBacklog() {
      if (!state.boardData) {
        loadBoard().then(renderBacklog);
        return;
      }
      const q = document.getElementById("backlog-filter").value.toLowerCase();
      const statusFilter = document.getElementById("backlog-status").value;
      const priorityFilter = document.getElementById("backlog-priority").value;

      const allTasks = [];
      STATUSES.forEach(st => {
        (state.boardData.columns[st] || []).forEach(t => allTasks.push(t));
      });

      const tbody = document.getElementById("backlog-rows");
      tbody.innerHTML = "";

      const filtered = allTasks.filter(t => {
        if (statusFilter && t.status !== statusFilter) return false;
        if (priorityFilter && t.priority !== priorityFilter) return false;
        if (q && !t.title.toLowerCase().includes(q) && !t.id.toLowerCase().includes(q)) return false;
        return true;
      });

      filtered.forEach(t => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${t.id}</code></td>
          <td style="font-weight:600;">${escapeHtml(t.title)}</td>
          <td><span class="pill">${t.status}</span></td>
          <td><span class="badge badge-${t.priority}">${t.priority}</span></td>
          <td>@${escapeHtml(t.owner)}</td>
          <td>${(t.labels || []).map(l => `<span class="pill">${escapeHtml(l)}</span>`).join(" ")}</td>
          <td>${t.blocked ? '<span class="badge badge-urgent">Blocked</span>' : '-'}</td>
          <td style="color:var(--text-muted); font-family:monospace;">${t.updated_at ? t.updated_at.split("T")[0] : "-"}</td>
        `;
        tr.onclick = () => openTaskDetail(t.id);
        tbody.appendChild(tr);
      });
    }

    // --- Search View ---
    async function executeSearch() {
      if (!state.project) return;
      const q = document.getElementById("search-q").value.trim();
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/search?q=" + encodeURIComponent(q));
      if (!res.ok) return;

      const meta = document.getElementById("search-meta");
      meta.textContent = `Found ${res.data.total} tasks (scanned ${res.data.freshness.scanned_tasks} tasks at ${res.data.freshness.scanned_at})`;

      const counts = res.data.counts;
      document.getElementById("facet-status").innerHTML = Object.entries(counts.by_status || {})
        .map(([k, v]) => `<div class="facet-item" onclick="filterByFacet('status', '${k}')"><span>${k}</span><span style="font-family:monospace;">${v}</span></div>`).join("");
      document.getElementById("facet-priority").innerHTML = Object.entries(counts.by_priority || {})
        .map(([k, v]) => `<div class="facet-item" onclick="filterByFacet('priority', '${k}')"><span>${k}</span><span style="font-family:monospace;">${v}</span></div>`).join("");
      document.getElementById("facet-owner").innerHTML = Object.entries(counts.by_owner || {})
        .map(([k, v]) => `<div class="facet-item"><span>${k}</span><span style="font-family:monospace;">${v}</span></div>`).join("");

      const list = document.getElementById("search-results");
      list.innerHTML = "";
      if (res.data.results.length === 0) {
        list.innerHTML = `<p style="color:var(--text-muted); font-size:12px;">No tasks matched your query.</p>`;
        return;
      }
      res.data.results.forEach(item => {
        const t = item.task;
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
          <div class="card-top">
            <span class="badge badge-${t.priority}">${t.priority}</span>
            <span class="pill">${t.status}</span>
            <span class="card-id">${t.id}</span>
          </div>
          <div class="card-title">${escapeHtml(t.title)}</div>
          ${item.matches && item.matches.length > 0 ? `<div style="font-size:11px; color:var(--accent-blue);">Matched fields: ${item.matches.join(", ")}</div>` : ''}
          ${item.snippet ? `<div class="snippet-box">${escapeHtml(item.snippet)}</div>` : ''}
        `;
        card.onclick = () => openTaskDetail(t.id);
        list.appendChild(card);
      });
    }

    function filterByFacet(field, val) {
      document.getElementById("search-q").value = val;
      executeSearch();
    }

    // --- Context View ---
    async function loadContext() {
      if (!state.project) return;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/context");
      if (!res.ok) return;
      state.contextFiles = res.data.files || [];

      const list = document.getElementById("context-file-list");
      list.innerHTML = "";
      state.contextFiles.forEach((file, idx) => {
        const item = document.createElement("div");
        item.className = "file-item" + (idx === 0 ? " active" : "");
        item.innerHTML = `<span><span class="doc-tag">DOC</span> ${escapeHtml(file.path)}</span><span style="font-size:11px; font-family:monospace;">${file.bytes}B</span>`;
        item.onclick = () => selectContextFile(idx);
        list.appendChild(item);
      });
      if (state.contextFiles.length > 0) {
        selectContextFile(0);
      }
    }

    function selectContextFile(idx) {
      const items = document.querySelectorAll("#context-file-list .file-item");
      items.forEach((it, i) => it.classList.toggle("active", i === idx));
      const f = state.contextFiles[idx];
      if (f) {
        document.getElementById("context-file-path").textContent = f.path;
        document.getElementById("context-file-size").textContent = f.bytes + " bytes";
        document.getElementById("context-file-body").innerHTML = renderMarkdown(f.content || "");
      }
    }

    // --- Commits View ---
    async function loadCommits() {
      if (!state.project) return;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/commits");
      if (!res.ok) return;
      const commits = res.data.commits || [];
      const tbody = document.getElementById("commit-rows");
      tbody.innerHTML = "";
      if (commits.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:var(--text-muted);">No commits found in local repository folder.</td></tr>`;
        return;
      }
      commits.forEach(c => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${c.short_sha}</code></td>
          <td style="font-weight:500;">${escapeHtml(c.subject)}</td>
          <td>${escapeHtml(c.author)}</td>
          <td style="color:var(--text-muted); font-family:monospace;">${c.date.split("T")[0]}</td>
          <td><button class="btn btn-sm" onclick="copyToClipboard('${c.sha}', this)">Copy SHA</button></td>
        `;
        tbody.appendChild(tr);
      });
    }

    // --- Activity & Metrics View ---
    async function loadActivity() {
      if (!state.project) return;
      const monthInput = document.getElementById("activity-month");
      if (!monthInput.value) {
        const now = new Date();
        const y = now.getFullYear();
        const m = String(now.getMonth() + 1).padStart(2, "0");
        monthInput.value = y + "-" + m;
      }
      const month = monthInput.value;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/activity?month=" + encodeURIComponent(month));
      if (!res.ok) return;
      const data = res.data;

      document.getElementById("stat-human-hours").textContent = (data.hours.human_total || 0).toFixed(2) + " h";
      document.getElementById("stat-agent-hours").textContent = (data.hours.agent_total || 0).toFixed(2) + " h";

      const usage = data.usage || {};
      document.getElementById("stat-token-sessions").textContent = usage.total_sessions || 0;
      const inTok = (usage.input_tokens || 0).toLocaleString();
      const outTok = (usage.output_tokens || 0).toLocaleString();
      document.getElementById("stat-token-counts").textContent = inTok + " in / " + outTok + " out";

      const pill = document.getElementById("activity-clock-pill");
      const btnIn = document.getElementById("btn-clock-in");
      const btnOut = document.getElementById("btn-clock-out");
      if (data.active_clocks) {
        if (data.active_clocks.human) {
          pill.style.display = "inline-block";
          pill.className = "badge badge-primary";
          pill.textContent = "HUMAN CLOCKED IN: " + (data.active_clocks.human.actor || "active");
          if (btnIn) btnIn.style.display = "none";
          if (btnOut) btnOut.style.display = "inline-block";
        } else if (data.active_clocks.agent) {
          pill.style.display = "inline-block";
          pill.className = "badge badge-success";
          pill.textContent = "AGENT ACTIVE: " + (data.active_clocks.agent.tool || "agent");
          if (btnIn) btnIn.style.display = "inline-block";
          if (btnOut) btnOut.style.display = "none";
        } else {
          pill.style.display = "none";
          if (btnIn) btnIn.style.display = "inline-block";
          if (btnOut) btnOut.style.display = "none";
        }
      } else {
        pill.style.display = "none";
        if (btnIn) btnIn.style.display = "inline-block";
        if (btnOut) btnOut.style.display = "none";
      }

      const tbody = document.getElementById("activity-rows");
      tbody.innerHTML = "";

      const days = data.hours.days || [];
      const usageDays = {};
      (usage.days || []).forEach(ud => { usageDays[ud.day] = ud; });

      const allDates = Array.from(new Set([...days.map(d => d.day), ...(usage.days || []).map(d => d.day)])).sort().reverse();

      if (allDates.length === 0) {
        tbody.innerHTML = "<tr><td colspan='5' style='text-align: center; color: var(--text-muted); padding: 24px;'>No activity recorded for this month.</td></tr>";
        return;
      }

      allDates.forEach(d => {
        const hDay = days.find(x => x.day === d) || { human_hours: 0, agent_hours: 0, human_sessions: 0, agent_sessions: 0 };
        const uDay = usageDays[d] || { sessions: 0, input_tokens: 0, output_tokens: 0 };

        const totalHours = (hDay.human_hours || 0) + (hDay.agent_hours || 0);
        const humanPct = totalHours > 0 ? ((hDay.human_hours / totalHours) * 100).toFixed(0) : 0;
        const agentPct = totalHours > 0 ? ((hDay.agent_hours / totalHours) * 100).toFixed(0) : 0;

        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td style="font-family: monospace; font-weight: 500;">${d}</td>
          <td style="font-family: monospace; color: var(--accent-blue);">${hDay.human_hours ? hDay.human_hours.toFixed(2) + ' h' : '-'}</td>
          <td style="font-family: monospace; color: var(--accent-green);">${hDay.agent_hours ? hDay.agent_hours.toFixed(2) + ' h' : '-'}</td>
          <td style="width: 140px;">
            ${totalHours > 0 ? `
            <div style="display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--border-subtle); width: 100%;">
              <div style="width: ${humanPct}%; background: var(--accent-blue);" title="Human: ${humanPct}%"></div>
              <div style="width: ${agentPct}%; background: var(--accent-green);" title="Agent: ${agentPct}%"></div>
            </div>
            ` : '<span style="color: var(--text-muted); font-size: 11px;">-</span>'}
          </td>
          <td style="font-family: monospace; font-size: 12px; color: var(--text-secondary);">
            ${uDay.sessions ? `${uDay.sessions} sess (${(uDay.input_tokens + uDay.output_tokens).toLocaleString()} tok)` : '-'}
          </td>
        `;
        tbody.appendChild(tr);
      });
    }

    async function clockAction(action) {
      if (!state.project) return;
      const promptMsg = action === "in" ? "Optional note for clock in:" : "Optional note for clock out:";
      const note = prompt(promptMsg, "");
      if (note === null) return;
      try {
        const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/clock", {
          method: "POST",
          body: JSON.stringify({ action: action, kind: "human", note: note.trim() }),
        });
        if (res.ok) {
          showBanner(res.data.message || ("Clock " + action + " succeeded"), "success");
          loadActivity();
        } else {
          showBanner(res.error || "Clock action failed", "danger");
        }
      } catch (err) {
        showBanner("Clock action failed: " + err.message, "danger");
      }
    }

    function copyToClipboard(text, btn) {
      navigator.clipboard.writeText(text).then(() => {
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = original; }, 1500);
      });
    }

    // --- Utilities ---
    function openModal(id) {
      document.getElementById(id).classList.add("open");
    }
    function closeModal(id) {
      document.getElementById(id).classList.remove("open");
    }
    function escapeHtml(str) {
      return (str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function renderMarkdown(src) {
      const fences = [];
      let raw = escapeHtml(src || "");
      raw = raw.replace(/```[a-zA-Z0-9_-]*\\n([\\s\\S]*?)```/g, (_, code) => {
        fences.push("<pre><code>" + code + "</code></pre>");
        return "%%FENCE" + (fences.length - 1) + "%%";
      });
      function inline(s) {
        s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
        s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
        s = s.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
        s = s.replace(/\\*([^*]+)\\*/g, "<em>$1</em>");
        s = s.replace(/\\[([^\\]]+)\\]\\((https?:[^)]+)\\)/g, '<a href="$2" rel="noreferrer" target="_blank">$1</a>');
        return s;
      }
      const lines = raw.split("\\n");
      const out = [];
      let i = 0;
      while (i < lines.length) {
        const line = lines[i];
        if (line.indexOf("%%FENCE") === 0) { out.push(line); i++; continue; }
        if (line === "---" || line === "***") { out.push("<hr>"); i++; continue; }
        if (line.indexOf("&gt;") === 0) {
          out.push("<blockquote>" + inline(line.replace(/^(&gt;\\s?)+/, "")) + "</blockquote>");
          i++; continue;
        }
        if (line.charAt(0) === "|" && i + 1 < lines.length && /-/.test(lines[i + 1]) && lines[i + 1].indexOf("|") !== -1) {
          const rows = [];
          while (i < lines.length && lines[i].charAt(0) === "|") {
            if (/^\\|\\s*:?-+/.test(lines[i]) || /^\\|[-:| ]+$/.test(lines[i])) { i++; continue; }
            const cells = lines[i].split("|").slice(1, -1).map(function(c) { return "<td>" + inline(c.trim()) + "</td>"; }).join("");
            rows.push("<tr>" + cells + "</tr>");
            i++;
          }
          if (rows.length) {
            rows[0] = rows[0].replace(/<td>/g, "<th>").replace(/<\\/td>/g, "</th>");
            out.push("<table>" + rows.join("") + "</table>");
          }
          continue;
        }
        if (/^\\d+\\. /.test(line)) {
          const items = [];
          while (i < lines.length && /^\\d+\\. /.test(lines[i])) {
            items.push("<li>" + inline(lines[i].replace(/^\\d+\\. /, "")) + "</li>");
            i++;
          }
          out.push("<ol>" + items.join("") + "</ol>");
          continue;
        }
        if (/^(- \\[[ xX]\\] |[-*+] )/.test(line)) {
          const items = [];
          while (i < lines.length && /^(- \\[[ xX]\\] |[-*+] )/.test(lines[i])) {
            let t = lines[i];
            if (/^- \\[[xX]\\] /.test(t)) items.push("<li><input type='checkbox' disabled checked> " + inline(t.replace(/^- \\[[xX]\\] /, "")) + "</li>");
            else if (/^- \\[ \\] /.test(t)) items.push("<li><input type='checkbox' disabled> " + inline(t.replace(/^- \\[ \\] /, "")) + "</li>");
            else items.push("<li>" + inline(t.replace(/^[-*+] /, "")) + "</li>");
            i++;
          }
          out.push("<ul>" + items.join("") + "</ul>");
          continue;
        }
        if (line.indexOf("### ") === 0) { out.push("<h3>" + inline(line.slice(4)) + "</h3>"); i++; continue; }
        if (line.indexOf("## ") === 0) { out.push("<h2>" + inline(line.slice(3)) + "</h2>"); i++; continue; }
        if (line.indexOf("# ") === 0) { out.push("<h1>" + inline(line.slice(2)) + "</h1>"); i++; continue; }
        if (!line.trim()) { i++; continue; }
        out.push("<p>" + inline(line) + "</p>");
        i++;
      }
      let html = out.join("");
      fences.forEach(function(block, idx) { html = html.replace("%%FENCE" + idx + "%%", block); });
      return html;
    }

    const PALETTE_COMMANDS = [
      { id: "overview", label: "Overview", hint: "1" },
      { id: "clients", label: "Clients", hint: "" },
      { id: "board", label: "Board", hint: "2" },
      { id: "backlog", label: "Backlog", hint: "3" },
      { id: "search", label: "Search", hint: "/" },
      { id: "context", label: "Context", hint: "5" },
      { id: "plans", label: "Plans", hint: "" },
      { id: "runs", label: "Runs", hint: "6" },
      { id: "commits", label: "Commits", hint: "7" },
      { id: "activity", label: "Activity", hint: "8" },
      { id: "health", label: "Health", hint: "9" },
      { id: "settings", label: "Settings", hint: "," },
      { id: "new-task", label: "New task", hint: "n" }
    ];
    let paletteIndex = 0;

    function paletteItems() {
      const q = (document.getElementById("palette-q").value || "").toLowerCase();
      const cmds = PALETTE_COMMANDS.filter(c => c.label.toLowerCase().includes(q) || c.id.includes(q));
      const projects = (state.projects || []).filter(p => !q || p.key.toLowerCase().includes(q) || (p.client || "").toLowerCase().includes(q))
        .map(p => ({ id: "project:" + p.key, label: "Project " + p.key, hint: p.client || "" }));
      return cmds.concat(projects);
    }
    function renderPalette() {
      const items = paletteItems();
      if (paletteIndex >= items.length) paletteIndex = 0;
      document.getElementById("palette-list").innerHTML = items.map((item, i) =>
        `<div class="palette-item${i===paletteIndex?" active":""}" data-id="${escapeHtml(item.id)}" onclick="runPalette('${escapeHtml(item.id)}')">${escapeHtml(item.label)}<kbd>${escapeHtml(item.hint || "")}</kbd></div>`
      ).join("") || `<div class="palette-item">No matches</div>`;
    }
    function openPalette() {
      document.getElementById("command-palette").classList.add("open");
      document.getElementById("palette-q").value = "";
      paletteIndex = 0;
      renderPalette();
      document.getElementById("palette-q").focus();
    }
    function closePalette() {
      document.getElementById("command-palette").classList.remove("open");
    }
    function filterPalette() { paletteIndex = 0; renderPalette(); }
    function runPalette(id) {
      closePalette();
      if (id === "new-task") { openCreateTaskModal(); return; }
      if (id.indexOf("project:") === 0) { selectProject(id.slice(8)); return; }
      switchTab(id);
    }
    function paletteKey(event) {
      const items = paletteItems();
      if (event.key === "ArrowDown") { event.preventDefault(); paletteIndex = (paletteIndex + 1) % Math.max(items.length, 1); renderPalette(); }
      if (event.key === "ArrowUp") { event.preventDefault(); paletteIndex = (paletteIndex - 1 + Math.max(items.length, 1)) % Math.max(items.length, 1); renderPalette(); }
      if (event.key === "Enter") { event.preventDefault(); if (items[paletteIndex]) runPalette(items[paletteIndex].id); }
      if (event.key === "Escape") { event.preventDefault(); closePalette(); }
    }

    async function loadClients() {
      const res = await api("/api/clients");
      if (!res.ok) return;
      const host = document.getElementById("clients-list");
      const clients = res.data.clients || [];
      if (!clients.length) {
        host.innerHTML = `<div class="empty-state">No clients in this context.</div>`;
        return;
      }
      host.innerHTML = clients.map(client => {
        const cards = (client.projects || []).map(p => `
          <div class="project-card" onclick="selectProject('${escapeHtml(p.key)}')">
            <h4>${escapeHtml(p.key)}</h4>
            <div style="font-size:12px;color:var(--text-secondary)">${escapeHtml(p.description || "")}</div>
          </div>`).join("") || `<div class="empty-state">No projects</div>`;
        return `<div class="client-block"><h3>${escapeHtml(client.key)}</h3><div class="md-body">${renderMarkdown(client.summary || "")}</div><div class="project-grid">${cards}</div></div>`;
      }).join("");
    }

    async function loadPlans() {
      const query = state.project ? ("?project=" + encodeURIComponent(state.project)) : "";
      const res = await api("/api/plans" + query);
      if (!res.ok) return;
      const host = document.getElementById("plans-list");
      const plans = res.data.plans || [];
      if (!plans.length) {
        host.innerHTML = `<div class="empty-state">No plan.md files found.</div>`;
        return;
      }
      host.innerHTML = plans.map(plan => `
        <article class="run-card">
          <h4>${escapeHtml(plan.title)}</h4>
          <div style="font-size:11px;color:var(--text-muted)">${escapeHtml(plan.project)} · ${escapeHtml(plan.path)}</div>
          <div class="md-body">${renderMarkdown(plan.body || "")}</div>
        </article>`).join("");
    }

    async function loadSettings() {
      const res = await api("/api/settings");
      if (!res.ok) return;
      const id = res.data.identity || {};
      const rows = [
        ["Root", res.data.root_name || ""],
        ["Packs", id.packs || ""],
        ["Context dir", id.context_dir || ""],
        ["Context remote", id.context_remote || "(local-only)"],
        ["Default project", id.default_project || "(none)"],
        ["Runtime", res.data.runtime || ""],
        ["Loopback", res.data.loopback ? "yes" : "no"],
      ].map(([k, v]) => `<div class="settings-row"><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd></div>`).join("");
      document.getElementById("settings-list").innerHTML = rows;
    }

    document.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        const pal = document.getElementById("command-palette");
        if (pal.classList.contains("open")) closePalette(); else openPalette();
        return;
      }
      if (event.key === "Escape") closePalette();
      if (document.getElementById("command-palette").classList.contains("open")) return;
      const typing = /INPUT|TEXTAREA|SELECT/.test((event.target && event.target.tagName) || "");
      if (typing) return;
      const keys = { "1": "overview", "2": "board", "3": "backlog", "4": "search", "5": "context", "6": "runs", "7": "commits", "8": "activity", "9": "health" };
      if (keys[event.key]) { event.preventDefault(); switchTab(keys[event.key]); }
      if (event.key === "n") { event.preventDefault(); openCreateTaskModal(); }
      if (event.key === ",") { event.preventDefault(); switchTab("settings"); }
      if (event.key === "/") { event.preventDefault(); switchTab("search"); const q = document.getElementById("search-q"); if (q) q.focus(); }
    });

    window.onload = init;
  </script>
</body>
</html>
"""


def serve(
    root: str | Path,
    host: str,
    port: int,
    token: str | None = None,
    runtime: str = "uidl",
) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise WebError("web control must bind to 127.0.0.1 or localhost")
    state = build_state(root, token=token, runtime=runtime)

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            headers = {k.lower(): v for k, v in self.headers.items()}
            try:
                allowed_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                request_host = headers.get("host", "")
                if request_host not in allowed_hosts:
                    raise Forbidden("untrusted host")
                origin = headers.get("origin")
                if origin and origin != f"http://{request_host}":
                    raise Forbidden("cross-origin access is not allowed")
                if headers.get("sec-fetch-site") == "cross-site":
                    raise Forbidden("cross-site access is not allowed")
                try:
                    content_length = int(headers.get("content-length", 0))
                except ValueError as error:
                    raise WebError("invalid content length") from error
                if content_length < 0 or content_length > 1024 * 1024:
                    raise WebError("request body exceeds limit")
                body = self.rfile.read(content_length) if content_length > 0 else b""
                status, content_type, response_body = route(state, method, self.path, headers, body=body)
            except WebError as error:
                status, content_type, response_body = _json_error(error.status, str(error))
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(response_body)))
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(response_body)

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("OPTIONS")

        def do_HEAD(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("HEAD")

        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("GET")

        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("POST")

        def do_PUT(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("PUT")

        def do_DELETE(self) -> None:  # noqa: N802 - stdlib callback name
            self._handle("DELETE")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address
    ui = "uidl" if state.runtime == "uidl" and _uidl_available(state.root) else "vanilla"
    print(f"Agent Workspace Control: http://{actual_host}:{actual_port}/")
    print(f"Open in browser:         http://{actual_host}:{actual_port}/?token={state.token}")
    print(f"Bearer token:            {state.token}")
    print(f"UI runtime:              {ui}")
    if state.runtime == "uidl" and ui == "vanilla":
        print("UIDL UI build not found; serving vanilla. Run: cd apps/workspace-control && npm ci && npm run build")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent Workspace Control server...")
    finally:
        server.server_close()


def _context_dir(root: Path) -> str:
    config = root / "workspace.conf"
    if not config.exists():
        return "context"
    for line in config.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("context_dir") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            return value or "context"
    return "context"


def _registry_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def _project_summary(state: WorkspaceWebState, project: str) -> ProjectSummary:
    if not PROJECT_RE.fullmatch(project):
        raise NotFound("project not found")
    projects = {item.key: item for item in load_projects(state)}
    summary = projects.get(project)
    if summary is None:
        raise NotFound("project not found")
    return summary


def _load_context_tasks(state: WorkspaceWebState) -> tuple[list[TaskRecord], list[object]]:
    tasks_root = _contained(state.context, "tasks")
    if not tasks_root.exists():
        return [], []
    try:
        return load_tasks(load_source("context", state.context))
    except TaskError as error:
        raise WebError(str(error)) from error


def _require_token(state: WorkspaceWebState, headers: dict[str, str]) -> None:
    auth = headers.get("authorization", "")
    if auth != f"Bearer {state.token}":
        raise Unauthorized("valid bearer token required")


def _contained(base: Path, relative: str) -> Path:
    if relative.startswith("/") or ".." in Path(relative).parts:
        raise WebError("path escapes context")
    root = base.resolve()
    candidate = root / relative
    if any(parent.is_symlink() for parent in [candidate, *candidate.parents] if parent != root and root in parent.parents):
        raise WebError("symlinks are not allowed in context read flow")
    target = (root / relative).resolve()
    if root not in target.parents and target != root:
        raise WebError("path escapes context")
    return target


def _file_payload(root: Path, path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_CONTEXT_BYTES:
        raise WebError("context file exceeds read limit")
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "content": path.read_text(encoding="utf-8"),
    }


def _project_to_dict(project: ProjectSummary) -> dict[str, str]:
    return project.__dict__.copy()


def _task_card(task: TaskRecord) -> dict[str, object]:
    return {
        "source": task.source,
        "id": task.id,
        "project": task.project,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "owner": task.owner,
        "labels": list(task.labels),
        "blocked": task.blocked,
        "blocked_reason": task.blocked_reason,
        "updated_at": task.updated_at,
        "path": task.path,
    }


def _task_detail_payload(state: WorkspaceWebState, task: TaskRecord) -> dict[str, object]:
    data = _task_card(task)
    data.update(
        {
            "body": task.body,
            "acceptance_criteria": list(task.acceptance_criteria),
            "related_plans": [_resolve_related_ref(state, ref) for ref in task.related_plans],
            "related_runs": [_resolve_related_ref(state, ref, prefer_handoff=True) for ref in task.related_runs],
            "git_links": [link.__dict__.copy() for link in task.git_links],
            "created_at": task.created_at,
            "revision": task.revision,
        }
    )
    return data


def _resolve_related_ref(state: WorkspaceWebState, ref: str, *, prefer_handoff: bool = False) -> dict[str, object]:
    path = _contained(state.context, ref)
    if prefer_handoff and path.is_dir():
        handoff = path / "handoff.md"
        if handoff.exists():
            path = handoff
    if path.exists() and path.is_file():
        return {"ref": ref, "resolved": True, "file": _file_payload(state.root, path)}
    return {"ref": ref, "resolved": False}


def _json(data: object, status: int = HTTPStatus.OK) -> tuple[int, str, bytes]:
    return status, "application/json; charset=utf-8", (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def _json_error(status: HTTPStatus, message: str) -> tuple[int, str, bytes]:
    return int(status), "application/json; charset=utf-8", (json.dumps({"error": message}) + "\n").encode()


def _extract_string_list(data: dict[str, object], name: str) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise WebError(f"{name} must be a list of strings")
    return [item.strip() for item in value]


def _extract_git_links(value: object) -> list[GitLink]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise WebError("git_links must be a list")
    links = []
    for item in value:
        if isinstance(item, dict):
            repo = item.get("repository", "")
            sha = item.get("sha", "")
        elif isinstance(item, str) and "@" in item:
            repo, sha = item.split("@", 1)
        else:
            raise WebError("git_links items must be repository@sha or {'repository': ..., 'sha': ...}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(repo)) or not re.fullmatch(r"[0-9a-f]{7,40}", str(sha)):
            raise WebError("invalid git link repository or sha")
        links.append(GitLink(str(repo), str(sha)))
    return links


def _parse_json_body(body: bytes) -> dict[str, object]:
    if not body:
        return {}
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception as error:
        raise WebError("invalid JSON body") from error
    if not isinstance(data, dict):
        raise WebError("request body must be a JSON object")
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run the local Agent Workspace control shell")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=0, type=int)
    parser.add_argument("--token")
    parser.add_argument(
        "--runtime",
        choices=["vanilla", "uidl"],
        default="uidl",
        help="Web UI runtime (default: uidl; falls back to vanilla if no UI build is available)",
    )
    args = parser.parse_args(argv)
    serve(args.root, args.host, args.port, args.token, runtime=args.runtime)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(0)
    except WebError as error:
        print(f"workspace web: {error}", file=sys.stderr)
        raise SystemExit(1)
