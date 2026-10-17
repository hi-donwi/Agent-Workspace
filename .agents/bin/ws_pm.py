"""Today and alerts for the workspace's project management (ADR-0024).

Alerts are computed from the records every time - tasks in context/, local approvals and
agent activity records in .local/agent/ - with thresholds from context/pm.json. Only an
operator's snoozes are stored, in .local/pm/snoozes.json, because they are that person's
and that machine's. Standard library only, like the rest of ws.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from ws_tasks import ACTIVITY_RE, TaskError, TaskRecord, activity, load_source, load_tasks, registry_clients, task_json

DEFAULTS = {
    "stale_days": 5,
    "blocked_days": 2,
    "review_days": 2,
    "reminder_lead_minutes": 15,
    "agent_waiting_hours": 2,
}

# Who waits for whom comes first, then dates, then work that has stalled.
ORDER = {"approval": 0, "agent": 1, "overdue": 2, "reminder": 3, "due_today": 4, "review": 5, "blocked": 6, "stale": 7}
SEVERITY = {"approval": "attn", "agent": "attn", "overdue": "warn", "reminder": "attn", "due_today": "attn",
            "review": "info", "blocked": "info", "stale": "info"}
SNOOZE_FOR = re.compile(r"(\d+)([hdw])")


@dataclass(frozen=True)
class Alert:
    id: str
    kind: str
    severity: str
    scope: str
    client: str
    title: str
    detail: str
    ref: str
    at: str


def thresholds(context_root: str | Path) -> dict[str, int]:
    """context/pm.json over the defaults; a missing or broken file leaves the defaults."""
    values = dict(DEFAULTS)
    path = Path(context_root) / "pm.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return values
        for key in DEFAULTS:
            if isinstance(data.get(key), int) and not isinstance(data.get(key), bool) and data[key] >= 0:
                values[key] = data[key]
    return values


def _moment(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


def _blocked_since(task: TaskRecord) -> datetime | None:
    entries = [entry for entry in activity(task.body) if entry["text"].startswith("blocked:")]
    return _moment(entries[-1]["at"]) if entries else _moment(task.updated_at)


def _task_alerts(task: TaskRecord, client: str, now: datetime, limits: dict[str, int]) -> list[Alert]:
    if task.status == "done":
        return []
    scope = task.project or f"@{task.client}"
    found: list[tuple[str, str, str]] = []
    today_ = now.date()
    if task.remind_at:
        moment = _moment(task.remind_at)
        if moment and moment <= now + timedelta(minutes=limits["reminder_lead_minutes"]):
            local = moment.astimezone(now.tzinfo)
            when = local.strftime("%H:%M") if local.date() == today_ else local.strftime("%Y-%m-%d %H:%M")
            found.append(("reminder", f"at {when}", task.remind_at))
    elif task.due:
        due = date.fromisoformat(task.due)
        if due < today_:
            found.append(("overdue", f"due {task.due} ({_days((today_ - due).days)} ago)", task.due))
        elif due == today_:
            found.append(("due_today", "due today", task.due))
    updated = _moment(task.updated_at)
    if task.blocked:
        since = _blocked_since(task)
        if since and now - since >= timedelta(days=limits["blocked_days"]):
            found.append(("blocked", f"blocked {_days((now - since).days)}: {task.blocked_reason}", since.isoformat()))
    elif updated and task.status == "in_progress" and now - updated >= timedelta(days=limits["stale_days"]):
        found.append(("stale", f"in progress, untouched for {_days((now - updated).days)}", task.updated_at))
    elif updated and task.status == "review" and now - updated >= timedelta(days=limits["review_days"]):
        found.append(("review", f"awaiting review for {_days((now - updated).days)}", task.updated_at))
    return [Alert(f"{kind}:{scope}:{task.id}", kind, SEVERITY[kind], scope, client, task.title, detail, task.id, at)
            for kind, detail, at in found]


def _approval_alerts(workspace_root: Path, owners: dict[str, str], now: datetime) -> list[Alert]:
    base = workspace_root / ".local" / "agent" / "approvals"
    if not base.is_dir():
        return []
    alerts = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()):
        requested: dict[str, dict] = {}
        decided: set[str] = set()
        for log in sorted(folder.glob("*.jsonl")):
            for line in log.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "requested" and isinstance(event.get("id"), str):
                    requested[event["id"]] = event
                elif event.get("type") in ("approved", "denied") and isinstance(event.get("id"), str):
                    decided.add(event["id"])
        for request_id, event in requested.items():
            expires = _moment(str(event.get("expiresAt", "")))
            asked = _moment(str(event.get("requestedAt", "")))
            if request_id in decided or not expires or expires <= now:
                continue
            project = str(event.get("project") or folder.name)
            minutes = int((now - asked).total_seconds() // 60) if asked else 0
            alerts.append(Alert(f"approval:{project}:{request_id}", "approval", "attn", project, owners.get(project, ""),
                                f"Approve {event.get('action', 'an action')}", f"waiting {minutes} min", request_id,
                                str(event.get("requestedAt", ""))))
    return alerts


def _agent_alerts(workspace_root: Path, owners: dict[str, str], now: datetime, limits: dict[str, int]) -> list[Alert]:
    base = workspace_root / ".local" / "agent" / "activity"
    if not base.is_dir():
        return []
    alerts = []
    for path in sorted(base.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        state, at = record.get("state"), _moment(str(record.get("at", "")))
        if state not in ("waiting", "warning") or not at or now - at > timedelta(hours=limits["agent_waiting_hours"]):
            continue
        project, session = str(record.get("project", "")), str(record.get("session", path.stem))
        verb = "needs you" if state == "waiting" else "reports a problem"
        alerts.append(Alert(f"agent:{project}:{session}", "agent", "attn" if state == "waiting" else "warn", project,
                            owners.get(project, ""), f"{record.get('tool', 'agent')} {verb}", str(record.get("detail", "")),
                            session, str(record.get("at", ""))))
    return alerts


def compute_alerts(context_root: str | Path, workspace_root: str | Path, now: datetime, *,
                   scope: str | None = None, client: str = "") -> list[Alert]:
    """Every alert, snoozed or not, ordered by urgency; `scope` is a project key or @<client>."""
    source = load_source("context", context_root)
    owners = registry_clients(source)
    limits = thresholds(context_root)
    alerts: list[Alert] = []
    for task in load_tasks(source)[0]:
        alerts.extend(_task_alerts(task, task.client or owners.get(task.project, ""), now, limits))
    alerts.extend(_approval_alerts(Path(workspace_root), owners, now))
    alerts.extend(_agent_alerts(Path(workspace_root), owners, now, limits))
    if scope:
        alerts = [a for a in alerts if a.scope == scope]
    if client:
        alerts = [a for a in alerts if a.client == client]
    return sorted(alerts, key=lambda a: (ORDER[a.kind], a.at, a.id))


def _snooze_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root) / ".local" / "pm" / "snoozes.json"


def snoozes(workspace_root: str | Path) -> dict[str, str]:
    path = _snooze_path(workspace_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}


def snooze(workspace_root: str | Path, alert_id: str, until: datetime | None, now: datetime) -> None:
    """Hides `alert_id` until `until`; None lifts it. Expired snoozes are dropped on every write."""
    if not re.fullmatch(r"[a-z_]+:@?[a-z0-9][a-z0-9_-]*:[A-Za-z0-9._-]+", alert_id):
        raise TaskError(f"invalid alert id '{alert_id}'")
    current = {k: v for k, v in snoozes(workspace_root).items() if (_moment(v) or now) > now}
    if until is None:
        current.pop(alert_id, None)
    else:
        if until.tzinfo is None:
            until = until.astimezone()
        current[alert_id] = until.isoformat(timespec="minutes")
    path = _snooze_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".snoozes.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(current, handle, indent=2, sort_keys=True)
    os.replace(temp, path)


def active_alerts(context_root: str | Path, workspace_root: str | Path, now: datetime, **filters: str) -> list[Alert]:
    hidden = {k for k, v in snoozes(workspace_root).items() if (_moment(v) or now) > now}
    return [a for a in compute_alerts(context_root, workspace_root, now, **filters) if a.id not in hidden]  # type: ignore[arg-type]


def today(context_root: str | Path, workspace_root: str | Path, now: datetime, **filters: str) -> dict[str, object]:
    """The operator's day: counts per signal, what needs doing in order, and work in hand."""
    alerts = active_alerts(context_root, workspace_root, now, **filters)
    count = lambda *kinds: sum(1 for a in alerts if a.kind in kinds)  # noqa: E731
    source = load_source("context", context_root)
    owners = registry_clients(source)
    scope, client = filters.get("scope"), filters.get("client", "")
    in_hand = [
        task_json(task, owners) for task in load_tasks(source)[0]
        if task.status == "in_progress"
        and (not scope or (task.project or f"@{task.client}") == scope)
        and (not client or (task.client or owners.get(task.project, "")) == client)
    ]
    return {
        "date": now.date().isoformat(),
        "signals": {
            "overdue": count("overdue"), "due_today": count("due_today"), "waiting": count("approval", "agent"),
            "blocked": count("blocked"), "stale": count("stale"), "review": count("review"), "reminders": count("reminder"),
        },
        "items": [asdict(a) for a in alerts],
        "in_progress": sorted(in_hand, key=lambda t: (str(t["scope"]), str(t["id"]))),
    }


