#!/usr/bin/env python3
"""Validate and compare pinned cross-repository compatibility metadata."""

import json
import pathlib
import re
import sys


SEMVER = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def load(path):
    try:
        return json.loads(pathlib.Path(path).read_text()), None
    except (OSError, json.JSONDecodeError):
        return None, "invalid JSON input"


def validate(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return "compatibility manifest requires schema_version 1"
    components = manifest.get("components")
    if not isinstance(components, list) or not components:
        return "compatibility manifest requires components"
    identifiers = set()
    for component in components:
        if not isinstance(component, dict):
            return "component must be an object"
        identifier = component.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            return "component ids must be unique non-empty strings"
        identifiers.add(identifier)
        if not isinstance(component.get("source"), str) \
                or not component["source"].startswith(("https://", "git@", "ssh://")):
            return f"component {identifier} requires a repository source"
        if not isinstance(component.get("version"), str) or not SEMVER.fullmatch(component["version"]):
            return f"component {identifier} requires a pinned semantic version"
        if not isinstance(component.get("commit"), str) or not SHA.fullmatch(component["commit"]):
            return f"component {identifier} requires a 40-character commit pin"
        if not isinstance(component.get("interface"), str) or not component["interface"]:
            return f"component {identifier} requires an interface identifier"
    checks = manifest.get("required_checks", [])
    if not isinstance(checks, list) or any(not isinstance(check, str) or not check for check in checks):
        return "required_checks must be a list of non-empty strings"
    return None


def main(argv):
    if len(argv) < 3 or argv[1] not in {"validate", "compare"}:
        print("usage: ws compat validate <manifest.json> | ws compat compare <manifest.json> --observed <results.json>", file=sys.stderr)
        return 2
    mode, manifest_path = argv[1], argv[2]
    manifest, error = load(manifest_path)
    if error:
        print(json.dumps({"version": 1, "status": "incomplete", "error": error}, sort_keys=True))
        return 2
    error = validate(manifest)
    if error:
        print(json.dumps({"version": 1, "status": "incomplete", "error": error}, sort_keys=True))
        return 2
    if mode == "validate":
        print(json.dumps({"version": 1, "status": "pass", "components": len(manifest["components"])}, indent=2))
        return 0
    if len(argv) != 5 or argv[3] != "--observed":
        print("usage: ws compat compare <manifest.json> --observed <results.json>", file=sys.stderr)
        return 2
    observed, error = load(argv[4])
    if error or not isinstance(observed, dict):
        print(json.dumps({"version": 1, "status": "incomplete", "error": "invalid observed results"}, sort_keys=True))
        return 2
    results = []
    findings = False
    for component in manifest["components"]:
        identifier = component["id"]
        actual = observed.get(identifier)
        if not isinstance(actual, dict):
            results.append({"id": identifier, "status": "not-run"})
            findings = True
            continue
        mismatches = {}
        for key in ("version", "commit", "interface"):
            if actual.get(key) != component[key]:
                mismatches[key] = "mismatch"
        status = "findings" if mismatches else "pass"
        findings = findings or bool(mismatches)
        results.append({"id": identifier, "status": status, **({"mismatches": mismatches} if mismatches else {})})
    report = {"version": 1, "status": "findings" if findings else "pass", "components": results}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
