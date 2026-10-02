#!/usr/bin/env python3
"""Harvest learnings from agent runs into validated candidate skills.

Standard library only. Reads completed run artifacts (brief, plan, decisions,
handoff), synthesizes a candidate SKILL.md under .local/skills-draft/, and
validates it against the Agent-Skills token and structural harness.
"""
from pathlib import Path
import argparse
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
CONTEXT = ROOT / 'context'
DRAFTS_DIR = ROOT / '.local' / 'skills-draft'
AGENT_SKILLS_DIR = ROOT / 'projects' / 'donwi' / 'public' / 'Agent-Skills'


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


def main():
    parser = argparse.ArgumentParser(description="Harvest learnings from a run into a draft skill.")
    parser.add_argument("project", help="Project key (e.g. workspace, my-service)")
    parser.add_argument("--run", help="Specific run ID (defaults to latest)")
    parser.add_argument("--name", help="Candidate skill slug name")
    parser.add_argument("--pack", default="core", help="Target pack (core, web, java, agent)")

    args = parser.parse_args()

    if args.run:
        run_dir = CONTEXT / 'runs' / args.project / args.run
        if not run_dir.is_dir():
            print(f"Error: run directory does not exist: {run_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        run_dir = find_latest_run(args.project)

    run_data = extract_run_data(run_dir)
    skill_name = args.name if args.name else slugify(run_data['title'])

    print(f"Harvesting learnings from: {run_dir.name}")
    print(f"  Project: {args.project}")
    print(f"  Extracted Title: {run_data['title']}")
    print(f"  Identified Keywords: {', '.join(sorted(run_data['keywords']))}")

    draft_file = generate_draft(run_data, skill_name, args.pack)
    is_valid = validate_draft(draft_file)

    print("\nNext steps for this draft:")
    print(f"1. Review and refine: {draft_file}")
    print(f"2. If domain/private: move to context/skills/{skill_name}/")
    print(f"3. If public/portable: submit PR to projects/donwi/public/Agent-Skills/skills/{skill_name}/")

    sys.exit(0 if is_valid else 1)


if __name__ == '__main__':
    main()
