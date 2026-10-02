#!/usr/bin/env python3
"""Context and memory auto-compactor for Agent-Workspace.

Provides:
1. Memory Compactor: Prunes append-only log.md and closed active runs to prevent CONTEXT.md bloating.
2. Output Condenser: Intelligently truncates large command outputs (diffs, test dumps) and saves
   the full output to .local/logs/ so the LLM context window remains unpolluted.
"""
from pathlib import Path
import argparse
import datetime
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT = ROOT / 'context'
LOCAL_LOGS = ROOT / '.local' / 'logs'


def compact_memory(project: str, max_milestones: int = 15, max_closed_runs: int = 3) -> bool:
    project_dir = CONTEXT / 'memory' / 'projects' / project
    if not project_dir.is_dir():
        print(f"Error: project memory directory not found: {project_dir}", file=sys.stderr)
        return False

    bytes_saved = 0

    # 1. Compact log.md
    log_file = project_dir / 'log.md'
    if log_file.is_file():
        content = log_file.read_text(encoding='utf-8')
        lines = content.splitlines()

        header_lines = []
        table_rows = []
        in_table = False

        for line in lines:
            if line.startswith('| Date |') or line.startswith('|Date|'):
                in_table = True
                header_lines.append(line)
            elif in_table and line.startswith('|---|'):
                header_lines.append(line)
            elif in_table and line.startswith('|'):
                table_rows.append(line)
            elif not in_table:
                header_lines.append(line)

        if len(table_rows) > max_milestones:
            kept_rows = table_rows[-max_milestones:]
            archived_rows = table_rows[:-max_milestones]

            new_log_content = '\n'.join(header_lines + kept_rows) + '\n'
            archive_file = project_dir / 'log-archive.md'

            # Append to log-archive.md
            archive_content = ""
            if archive_file.is_file():
                archive_content = archive_file.read_text(encoding='utf-8').strip() + '\n'
            else:
                archive_content = f"# {project} — log archive\n\n| Date | Milestone |\n|---|---|\n"

            archive_content += '\n'.join(archived_rows) + '\n'
            archive_file.write_text(archive_content, encoding='utf-8')

            original_size = len(content.encode('utf-8'))
            new_size = len(new_log_content.encode('utf-8'))
            diff = original_size - new_size
            bytes_saved += diff

            log_file.write_text(new_log_content, encoding='utf-8')
            print(f"  [log.md] Rolled {len(archived_rows)} older milestones to log-archive.md (saved ~{diff} bytes)")
        else:
            print(f"  [log.md] Clean ({len(table_rows)} rows <= threshold {max_milestones})")

    # 2. Compact active.md runs
    active_file = project_dir / 'active.md'
    if active_file.is_file():
        content = active_file.read_text(encoding='utf-8')
        lines = content.splitlines()

        new_lines = []
        in_runs_table = False
        run_rows = []
        table_header = []

        for line in lines:
            if line.strip().startswith('## Active runs'):
                in_runs_table = True
                new_lines.append(line)
                continue
            if in_runs_table:
                if line.startswith('| Run |') or line.startswith('|Run|'):
                    table_header.append(line)
                elif line.startswith('|---|'):
                    table_header.append(line)
                elif line.startswith('|'):
                    run_rows.append(line)
                elif line.startswith('##') or not line.strip():
                    in_runs_table = False
                    # Process runs table
                    open_runs = [r for r in run_rows if 'open' in r.lower()]
                    closed_runs = [r for r in run_rows if 'open' not in r.lower()]

                    kept_closed = closed_runs[-max_closed_runs:] if len(closed_runs) > max_closed_runs else closed_runs
                    new_lines.extend(table_header)
                    new_lines.extend(open_runs)
                    new_lines.extend(kept_closed)
                    new_lines.append(line)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        new_active_content = '\n'.join(new_lines) + '\n'
        if len(new_active_content) < len(content):
            diff = len(content.encode('utf-8')) - len(new_active_content.encode('utf-8'))
            bytes_saved += diff
            active_file.write_text(new_active_content, encoding='utf-8')
            print(f"  [active.md] Pruned closed runs table (saved ~{diff} bytes)")
        else:
            print(f"  [active.md] Clean (no stale run rows to prune)")

    tokens_saved = bytes_saved // 4
    print(f"\nMemory Compaction Complete for '{project}':")
    print(f"  Total disk bytes saved: {bytes_saved} B")
    print(f"  Estimated prompt tokens saved per session bind: ~{tokens_saved} tokens")
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

    # exec command
    p_exec = subparsers.add_parser("exec", help="Run a command with smart output condensation")
    p_exec.add_argument("--max-lines", type=int, default=60, help="Max output lines before condensing")
    p_exec.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to execute")

    args = parser.parse_args()

    if args.command == "memory":
        ok = compact_memory(args.project, args.max_milestones, args.max_closed_runs)
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
