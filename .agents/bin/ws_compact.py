#!/usr/bin/env python3
"""Context and memory auto-compactor for Agent-Workspace.

Provides:
1. Memory Compactor: Archives old log.md milestones and closed active runs to keep CONTEXT.md
   small. A dry run unless --apply; nothing outside the two tables is touched.
2. Output Condenser: Intelligently truncates large command outputs (diffs, test dumps) and saves
   the full output to .local/logs/ so the LLM context window remains unpolluted.
"""
from pathlib import Path
import argparse
import datetime
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
# `ws` passes the context directory it resolved from workspace.conf.
CONTEXT = Path(os.environ.get('WS_CONTEXT_DIR') or ROOT / 'context')
LOCAL_LOGS = ROOT / '.local' / 'logs'
KEY_RE = re.compile(r'[a-z0-9][a-z0-9_-]*')
# Only these end a run. Anything else - open, in progress, blocked, ready for review, or
# a state nobody anticipated - is a run someone may still be working on, and stays.
CLOSED_STATES = {'done', 'closed', 'dropped', 'merged', 'abandoned', 'superseded'}
SEPARATOR_RE = re.compile(r'^\|\s*:?-{3,}')
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
RUN_STAMP_RE = re.compile(r'\d{4}-\d{2}-\d{2}-\d{6}')


class Changed(Exception):
    """A memory file changed while it was being compacted."""


def cells(row: str) -> list:
    return [cell.strip() for cell in row.strip().strip('|').split('|')]


def find_table(lines: list, header: str, start: int = 0, section: bool = False):
    """(first_row, end) of the first table whose header's first cell is `header`.

    With `section`, the search stops at the next `## ` heading, so a table belongs to
    the section it was found from. Blank lines before the table are allowed.
    """
    for i in range(start, len(lines) - 1):
        if section and lines[i].startswith('## '):
            return None
        if lines[i].startswith('|') and cells(lines[i])[0].lower() == header \
                and SEPARATOR_RE.match(lines[i + 1]):
            end = i + 2
            while end < len(lines) and lines[end].startswith('|'):
                end += 1
            return i + 2, end
    return None


def compact_log(text: str, keep: int):
    """New log.md text and the archived rows, or (None, []) when nothing changes.

    The newest rows by date stay, whatever order the file uses: `ws log` appends at the
    bottom, the template says newest first. Every line outside the table stays.
    """
    lines = text.splitlines()
    table = find_table(lines, 'date')
    if not table:
        return None, []
    first, end = table
    rows = lines[first:end]
    if len(rows) <= keep:
        return None, []

    def date(i):
        found = DATE_RE.search(cells(rows[i])[0])
        return found.group(0) if found else ''

    newest = set(sorted(range(len(rows)), key=lambda i: (date(i), i), reverse=True)[:keep])
    kept = [row for i, row in enumerate(rows) if i in newest]
    archived = [row for i, row in enumerate(rows) if i not in newest]
    return '\n'.join(lines[:first] + kept + lines[end:]) + '\n', archived


def compact_active(text: str, keep_closed: int):
    """New active.md text and the dropped rows, or (None, []) when nothing changes.

    Only rows whose State column is a closed state are candidates; the newest
    `keep_closed` of them stay. Newest is the run id's timestamp, then position:
    `ws run` inserts new rows at the top. Every line outside the table stays.
    """
    lines = text.splitlines()
    heading = next((i for i, line in enumerate(lines) if line.strip().lower() == '## active runs'), None)
    if heading is None:
        return None, []
    table = find_table(lines, 'run', heading + 1, section=True)
    if not table:
        return None, []
    first, end = table
    rows = lines[first:end]

    def state(row):
        return cells(row)[-1].strip('`* ').lower()

    def stamp(i):
        found = RUN_STAMP_RE.search(cells(rows[i])[0])
        return found.group(0) if found else ''

    closed = [i for i, row in enumerate(rows) if state(row) in CLOSED_STATES]
    if len(closed) <= keep_closed:
        return None, []
    newest = set(sorted(closed, key=lambda i: (stamp(i), -i), reverse=True)[:keep_closed])
    gone = {i for i in closed if i not in newest}
    kept = [row for i, row in enumerate(rows) if i not in gone]
    return '\n'.join(lines[:first] + kept + lines[end:]) + '\n', [rows[i] for i in sorted(gone)]


def replace_if_unchanged(path: Path, original: str, new_text: str) -> None:
    """Write new_text over path, unless someone else wrote path since it was read.

    `ws log` appends without a lock; losing its row to a compaction is the failure this
    check exists for. The window left is between the re-read and the rename.
    """
    tmp = path.with_name(path.name + '.compact.tmp')
    tmp.write_text(new_text, encoding='utf-8')
    if path.read_text(encoding='utf-8') != original:
        tmp.unlink()
        raise Changed(path)
    os.replace(tmp, path)


