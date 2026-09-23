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


def write_segments(filename, record, start, finish, note, extra=None):
    """Append one record per calendar day from start to finish, then drop the open file."""
    cursor = start
    months = set()
    while cursor <= finish:
        boundary = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = min(boundary, finish)
        segment = dict(record, start=cursor.isoformat(timespec="seconds"), end=end.isoformat(timespec="seconds"),
                       start_ts=int(cursor.timestamp()), end_ts=int(end.timestamp()),
                       minutes=int((end - cursor).total_seconds() // 60), note=note or record["note"])
        if extra:
            segment.update(extra)
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
        if end == finish:
            break
        cursor = end
    filename.unlink()
    return months


def opened(filename):
    """The open record and its start, rejecting a start in the future."""
    record = json.loads(filename.read_text())
    key(record["project"])
    now = datetime.now().astimezone()
    start = datetime.fromtimestamp(record["start_ts"], now.tzinfo)
    if start > now:
        raise ValueError("session start is in the future")
    return record, start, now


def clock_out(filename, note):
    filename = Path(filename)
    with locked(filename.parent):
        record, start, now = opened(filename)
        months = write_segments(filename, record, start, now, note)
    print(" ".join(sorted(months)))


def clock_recover(filename, cap_hours, end_iso, note):
    """Close a clock whose session ended without clocking out.

    A session killed by a quota limit, a crash, or a closed terminal leaves its
    open file behind. Its true end is unknown, and closing it with `now` would
    bill every hour since — a clock left from Monday reports Monday to Friday as
    one unbroken session, and because `hours` merges overlaps within a column,
    that one interval swallows every real session that month.

    So the end is never invented. The evidence is the open file's mtime, which
    every ws invocation touches while the clock is open, bounded by cap_hours
    from the start. Whichever bound applies is written into the record, because
    an estimate that reads like a measurement is worse than no record at all.
    """
    filename = Path(filename)
    cap = timedelta(hours=float(cap_hours))
    with locked(filename.parent):
        record, start, now = opened(filename)
        if end_iso:
            finish = datetime.fromisoformat(end_iso)
            if finish.tzinfo is None:
                finish = finish.replace(tzinfo=now.tzinfo)
            if not start <= finish <= now:
                raise ValueError("the stated end must fall between the session start and now")
            basis = "stated"
        else:
            beat = datetime.fromtimestamp(filename.stat().st_mtime, now.tzinfo)
            finish = max(start, min(beat, now))
            # The clock-in write itself lands a few milliseconds after start_ts is
            # taken, so a bare mtime always looks marginally later than the start.
            # Under a minute is that write, not a sign of life.
            basis = "heartbeat" if finish - start >= timedelta(minutes=1) else "start"
        if finish - start > cap:
            finish, basis = start + cap, "cap"
        minutes = int((finish - start).total_seconds() // 60)
        months = write_segments(filename, record, start, finish, note,
                                {"recovered": True, "recovered_basis": basis})
    print(" ".join(sorted(months)))
    print(f"{record['project']} {basis} {minutes}", file=sys.stderr)


def hours(kind):
    groups = {}
    # Third column: how much of the day came from a recovered clock, so an
    # estimate is never read as a measurement. Summed, not merged - it is a
    # provenance note about the merged figure beside it, not a total of its own.
    estimated = {}
    for line in sys.stdin:
        if not line.strip():
            continue
        record = json.loads(line)
        day = record["start"][:10]
        actor = record.get("actor", "legacy") if kind == "human" else "elapsed"
        groups.setdefault((day, actor), []).append((int(record["start_ts"]), int(record["end_ts"])))
        if record.get("recovered"):
            estimated[day] = estimated.get(day, 0) + int(record["end_ts"]) - int(record["start_ts"])
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
        print(f"{day} {seconds / 3600:.2f} {estimated.get(day, 0) / 3600:.2f}")
    print(f"TOTAL {sum(days.values()) / 3600:.2f} {sum(estimated.values()) / 3600:.2f}")


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
    if scope not in ("client", "group", "org"):
        raise ValueError(f"unknown context_scope '{scope}'")
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
    # A project whose context is a repository of its own: the root context then holds
    # routing stubs, and packing only those hands the agent seven pointers and an
    # allowlist forbidding it to follow them. Both are packed — the stub explains the
    # arrangement, the repo carries the facts.
    external = (row.get("context_repo") or "-").strip()
    if external in ("", "-"):
        external = None
    else:
        if Path(external).is_absolute() or ".." in Path(external).parts:
            raise ValueError("context_repo must be a relative path inside the workspace")
    if args:
        if len(args) != 2 or args[0] != "--run":
            raise ValueError("usage: ws context pack <project> [--run <run-id>]")
        run = key(args[1])
        # The run may live in either tree: runs/<project>/<run> in the root context, or
        # runs/<run> in the project's own context repo, where the repo is the project.
        here = contained(context, f"runs/{project}/{run}").is_dir()
        there = external is not None and contained(root, f"{external}/runs/{run}").is_dir()
        if not (here or there):
            raise ValueError("run does not exist in project")
        if here:
            selected += [f"runs/{project}/{run}/{name}.md" for name in ["brief", "plan", "handoff"]]
    # (base, relative) so each file resolves against the tree that owns it: the context
    # repo for the root's own material, the workspace root for a project context repo.
    targets = [(context, relative) for relative in selected]
    if external:
        outside = [f"{name}.md" for name in ["project", "active", "decisions", "log"]]
        outside += [f"client/{name}.md" for name in ["client", "decisions"]]
        if args:
            outside += [f"runs/{key(args[1])}/{name}.md" for name in ["brief", "plan", "handoff"]]
            outside += [f"runs/{key(args[1])}/{name}.md" for name in ["progress", "parity-audit"]]
        targets += [(root, f"{external}/{name}") for name in outside]
    files, total = [], 0
    for base, relative in targets:
        path = contained(base, relative)
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
                          context_repo=external, files=files,
                          handling="Local/private context only. This pack is not approved for cloud upload or a sandbox boundary."), indent=2))


def main():
    command, *args = sys.argv[1:]
    if command == "clock-in":
        clock_in(*args)
    elif command == "clock-out":
        clock_out(*args)
    elif command == "clock-recover":
        clock_recover(*args)
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