# ── Client dossier (ADR-0024) ─────────────────────────────────────────────────────────
# What an operator or an agent may read about a client. contacts.md and commercial.md are
# restricted: only whether they exist is reported, never a word of what they say.
RESTRICTED = ("contacts", "commercial")
FIELD_RE = re.compile(r"- \*\*([^*]+):\*\*[ \t]*(.*)")
CLIENT_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _client_dir(context_root: str | Path, client: str) -> Path:
    if not CLIENT_KEY_RE.fullmatch(client):
        raise TaskError(f"invalid client key '{client}'")
    folder = Path(context_root) / "clients" / client
    if not (folder / "client.md").is_file():
        raise TaskError(f"no client '{client}'")
    return folder


def _section(text: str, heading: str) -> str:
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip().lower() == f"## {heading}".lower())
    except StopIteration:
        return ""
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body).strip()


def interactions(context_root: str | Path, client: str) -> list[dict[str, str]]:
    """The client's interaction log, newest first."""
    path = _client_dir(context_root, client) / "log.md"
    if not path.is_file():
        return []
    found = [m for m in (ACTIVITY_RE.fullmatch(line.strip()) for line in path.read_text(encoding="utf-8").splitlines()) if m]
    return [{"at": m.group(1), "actor": m.group(2), "text": m.group(3)} for m in reversed(found)]


