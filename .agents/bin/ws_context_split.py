#!/usr/bin/env python3
"""Split a mixed context tree into two audience copies (ADR-0010).

Usage:
  ws_context_split.py <src_context> <personal_client> <out_personal> <out_org>

Copies the current tree only (no git history). History with mixed audiences or
redacted secrets stays in the source repository, which must remain private-local.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def load_registry(src: Path) -> tuple[str, list[list[str]]]:
    path = src / "registry.tsv"
    lines = path.read_text().splitlines()
    header = lines[0] if lines else "key\tclient\tgroup\tfolder\tremote\tcontext_scope\tsecurity_profile\tdescription"
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        rows.append(line.split("\t"))
    return header, rows


def load_groups(src: Path) -> tuple[str, list[list[str]]]:
    path = src / "groups.tsv"
    if not path.exists():
        return "key\tclient\tdescription", []
    lines = path.read_text().splitlines()
    header = lines[0] if lines else "key\tclient\tdescription"
    rows = [line.split("\t") for line in lines[1:] if line.strip()]
    return header, rows


def keys_for_client(rows: list[list[str]], client: str) -> set[str]:
    return {r[0] for r in rows if len(r) > 1 and r[1] == client}


def write_tsv(path: Path, header: str, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [header]
    lines.extend("\t".join(r) for r in rows)
    path.write_text("\n".join(lines) + "\n")


def copy_dir(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def copy_file(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def filter_index(text: str, keep_keys: set[str]) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        if line.startswith("| `") and " |" in line:
            key = line.split("`")[1] if "`" in line else ""
            if key and key not in keep_keys and key != "workspace":
                # workspace row stays in the org copy only; dropped here if not kept
                if "workspace" not in keep_keys and key == "workspace":
                    continue
                if key not in keep_keys:
                    continue
        out.append(line)
    return "".join(out)


def materialise(src: Path, dest: Path, header: str, rows: list[list[str]],
                gheader: str, grows: list[list[str]], keep_workspace: bool) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    keys = {r[0] for r in rows}
    clients = {r[1] for r in rows if len(r) > 1}
    if keep_workspace:
        keys.add("workspace")

    write_tsv(dest / "registry.tsv", header, rows)
    write_tsv(dest / "groups.tsv", gheader, grows)

    for name in ("README.md", ".gitattributes", ".gitignore"):
        copy_file(src / name, dest / name)

    copy_dir(src / "docs", dest / "docs")
    copy_dir(src / "skills", dest / "skills")

    for client in clients:
        copy_dir(src / "clients" / client, dest / "clients" / client)

    for key in keys:
        copy_dir(src / "memory" / "projects" / key, dest / "memory" / "projects" / key)
        copy_dir(src / "runs" / key, dest / "runs" / key)
        copy_dir(src / "works" / "human" / key, dest / "works" / "human" / key)
        copy_dir(src / "works" / "agent" / key, dest / "works" / "agent" / key)

    idx = src / "memory" / "projects" / "index.md"
    if idx.is_file():
        dest_idx = dest / "memory" / "projects" / "index.md"
        dest_idx.parent.mkdir(parents=True, exist_ok=True)
        dest_idx.write_text(filter_index(idx.read_text(), keys))

    mem_readme = src / "memory" / "README.md"
    copy_file(mem_readme, dest / "memory" / "README.md")
    copy_file(src / "runs" / "README.md", dest / "runs" / "README.md")
    copy_dir(src / "works" / "rollup", dest / "works" / "rollup")


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: ws_context_split.py <src> <personal_client> <out_personal> <out_org>",
              file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    personal = sys.argv[2]
    out_p = Path(sys.argv[3])
    out_o = Path(sys.argv[4])
    header, rows = load_registry(src)
    gheader, grows = load_groups(src)
    p_rows = [r for r in rows if len(r) > 1 and r[1] == personal]
    o_rows = [r for r in rows if len(r) > 1 and r[1] != personal]
    p_groups = [g for g in grows if len(g) > 1 and g[1] == personal]
    o_groups = [g for g in grows if len(g) > 1 and g[1] != personal]
    materialise(src, out_p, header, p_rows, gheader, p_groups, keep_workspace=False)
    materialise(src, out_o, header, o_rows, gheader, o_groups, keep_workspace=True)
    print(f"personal keys: {', '.join(sorted(r[0] for r in p_rows)) or '(none)'}")
    print(f"org keys: {', '.join(sorted(r[0] for r in o_rows)) or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
