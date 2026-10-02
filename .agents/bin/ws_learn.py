#!/usr/bin/env python3
"""Harvest learnings from agent runs into candidate skills.

Standard library only. Reads completed run artifacts (brief, plan, decisions,
handoff), synthesizes a candidate SKILL.md under .local/skills-draft/, and checks
it against the skill line budget.

A run carries its project's facts. Where the skill goes decides who reads them:

- draft  (default) .local/skills-draft/, read by no agent until someone moves it
- domain           context/skills/, routable from every project of the organisation
- user             a machine-wide skills folder that every session on this machine
                   loads, whatever client it works for - so only the framework's own
                   runs and projects declared public in context/public-identifiers
                   may go there (ADR-0011)
"""
from pathlib import Path
import argparse
import os
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
# `ws` passes the context directory it resolved from workspace.conf.
CONTEXT = Path(os.environ.get('WS_CONTEXT_DIR') or ROOT / 'context')
DRAFTS_DIR = ROOT / '.local' / 'skills-draft'
USER_SKILLS_DIR = Path(os.environ.get('WS_USER_SKILLS_DIR')
                       or Path.home() / '.gemini' / 'config' / 'skills')
DOMAIN_SKILLS_DIR = CONTEXT / 'skills'
# The run key for work on the framework itself. Matches FRAMEWORK_KEY in ws.
FRAMEWORK_KEY = 'workspace'
KEY_RE = re.compile(r'[a-z0-9][a-z0-9_-]*')


def require_key(value: str, what: str) -> str:
    """A project key, run id, or skill name: one path segment, never a path."""
    if not KEY_RE.fullmatch(value or ''):
        print(f"Error: invalid {what} '{value}' (lowercase letters, digits, '-' and '_' only)",
              file=sys.stderr)
        sys.exit(2)
    return value


def is_public(project: str) -> bool:
    """True for the framework key and for keys declared public in context/public-identifiers."""
    if project == FRAMEWORK_KEY:
        return True
    allow = CONTEXT / 'public-identifiers'
    if not allow.is_file():
        return False
    names = {line.split('#', 1)[0].strip().lower() for line in allow.read_text(encoding='utf-8').splitlines()}
    return project in names


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9]+', '-', text)
    return text.strip('-')[:40]


def find_latest_run(project: str) -> Path:
    runs_dir = CONTEXT / 'runs' / project
    if not runs_dir.is_dir():
        print(f"Error: no runs found for project '{project}' at {runs_dir}", file=sys.stderr)
        sys.exit(1)
    runs = sorted([d for d in runs_dir.iterdir() if d.is_dir()], reverse=True)
    if not runs:
        print(f"Error: run directory empty for project '{project}'", file=sys.stderr)
        sys.exit(1)
    return runs[0]


