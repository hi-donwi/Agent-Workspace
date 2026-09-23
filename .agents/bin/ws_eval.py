#!/usr/bin/env python3
"""Validate and compare synthetic agent evaluation scenarios."""

import json
import pathlib
import sys


def load(path: pathlib.Path):
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError):
        return None, "invalid JSON input"


def validate(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return "scenario catalog requires schema_version 1"
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return "scenario catalog requires scenarios"
    ids = set()
    for item in scenarios:
        if not isinstance(item, dict):
            return "scenario must be an object"
        scenario_id = item.get("id")
        if not isinstance(scenario_id, str) or not scenario_id or scenario_id in ids:
            return "scenario ids must be unique non-empty strings"
        ids.add(scenario_id)
        if not isinstance(item.get("request"), str) or not item["request"].strip():
            return f"scenario {scenario_id} requires a request"
        expected = item.get("expected")
        if not isinstance(expected, dict):
            return f"scenario {scenario_id} requires expected outcomes"
        for key in ("skills", "actions", "artifacts"):
            values = expected.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
                return f"scenario {scenario_id} has invalid expected {key}"
        fixture = item.get("fixture", {})
        if not isinstance(fixture, dict):
            return f"scenario {scenario_id} fixture must be an object"
    return None


def main(argv):
    if len(argv) < 3 or argv[1] not in {"validate", "compare"}:
        print("usage: ws eval validate <scenarios.json> | ws eval compare <scenarios.json> --observed <results.json>", file=sys.stderr)
        return 2
    mode = argv[1]
    scenario_path = pathlib.Path(argv[2])
    scenarios, error = load(scenario_path)
    if error:
        print(json.dumps({"version": 1, "status": "incomplete", "error": error}, sort_keys=True))
        return 2
    error = validate(scenarios)
    if error:
        print(json.dumps({"version": 1, "status": "incomplete", "error": error}, sort_keys=True))
        return 2
    if mode == "validate":
        print(json.dumps({"version": 1, "status": "pass", "scenarios": len(scenarios["scenarios"])}, indent=2))
        return 0

    if len(argv) != 5 or argv[3] != "--observed":
        print("usage: ws eval compare <scenarios.json> --observed <results.json>", file=sys.stderr)
        return 2
    observed, error = load(pathlib.Path(argv[4]))
    if error or not isinstance(observed, dict):
        print(json.dumps({"version": 1, "status": "incomplete", "error": "invalid observed results"}, sort_keys=True))
        return 2

    results = []
    findings = False
    not_run = False
    for scenario in scenarios["scenarios"]:
        scenario_id = scenario["id"]
        actual = observed.get(scenario_id)
        if not isinstance(actual, dict):
            results.append({"id": scenario_id, "status": "not-run"})
            not_run = True
            continue
        missing = {}
        for key in ("skills", "actions", "artifacts"):
            values = actual.get(key, [])
            expected = scenario["expected"].get(key, [])
            if not isinstance(values, list):
                values = []
            absent = sorted(set(expected) - set(values))
            if absent:
                missing[key] = absent
        status = "findings" if missing else "pass"
        findings = findings or bool(missing)
        results.append({"id": scenario_id, "status": status, **({"missing": missing} if missing else {})})
    status = "findings" if findings else ("not-run" if not_run else "pass")
    print(json.dumps({"version": 1, "status": status, "scenarios": results}, indent=2, sort_keys=True))
    return 1 if findings else (3 if not_run else 0)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
