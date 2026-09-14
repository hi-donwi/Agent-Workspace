"""Local web-control shell for Agent Workspace.

M2 is intentionally small: a read-only local HTTP shell that exposes project and context
summaries from the configured workspace. It requires a per-process bearer token so another
local page cannot read context by guessing the port.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import unquote, urlparse


PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
MAX_CONTEXT_BYTES = 32768


class WebError(ValueError):
    status = HTTPStatus.BAD_REQUEST


class NotFound(WebError):
    status = HTTPStatus.NOT_FOUND


class Unauthorized(WebError):
    status = HTTPStatus.UNAUTHORIZED


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


def route(state: WorkspaceWebState, method: str, raw_path: str, headers: dict[str, str]) -> tuple[int, str, bytes]:
    parsed = urlparse(raw_path)
    path = parsed.path
    if method != "GET":
        raise WebError("only GET is supported")
    if path == "/":
        return HTTPStatus.OK, "text/html; charset=utf-8", index_html().encode()
    _require_token(state, headers)
    if path == "/api/projects":
        return _json({"projects": [_project_to_dict(project) for project in load_projects(state)]})
    prefix = "/api/projects/"
    suffix = "/context"
    if path.startswith(prefix) and path.endswith(suffix):
        key = unquote(path[len(prefix) : -len(suffix)])
        return _json(project_context(state, key))
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


def index_html() -> str:
    return """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Agent Workspace Control</title></head>
<body>
  <main>
    <h1>Agent Workspace Control</h1>
    <p>Local read-only shell. API access requires the startup bearer token.</p>
  </main>
</body>
</html>
"""


def serve(root: str | Path, host: str, port: int, token: str | None = None) -> None:
    state = build_state(root, token=token)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib callback name
            try:
                status, content_type, body = route(state, "GET", self.path, {k.lower(): v for k, v in self.headers.items()})
            except WebError as error:
                status, content_type, body = _json_error(error.status, str(error))
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    actual_host, actual_port = server.server_address
    print(f"Agent Workspace Control: http://{actual_host}:{actual_port}/")
    print(f"Bearer token: {state.token}")
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


def _json(data: object) -> tuple[int, str, bytes]:
    return HTTPStatus.OK, "application/json; charset=utf-8", (json.dumps(data, indent=2, sort_keys=True) + "\n").encode()


def _json_error(status: HTTPStatus, message: str) -> tuple[int, str, bytes]:
    return int(status), "application/json; charset=utf-8", (json.dumps({"error": message}) + "\n").encode()


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
