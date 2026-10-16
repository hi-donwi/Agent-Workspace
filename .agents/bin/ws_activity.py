"""What an agent session is doing right now, for the desk (ADR-0023).

One file per session, replaced on every change:

    <root>/.local/agent/activity/<session>.json
    {"version": 1, "session": "...", "project": "...", "tool": "...",
     "state": "reading", "detail": "Read", "at": "2026-10-16T17:40:00+07:00"}

A record holds names only - a tool name, never its input, a prompt, or output.
Writes are atomic (temporary file and rename) and mode 0600; `.local/` is never
committed or pushed.

Commands (standard library only, so a hook costs one Python start-up):

    ws_activity.py set  <root> <session> <project> <tool> <state> [detail]
    ws_activity.py off  <root> <session>
    ws_activity.py hook <root>        Claude Code hook event on stdin

`hook` never fails and never blocks a tool: anything it cannot use is ignored.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile

VERSION = 1
STATES = ("idle", "working", "thinking", "reading", "typing", "running", "learning", "waiting", "warning")
KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
DETAIL_MAX = 120

# Claude Code tool names -> the pose the desk draws. Anything else is `working`.
CLAUDE_TOOLS = {
    "Read": "reading", "Grep": "reading", "Glob": "reading", "LS": "reading",
    "NotebookRead": "reading", "WebFetch": "reading", "WebSearch": "reading",
    "Edit": "typing", "MultiEdit": "typing", "Write": "typing", "NotebookEdit": "typing",
    "Bash": "running", "BashOutput": "running", "KillShell": "running",
    "Skill": "learning", "ToolSearch": "learning",
    "TodoWrite": "thinking",
}


def slug(value):
    """The same normalisation `ws` applies to session ids and agent names."""
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text[:48]


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def activity_dir(root):
    return Path(root) / ".local" / "agent" / "activity"


def record_path(root, session):
    session = slug(session)
    if not session:
        raise ValueError("empty session id")
    return activity_dir(root) / f"{session}.json"


def write_record(root, session, project, tool, state, detail=""):
    if state not in STATES:
        raise ValueError(f"unknown state '{state}' (one of: {', '.join(STATES)})")
    if not KEY_RE.fullmatch(project):
        raise ValueError(f"invalid project key '{project}'")
    record = {
        "version": VERSION,
        "session": slug(session),
        "project": project,
        "tool": slug(tool) or "agent",
        "state": state,
        "detail": " ".join(detail.split())[:DETAIL_MAX],
        "at": now_iso(),
    }
    target = record_path(root, session)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle)
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        with_suppress_unlink(tmp)
        raise
    return record


def with_suppress_unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def remove_record(root, session):
    with_suppress_unlink(record_path(root, session))


def read_conf(root):
    conf = {}
    path = Path(root) / "workspace.conf"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if "=" in line:
                name, value = line.split("=", 1)
                conf[name.strip()] = value.strip()
    return conf


def context_dir(root):
    configured = read_conf(root).get("context_dir") or "context"
    path = Path(configured)
    return path if path.is_absolute() else Path(root) / path


def open_clock(root, session):
    """This session's open agent clock, if `ws agent in` or the auto hook opened one."""
    works = context_dir(root) / "works"
    suffix = f"-{slug(session)}.json"
    if not works.is_dir():
        return None
    for path in works.glob(".open-agent-*.json"):
        if path.name.endswith(suffix):
            return path
    return None