def log_interaction(context_root: str | Path, client: str, text: str, actor: str = "") -> str:
    """Appends one line to clients/<c>/log.md - a meeting, a call, an agreement."""
    text = " ".join(text.split())
    if not text:
        raise TaskError("an interaction needs text")
    if len(text) > 1000:
        raise TaskError("the entry is longer than 1000 characters")
    path = _client_dir(context_root, client) / "log.md"
    who = re.sub(r"\s+", "-", (actor or os.environ.get("WS_TASK_ACTOR", "") or "unknown").strip())
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    if not path.exists():
        path.write_text(f"# {client} — interactions\n\nAppend-only: `ws client log {client} \"what happened\"`. "
                        "Never write contact details or commercial terms here.\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"- {stamp} {who}: {text}\n")
    return stamp


def client_dossier(context_root: str | Path, workspace_root: str | Path, client: str, now: datetime) -> dict[str, object]:
    """Profile, projects, open work, alerts, and interactions - never the restricted records."""
    folder = _client_dir(context_root, client)
    text = (folder / "client.md").read_text(encoding="utf-8")
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), client)
    fields = {m.group(1).strip(): m.group(2).strip() for m in (FIELD_RE.fullmatch(line.strip()) for line in text.splitlines()) if m}
    source = load_source("context", context_root)
    owners = registry_clients(source)
    tasks = load_tasks(source)[0]
    today_ = now.date().isoformat()
    open_tasks = [t for t in tasks if t.status != "done" and (t.client == client or owners.get(t.project) == client)]
    projects = [
        {"key": key, "open": sum(1 for t in open_tasks if t.project == key),
         "overdue": sum(1 for t in open_tasks if t.project == key and t.due and t.due < today_)}
        for key, owner in sorted(owners.items()) if owner == client
    ]
    return {
        "client": client,
        "profile": {"title": title, "fields": fields, "about": _section(text, "What they are"),
                    "working_agreement": _section(text, "Working agreement"), "stakeholders": _section(text, "Stakeholders")},
        "projects": projects,
        "tasks": [task_json(t, owners) for t in sorted(open_tasks, key=lambda t: (t.due or "9999", t.id)) if t.client == client],
        "open": len(open_tasks),
        "overdue": sum(1 for t in open_tasks if t.due and t.due < today_),
        "alerts": len(active_alerts(context_root, workspace_root, now, client=client)),
        "interactions": interactions(context_root, client)[:10],
        "restricted": {name: (folder / f"{name}.md").is_file() for name in RESTRICTED},
    }