def extract_run_data(run_dir: Path) -> dict:
    data = {
        'run_id': run_dir.name,
        'title': run_dir.name,
        'goal': '',
        'decisions': [],
        'handoff_next': '',
        'keywords': set()
    }

    brief_file = run_dir / 'brief.md'
    if brief_file.is_file():
        content = brief_file.read_text(encoding='utf-8')
        m_title = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if m_title:
            data['title'] = m_title.group(1).strip()
        m_goal = re.search(r'##\s+Goal\s*\n+(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if m_goal:
            data['goal'] = ' '.join(m_goal.group(1).split())

    decisions_file = run_dir / 'decisions.md'
    if decisions_file.is_file():
        content = decisions_file.read_text(encoding='utf-8')
        decisions = re.findall(r'##\s+(?:D-\d+:\s*)?(.+?)\n+(.*?)(?=\n##|\Z)', content, re.DOTALL)
        for d_title, d_body in decisions:
            clean_body = ' '.join(d_body.split())
            data['decisions'].append((d_title.strip(), clean_body))

    handoff_file = run_dir / 'handoff.md'
    if handoff_file.is_file():
        content = handoff_file.read_text(encoding='utf-8')
        m_next = re.search(r'##\s+Immediate next step\s*\n+(.*?)(?=\n##|\Z)', content, re.DOTALL)
        if m_next:
            data['handoff_next'] = ' '.join(m_next.group(1).split())

    # Extract domain keywords from title and decisions
    tokens = re.findall(r'[a-zA-Z0-9_\-]+', data['title'])
    for t in tokens:
        if len(t) > 3:
            data['keywords'].add(t.lower())

    return data


def generate_draft(run_data: dict, skill_name: str, pack: str) -> Path:
    out_dir = DRAFTS_DIR / skill_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / 'SKILL.md'

    keywords_list = sorted(list(run_data['keywords']))[:8]
    kw_str = ', '.join(keywords_list) if keywords_list else 'workflow, practice'

    description = run_data['goal'] if run_data['goal'] else f"Workflow and guidance derived from {run_data['title']}."
    if len(description) > 280:
        description = description[:277] + '...'

    decisions_section = ""
    if run_data['decisions']:
        decisions_section = "## Key Principles & Decisions\n\n"
        for title, body in run_data['decisions'][:4]:
            decisions_section += f"### {title}\n{body}\n\n"

    content = f"""---
name: {skill_name}
description: >-
  {description}
keywords: [{kw_str}]
metadata:
  pack: {pack}
---

# {run_data['title']}

## Overview
{description}

## When to use
- Applying patterns and lessons established during {run_data['run_id']}.

{decisions_section}## Verification & Quality Gate
- Adhere to token budget: keep instructions concise, verifiable, and under 100 lines.
"""

    out_file.write_text(content, encoding='utf-8')
    return out_file


def validate_draft(skill_file: Path) -> bool:
    lines = skill_file.read_text(encoding='utf-8').splitlines()
    line_count = len(lines)
    print(f"\n[Audit] Draft generated at: {skill_file}")
    print(f"  Line count: {line_count} lines (budget limit: 100)")

    if line_count > 100:
        print(f"  [FAIL] Draft exceeds 100 lines limit ({line_count} > 100)", file=sys.stderr)
        return False

    print("  [PASS] Structure adheres to portable skill budget constraints.")
    return True


def deploy_skill(draft_file: Path, skill_name: str, target: str) -> Path:
    content = draft_file.read_text(encoding='utf-8')

    if target == 'user':
        dest_dir = USER_SKILLS_DIR / skill_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / 'SKILL.md'
        dest_file.write_text(content, encoding='utf-8')
        print(f"\n[INSTALLED] User skill deployed to: {dest_file}")
        print("  - Scope: every session on this machine (untracked by Git)")
        return dest_file

    elif target == 'domain':
        dest_dir = DOMAIN_SKILLS_DIR / skill_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / 'SKILL.md'
        dest_file.write_text(content, encoding='utf-8')
        print(f"\n[INSTALLED] Private domain skill deployed to: {dest_file}")
        print("  - Scope: every project of this organisation (context/ repository)")
        print("  - Run 'ws skills index' to register in context/skills/index.json.")
        return dest_file

    return draft_file


def main():
    parser = argparse.ArgumentParser(description="Harvest learnings from a run into a candidate skill.")
    parser.add_argument("project", help="Project key (e.g. workspace, my-service)")
    parser.add_argument("--run", help="Specific run ID (defaults to latest)")
    parser.add_argument("--name", help="Candidate skill slug name")
    parser.add_argument("--pack", default="core", help="Target pack (core, web, java, agent)")
    parser.add_argument("--target", choices=["user", "domain", "draft"], default="draft",
                        help="Target scope: 'draft' (.local/skills-draft, default), 'domain' (context/skills), "
                             "or 'user' (machine-wide; framework and public projects only)")
    parser.add_argument("--user", action="store_true", help="Shortcut for --target user")
    parser.add_argument("--domain", action="store_true", help="Shortcut for --target domain")
    parser.add_argument("--draft", action="store_true", help="Shortcut for --target draft (default)")
    parser.add_argument("--no-install", action="store_true", help="Stage only in .local/skills-draft/ without deploying to target")

    args = parser.parse_args()

    # Determine effective target
    target = args.target
    if args.domain:
        target = 'domain'
    elif args.draft:
        target = 'draft'
    elif args.user:
        target = 'user'

    require_key(args.project, 'project key')
    if target == 'user' and not args.no_install and not is_public(args.project):
        print(f"Error: '{args.project}' is not the framework or a project declared public, so its "
              "run may not be installed machine-wide: every session on this machine would load "
              "it, whatever client it works for (ADR-0011).", file=sys.stderr)
        print("  Keep it as a draft (default) or install it for the organisation with --domain.",
              file=sys.stderr)
        sys.exit(2)

    if args.run:
        run_dir = CONTEXT / 'runs' / args.project / require_key(args.run, 'run id')
        if not run_dir.is_dir():
            print(f"Error: run directory does not exist: {run_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        run_dir = find_latest_run(args.project)

    run_data = extract_run_data(run_dir)
    skill_name = require_key(args.name or slugify(run_data['title']), 'skill name')

    print(f"Harvesting learnings from: {run_dir.name}")
    print(f"  Project: {args.project}")
    print(f"  Extracted Title: {run_data['title']}")
    print(f"  Target Scope: {target}")
    print(f"  Identified Keywords: {', '.join(sorted(run_data['keywords']))}")

    draft_file = generate_draft(run_data, skill_name, args.pack)
    is_valid = validate_draft(draft_file)

    if not is_valid:
        sys.exit(1)

    if not args.no_install and target in ('user', 'domain'):
        dest_file = deploy_skill(draft_file, skill_name, target)
    else:
        dest_file = draft_file

    print("\nNext steps for this learned skill:")
    if target == 'user':
        print("1. Audit token budget and routing with the skills repository's harness")
        print(f"2. Refine as needed:   {dest_file}")
    elif target == 'domain':
        print("1. Update index:       ws skills index")
        print("2. Audit token budget and routing with the skills repository's harness")
        print(f"3. Refine as needed:   {dest_file}")
    else:
        print(f"1. Review and refine:  {draft_file}")
        print(f"2. Deploy for the organisation: ws learn {args.project} --run {run_dir.name} --name {skill_name} --domain")

    sys.exit(0)


if __name__ == '__main__':
    main()
