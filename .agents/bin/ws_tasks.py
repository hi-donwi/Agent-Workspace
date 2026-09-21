"""Workspace task/source parsing for the local web-control MVP.

The module deliberately uses only the Python standard library. It is the first slice of
the local project-management feature: read task documents safely, keep source identity
explicit, and reject malformed or ambiguous records before any UI writes are added.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Iterable


TASK_STATUSES = {"backlog", "ready", "in_progress", "review", "done"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
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
    if not tasks_root.exists():
        return tasks, legacy
    for candidate in tasks_root.rglob("*"):
        if candidate.is_symlink():
            raise TaskError("symlinks are not allowed in task source")
    for path in sorted(tasks_root.glob("**/*.md")):
        if not path.is_file():
            continue
        relative = _contained(source.root, path)
        text = path.read_text(encoding="utf-8")
        revision = _revision(path)
        if text.startswith("---\n"):
            task = parse_task_document(source.id, relative, revision, text)
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
    if schema_version != 1:
        raise TaskError("unsupported task schema_version")
    task_id = _string_field(metadata, "id", required=True)
    if not TASK_ID_RE.fullmatch(task_id):
        raise TaskError("invalid task id")
    project = _string_field(metadata, "project", required=True)
    if not PROJECT_RE.fullmatch(project):
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
    )


def parse_legacy_candidates(source: str, path: str, revision: str, text: str) -> list[LegacyCandidate]:
    candidates: list[LegacyCandidate] = []
    project = _project_from_path(path)
    for index, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"\s*- \[[ xX]\]\s+(.+?)\s*$", line)
        if match:
            candidates.append(LegacyCandidate(source, path, revision, project, match.group(1), index))
    return candidates
 
 
def serialize_task_document(task: TaskRecord) -> str:
    if task.schema_version != 1:
        raise TaskError("unsupported task schema_version")
    if not TASK_ID_RE.fullmatch(task.id):
        raise TaskError("invalid task id")
    if not PROJECT_RE.fullmatch(task.project):
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
        f"schema_version: {task.schema_version}",
        f"id: {task.id}",
        f"project: {task.project}",
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
    if not PROJECT_RE.fullmatch(project):
        raise TaskError("invalid project key")
    if task.project != project:
        raise TaskError(f"task project '{task.project}' does not match '{project}'")
    if not TASK_ID_RE.fullmatch(task.id):
        raise TaskError(f"invalid task id '{task.id}'")

    tasks_dir = source.root / "tasks" / project
    tasks_dir.mkdir(parents=True, exist_ok=True)
    if task.path:
        target_path = (source.root / task.path).resolve()
        relative_path = _contained(source.root, target_path)
        if _project_from_path(relative_path) != project:
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

    new_rev = _revision(target_path)
    return TaskRecord(
        source=source.id,
        path=relative_path,
        revision=new_rev,
        schema_version=task.schema_version,
        id=task.id,
        project=task.project,
        title=task.title,
        status=task.status,
        priority=task.priority,
        owner=task.owner,
        labels=task.labels,
        acceptance_criteria=task.acceptance_criteria,
        related_plans=task.related_plans,
        related_runs=task.related_runs,
        git_links=task.git_links,
        blocked=task.blocked,
        blocked_reason=task.blocked_reason,
        created_at=task.created_at,
        updated_at=task.updated_at,
        body=task.body,
    )


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
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] != "scan":
        print("usage: ws_tasks.py scan <source-id> <source-root>", file=sys.stderr)
        return 2
    source = load_source(argv[1], argv[2])
    tasks, legacy = load_tasks(source)
    print(to_json(tasks, legacy), end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except TaskError as error:
        print(f"workspace tasks: {error}", file=sys.stderr)
        raise SystemExit(1)
