"""Workspace task/source parsing for the local web-control MVP.

The module deliberately uses only the Python standard library. It is the first slice of
the local project-management feature: read task documents safely, keep source identity
explicit, and reject malformed or ambiguous records before any UI writes are added.
"""

from __future__ import annotations
import argparse

from dataclasses import dataclass, replace
import calendar
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Iterable


TASK_STATUSES = {"backlog", "ready", "in_progress", "review", "done"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
# Schema version 2 (ADR-0024): project management fields, all optional.
TASK_KINDS = {"task", "milestone", "reminder"}
TASK_RECURS = {"daily", "weekly", "monthly"}
ASSIGNEE_RE = re.compile(r"(agent:)?[a-z0-9][a-z0-9_.-]*")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
SCHEMA_VERSIONS = {1, 2}
PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
TASK_ID_RE = re.compile(r"task_[a-z0-9][a-z0-9_-]*")
SHA_RE = re.compile(r"[0-9a-f]{7,40}")


class TaskError(ValueError):
    """Raised when a task source or task document is invalid."""


class TaskConflict(TaskError):
    """Raised when a task write encounters a revision conflict or duplicate id."""


@dataclass(frozen=True)
class GitLink:
    repository: str
    sha: str


@dataclass(frozen=True)
class TaskRecord:
    source: str
    path: str
    revision: str
    schema_version: int
    id: str
    project: str
    title: str
    status: str
    priority: str
    owner: str
    labels: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    related_plans: tuple[str, ...]
    related_runs: tuple[str, ...]
    git_links: tuple[GitLink, ...]
    blocked: bool
    blocked_reason: str
    created_at: str
    updated_at: str
    body: str
    kind: str = "task"
    client: str = ""
    due: str = ""
    remind_at: str = ""
    recur: str = ""
    assignee: str = ""
    rank: int = 0
    parent: str = ""
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyCandidate:
    source: str
    path: str
    revision: str
    project: str
    title: str
    line: int


@dataclass(frozen=True)
class TaskSource:
    id: str
    root: Path
    writable: bool = True


def load_source(source_id: str, root: str | Path, *, writable: bool = True) -> TaskSource:
    if not _is_key(source_id):
        raise TaskError("invalid source id")
    base = Path(root).resolve()
    if not base.exists() or not base.is_dir():
        raise TaskError("source root does not exist")
    return TaskSource(source_id, base, writable)


def load_tasks(source: TaskSource) -> tuple[list[TaskRecord], list[LegacyCandidate]]:
    tasks: list[TaskRecord] = []
    legacy: list[LegacyCandidate] = []
    seen: dict[str, TaskRecord] = {}
    tasks_root = source.root / "tasks"
    clients_root = source.root / "clients"
    # Project tasks under tasks/<key>/; a client's own tasks under clients/<c>/tasks/ (ADR-0024).
    paths: list[Path] = []
    if tasks_root.exists():
        for candidate in tasks_root.rglob("*"):
            if candidate.is_symlink():
                raise TaskError("symlinks are not allowed in task source")
        paths.extend(tasks_root.glob("**/*.md"))
    if clients_root.exists():
        for folder in clients_root.glob("*/tasks"):
            for candidate in [folder, *folder.rglob("*")]:
                if candidate.is_symlink():
                    raise TaskError("symlinks are not allowed in task source")
            paths.extend(folder.glob("*.md"))
    for path in sorted(paths):
        if not path.is_file():
            continue
        relative = _contained(source.root, path)
        text = path.read_text(encoding="utf-8")
        revision = _revision(path)
        if relative.startswith("clients/") and not text.startswith("---\n"):
            continue
        if text.startswith("---\n"):
            task = parse_task_document(source.id, relative, revision, text)
            if relative.startswith("clients/") and _scope_from_path(relative) != _scope_of(task):
                raise TaskError(f"{relative} holds a task of {_scope_of(task)}")
            previous = seen.get(task.id)
            if previous:
                raise TaskError(f"duplicate task id '{task.id}' in {previous.path} and {task.path}")
            seen[task.id] = task
            tasks.append(task)
        else:
            legacy.extend(parse_legacy_candidates(source.id, relative, revision, text))
    return tasks, legacy


def parse_task_document(source: str, path: str, revision: str, text: str) -> TaskRecord:
    metadata, body = _split_frontmatter(text)
    schema_version = _int_field(metadata, "schema_version", required=True)
    if schema_version not in SCHEMA_VERSIONS:
        raise TaskError("unsupported task schema_version")
    task_id = _string_field(metadata, "id", required=True)
    if not TASK_ID_RE.fullmatch(task_id):
        raise TaskError("invalid task id")
    project = _string_field(metadata, "project", required=True)
    if bool(project) == bool(_string_field(metadata, "client", default="")):
        raise TaskError("a task belongs to a project or a client, not both and not neither")
    if project and not PROJECT_RE.fullmatch(project):
        raise TaskError("invalid project key")
    title = _string_field(metadata, "title", required=True)
    if not title.strip():
        raise TaskError("title is required")
    status = _string_field(metadata, "status", required=True)
    if status not in TASK_STATUSES:
        raise TaskError("invalid task status")
    priority = _string_field(metadata, "priority", default="normal")
    if priority not in TASK_PRIORITIES:
        raise TaskError("invalid task priority")
    blocked = _bool_field(metadata, "blocked", default=False)
    blocked_reason = _string_field(metadata, "blocked_reason", default="")
    if blocked and not blocked_reason.strip():
        raise TaskError("blocked tasks require blocked_reason")
    if not blocked and blocked_reason.strip():
        raise TaskError("blocked_reason requires blocked=true")
    labels = _string_list(metadata, "labels")
    for label in labels:
        if not _is_key(label):
            raise TaskError("invalid label")
    git_links = tuple(_git_links(metadata.get("git_links", [])))
    return TaskRecord(
        source=source,
        path=path,
        revision=revision,
        schema_version=schema_version,
        id=task_id,
        project=project,
        title=title,
        status=status,
        priority=priority,
        owner=_string_field(metadata, "owner", default="unassigned"),
        labels=tuple(labels),
        acceptance_criteria=tuple(_string_list(metadata, "acceptance_criteria")),
        related_plans=tuple(_safe_refs(metadata, "related_plans")),
        related_runs=tuple(_safe_refs(metadata, "related_runs")),
        git_links=git_links,
        blocked=blocked,
        blocked_reason=blocked_reason,
        created_at=_string_field(metadata, "created_at", required=True),
        updated_at=_string_field(metadata, "updated_at", required=True),
        body=body.strip(),
        **_v2_fields(metadata),
    )


def _v2_fields(metadata: dict[str, object]) -> dict[str, object]:
    """The schema version 2 fields, validated; a version 1 document has none of them."""
    fields = {
        "kind": _string_field(metadata, "kind", default="task"),
        "client": _string_field(metadata, "client", default=""),
        "due": _string_field(metadata, "due", default=""),
        "remind_at": _string_field(metadata, "remind_at", default=""),
        "recur": _string_field(metadata, "recur", default=""),
        "assignee": _string_field(metadata, "assignee", default=""),
        "rank": _int_field(metadata, "rank", default=0),
        "parent": _string_field(metadata, "parent", default=""),
        "depends_on": tuple(_string_list(metadata, "depends_on")),
    }
    _check_v2(fields)
    return fields


def _check_v2(fields: dict[str, object]) -> None:
    if fields["kind"] not in TASK_KINDS:
        raise TaskError(f"invalid kind '{fields['kind']}' (one of: {', '.join(sorted(TASK_KINDS))})")
    if fields["client"] and not _is_key(str(fields["client"])):
        raise TaskError("invalid client key")
    if fields["due"]:
        _check_date(str(fields["due"]), "due")
    if fields["remind_at"]:
        _check_moment(str(fields["remind_at"]))
    if fields["recur"] and fields["recur"] not in TASK_RECURS:
        raise TaskError(f"invalid recur '{fields['recur']}' (one of: {', '.join(sorted(TASK_RECURS))})")
    if fields["assignee"] and not ASSIGNEE_RE.fullmatch(str(fields["assignee"])):
        raise TaskError(f"invalid assignee '{fields['assignee']}' (a key, or agent:<tool>)")
    if fields["parent"] and not TASK_ID_RE.fullmatch(str(fields["parent"])):
        raise TaskError(f"invalid parent '{fields['parent']}'")
    for ref in fields["depends_on"]:  # type: ignore[union-attr]
        if not TASK_ID_RE.fullmatch(ref):
            raise TaskError(f"invalid depends_on entry '{ref}'")


def _check_date(value: str, name: str) -> None:
    try:
        if not DATE_RE.fullmatch(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise TaskError(f"invalid {name} '{value}' (YYYY-MM-DD)") from None


def _check_moment(value: str) -> None:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise TaskError(f"invalid remind_at '{value}'") from None
    if moment.tzinfo is None:
        raise TaskError("remind_at needs a time zone offset")


def parse_legacy_candidates(source: str, path: str, revision: str, text: str) -> list[LegacyCandidate]:
    candidates: list[LegacyCandidate] = []
    project = _project_from_path(path)
    for index, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"\s*- \[[ xX]\]\s+(.+?)\s*$", line)
        if match:
            candidates.append(LegacyCandidate(source, path, revision, project, match.group(1), index))
    return candidates
 
 
def serialize_task_document(task: TaskRecord) -> str:
    """Always writes schema version 2, so an older `ws` refuses the file instead of dropping fields."""
    if task.schema_version not in SCHEMA_VERSIONS:
        raise TaskError("unsupported task schema_version")
    _check_v2({name: getattr(task, name) for name in ("kind", "client", "due", "remind_at", "recur", "assignee", "rank", "parent", "depends_on")})
    if not TASK_ID_RE.fullmatch(task.id):
        raise TaskError("invalid task id")
    if bool(task.project) == bool(task.client):
        raise TaskError("a task belongs to a project or a client, not both and not neither")
    if task.project and not PROJECT_RE.fullmatch(task.project):
        raise TaskError("invalid project key")
    if not task.title.strip() or "\n" in task.title or "\r" in task.title:
        raise TaskError("invalid task title")
    if task.status not in TASK_STATUSES:
        raise TaskError("invalid task status")
    if task.priority not in TASK_PRIORITIES:
        raise TaskError("invalid task priority")
    if task.blocked and not task.blocked_reason.strip():
        raise TaskError("blocked tasks require blocked_reason")
    if not task.blocked and task.blocked_reason.strip():
        raise TaskError("blocked_reason requires blocked=true")
    for label in task.labels:
        if not _is_key(label):
            raise TaskError("invalid label")
    for ref in (*task.related_plans, *task.related_runs):
        if ref.startswith("/") or ".." in Path(ref).parts:
            raise TaskError("unsafe reference in related_plans/related_runs")

    lines = [
        "---",
        "schema_version: 2",
        f"id: {task.id}",
        "project: " + (task.project or '""'),
        f"title: {task.title.strip()}",
        f"status: {task.status}",
        f"priority: {task.priority}",
        f"owner: {task.owner or 'unassigned'}",
    ]
    lines.append("labels:")
    for label in task.labels:
        lines.append(f"  - {label}")
    lines.append("acceptance_criteria:")
    for criteria in task.acceptance_criteria:
        lines.append(f"  - {criteria}")
    lines.append("related_plans:")
    for plan in task.related_plans:
        lines.append(f"  - {plan}")
    lines.append("related_runs:")
    for run in task.related_runs:
        lines.append(f"  - {run}")
    lines.append("git_links:")
    for link in task.git_links:
        lines.append(f"  - {link.repository}@{link.sha}")
    if task.blocked:
        lines.append("blocked: true")
        reason = task.blocked_reason.strip().replace('"', '\\"')
        lines.append(f'blocked_reason: "{reason}"')
    else:
        lines.append("blocked: false")
        lines.append('blocked_reason: ""')
    # Version 2 fields, written only when set so a plain task stays short.
    for name in ("kind", "client", "due", "remind_at", "recur", "assignee", "parent"):
        value = getattr(task, name)
        if value and not (name == "kind" and value == "task"):
            lines.append(f"{name}: {value}")
    if task.rank:
        lines.append(f"rank: {task.rank}")
    if task.depends_on:
        lines.append("depends_on:")
        for ref in task.depends_on:
            lines.append(f"  - {ref}")
    lines.append(f"created_at: {task.created_at}")
    lines.append(f"updated_at: {task.updated_at}")
    lines.append("---")
    lines.append("")
    if task.body.strip():
        lines.append(task.body.strip())
        lines.append("")
    return "\n".join(lines)


def write_task_document(
    source: TaskSource,
    project: str,
    task: TaskRecord,
    *,
    expected_revision: str | None = None,
) -> TaskRecord:
    if not source.writable:
        raise TaskError("task source is not writable")
    scope = project  # a project key, or @<client> for a client's own task
    parse_scope(scope)
    if _scope_of(task) != scope:
        raise TaskError(f"task of '{_scope_of(task)}' does not match '{scope}'")
    if not TASK_ID_RE.fullmatch(task.id):
        raise TaskError(f"invalid task id '{task.id}'")

    tasks_dir = _scope_dir(source, scope)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    if task.path:
        target_path = (source.root / task.path).resolve()
        relative_path = _contained(source.root, target_path)
        if _scope_from_path(relative_path) != scope:
            raise TaskError("task path project mismatch")
    else:
        target_path = tasks_dir / f"{task.id}.md"
        relative_path = _contained(source.root, target_path)

    if target_path.is_symlink():
        raise TaskError("symlinks are not allowed in task source")

    if target_path.exists():
        current_rev = _revision(target_path)
        if expected_revision is None:
            raise TaskConflict(f"task '{task.id}' already exists")
        if current_rev != expected_revision:
            raise TaskConflict(f"revision mismatch: expected '{expected_revision}', found '{current_rev}'")
    else:
        if expected_revision is not None:
            raise TaskConflict("expected revision provided but task file does not exist")

    content = serialize_task_document(task)
    parse_task_document(source.id, relative_path, "check", content)

    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    fd, temp_file = tempfile.mkstemp(prefix=f".tmp.{task.id}.", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
        os.replace(temp_file, target_path)
    except Exception:
        if os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except OSError:
                pass
        raise

    return replace(task, source=source.id, path=relative_path, revision=_revision(target_path), schema_version=2)


def to_json(tasks: Iterable[TaskRecord], legacy: Iterable[LegacyCandidate]) -> str:
    return json.dumps(
        {
            "tasks": [_task_to_dict(task) for task in tasks],
            "legacy_candidates": [candidate.__dict__ for candidate in legacy],
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    if not text.startswith("---\n"):
        raise TaskError("task document must start with frontmatter")
    marker = text.find("\n---\n", 4)
    if marker == -1:
        raise TaskError("frontmatter is not closed")
    raw = text[4:marker]
    return _parse_frontmatter(raw), text[marker + 5 :]


def _parse_frontmatter(raw: str) -> dict[str, object]:
    data: dict[str, object] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - "):
            if current_key is None or not isinstance(data.get(current_key), list):
                raise TaskError("list item without list field")
            data[current_key].append(_scalar(line[4:].strip()))  # type: ignore[index]
            continue
        if ":" not in line or line.startswith(" "):
            raise TaskError("invalid frontmatter line")
        key, value = line.split(":", 1)
        key = key.strip()
        if not _is_key(key):
            raise TaskError("invalid frontmatter key")
        value = value.strip()
        if value == "":
            data[key] = []
            current_key = key
        else:
            data[key] = _scalar(value)
            current_key = None
    return data


def _scalar(value: str) -> object:
    if value in ("true", "false"):
        return value == "true"
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def _contained(base: Path, path: Path) -> str:
    resolved_base = base.resolve()
    resolved = path.resolve()
    if resolved_base not in resolved.parents:
        raise TaskError("task path escapes source")
    relative = resolved.relative_to(resolved_base)
    if any(part in ("", ".", "..") for part in relative.parts):
        raise TaskError("invalid task path")
    if any(parent.is_symlink() for parent in [resolved, *resolved.parents] if parent != resolved_base and resolved_base in parent.parents):
        raise TaskError("symlinks are not allowed in task source")
    return relative.as_posix()


def _revision(path: Path) -> str:
    stat = path.stat()
    return f"mtime:{stat.st_mtime_ns}:size:{stat.st_size}"


def _project_from_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) >= 3 and parts[0] == "tasks" and PROJECT_RE.fullmatch(parts[1]):
        return parts[1]
    return "unknown"


def _string_field(data: dict[str, object], name: str, *, required: bool = False, default: str = "") -> str:
    value = data.get(name, default)
    if required and name not in data:
        raise TaskError(f"missing {name}")
    if not isinstance(value, str):
        raise TaskError(f"{name} must be a string")
    return value


def _int_field(data: dict[str, object], name: str, *, required: bool = False, default: int = 0) -> int:
    value = data.get(name, default)
    if required and name not in data:
        raise TaskError(f"missing {name}")
    if not isinstance(value, int) or isinstance(value, bool):
        raise TaskError(f"{name} must be an integer")
    return value


def _bool_field(data: dict[str, object], name: str, *, default: bool = False) -> bool:
    value = data.get(name, default)
    if not isinstance(value, bool):
        raise TaskError(f"{name} must be a boolean")
    return value


def _string_list(data: dict[str, object], name: str) -> list[str]:
    value = data.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise TaskError(f"{name} must be a string list")
    return value


def _safe_refs(data: dict[str, object], name: str) -> list[str]:
    refs = _string_list(data, name)
    for ref in refs:
        if ref.startswith("/") or ".." in Path(ref).parts:
            raise TaskError(f"{name} contains an unsafe reference")
    return refs


def _git_links(value: object) -> Iterable[GitLink]:
    if value in (None, []):
        return []
    if not isinstance(value, list):
        raise TaskError("git_links must be a list")
    links = []
    for item in value:
        if not isinstance(item, str) or "@" not in item:
            raise TaskError("git_links entries must be repository@sha")
        repository, sha = item.split("@", 1)
        if not _is_key(repository) or not SHA_RE.fullmatch(sha):
            raise TaskError("invalid git link")
        links.append(GitLink(repository, sha))
    return links


def _is_key(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value))


def _task_to_dict(task: TaskRecord) -> dict[str, object]:
    data = task.__dict__.copy()
    data["labels"] = list(task.labels)
    data["acceptance_criteria"] = list(task.acceptance_criteria)
    data["related_plans"] = list(task.related_plans)
    data["related_runs"] = list(task.related_runs)
    data["git_links"] = [link.__dict__ for link in task.git_links]
    data["depends_on"] = list(task.depends_on)
    return data


TITLE_MAX = 120


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_scope(scope: str) -> tuple[str, str]:
    """`<project-key>` or `@<client-key>`, as (project, client)."""
    if scope.startswith("@"):
        if not _is_key(scope[1:]):
            raise TaskError(f"invalid client key '{scope[1:]}'")
        return "", scope[1:]
    if not PROJECT_RE.fullmatch(scope):
        raise TaskError("invalid project key")
    return scope, ""


def _scope_of(task: TaskRecord) -> str:
    return task.project or f"@{task.client}"


def _scope_dir(source: TaskSource, scope: str) -> Path:
    project, client = parse_scope(scope)
    return source.root / "tasks" / project if project else source.root / "clients" / client / "tasks"


def _scope_from_path(path: str) -> str:
    parts = Path(path).parts
    if len(parts) == 4 and parts[0] == "clients" and parts[2] == "tasks" and _is_key(parts[1]):
        return f"@{parts[1]}"
    return _project_from_path(path)


def registry_clients(source: TaskSource) -> dict[str, str]:
    """Project key to client key, from registry.tsv by header name; empty without one."""
    path = source.root / "registry.tsv"
    if not path.is_file():
        return {}
    lines = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines or "key" not in lines[0] or "client" not in lines[0]:
        return {}
    key, client = lines[0].index("key"), lines[0].index("client")
    return {row[key]: row[client] for row in lines[1:] if len(row) > max(key, client)}


def project_tasks(source: TaskSource, project: str) -> list[TaskRecord]:
    """The tasks of one scope: a project key, or @<client> for the client's own tasks."""
    key, client = parse_scope(project)
    tasks, _ = load_tasks(source)
    return sorted((task for task in tasks if task.project == key and task.client == client), key=lambda task: task.id)


def create_task(
    source: TaskSource,
    project: str,
    title: str,
    priority: str,
    owner: str,
    body: str = "",
    *,
    kind: str = "task",
    due: str = "",
    assignee: str = "",
    labels: Iterable[str] = (),
    parent: str = "",
    remind_at: str = "",
    recur: str = "",
    rank: int = 0,
    depends_on: Iterable[str] = (),
    actor: str = "",
    note: str = "created",
) -> TaskRecord:
    """A new task in `backlog`, with an id from its title that no other task in the source has.

    `project` is the scope: a project key, or @<client> for work that belongs to the client.
    """
    title = " ".join(title.split())
    if not title:
        raise TaskError("a task needs a title")
    if len(title) > TITLE_MAX:
        raise TaskError(f"the title is longer than {TITLE_MAX} characters")
    if priority not in TASK_PRIORITIES:
        raise TaskError(f"unknown priority '{priority}' (one of: {', '.join(sorted(TASK_PRIORITIES))})")
    project_key, client_key = parse_scope(project)
    labels = tuple(labels)
    for label in labels:
        if not _is_key(label):
            raise TaskError(f"invalid label '{label}'")
    existing = load_tasks(source)[0]
    for ref in (parent, *depends_on):
        if ref:
            _require(existing, ref)
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40].strip("_") or "task"
    taken = {task.id for task in existing}
    base = task_id = f"task_{slug}"
    suffix = 2
    while task_id in taken or (_scope_dir(source, project) / f"{task_id}.md").exists():
        task_id = f"{base}_{suffix}"
        suffix += 1
    stamp = _now()
    record = TaskRecord(
        source=source.id, path="", revision="", schema_version=2, id=task_id, project=project_key,
        client=client_key, title=title, status="backlog", priority=priority, owner=owner or "unassigned",
        labels=labels, acceptance_criteria=(), related_plans=(), related_runs=(), git_links=(),
        blocked=False, blocked_reason="", created_at=stamp, updated_at=stamp,
        body=_with_activity(body.strip(), actor, note),
        kind=kind, due=due, assignee=assignee, parent=parent,
        remind_at=_moment(remind_at) if remind_at else "", recur=recur, rank=rank, depends_on=tuple(depends_on),
    )
    return write_task_document(source, project, record)


def set_status(source: TaskSource, project: str, task_id: str, status: str, expected_revision: str | None = None, *, actor: str = "") -> TaskRecord:
    """Moves a task to `status`. With `expected_revision`, refuses when the file changed since."""
    return change_status(source, project, task_id, status, expected_revision, actor=actor)[0]


def change_status(source: TaskSource, project: str, task_id: str, status: str, expected_revision: str | None = None,
                  *, actor: str = "") -> tuple[TaskRecord, TaskRecord | None]:
    """`set_status`, and the next occurrence when recurring work is done."""
    if status not in TASK_STATUSES:
        raise TaskError(f"unknown status '{status}' (one of: {', '.join(sorted(TASK_STATUSES))})")
    task = _task(source, project, task_id, expected_revision)
    body = task.body if status == task.status else _with_activity(task.body, actor, f"status {task.status} -> {status}")
    saved = write_task_document(source, project, replace(task, status=status, body=body, updated_at=_now()), expected_revision=task.revision)
    upcoming = None
    if task.recur and status == "done" and task.status != "done":
        upcoming = _next_occurrence(source, saved, actor)
    return saved, upcoming


def _shift(day: date, recur: str) -> date:
    if recur == "daily":
        return day + timedelta(days=1)
    if recur == "weekly":
        return day + timedelta(days=7)
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def _next_occurrence(source: TaskSource, task: TaskRecord, actor: str) -> TaskRecord:
    """The same work, one period later: dates shifted, checklist cleared, a fresh activity."""
    due = _shift(date.fromisoformat(task.due), task.recur).isoformat() if task.due else ""
    remind_at = ""
    if task.remind_at:
        moment = datetime.fromisoformat(task.remind_at)
        day = _shift(moment.date(), task.recur)
        remind_at = moment.replace(year=day.year, month=day.month, day=day.day).isoformat(timespec="minutes")
    if not due and not remind_at:
        due = _shift(date.today(), task.recur).isoformat()
    description = _split_body(task.body)[0].replace("- [x] ", "- [ ] ").replace("- [X] ", "- [ ] ")
    return create_task(
        source, _scope_of(task), task.title, task.priority, task.owner, description,
        kind=task.kind, due=due, assignee=task.assignee, labels=task.labels, parent=task.parent,
        remind_at=remind_at, recur=task.recur, rank=task.rank, actor=actor, note=f"created; repeats {task.id}",
    )


def create_reminder(source: TaskSource, scope: str, text: str, at: str, owner: str = "", *,
                    recur: str = "", actor: str = "") -> TaskRecord:
    """A reminder is a task of kind `reminder`, due on its day, with the time it should surface."""
    moment = _moment(at)
    return create_task(source, scope, text, "normal", owner or _actor(actor), kind="reminder",
                       due=moment[:10], remind_at=moment, recur=recur, actor=actor)


REASON_MAX = 200


def set_blocked(source: TaskSource, project: str, task_id: str, reason: str | None, expected_revision: str | None = None, *, actor: str = "") -> TaskRecord:
    """Marks a task blocked with `reason`, or unblocks it when `reason` is None."""
    task = _task(source, project, task_id, expected_revision)
    if reason is not None:
        reason = " ".join(reason.split())
        if not reason:
            raise TaskError("a blocked task says why")
        if len(reason) > REASON_MAX:
            raise TaskError(f"the reason is longer than {REASON_MAX} characters")
    note = f"blocked: {reason}" if reason is not None else "unblocked"
    updated = replace(task, blocked=reason is not None, blocked_reason=reason or "", body=_with_activity(task.body, actor, note), updated_at=_now())
    return write_task_document(source, project, updated, expected_revision=task.revision)


# ── Activity and checklist, kept in the task body (ADR-0024) ──────────────────────────

ACTIVITY_HEADING = "## Activity"
ACTIVITY_RE = re.compile(r"- (\S+) (\S+): (.*)")
CHECK_RE = re.compile(r"- \[([ xX])\] (.+)")
TEXT_MAX = 1000


def _actor(actor: str) -> str:
    name = actor or os.environ.get("WS_TASK_ACTOR", "") or "unknown"
    return re.sub(r"\s+", "-", name.strip()) or "unknown"


def _split_body(body: str) -> tuple[str, list[str]]:
    lines = body.split("\n")
    if ACTIVITY_HEADING not in lines:
        return body.strip(), []
    at = lines.index(ACTIVITY_HEADING)
    return "\n".join(lines[:at]).strip(), [line for line in lines[at + 1:] if line.strip()]


def _join_body(description: str, activity: list[str]) -> str:
    parts = [description.strip()] if description.strip() else []
    if activity:
        parts.append(ACTIVITY_HEADING + "\n" + "\n".join(activity))
    return "\n\n".join(parts)


def _with_activity(body: str, actor: str, text: str) -> str:
    description, activity = _split_body(body)
    activity.append(f"- {_now()} {_actor(actor)}: {' '.join(text.split())}")
    return _join_body(description, activity)


def checklist(body: str) -> list[dict[str, object]]:
    description, _ = _split_body(body)
    items = []
    for line in description.splitlines():
        match = CHECK_RE.fullmatch(line.strip())
        if match:
            items.append({"n": len(items) + 1, "done": match.group(1) != " ", "text": match.group(2).strip()})
    return items


def activity(body: str) -> list[dict[str, str]]:
    return [
        {"at": m.group(1), "actor": m.group(2), "text": m.group(3)}
        for m in (ACTIVITY_RE.fullmatch(line.strip()) for line in _split_body(body)[1]) if m
    ]


def _moment(value: str) -> str:
    """A reminder time: ISO 8601, or "YYYY-MM-DD HH:MM" in local time; stored with its offset."""
    try:
        moment = datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError:
        raise TaskError(f"invalid remind_at '{value}' (YYYY-MM-DD HH:MM)") from None
    return (moment if moment.tzinfo else moment.astimezone()).isoformat(timespec="minutes")


def _task(source: TaskSource, project: str, task_id: str, expected_revision: str | None) -> TaskRecord:
    task = next((t for t in project_tasks(source, project) if t.id == task_id), None)
    if task is None:
        raise TaskError(f"no task '{task_id}' in {project}")
    if expected_revision is not None and expected_revision != task.revision:
        raise TaskConflict("revision mismatch: the task changed since it was read")
    return task


def _require(tasks: Iterable[TaskRecord], task_id: str) -> TaskRecord:
    found = next((t for t in tasks if t.id == task_id), None)
    if found is None:
        raise TaskError(f"no task '{task_id}'")
    return found


SCALARS = ("title", "priority", "due", "assignee", "parent", "remind_at", "recur", "kind", "rank")


def edit_task(source: TaskSource, project: str, task_id: str, changes: dict[str, object],
              expected_revision: str | None = None, *, actor: str = "") -> TaskRecord:
    """Changes fields; `none` clears a scalar. Every change is written to the task's activity."""
    task = _task(source, project, task_id, expected_revision)
    updates: dict[str, object] = {}
    notes: list[str] = []
    for name in SCALARS:
        if changes.get(name) is None:
            continue
        value = changes[name]
        if name == "rank":
            value = int(value)  # type: ignore[arg-type]
        elif value == "none":
            value = "task" if name == "kind" else ""
        elif name == "title":
            value = " ".join(str(value).split())
            if not value or len(value) > TITLE_MAX:
                raise TaskError(f"a title has 1 to {TITLE_MAX} characters")
        elif name == "priority" and value not in TASK_PRIORITIES:
            raise TaskError(f"unknown priority '{value}' (one of: {', '.join(sorted(TASK_PRIORITIES))})")
        elif name == "remind_at":
            value = _moment(str(value))
        elif name == "parent":
            if value == task_id:
                raise TaskError("a task cannot be its own parent")
            _require(load_tasks(source)[0], str(value))
        if getattr(task, name) != value:
            updates[name] = value
            notes.append(f"{name} {value}" if value not in ("", 0) else f"{name} cleared")
    labels = list(task.labels)
    for label in changes.get("labels_add") or []:
        if not _is_key(str(label)):
            raise TaskError(f"invalid label '{label}'")
        if label not in labels:
            labels.append(str(label))
            notes.append(f"+label {label}")
    for label in changes.get("labels_rm") or []:
        if label in labels:
            labels.remove(str(label))
            notes.append(f"-label {label}")
    if tuple(labels) != task.labels:
        updates["labels"] = tuple(labels)
    depends = changes.get("depends")
    if depends is not None:
        refs = () if list(depends) == ["none"] else tuple(str(ref) for ref in depends)  # type: ignore[arg-type]
        existing = load_tasks(source)[0]
        for ref in refs:
            if ref == task_id:
                raise TaskError("a task cannot depend on itself")
            _require(existing, ref)
        if refs != task.depends_on:
            updates["depends_on"] = refs
            notes.append(f"depends on {', '.join(refs) or 'nothing'}")
    accept = [" ".join(str(a).split()) for a in changes.get("accept_add") or [] if str(a).strip()]
    if accept:
        updates["acceptance_criteria"] = task.acceptance_criteria + tuple(accept)
        notes.append(f"+{len(accept)} acceptance criteria")
    body = task.body
    items = [" ".join(str(i).split()) for i in changes.get("check_add") or [] if str(i).strip()]
    if items:
        description, log = _split_body(body)
        description = "\n".join(filter(None, [description, *(f"- [ ] {item}" for item in items)]))
        body = _join_body(description, log)
        notes.append(f"+{len(items)} checklist")
    if not notes:
        raise TaskError("nothing to change")
    updated = replace(task, **updates, body=_with_activity(body, actor, "set " + "; ".join(notes)), updated_at=_now())
    return write_task_document(source, project, updated, expected_revision=task.revision)


def comment_task(source: TaskSource, project: str, task_id: str, text: str,
                 expected_revision: str | None = None, *, actor: str = "") -> TaskRecord:
    text = " ".join(text.split())
    if not text:
        raise TaskError("a comment needs text")
    if len(text) > TEXT_MAX:
        raise TaskError(f"the comment is longer than {TEXT_MAX} characters")
    task = _task(source, project, task_id, expected_revision)
    updated = replace(task, body=_with_activity(task.body, actor, text), updated_at=_now())
    return write_task_document(source, project, updated, expected_revision=task.revision)


def check_item(source: TaskSource, project: str, task_id: str, n: int,
               expected_revision: str | None = None, *, actor: str = "") -> TaskRecord:
    """Toggles checklist item `n` (from 1)."""
    task = _task(source, project, task_id, expected_revision)
    description, log = _split_body(task.body)
    lines = description.split("\n")
    seen = 0
    for index, line in enumerate(lines):
        match = CHECK_RE.fullmatch(line.strip())
        if not match:
            continue
        seen += 1
        if seen == n:
            done = match.group(1) == " "
            lines[index] = f"- [{'x' if done else ' '}] {match.group(2).strip()}"
            body = _with_activity(_join_body("\n".join(lines), log), actor, f"{'checked' if done else 'unchecked'}: {match.group(2).strip()}")
            return write_task_document(source, project, replace(task, body=body, updated_at=_now()), expected_revision=task.revision)
    raise TaskError(f"no checklist item {n} (the task has {seen})")


def list_tasks(source: TaskSource, project: str | None = None, *, status: Iterable[str] = (), assignee: str = "",
               label: str = "", due_before: str = "", client: str = "") -> list[TaskRecord]:
    """Tasks of one scope or of all, ranked first (lower rank earlier), then by id. `client`
    keeps the client's own tasks and its projects' tasks, by the registry."""
    if project is not None:
        parse_scope(project)
    if client and not _is_key(client):
        raise TaskError(f"invalid client key '{client}'")
    if due_before:
        _check_date(due_before, "due-before")
    statuses = set(status)
    owners = registry_clients(source) if client else {}
    found = [
        task for task in load_tasks(source)[0]
        if (project is None or _scope_of(task) == project)
        and (not client or task.client == client or owners.get(task.project) == client)
        and (not statuses or task.status in statuses)
        and (not assignee or task.assignee == assignee)
        and (not label or label in task.labels)
        and (not due_before or (task.due and task.due <= due_before))
    ]
    return sorted(found, key=lambda t: (_scope_of(t).lstrip("@"), t.rank == 0, t.rank, t.id))


def task_json(task: TaskRecord, owners: dict[str, str] | None = None,
              everything: Iterable[TaskRecord] | None = None) -> dict[str, object]:
    """A task for agents and the desk: its fields, the description, checklist, and activity.
    `client` is the task's own, or its project's from the registry (`owners`). With
    `everything`, a milestone carries its progress: how many of its children are done."""
    data = _task_to_dict(task)
    if task.kind == "milestone" and everything is not None:
        children = [t for t in everything if t.parent == task.id]
        data["progress"] = {"done": sum(1 for t in children if t.status == "done"), "total": len(children)}
    data["client"] = task.client or (owners or {}).get(task.project, "")
    data["scope"] = _scope_of(task)
    data["description"] = _split_body(task.body)[0]
    data["checklist"] = checklist(task.body)
    data["activity"] = activity(task.body)
    return data


USAGE = """usage:
  ws_tasks.py scan <source-id> <source-root>
  ws_tasks.py list <context-root> <scope>|--all [--json] [--status S]... [--assignee A] [--label L] [--due-before D] [--client C] [--kind K]
  ws_tasks.py remind <context-root> <scope> <text> <owner> --at T [--recur R]

<scope> is a project key, or @<client> for work that belongs to the client itself.
  ws_tasks.py add <context-root> <project> <title> <priority> <owner> [field options]     body on stdin
  ws_tasks.py show <context-root> <project> <task-id> [--json]
  ws_tasks.py edit <context-root> <project> <task-id> [field options] [--revision R]
  ws_tasks.py comment <context-root> <project> <task-id> <text> [--revision R]
  ws_tasks.py check <context-root> <project> <task-id> <n> [--revision R]
  ws_tasks.py status <context-root> <project> <task-id> <status> [<revision>]
  ws_tasks.py block <context-root> <project> <task-id> <revision|-> <reason>
  ws_tasks.py unblock <context-root> <project> <task-id> <revision|->

field options: --due D --assignee A --label L --parent ID --kind K --remind-at T --recur R
  --rank N --depends ID; edit also takes --title, --priority, --label-rm, --check-add,
  --accept-add, and `none` to clear a value"""


def _options(prog: str, edit: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, add_help=False)
    parser.add_argument("--due")
    parser.add_argument("--assignee")
    parser.add_argument("--parent")
    parser.add_argument("--kind")
    parser.add_argument("--remind-at", dest="remind_at")
    parser.add_argument("--recur")
    parser.add_argument("--rank", type=int)
    parser.add_argument("--depends", action="append")
    if edit:
        parser.add_argument("--title")
        parser.add_argument("--priority")
        parser.add_argument("--label-add", "--label", dest="labels_add", action="append")
        parser.add_argument("--label-rm", dest="labels_rm", action="append")
        parser.add_argument("--check-add", dest="check_add", action="append")
        parser.add_argument("--accept-add", dest="accept_add", action="append")
        parser.add_argument("--revision")
    else:
        parser.add_argument("--label", dest="labels", action="append")
    return parser


def _parse(parser: argparse.ArgumentParser, args: list[str]) -> argparse.Namespace:
    try:
        return parser.parse_args(args)
    except SystemExit:
        raise TaskError(f"invalid options for {parser.prog}") from None


def _print_task(task: TaskRecord, as_json: bool, owners: dict[str, str], everything: list[TaskRecord]) -> None:
    if as_json:
        print(json.dumps(task_json(task, owners, everything), indent=2, sort_keys=True))
        return
    data = task_json(task, owners, everything)
    print(f"{task.id}  {task.title}")
    for name in ("project", "client", "kind", "status", "priority", "assignee", "due", "remind_at", "recur", "parent", "rank"):
        value = data.get(name)
        if value not in ("", 0, None) and not (name == "kind" and value == "task"):
            print(f"  {name}: {value}")
    if task.blocked:
        print(f"  blocked: {task.blocked_reason}")
    if task.labels:
        print(f"  labels: {', '.join(task.labels)}")
    if task.depends_on:
        print(f"  depends on: {', '.join(task.depends_on)}")
    if "progress" in data:
        progress = data["progress"]
        print(f"  progress: {progress['done']}/{progress['total']} done")  # type: ignore[index]
    for item in data["checklist"]:  # type: ignore[union-attr]
        print(f"  [{'x' if item['done'] else ' '}] {item['n']}. {item['text']}")
    if data["description"]:
        print("\n" + str(data["description"]))
    for entry in data["activity"][-5:]:  # type: ignore[index]
        print(f"  {entry['at']} {entry['actor']}: {entry['text']}")
    print(f"  revision: {task.revision}")


def _report(task: TaskRecord) -> int:
    print(f"task {task.id} {task.status} {task.revision}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "scan":
        source = load_source(argv[1], argv[2])
        tasks, legacy = load_tasks(source)
        print(to_json(tasks, legacy), end="")
        return 0
    if len(argv) == 3 and argv[0] == "list" and not argv[2].startswith("--"):
        for task in list_tasks(load_source("context", argv[1]), argv[2]):
            blocked = f"\t[blocked] {task.blocked_reason}" if task.blocked else ""
            print(f"{task.id}\t{task.status}\t{task.priority}\t{task.title}{blocked}")
        return 0
    if len(argv) >= 3 and argv[0] == "list":
        parser = argparse.ArgumentParser(prog="ws task list", add_help=False)
        parser.add_argument("--json", action="store_true")
        parser.add_argument("--status", action="append", default=[])
        parser.add_argument("--assignee", default="")
        parser.add_argument("--label", default="")
        parser.add_argument("--due-before", dest="due_before", default="")
        parser.add_argument("--client", default="")
        parser.add_argument("--kind", default="")
        project = None if argv[2] == "--all" else argv[2]
        opts = _parse(parser, argv[3:])
        source = load_source("context", argv[1])
        found = list_tasks(source, project, status=opts.status, assignee=opts.assignee,
                           label=opts.label, due_before=opts.due_before, client=opts.client)
        if opts.kind:
            found = [task for task in found if task.kind == opts.kind]
        if opts.json:
            owners, everything = registry_clients(source), load_tasks(source)[0]
            print(json.dumps({"tasks": [task_json(task, owners, everything) for task in found]}, indent=2, sort_keys=True))
        else:
            for task in found:
                due = f"\tdue {task.due}" if task.due else ""
                print(f"{_scope_of(task)}\t{task.id}\t{task.status}\t{task.priority}\t{task.title}{due}")
        return 0
    if len(argv) >= 5 and argv[0] == "remind":
        parser = argparse.ArgumentParser(prog="ws remind", add_help=False)
        parser.add_argument("--at", required=True)
        parser.add_argument("--recur", default="")
        opts = _parse(parser, argv[5:])
        return _report(create_reminder(load_source("context", argv[1]), argv[2], argv[3], opts.at, argv[4], recur=opts.recur))
    if len(argv) >= 6 and argv[0] == "add":
        opts = _parse(_options("ws task add"), argv[6:])
        record = create_task(
            load_source("context", argv[1]), argv[2], argv[3], argv[4], argv[5], sys.stdin.read(),
            kind=opts.kind or "task", due=opts.due or "", assignee=opts.assignee or "", labels=opts.labels or (),
            parent=opts.parent or "", remind_at=opts.remind_at or "", recur=opts.recur or "", rank=opts.rank or 0,
            depends_on=opts.depends or (),
        )
        return _report(record)
    if len(argv) in (4, 5) and argv[0] == "show":
        if len(argv) == 5 and argv[4] != "--json":
            raise TaskError("usage: ws task show <project-key> <task-id> [--json]")
        source = load_source("context", argv[1])
        _print_task(_task(source, argv[2], argv[3], None), len(argv) == 5, registry_clients(source), load_tasks(source)[0])
        return 0
    if len(argv) >= 4 and argv[0] == "edit":
        opts = _parse(_options("ws task edit", edit=True), argv[4:])
        changes = {key: value for key, value in vars(opts).items() if key != "revision"}
        changes["depends"] = changes.pop("depends", None)
        return _report(edit_task(load_source("context", argv[1]), argv[2], argv[3], changes, opts.revision))
    if len(argv) >= 5 and argv[0] in ("comment", "check"):
        parser = argparse.ArgumentParser(prog=f"ws task {argv[0]}", add_help=False)
        parser.add_argument("--revision")
        opts = _parse(parser, argv[5:])
        source = load_source("context", argv[1])
        if argv[0] == "comment":
            return _report(comment_task(source, argv[2], argv[3], argv[4], opts.revision))
        if not argv[4].isdigit():
            raise TaskError("a checklist item is a number, from 1")
        return _report(check_item(source, argv[2], argv[3], int(argv[4]), opts.revision))
    if len(argv) in (5, 6) and argv[0] == "status":
        revision = argv[5] if len(argv) == 6 else None
        record, upcoming = change_status(load_source("context", argv[1]), argv[2], argv[3], argv[4], revision)
        print(f"task {record.id} {record.status} {record.revision}")
        if upcoming:
            print(f"next {upcoming.id} {upcoming.status} {upcoming.revision}")
        return 0
    if len(argv) in (5, 6) and argv[0] in ("block", "unblock") and (argv[0] == "block") == (len(argv) == 6):
        revision = None if argv[4] == "-" else argv[4]
        reason = argv[5] if argv[0] == "block" else None
        record = set_blocked(load_source("context", argv[1]), argv[2], argv[3], reason, revision)
        print(f"task {record.id} {'blocked' if record.blocked else 'unblocked'} {record.revision}")
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except TaskError as error:
        print(f"workspace tasks: {error}", file=sys.stderr)
        raise SystemExit(1)
