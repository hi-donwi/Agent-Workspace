"""Merge the framework's Claude Code hooks into `.claude/settings.json`.

`.claude/settings.json` is also where Claude Code keeps the operator's own settings - most
often a growing `permissions.allow` list. Copying the example over it, as `ws hooks
install` used to, threw those away. This merges instead: a hook command that runs
`.agents/bin/ws` (or a helper next to it) is ours and is replaced; everything else is
left exactly as it was.

    ws_hooks.py install <example> <settings>   add or refresh our hooks
    ws_hooks.py remove  <settings>             take ours out; delete the file if nothing is left
    ws_hooks.py status  <settings>             print "clock" and/or "activity" when installed

Standard library only.
"""
import json
from pathlib import Path
import sys

OURS = ".agents/bin/ws"


def is_ours(hook):
    return isinstance(hook, dict) and OURS in str(hook.get("command", ""))


def load(path):
    path = Path(path)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def without_ours(groups):
    """The event's matcher groups with our hook commands removed, and empty groups dropped."""
    kept = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            kept.append(group)
            continue
        hooks = [hook for hook in group.get("hooks", []) if not is_ours(hook)]
        if hooks:
            kept.append({**group, "hooks": hooks})
    return kept


def strip(settings):
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings
    cleaned = {event: without_ours(groups) for event, groups in hooks.items()}
    cleaned = {event: groups for event, groups in cleaned.items() if groups}
    result = dict(settings)
    if cleaned:
        result["hooks"] = cleaned
    else:
        result.pop("hooks", None)
    return result


def install(example, settings):
    ours = load(example)
    merged = strip(settings)
    hooks = dict(merged.get("hooks", {}))
    for event, groups in ours.get("hooks", {}).items():
        hooks[event] = list(hooks.get(event, [])) + list(groups)
    merged["hooks"] = hooks
    if "$comment" in ours:
        merged["$comment"] = ours["$comment"]
    return merged


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def installed(settings):
    commands = [
        str(hook.get("command", ""))
        for groups in (settings.get("hooks") or {}).values() if isinstance(groups, list)
        for group in groups if isinstance(group, dict)
        for hook in group.get("hooks", []) if is_ours(hook)
    ]
    found = []
    if any("agent auto" in command for command in commands):
        found.append("clock")
    if any("ws_activity.py" in command or "agent activity" in command for command in commands):
        found.append("activity")
    return found


def main(argv):
    try:
        if len(argv) == 4 and argv[1] == "install":
            write(argv[3], install(argv[2], load(argv[3])))
            return 0
        if len(argv) == 3 and argv[1] == "remove":
            settings = strip(load(argv[2]))
            leftover = {key: value for key, value in settings.items() if key != "$comment"}
            if leftover:
                settings.pop("$comment", None)
                write(argv[2], settings)
            elif Path(argv[2]).exists():
                Path(argv[2]).unlink()
            return 0
        if len(argv) == 3 and argv[1] == "status":
            print(" ".join(installed(load(argv[2]))))
            return 0
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