# ── Work digest for a session pack (ADR-0024) ─────────────────────────────────────────
DIGEST_LIMIT = 5


def _line(task: TaskRecord, everything: list[TaskRecord]) -> str:
    bits = []
    if task.assignee:
        bits.append(task.assignee)
    if task.priority in ("high", "urgent"):
        bits.append(task.priority)
    if task.due:
        bits.append(f"due {task.due}")
    items = task_json(task)["checklist"]
    if items:
        bits.append(f"{sum(1 for i in items if i['done'])}/{len(items)} checklist")  # type: ignore[union-attr]
    if task.kind == "milestone":
        children = [t for t in everything if t.parent == task.id]
        bits.append(f"{sum(1 for t in children if t.status == 'done')}/{len(children)} done")
    if task.blocked:
        bits.append(f"blocked: {task.blocked_reason}")
    detail = f" ({', '.join(bits)})" if bits else ""
    return f"- `{task.id}` {task.title}{detail}"


def digest(context_root: str | Path, workspace_root: str | Path, project: str, now: datetime) -> str:
    """The bound project's work, and its client's own, for CONTEXT.md - nothing of any other
    client, and no restricted record. Short: five per group, the rest by count."""
    source = load_source("context", context_root)
    owners = registry_clients(source)
    client = owners.get(project, "")
    everything = load_tasks(source)[0]
    mine = [t for t in everything if t.status != "done" and (t.project == project or (client and t.client == client))]
    soon = (now.date() + timedelta(days=7)).isoformat()
    groups = [
        ("In progress", [t for t in mine if t.project == project and t.status == "in_progress"]),
        ("In review", [t for t in mine if t.project == project and t.status == "review"]),
        ("Ready", [t for t in mine if t.project == project and t.status == "ready"]),
        ("Blocked", [t for t in mine if t.project == project and t.blocked]),
        ("Due within 7 days or overdue", [t for t in mine if t.project == project and t.due and t.due <= soon]),
        ("Milestones", [t for t in mine if t.project == project and t.kind == "milestone"]),
    ]
    if client:
        groups.append((f"Client `{client}`'s own open work", [t for t in mine if t.client == client]))
    lines = [f"## Work for {project}", "",
             f"Generated at bind, {now.isoformat(timespec='minutes')}. Live: `ws today --scope {project}`, "
             f"`ws task list {project} --json`, `ws task show {project} <task-id>`."]
    for title, tasks in groups:
        if not tasks:
            continue
        ordered = sorted(tasks, key=lambda t: (t.rank == 0, t.rank, t.due or "9999", t.id))
        lines += ["", f"{title}:"] + [_line(t, everything) for t in ordered[:DIGEST_LIMIT]]
        if len(ordered) > DIGEST_LIMIT:
            lines.append(f"- ... and {len(ordered) - DIGEST_LIMIT} more")
    waiting = [a for a in active_alerts(context_root, workspace_root, now, scope=project) if a.kind in ("approval", "agent")]
    if waiting:
        lines += ["", f"Waiting for a person: {len(waiting)} ({', '.join(a.title for a in waiting[:3])})"]
    backlog = sum(1 for t in mine if t.project == project and t.status == "backlog")
    lines += ["", f"Open in {project}: {sum(1 for t in mine if t.project == project)} ({backlog} in backlog)."]
    return "\n".join(lines) + "\n"


def _until(spec: str, now: datetime) -> datetime:
    match = SNOOZE_FOR.fullmatch(spec)
    if match:
        amount, unit = int(match.group(1)), match.group(2)
        return now + {"h": timedelta(hours=amount), "d": timedelta(days=amount), "w": timedelta(weeks=amount)}[unit]
    try:
        moment = datetime.fromisoformat(spec.strip().replace(" ", "T"))
    except ValueError:
        raise TaskError(f"snooze for 1h, 1d, 1w, or until \"YYYY-MM-DD HH:MM\", not '{spec}'") from None
    return moment if moment.tzinfo else moment.astimezone()


