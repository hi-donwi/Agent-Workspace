"""Structured local workspace state. Uses only the Python standard library."""
import contextlib
import csv
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid


def key(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
        raise ValueError("invalid key")
    return value


def contained(base, relative):
    base = Path(base).resolve()
    target = base / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or base not in target.resolve().parents:
        raise ValueError("path escapes scope")
    if any(p.is_symlink() for p in [target, *target.parents] if p != base and base in p.parents):
        raise ValueError("symlinks are not allowed in context")
    return target


@contextlib.contextmanager
def locked(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".state.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def dump(data):
    return json.dumps(data, separators=(",", ":")) + "\n"


def clock_in(filename, project, actor, tool, note):
    filename = Path(filename)
    key(project)
    now = datetime.now().astimezone()
    record = dict(id=str(uuid.uuid4()), kind="human" if ".open-human-" in filename.name else "agent",
                  project=project, actor=actor, tool=tool, start=now.isoformat(timespec="seconds"),
                  start_ts=int(now.timestamp()), note=note)
    with locked(filename.parent):
        with filename.open("x") as target:
            os.chmod(filename, 0o600)
            target.write(dump(record))


def clock_out(filename, note):
    filename = Path(filename)
    with locked(filename.parent):
        record = json.loads(filename.read_text())
        key(record["project"])
        now = datetime.now().astimezone()
        start = datetime.fromtimestamp(record["start_ts"], now.tzinfo)
        if start > now:
            raise ValueError("session start is in the future")
        cursor = start
        months = set()
        while cursor <= now:
            boundary = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            end = min(boundary, now)
            segment = dict(record, start=cursor.isoformat(timespec="seconds"), end=end.isoformat(timespec="seconds"),
                           start_ts=int(cursor.timestamp()), end_ts=int(end.timestamp()),
                           minutes=int((end - cursor).total_seconds() // 60), note=note or record["note"])
            segment["id"] = record.get("id", hashlib.sha256(dump(record).encode()).hexdigest()) + ":" + cursor.date().isoformat()
            month = cursor.strftime("%Y-%m")
            target = filename.parent / record["kind"] / record["project"] / (month + ".jsonl")
            target.parent.mkdir(parents=True, exist_ok=True)
            # Idempotent recovery if a process stops after append but before unlink.
            known = {json.loads(line).get("id") for line in target.read_text().splitlines()} if target.exists() else set()
            if segment["id"] not in known:
                with target.open("a") as output:
                    output.write(dump(segment))
                    output.flush()
                    os.fsync(output.fileno())
            months.add(month)
            if end == now:
                break
            cursor = end
        filename.unlink()
    print(" ".join(sorted(months)))


def hours(kind):
    groups = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        record = json.loads(line)
        day = record["start"][:10]
        actor = record.get("actor", "legacy") if kind == "human" else "elapsed"
        groups.setdefault((day, actor), []).append((int(record["start_ts"]), int(record["end_ts"])))
    days = {}
    for (day, _), intervals in groups.items():
        seconds = 0
        start = end = None
        for first, last in sorted(intervals):
            if last < first:
                raise ValueError("negative session interval")
            if start is None:
                start, end = first, last
            elif first <= end:
                end = max(end, last)
            else:
                seconds += end - start
                start, end = first, last
        if start is not None:
            seconds += end - start
        days[day] = days.get(day, 0) + seconds
    for day, seconds in sorted(days.items()):
        print(f"{day} {seconds / 3600:.2f} 0")
    print(f"TOTAL {sum(days.values()) / 3600:.2f} 0")


def context_pack(root, context, project, *args):
    root, context = Path(root).resolve(), Path(context).resolve()
    key(project)
    with (context / "registry.tsv").open() as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    matches = [row for row in rows if row["key"] == project]
    if len(matches) != 1:
        raise ValueError("unknown or duplicate project")
    row = matches[0]
    client = key(row["client"])
    group = row.get("group") or "-"
    scope = row.get("context_scope") or "client"
    if group not in ("", "-"):
        group = key(group)
        owners = list(csv.DictReader((context / "groups.tsv").open(), delimiter="\t")) \
            if (context / "groups.tsv").exists() else []
        owner = [g for g in owners if g["key"] == group]
        if len(owner) != 1 or owner[0]["client"] != client:
            raise ValueError("project group is unknown or owned by a different client")
    else:
        group = None
    # context_scope is the pack's audience boundary, not a suggestion:
    #   group  -> group material only (requires a group; no client-wide docs)
    #   client -> client-wide + own group (if any)   [default]
    #   org    -> everything above + org-wide material
    if scope == "group":
        if not group:
            raise ValueError("context_scope 'group' requires the project to have a group")
        selected = [f"clients/{client}/groups/{group}/{name}.md" for name in ["client", "decisions"]]
    else:
        selected = [f"clients/{client}/{name}.md" for name in ["client", "decisions"]]
        if group:
            selected += [f"clients/{client}/groups/{group}/{name}.md" for name in ["client", "decisions"]]
        if scope == "org":
            # Org-wide material lives in memory/ minus the per-project subtrees.
            selected += ["memory/README.md", "docs/adr/README.md"]
    selected += [f"memory/projects/{project}/{name}.md" for name in ["project", "active", "decisions"]]
    if args:
        if len(args) != 2 or args[0] != "--run":
            raise ValueError("usage: ws context pack <project> [--run <run-id>]")
        run = key(args[1])
        directory = contained(context, f"runs/{project}/{run}")
        if not directory.is_dir():
            raise ValueError("run does not exist in project")
        selected += [f"runs/{project}/{run}/{name}.md" for name in ["brief", "plan", "handoff"]]
    files, total = [], 0
    for relative in selected:
        path = contained(context, relative)
        if not path.exists():
            continue
        if path.stat().st_size > 32768:
            raise ValueError("context file exceeds 32 KiB; curate it before packing")
        data = path.read_bytes()
        total += len(data)
        if total > 131072:
            raise ValueError("context exceeds 128 KiB")
        files.append(dict(path=str(path.relative_to(root)), sha256=hashlib.sha256(data).hexdigest(),
                          content=data.decode(), classification="private-context"))
    print(json.dumps(dict(version=1, project=project, client=client, group=group, scope=scope,
                          files=files,
                          handling="Local/private context only. This pack is not approved for cloud upload or a sandbox boundary."), indent=2))


def main():
    command, *args = sys.argv[1:]
    if command == "clock-in":
        clock_in(*args)
    elif command == "clock-out":
        clock_out(*args)
    elif command == "hours":
        hours(*args)
    elif command == "context-pack":
        context_pack(*args)
    else:
        raise ValueError("unknown state operation")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(f"workspace state: {error}", file=sys.stderr)
        sys.exit(1)