def compact_memory(project: str, max_milestones: int = 15, max_closed_runs: int = 3,
                   apply: bool = False) -> bool:
    if not KEY_RE.fullmatch(project or ''):
        print(f"Error: invalid project key '{project}'", file=sys.stderr)
        return False
    project_dir = CONTEXT / 'memory' / 'projects' / project
    if not project_dir.is_dir():
        print(f"Error: project memory directory not found: {project_dir}", file=sys.stderr)
        return False

    verb = 'Compacted' if apply else 'Would compact (dry run; --apply writes)'
    try:
        log_file = project_dir / 'log.md'
        if log_file.is_file():
            original = log_file.read_text(encoding='utf-8')
            new_text, archived = compact_log(original, max_milestones)
            if new_text is None:
                print(f"  [log.md] Clean (no more than {max_milestones} milestones)")
            else:
                print(f"  [log.md] {len(archived)} older milestones to log-archive.md")
                if apply:
                    if log_file.read_text(encoding='utf-8') != original:
                        raise Changed(log_file)
                    archive_file = project_dir / 'log-archive.md'
                    if archive_file.is_file():
                        archive = archive_file.read_text(encoding='utf-8').rstrip('\n') + '\n'
                    else:
                        archive = f"# {project} - log archive\n\n| Date | Milestone |\n|---|---|\n"
                    archive_file.write_text(archive + '\n'.join(archived) + '\n', encoding='utf-8')
                    replace_if_unchanged(log_file, original, new_text)

        active_file = project_dir / 'active.md'
        if active_file.is_file():
            original = active_file.read_text(encoding='utf-8')
            new_text, dropped = compact_active(original, max_closed_runs)
            if new_text is None:
                print(f"  [active.md] Clean (no more than {max_closed_runs} closed runs)")
            else:
                print(f"  [active.md] {len(dropped)} closed runs leave the table:")
                for row in dropped:
                    print(f"    {cells(row)[0]}")
                if apply:
                    replace_if_unchanged(active_file, original, new_text)
    except Changed as changed:
        print(f"Error: {changed.args[0]} changed during compaction; nothing more written. Run it again.",
              file=sys.stderr)
        return False

    print(f"\n{verb}: '{project}'")
    return True


def condense_exec(cmd_args: list, max_lines: int = 60, head_lines: int = 25, tail_lines: int = 25) -> int:
    """Executes a command and condenses its output to prevent token window pollution."""
    LOCAL_LOGS.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    cmd_name = Path(cmd_args[0]).name if cmd_args else "cmd"
    log_file = LOCAL_LOGS / f"{cmd_name}-{ts}.log"

    print(f"[ws compact exec] Running: {' '.join(cmd_args)}", file=sys.stderr)
    proc = subprocess.Popen(
        cmd_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace'
    )
    output, _ = proc.communicate()
    lines = output.splitlines()

    # Always persist full output to .local/logs/
    log_file.write_text(output, encoding='utf-8')

    if len(lines) <= max_lines:
        print(output, end='')
    else:
        omitted = len(lines) - (head_lines + tail_lines)
        head_part = '\n'.join(lines[:head_lines])
        tail_part = '\n'.join(lines[-tail_lines:])
        condensed = (
            f"{head_part}\n\n"
            f"[... {omitted} lines omitted by ws compact. Full output saved to: {log_file} ...]\n\n"
            f"{tail_part}\n"
        )
        print(condensed, end='')

    return proc.returncode


def main():
    parser = argparse.ArgumentParser(description="Context and memory auto-compactor for Agent-Workspace.")
    subparsers = parser.add_subparsers(dest="command")

    # memory command
    p_mem = subparsers.add_parser("memory", help="Compact project memory (active.md and log.md)")
    p_mem.add_argument("project", help="Project key")
    p_mem.add_argument("--max-milestones", type=int, default=15, help="Number of recent log milestones to keep")
    p_mem.add_argument("--max-closed-runs", type=int, default=3, help="Number of closed runs to keep in active table")
    p_mem.add_argument("--apply", action="store_true", help="Write the changes (default: dry run)")

    # exec command
    p_exec = subparsers.add_parser("exec", help="Run a command with smart output condensation")
    p_exec.add_argument("--max-lines", type=int, default=60, help="Max output lines before condensing")
    p_exec.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to execute")

    args = parser.parse_args()

    if args.command == "memory":
        ok = compact_memory(args.project, args.max_milestones, args.max_closed_runs, args.apply)
        sys.exit(0 if ok else 1)
    elif args.command == "exec":
        if not args.cmd:
            print("Error: command to execute is required", file=sys.stderr)
            sys.exit(2)
        # Strip leading '--' if present
        cmd = args.cmd[1:] if args.cmd and args.cmd[0] == '--' else args.cmd
        rc = condense_exec(cmd, max_lines=args.max_lines)
        sys.exit(rc)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
