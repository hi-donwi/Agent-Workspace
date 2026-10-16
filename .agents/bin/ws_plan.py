"""A run's plan table, changed one row at a time (`ws plan`). Standard library only.

The table is the one the run template writes:

    | # | Task | Status | Notes |
    |---|---|---|---|
    | 1 | Write the parser | `in_progress` | |

The rules of AGENTS.md §6 hold here, not only in prose: at most one row `in_progress`, a
`blocked` or `dropped` row states why in Notes, and a change can carry the revision the
caller read (`mtime:<ns>:size:<bytes>`, the same form ws_tasks.py uses) and is refused
when the file changed since. Who may edit is checked by `ws` before this runs.

    ws_plan.py show   <plan.md>
    ws_plan.py status <plan.md> <row> <status> <revision|-> [notes]
"""
import os
from pathlib import Path
import re
import sys
import tempfile

STATUSES = ("pending", "in_progress", "done", "blocked", "dropped")
NEEDS_REASON = ("blocked", "dropped")
ROW_RE = re.compile(r"\d+[a-z]?")
CELL_SPLIT = re.compile(r"(?<!\\)\|")


class PlanError(ValueError):
    pass


class PlanConflict(PlanError):
    pass


def revision(path: Path) -> str:
    stat = path.stat()
    return f"mtime:{stat.st_mtime_ns}:size:{stat.st_size}"


def cells(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [cell.strip() for cell in CELL_SPLIT.split(inner)]


def task_rows(lines: list[str]) -> dict[str, int]:
    """Row number -> line index, for the first `| # | Task | Status | ... |` table."""
    rows: dict[str, int] = {}
    in_table = False
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            if in_table:
                break
            continue
        head = [cell.lower() for cell in cells(line)]
        if not in_table:
            if len(head) >= 3 and head[0] == "#" and head[1] == "task" and head[2] == "status":
                in_table = True
            continue
        row = cells(line)
        if row and ROW_RE.fullmatch(row[0]):
            rows[row[0]] = index
    return rows


def status_of(cell: str) -> str:
    return cell.replace("`", "").strip()


def show(path: Path) -> list[tuple[str, str, str, str]]:
    lines = path.read_text(encoding="utf-8").split("\n")
    shown = []
    for number, index in task_rows(lines).items():
        row = cells(lines[index]) + ["", "", ""]
        shown.append((number, row[1], status_of(row[2]), row[3]))
    return shown


def set_status(path: Path, number: str, status: str, expected: str | None, notes: str | None) -> str:
    if status not in STATUSES:
        raise PlanError(f"unknown status '{status}' (one of: {', '.join(STATUSES)})")
    if expected is not None and expected != revision(path):
        raise PlanConflict("revision mismatch: the plan changed since it was read")
    lines = path.read_text(encoding="utf-8").split("\n")
    rows = task_rows(lines)
    if number not in rows:
        raise PlanError(f"no row {number} in the plan's task table")
    if status == "in_progress":
        for other, index in rows.items():
            if other != number and status_of((cells(lines[index]) + ["", "", ""])[2]) == "in_progress":
                raise PlanError(f"row {other} is already in progress - one row in_progress per run")
    row = cells(lines[rows[number]]) + ["", "", ""]
    task = row[1]
    if not task:
        raise PlanError(f"row {number} has no task yet")
    note = row[3] if notes is None else " ".join(notes.split()).replace("|", "\\|")
    if status in NEEDS_REASON and not note.strip():
        raise PlanError(f"a {status} row states why in Notes - pass the reason")
    lines[rows[number]] = f"| {number} | {task} | `{status}` | {note} |".replace("|  |", "| |")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-plan-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return revision(path)


def main(argv: list[str]) -> int:
    try:
        if len(argv) == 2 and argv[0] == "show":
            for number, task, status, note in show(Path(argv[1])):
                print(f"{number}\t{status}\t{task}\t{note}")
            return 0
        if len(argv) in (5, 6) and argv[0] == "status":
            expected = None if argv[4] == "-" else argv[4]
            notes = argv[5] if len(argv) == 6 else None
            print(f"{argv[2]} {argv[3]} {set_status(Path(argv[1]), argv[2], argv[3], expected, notes)}")
            return 0
    except PlanError as error:
        print(f"plan: {error}", file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
