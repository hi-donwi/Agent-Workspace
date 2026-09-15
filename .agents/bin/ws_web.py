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
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlparse

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


def build_state(root: str | Path, *, token: str | None = None) -> WorkspaceWebState:
    base = Path(root).resolve()
    context = base / _context_dir(base)
    if not (context / "registry.tsv").is_file():
        raise WebError("context registry not found")
    return WorkspaceWebState(base, context.resolve(), token or secrets.token_urlsafe(32))


def route(
    state: WorkspaceWebState,
    method: str,
    raw_path: str,
    headers: dict[str, str],
    body: bytes = b"",
) -> tuple[int, str, bytes]:
    parsed = urlparse(raw_path)
    path = parsed.path
    if method not in ("GET", "POST", "PUT", "DELETE"):
        raise WebError(f"unsupported method: {method}")
    if method == "GET" and path == "/":
        return HTTPStatus.OK, "text/html; charset=utf-8", index_html().encode()
    _require_token(state, headers)
    if method == "GET":
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
    elif method == "POST":
        prefix = "/api/projects/"
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


def index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agent Workspace Control</title>
  <style>
    :root {
      --bg-base: #090d16;
      --bg-header: #111827;
      --bg-card: #1e293b;
      --bg-card-hover: #26354a;
      --bg-input: #0f172a;
      --border: #334155;
      --border-light: #475569;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --sky: #38bdf8;
      --indigo: #818cf8;
      --emerald: #34d399;
      --amber: #fbbf24;
      --rose: #f43f5e;
      --purple: #c084fc;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background-color: var(--bg-base);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.5;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--bg-header);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
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
      font-weight: 700;
      font-size: 16px;
      color: var(--sky);
      letter-spacing: -0.3px;
    }
    .brand-badge {
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.4);
      padding: 2px 8px;
      border-radius: 12px;
      font-size: 11px;
      color: var(--sky);
      font-weight: 600;
    }
    .nav-tabs {
      display: flex;
      align-items: center;
      gap: 4px;
      background: var(--bg-input);
      padding: 4px;
      border-radius: 8px;
      border: 1px solid var(--border);
    }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      transition: all 0.15s ease;
    }
    .tab-btn:hover { color: var(--text); background: rgba(255,255,255,0.05); }
    .tab-btn.active {
      background: var(--bg-card);
      color: var(--sky);
      font-weight: 600;
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }
    .header-controls {
      display: flex;
      align-items: center;
      gap: 12px;
    }
    select, input, textarea {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 13px;
      outline: none;
      transition: border-color 0.15s;
    }
    select:focus, input:focus, textarea:focus { border-color: var(--sky); }
    .btn {
      background: var(--bg-card);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 500;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }
    .btn:hover { background: var(--border); }
    .btn-primary {
      background: #0284c7;
      border-color: #38bdf8;
      color: #fff;
    }
    .btn-primary:hover { background: #0369a1; }
    .btn-success {
      background: #059669;
      border-color: #34d399;
      color: #fff;
    }
    .btn-success:hover { background: #047857; }
    .btn-danger {
      background: #dc2626;
      border-color: #f87171;
      color: #fff;
    }
    .btn-danger:hover { background: #b91c1c; }
    .btn-sm { padding: 3px 8px; font-size: 12px; }
    .auth-box {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--rose);
      display: inline-block;
    }
    .status-dot.connected { background: var(--emerald); }
    #banner {
      padding: 8px 20px;
      font-size: 13px;
      display: none;
      align-items: center;
      justify-content: space-between;
    }
    #banner.warning {
      background: #78350f;
      color: #fef3c7;
      border-bottom: 1px solid #b45309;
      display: flex;
    }
    #banner.error {
      background: #7f1d1d;
      color: #fee2e2;
      border-bottom: 1px solid #b91c1c;
      display: flex;
    }
    #banner.info {
      background: #0c4a6e;
      color: #e0f2fe;
      border-bottom: 1px solid #0284c7;
      display: flex;
    }
    main {
      flex: 1;
      padding: 20px;
      max-width: 1600px;
      margin: 0 auto;
      width: 100%;
    }
    .view-panel { display: none; }
    .view-panel.active { display: block; }
    /* Board View */
    .board-container {
      display: grid;
      grid-template-columns: repeat(5, minmax(280px, 1fr));
      gap: 16px;
      align-items: start;
      overflow-x: auto;
      padding-bottom: 20px;
    }
    .board-col {
      background: rgba(17, 24, 39, 0.7);
      border: 1px solid var(--border);
      border-radius: 10px;
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - 170px);
    }
    .col-header {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-weight: 600;
      font-size: 13px;
    }
    .col-title {
      display: flex;
      align-items: center;
      gap: 8px;
      text-transform: capitalize;
    }
    .col-count {
      background: var(--bg-card);
      border: 1px solid var(--border);
      padding: 1px 7px;
      border-radius: 10px;
      font-size: 11px;
      color: var(--text-muted);
    }
    .col-limit {
      font-size: 11px;
      color: var(--text-dim);
    }
    .col-limit.exceeded {
      color: var(--rose);
      font-weight: 700;
    }
    .card-list {
      padding: 10px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      min-height: 120px;
    }
    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.2);
      transition: all 0.15s ease;
      display: flex;
      flex-direction: column;
      gap: 8px;
      cursor: pointer;
    }
    .card:hover {
      border-color: var(--border-light);
      background: var(--bg-card-hover);
      transform: translateY(-1px);
    }
    .card.blocked-card {
      border-left: 4px solid var(--rose);
    }
    .card-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
    }
    .badge {
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }
    .badge-urgent { background: rgba(244,63,94,0.15); color: #fda4af; border: 1px solid rgba(244,63,94,0.3); }
    .badge-high { background: rgba(251,191,36,0.15); color: #fde68a; border: 1px solid rgba(251,191,36,0.3); }
    .badge-normal { background: rgba(56,189,248,0.15); color: #bae6fd; border: 1px solid rgba(56,189,248,0.3); }
    .badge-low { background: rgba(148,163,184,0.15); color: #cbd5e1; border: 1px solid rgba(148,163,184,0.3); }
    .badge-blocked { background: rgba(244,63,94,0.2); color: #fecdd3; border: 1px solid var(--rose); font-size: 10px; }
    .card-id {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11px;
      color: var(--text-dim);
    }
    .card-title {
      font-size: 13px;
      font-weight: 600;
      color: var(--text);
      line-height: 1.4;
    }
    .card-labels {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .pill {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 11px;
      color: var(--text-muted);
    }
    .card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      margin-top: 4px;
      padding-top: 8px;
      border-top: 1px solid rgba(255,255,255,0.06);
      font-size: 11px;
      color: var(--text-dim);
    }
    .card-actions {
      display: flex;
      gap: 4px;
    }
    /* Backlog & Table Views */
    .table-container {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
    }
    th, td {
      padding: 10px 14px;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
    }
    th {
      background: var(--bg-header);
      color: var(--text-muted);
      font-weight: 600;
    }
    tr:hover td { background: var(--bg-card-hover); cursor: pointer; }
    /* Search View */
    .search-layout {
      display: grid;
      grid-template-columns: 260px 1fr;
      gap: 20px;
    }
    .facet-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 16px;
    }
    .facet-card h4 {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-muted);
      margin-bottom: 10px;
    }
    .facet-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 4px 0;
      font-size: 13px;
      color: var(--text);
      cursor: pointer;
    }
    .facet-item:hover { color: var(--sky); }
    .snippet-box {
      background: var(--bg-input);
      border-left: 3px solid var(--sky);
      padding: 6px 10px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      color: #cbd5e1;
      margin-top: 6px;
      border-radius: 0 4px 4px 0;
    }
    /* Context View */
    .context-layout {
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 20px;
    }
    .file-tree {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .file-item {
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
      color: var(--text-muted);
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .file-item:hover { background: var(--bg-card-hover); color: var(--text); }
    .file-item.active { background: #0284c7; color: #fff; }
    .file-preview {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .file-content {
      background: var(--bg-input);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 12px;
      color: #e2e8f0;
      white-space: pre-wrap;
      max-height: 600px;
      overflow-y: auto;
    }
    /* Modal */
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.7);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 200;
    }
    .modal-backdrop.open { display: flex; }
    .modal {
      background: var(--bg-header);
      border: 1px solid var(--border-light);
      border-radius: 12px;
      width: 680px;
      max-width: 95vw;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5);
    }
    .modal-header {
      padding: 16px 20px;
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
      padding: 14px 20px;
      border-top: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-group label {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
    }
    .form-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .conflict-alert {
      background: #7f1d1d;
      border: 1px solid #ef4444;
      color: #fee2e2;
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 13px;
      display: none;
      align-items: center;
      justify-content: space-between;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span>⚡ Agent Workspace</span>
      <span class="brand-badge">Local Control</span>
    </div>
    <div class="nav-tabs">
      <button class="tab-btn active" onclick="switchTab('board')">Kanban Board</button>
      <button class="tab-btn" onclick="switchTab('backlog')">Backlog</button>
      <button class="tab-btn" onclick="switchTab('search')">Search</button>
      <button class="tab-btn" onclick="switchTab('context')">Context</button>
      <button class="tab-btn" onclick="switchTab('commits')">Commits</button>
    </div>
    <div class="header-controls">
      <select id="project-select" onchange="onProjectChanged()">
        <option value="">Loading projects...</option>
      </select>
      <button class="btn btn-primary" onclick="openCreateTaskModal()">+ New Task</button>
      <div class="auth-box">
        <span id="status-dot" class="status-dot" title="Not connected"></span>
        <input id="token-input" type="password" placeholder="Bearer token..." style="width: 140px;">
        <button class="btn btn-sm" onclick="saveToken()">Connect</button>
      </div>
    </div>
  </header>

  <div id="banner">
    <span id="banner-text"></span>
    <button class="btn btn-sm" onclick="hideBanner()">Dismiss</button>
  </div>

  <main>
    <!-- Board View -->
    <section id="view-board" class="view-panel active">
      <div class="board-container" id="board-columns">
        <!-- Injected via JS -->
      </div>
    </section>

    <!-- Backlog View -->
    <section id="view-backlog" class="view-panel">
      <div style="display: flex; gap: 12px; margin-bottom: 16px;">
        <input id="backlog-filter" type="text" placeholder="Filter backlog..." style="width: 300px;" oninput="renderBacklog()">
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
      <div style="display: flex; gap: 12px; margin-bottom: 16px;">
        <input id="search-q" type="text" placeholder="Search tasks by title, body, criteria, labels..." style="flex: 1;" onkeydown="if(event.key==='Enter') executeSearch()">
        <button class="btn btn-primary" onclick="executeSearch()">Search</button>
      </div>
      <div class="search-layout">
        <aside id="search-facets">
          <div class="facet-card">
            <h4>By Status</h4>
            <div id="facet-status"></div>
          </div>
          <div class="facet-card">
            <h4>By Priority</h4>
            <div id="facet-priority"></div>
          </div>
          <div class="facet-card">
            <h4>By Owner</h4>
            <div id="facet-owner"></div>
          </div>
        </aside>
        <div>
          <div id="search-meta" style="color: var(--text-muted); font-size: 12px; margin-bottom: 12px;"></div>
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
            <h3 id="context-file-path" style="font-size: 14px; color: var(--sky);">Select a file</h3>
            <span id="context-file-size" style="font-size: 12px; color: var(--text-dim);"></span>
          </div>
          <pre id="context-file-body" class="file-content">Select a context file from the left to view its contents.</pre>
        </div>
      </div>
    </section>

    <!-- Commits View -->
    <section id="view-commits" class="view-panel">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>SHA</th>
              <th>Subject</th>
              <th>Author</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody id="commit-rows"></tbody>
        </table>
      </div>
    </section>
  </main>

  <!-- Create Task Modal -->
  <div id="modal-create" class="modal-backdrop">
    <div class="modal">
      <div class="modal-header">
        <h3>Create New Task</h3>
        <button class="btn btn-sm" onclick="closeModal('modal-create')">✕</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label>Task Title *</label>
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
          <textarea id="create-criteria" rows="3" placeholder="- User can view board&#10;- Status is persisted"></textarea>
        </div>
        <div class="form-group">
          <label>Description / Body (Markdown)</label>
          <textarea id="create-body" rows="4" placeholder="Detailed requirements and context..."></textarea>
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
        <div style="display: flex; align-items: center; gap: 10px;">
          <h3 id="detail-task-id" style="font-family: monospace; color: var(--sky);">task_id</h3>
          <span id="detail-task-source" class="pill">context</span>
        </div>
        <button class="btn btn-sm" onclick="closeModal('modal-detail')">✕</button>
      </div>
      <div class="modal-body">
        <div id="detail-conflict" class="conflict-alert">
          <span>⚠️ Revision Conflict: This task was modified concurrently by another writer.</span>
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
            <span>Task is Blocked</span>
          </label>
          <input id="detail-blocked-reason" type="text" placeholder="Blocker reason..." style="display: none; flex: 1;">
        </div>
        <div class="form-group">
          <label>Acceptance Criteria (one per line)</label>
          <textarea id="detail-criteria" rows="3"></textarea>
        </div>
        <div class="form-group">
          <label>Body (Markdown)</label>
          <textarea id="detail-body" rows="4"></textarea>
        </div>
        <!-- Git Evidence Links -->
        <div class="form-group" style="background: var(--bg-input); padding: 10px; border-radius: 6px; border: 1px solid var(--border);">
          <label style="color: var(--sky);">Local Git Evidence Links</label>
          <div id="detail-git-links" style="display: flex; flex-direction: column; gap: 6px; margin-top: 6px;"></div>
          <div style="display: flex; gap: 8px; margin-top: 8px;">
            <input id="attach-commit-sha" type="text" placeholder="Commit SHA (7-40 hex chars)..." style="flex: 1;">
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
      const dot = document.getElementById("status-dot");
      dot.className = "status-dot " + (connected ? "connected" : "");
      dot.title = connected ? "Connected" : "Not connected";
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
          showBanner("Authentication required. Please enter the startup Bearer token.", "warning");
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
      document.querySelectorAll(".tab-btn").forEach(btn => btn.classList.remove("active"));
      document.querySelectorAll(".view-panel").forEach(p => p.classList.remove("active"));
      event.target.classList.add("active");
      const target = document.getElementById("view-" + tabId);
      if (target) target.classList.add("active");

      if (tabId === "board") loadBoard();
      else if (tabId === "backlog") renderBacklog();
      else if (tabId === "context") loadContext();
      else if (tabId === "commits") loadCommits();
      else if (tabId === "search") executeSearch();
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
        loadBoard();
      }
    }

    function onProjectChanged() {
      state.project = document.getElementById("project-select").value;
      sessionStorage.setItem("ws_project", state.project);
      loadBoard();
    }

    // --- Board ---
    async function loadBoard() {
      if (!state.project) return;
      const res = await api("/api/projects/" + encodeURIComponent(state.project) + "/board");
      if (!res.ok) return;
      state.boardData = res.data;

      if (res.data.wip_warnings && res.data.wip_warnings.length > 0) {
        showBanner("WIP Limit Exceeded: " + res.data.wip_warnings.join("; "), "warning");
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
      el.className = "card" + (task.blocked ? " blocked-card" : "");
      const currIdx = STATUSES.indexOf(task.status);

      const labelsHtml = (task.labels || []).map(l => `<span class="pill">${escapeHtml(l)}</span>`).join("");
      const gitBadge = task.git_links && task.git_links.length > 0 ? `<span class="pill">⎇ ${task.git_links.length}</span>` : "";

      el.innerHTML = `
        <div class="card-meta">
          <span class="badge badge-${task.priority}">${task.priority}</span>
          <span class="card-id">${task.id}</span>
        </div>
        <div class="card-title">${escapeHtml(task.title)}</div>
        ${task.blocked ? `<div class="badge badge-blocked">⛔ Blocked: ${escapeHtml(task.blocked_reason || "")}</div>` : ''}
        ${labelsHtml ? `<div class="card-labels">${labelsHtml}</div>` : ''}
        <div class="card-footer">
          <span>@${escapeHtml(task.owner || "unassigned")}</span>
          <div style="display:flex; gap:4px; align-items:center;">
            ${gitBadge}
            <div class="card-actions">
              ${currIdx > 0 ? `<button class="btn btn-sm" onclick="event.stopPropagation(); quickMove('${task.id}', '${STATUSES[currIdx - 1]}')">←</button>` : ''}
              ${currIdx < STATUSES.length - 1 ? `<button class="btn btn-sm" onclick="event.stopPropagation(); quickMove('${task.id}', '${STATUSES[currIdx + 1]}')">→</button>` : ''}
            </div>
          </div>
        </div>
      `;
      el.onclick = () => openTaskDetail(task.id);
      return el;
    }

    async function quickMove(taskId, targetStatus) {
      // First fetch detail to get latest revision
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
        container.innerHTML = `<span style="font-size:12px; color:var(--text-dim);">No commits linked.</span>`;
        return;
      }
      links.forEach(link => {
        const item = document.createElement("div");
        item.style.display = "flex";
        item.style.alignItems = "center";
        item.style.justifyContent = "space-between";
        item.style.fontSize = "12px";
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
          <td>${t.blocked ? '<span class="badge badge-blocked">Blocked</span>' : '-'}</td>
          <td style="color:var(--text-dim);">${t.updated_at ? t.updated_at.split("T")[0] : "-"}</td>
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

      // Render Facets
      const counts = res.data.counts;
      document.getElementById("facet-status").innerHTML = Object.entries(counts.by_status || {})
        .map(([k, v]) => `<div class="facet-item"><span>${k}</span><span>${v}</span></div>`).join("");
      document.getElementById("facet-priority").innerHTML = Object.entries(counts.by_priority || {})
        .map(([k, v]) => `<div class="facet-item"><span>${k}</span><span>${v}</span></div>`).join("");
      document.getElementById("facet-owner").innerHTML = Object.entries(counts.by_owner || {})
        .map(([k, v]) => `<div class="facet-item"><span>${k}</span><span>${v}</span></div>`).join("");

      // Render Results
      const list = document.getElementById("search-results");
      list.innerHTML = "";
      if (res.data.results.length === 0) {
        list.innerHTML = `<p style="color:var(--text-dim);">No tasks matched your query.</p>`;
        return;
      }
      res.data.results.forEach(item => {
        const t = item.task;
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
          <div class="card-meta">
            <span class="badge badge-${t.priority}">${t.priority}</span>
            <span class="pill">${t.status}</span>
            <span class="card-id">${t.id}</span>
          </div>
          <div class="card-title">${escapeHtml(t.title)}</div>
          ${item.matches && item.matches.length > 0 ? `<div style="font-size:11px; color:var(--sky);">Matches in: ${item.matches.join(", ")}</div>` : ''}
          ${item.snippet ? `<div class="snippet-box">${escapeHtml(item.snippet)}</div>` : ''}
        `;
        card.onclick = () => openTaskDetail(t.id);
        list.appendChild(card);
      });
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
        item.innerHTML = `<span>📄 ${escapeHtml(file.path)}</span><span style="font-size:11px;">${file.bytes}B</span>`;
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
        document.getElementById("context-file-body").textContent = f.content;
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
        tbody.innerHTML = `<tr><td colspan="4" style="color:var(--text-dim);">No commits found in local repository folder.</td></tr>`;
        return;
      }
      commits.forEach(c => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><code>${c.short_sha}</code></td>
          <td style="font-weight:500;">${escapeHtml(c.subject)}</td>
          <td>${escapeHtml(c.author)}</td>
          <td style="color:var(--text-dim);">${c.date.split("T")[0]}</td>
        `;
        tbody.appendChild(tr);
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

    window.onload = init;
  </script>
</body>
</html>
"""


def serve(root: str | Path, host: str, port: int, token: str | None = None) -> None:
    state = build_state(root, token=token)

    class Handler(BaseHTTPRequestHandler):
        def _handle(self, method: str) -> None:
            content_length = int(self.headers.get("content-length", 0))
            body = self.rfile.read(content_length) if content_length > 0 else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            try:
                status, content_type, response_body = route(state, method, self.path, headers, body=body)
            except WebError as error:
                status, content_type, response_body = _json_error(error.status, str(error))
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(response_body)

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
    print(f"Agent Workspace Control: http://{actual_host}:{actual_port}/")
    print(f"Open in browser:         http://{actual_host}:{actual_port}/?token={state.token}")
    print(f"Bearer token:            {state.token}")
    server.serve_forever()


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
    args = parser.parse_args(argv)
    serve(args.root, args.host, args.port, args.token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except WebError as error:
        print(f"workspace web: {error}", file=sys.stderr)
        raise SystemExit(1)