def registry_project(root, cwd):
    """The registered project whose folder holds `cwd` - the longest match, as `ws` does."""
    registry = context_dir(root) / "registry.tsv"
    if not cwd or not registry.is_file():
        return None
    here = Path(cwd).resolve()
    base = Path(root).resolve()
    lines = [line for line in registry.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return None
    header = lines[0].split("\t")
    if "key" not in header or "folder" not in header:
        return None
    key_at, folder_at = header.index("key"), header.index("folder")
    best, best_len = None, 0
    for line in lines[1:]:
        cells = line.split("\t")
        if len(cells) <= max(key_at, folder_at):
            continue
        key, folder = cells[key_at].strip(), cells[folder_at].strip()
        if not KEY_RE.fullmatch(key) or folder in ("", "-"):
            continue
        folder_path = (base / folder).resolve()
        if (here == folder_path or folder_path in here.parents) and len(folder) > best_len:
            best, best_len = key, len(folder)
    return best


def session_project(root, session, cwd=""):
    """The project a session is on: its bind, its open clock, the registry folder holding
    `cwd`, then `default_project` - the order `ws agent auto` uses. None if nothing says."""
    bind = Path(root) / ".local" / "sessions" / slug(session) / "bind"
    if bind.is_file():
        for line in bind.read_text(encoding="utf-8").splitlines():
            if line.startswith("project="):
                key = line.split("=", 1)[1].strip()
                if KEY_RE.fullmatch(key):
                    return key
    clock = open_clock(root, session)
    if clock is not None:
        try:
            key = json.loads(clock.read_text(encoding="utf-8")).get("project", "")
        except (OSError, ValueError):
            key = ""
        if isinstance(key, str) and KEY_RE.fullmatch(key):
            return key
    key = registry_project(root, cwd) or read_conf(root).get("default_project", "")
    return key if key and KEY_RE.fullmatch(key) else None


def hook_tool():
    """The agent name `ws` would record for this process (see agent_id in ws)."""
    if os.environ.get("WS_AGENT"):
        return slug(os.environ["WS_AGENT"])
    if os.environ.get("CLAUDECODE"):
        return "claude"
    return "agent"


def event_state(event):
    """(state, detail) for a Claude Code hook event, ('off', '') to remove, or None to ignore."""
    name = event.get("hook_event_name", "")
    tool = event.get("tool_name", "") if isinstance(event.get("tool_name"), str) else ""
    if name == "UserPromptSubmit":
        return "thinking", "prompt"
    if name == "PreToolUse" and tool:
        return CLAUDE_TOOLS.get(tool, "working"), tool
    if name == "PostToolUse" and tool:
        return "thinking", f"after {tool}"
    if name == "Notification":
        message = event.get("message", "")
        return "waiting", message if isinstance(message, str) and message else "needs input"
    if name == "PreCompact":
        return "thinking", "compacting"
    if name == "SessionStart":
        return "idle", "session started"
    if name == "Stop":
        return "idle", "turn finished"
    if name == "SessionEnd":
        return "off", ""
    return None


def env_session():
    """The session id `ws` would use (see session_id in ws), for events without one."""
    for name in ("WS_SESSION_ID", "GROK_SESSION_ID", "GROK_SESSION", "CLAUDE_SESSION_ID",
                 "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CURSOR_TRACE_ID"):
        if os.environ.get(name):
            return os.environ[name]
    return ""


def run_hook(root, stdin_text):
    try:
        event = json.loads(stdin_text or "{}")
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    mapped = event_state(event)
    if mapped is None:
        return
    session = env_session() or (event.get("session_id") if isinstance(event.get("session_id"), str) else "")
    if not slug(session):
        return
    state, detail = mapped
    if state == "off":
        remove_record(root, session)
        return
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    project = session_project(root, session, cwd)
    if project is None:
        return
    write_record(root, session, project, hook_tool(), state, detail)
    clock = open_clock(root, session)
    if clock is not None:
        # The same heartbeat `ws` gives an open clock on every call.
        os.utime(clock, None)


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    command, root = argv[1], argv[2]
    if command == "hook":
        try:
            run_hook(root, sys.stdin.read())
        except Exception:  # noqa: BLE001 - a hook must never break the editor session
            pass
        return 0
    try:
        if command == "set" and len(argv) >= 7:
            write_record(root, argv[3], argv[4], argv[5], argv[6], " ".join(argv[7:]))
            return 0
        if command == "off" and len(argv) == 4:
            remove_record(root, argv[3])
            return 0
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