def _print_alerts(alerts: list[Alert]) -> None:
    for a in alerts:
        print(f"[{a.severity}] {a.kind:<9} {a.scope:<16} {a.title} - {a.detail}  ({a.id})")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ws_pm.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("alerts", "today"):
        p = sub.add_parser(name)
        p.add_argument("context_root")
        p.add_argument("workspace_root")
        p.add_argument("--json", action="store_true")
        p.add_argument("--scope")
        p.add_argument("--client", default="")
        p.add_argument("--now")
        if name == "alerts":
            p.add_argument("--all", action="store_true", help="include snoozed alerts")
    p = sub.add_parser("client")
    p.add_argument("context_root")
    p.add_argument("workspace_root")
    p.add_argument("client")
    p.add_argument("--json", action="store_true")
    p.add_argument("--now")
    p = sub.add_parser("digest")
    p.add_argument("context_root")
    p.add_argument("workspace_root")
    p.add_argument("project")
    p.add_argument("--now")
    p = sub.add_parser("client-log")
    p.add_argument("context_root")
    p.add_argument("client")
    p.add_argument("text")
    p = sub.add_parser("snooze")
    p.add_argument("workspace_root")
    p.add_argument("alert_id")
    p.add_argument("--for", dest="spec")
    p.add_argument("--off", action="store_true")
    p.add_argument("--now")
    opts = parser.parse_args(argv)
    now = _moment(opts.now) if getattr(opts, "now", None) else datetime.now().astimezone()
    if now is None:
        raise TaskError("invalid --now")

    if opts.command == "digest":
        print(digest(opts.context_root, opts.workspace_root, opts.project, now), end="")
        return 0
    if opts.command == "client-log":
        stamp = log_interaction(opts.context_root, opts.client, opts.text)
        print(f"logged {opts.client} {stamp}")
        return 0
    if opts.command == "client":
        dossier = client_dossier(opts.context_root, opts.workspace_root, opts.client, now)
        if opts.json:
            print(json.dumps(dossier, indent=2, sort_keys=True))
            return 0
        profile = dossier["profile"]
        print(f"{profile['title']}")  # type: ignore[index]
        for name, value in profile["fields"].items():  # type: ignore[index]
            if value:
                print(f"  {name}: {value}")
        print(f"  open work: {dossier['open']} ({dossier['overdue']} overdue) · alerts: {dossier['alerts']}")
        for project in dossier["projects"]:  # type: ignore[union-attr]
            print(f"  project {project['key']}: {project['open']} open, {project['overdue']} overdue")
        for task in dossier["tasks"]:  # type: ignore[union-attr]
            due = f" (due {task['due']})" if task["due"] else ""
            print(f"  task {task['id']}: {task['title']}{due} [{task['status']}]")
        for entry in dossier["interactions"]:  # type: ignore[union-attr]
            print(f"  {entry['at'][:16]} {entry['actor']}: {entry['text']}")
        kept = [name for name, present in dossier["restricted"].items() if present]  # type: ignore[union-attr]
        if kept:
            print(f"  restricted, desk only: {', '.join(name + '.md' for name in kept)}")
        return 0
    if opts.command == "snooze":
        if opts.off == bool(opts.spec):
            raise TaskError("usage: ws alerts snooze <alert-id> --for 1h|1d|1w|\"YYYY-MM-DD HH:MM\", or --off")
        snooze(opts.workspace_root, opts.alert_id, None if opts.off else _until(opts.spec, now), now)
        print(f"alert {opts.alert_id} {'shown' if opts.off else 'snoozed until ' + snoozes(opts.workspace_root)[opts.alert_id]}")
        return 0
    filters = {"scope": opts.scope, "client": opts.client}
    if opts.command == "alerts":
        found = (compute_alerts if opts.all else active_alerts)(opts.context_root, opts.workspace_root, now, **filters)
        if opts.json:
            print(json.dumps({"alerts": [asdict(a) for a in found]}, indent=2, sort_keys=True))
        else:
            _print_alerts(found) if found else print("No alerts.")
        return 0
    day = today(opts.context_root, opts.workspace_root, now, **filters)
    if opts.json:
        print(json.dumps(day, indent=2, sort_keys=True))
        return 0
    s = day["signals"]
    print(f"Today, {now.strftime('%a')} {day['date']}")
    print(f"  {s['overdue']} overdue · {s['due_today']} due today · {s['waiting']} waiting for you · "
          f"{s['blocked']} blocked · {s['stale']} stale · {s['review']} in review · {s['reminders']} reminders")
    if day["items"]:
        print()
        _print_alerts([Alert(**item) for item in day["items"]])
    if day["in_progress"]:
        print("\nIn progress")
        for task in day["in_progress"]:
            who = f" ({task['assignee']})" if task["assignee"] else ""
            print(f"  {task['scope']:<16} {task['id']}  {task['title']}{who}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except TaskError as error:
        print(f"workspace pm: {error}", file=sys.stderr)
        raise SystemExit(1)
