"""Validate, export, aggregate, and summarize local test evidence."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import cast

from .json_schema import (
    JsonObject,
    JsonValue,
    load_object,
    write_json,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_evidence(path: Path, *, require_full: bool = True) -> JsonObject:
    value = load_object(path, "pytest-outcomes.schema.json")
    if require_full and value["full_suite"] is not True:
        raise ValueError(f"{path} is partial test evidence")
    if value["decision"] != "pass":
        raise ValueError(f"{path} does not contain passing evidence")
    return value


def environment_key(evidence: JsonObject) -> tuple[str, ...]:
    environment = cast(JsonObject, evidence["environment"])
    return tuple(
        str(environment[name])
        for name in ("revision", "lock_sha256", "os", "python", "architecture", "hostname")
    )


def comparable_runs(history: Path, current: JsonObject) -> list[JsonObject]:
    key = environment_key(current)
    runs: list[JsonObject] = []
    for path in sorted(history.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            candidate = validate_evidence(path)
        except (OSError, ValueError):
            continue
        if environment_key(candidate) == key:
            runs.append(candidate)
    return runs[:20]


def health(evidence_path: Path, history: Path) -> int:
    current = validate_evidence(evidence_path)
    runs = comparable_runs(history, current)
    outcomes: dict[str, set[str]] = defaultdict(set)
    durations: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for raw_test in cast(list[JsonValue], run["tests"]):
            if not isinstance(raw_test, dict):
                continue
            nodeid = raw_test.get("nodeid")
            outcome = raw_test.get("outcome")
            phases = raw_test.get("durations")
            if isinstance(nodeid, str) and isinstance(outcome, str):
                outcomes[nodeid].add(outcome)
            if isinstance(nodeid, str) and isinstance(phases, dict):
                values = [value for value in phases.values() if isinstance(value, (int, float))]
                durations[nodeid].append(float(sum(values)))
    flaky = sorted(nodeid for nodeid, values in outcomes.items() if len(values) > 1)
    observations = sum(len(values) for values in outcomes.values())
    flake_rate = (len(flaky) / observations * 100) if observations else 0.0
    slowest = sorted(((max(values), nodeid) for nodeid, values in durations.items()), reverse=True)[
        :10
    ]
    print(f"Comparable full runs: {len(runs)}/20")
    print(f"Observed flaky tests: {len(flaky)} ({flake_rate:.2f}%)")
    print("Slowest tests:")
    for duration, nodeid in slowest:
        print(f"  {duration:.3f}s  {nodeid}")
    if flaky:
        for nodeid in flaky:
            print(f"flake: {nodeid}", file=sys.stderr)
    return 1 if flake_rate >= 1.0 else 0


def compatibility(evidence_path: Path, destination: Path) -> Path:
    evidence = validate_evidence(evidence_path)
    environment = cast(JsonObject, evidence["environment"])
    python_minor = ".".join(str(environment["python"]).split(".")[:2])
    cell: JsonObject = {
        "version": 1,
        "kind": "weorold-compatibility-evidence",
        "os": environment["os"],
        "python": python_minor,
        "architecture": environment["architecture"],
        "revision": environment["revision"],
        "lock_sha256": environment["lock_sha256"],
        "test_run_id": evidence["run_id"],
        "test_evidence_sha256": digest(evidence_path),
        "decision": "pass",
    }
    destination.mkdir(parents=True, exist_ok=True)
    name = f"{cell['os']}-py{python_minor}-{cell['architecture']}.json"
    output = destination / name
    write_json(output, cell, "compatibility-evidence.schema.json")
    print(output)
    return output


def compatibility_check(directory: Path, matrix_path: Path, evidence_path: Path) -> int:
    current = validate_evidence(evidence_path)
    environment = cast(JsonObject, current["environment"])
    matrix = load_object(matrix_path, "compatibility-matrix.schema.json")
    required = cast(list[JsonValue], matrix["required"])
    found: dict[tuple[str, str], JsonObject] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        cell = load_object(path, "compatibility-evidence.schema.json")
        if (
            cell["revision"] != environment["revision"]
            or cell["lock_sha256"] != environment["lock_sha256"]
        ):
            errors.append(f"stale compatibility evidence: {path}")
            continue
        os_name = cast(str, cell["os"])
        python = cast(str, cell["python"])
        found[os_name, python] = cell
    missing: list[str] = []
    for raw in required:
        required_cell = cast(JsonObject, raw)
        key = cast(str, required_cell["os"]), cast(str, required_cell["python"])
        if key not in found:
            missing.append(f"{key[0]} Python {key[1]}")
    for message in (*errors, *(f"missing compatibility evidence: {cell}" for cell in missing)):
        print(message, file=sys.stderr)
    print(f"Compatibility cells: {len(found)}/{len(required)} required")
    return 1 if errors or missing else 0


def export_evidence(evidence_path: Path, destination: Path) -> None:
    evidence = validate_evidence(evidence_path)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / evidence_path.name
    shutil.copyfile(evidence_path, output)
    manifest = {
        "version": 1,
        "files": {output.name: digest(output)},
        "revision": cast(JsonObject, evidence["environment"])["revision"],
        "lock_sha256": cast(JsonObject, evidence["environment"])["lock_sha256"],
    }
    write_json(
        destination / "manifest.json",
        cast(JsonObject, manifest),
        "evidence-bundle-manifest.schema.json",
    )


def import_evidence(bundle: Path, destination: Path) -> None:
    manifest = load_object(bundle / "manifest.json", "evidence-bundle-manifest.schema.json")
    files = cast(JsonObject, manifest["files"])
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected_value in files.items():
        expected = cast(str, expected_value)
        source = bundle / name
        validate_evidence(source)
        if digest(source) != expected:
            raise ValueError(f"evidence digest mismatch: {name}")
        shutil.copyfile(source, destination / name)


def record_defect(
    ledger: Path,
    *,
    defect_id: str,
    affected_version: str,
    context: str,
    fix_revision: str,
    regression_test: str,
) -> None:
    if any(
        not value.strip()
        for value in (defect_id, affected_version, context, fix_revision, regression_test)
    ):
        raise ValueError("defect fields must be nonempty")
    data: JsonObject = {"version": 1, "defects": []}
    if ledger.exists():
        data = load_object(ledger, "defect-ledger.schema.json")
    defects = cast(list[JsonValue], data["defects"])
    if any(isinstance(item, dict) and item.get("id") == defect_id for item in defects):
        raise ValueError(f"duplicate defect id: {defect_id}")
    defects.append(
        {
            "id": defect_id,
            "affected_version": affected_version,
            "context": context,
            "fix_revision": fix_revision,
            "regression_test": regression_test,
        }
    )
    defects.sort(key=lambda item: str(item.get("id")) if isinstance(item, dict) else "")
    write_json(ledger, data, "defect-ledger.schema.json")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    health_parser = commands.add_parser("health")
    health_parser.add_argument("evidence", type=Path)
    health_parser.add_argument("history", type=Path)
    compat = commands.add_parser("compatibility")
    compat.add_argument("evidence", type=Path)
    compat.add_argument("destination", type=Path)
    check = commands.add_parser("compatibility-check")
    check.add_argument("directory", type=Path)
    check.add_argument("matrix", type=Path)
    check.add_argument("evidence", type=Path)
    export = commands.add_parser("export")
    export.add_argument("evidence", type=Path)
    export.add_argument("destination", type=Path)
    import_parser = commands.add_parser("import")
    import_parser.add_argument("bundle", type=Path)
    import_parser.add_argument("destination", type=Path)
    defect = commands.add_parser("record-defect")
    defect.add_argument("ledger", type=Path)
    defect.add_argument("--id", required=True)
    defect.add_argument("--affected-version", required=True)
    defect.add_argument("--context", required=True)
    defect.add_argument("--fix-revision", required=True)
    defect.add_argument("--regression-test", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "health":
            return health(args.evidence, args.history)
        if args.command == "compatibility":
            compatibility(args.evidence, args.destination)
        elif args.command == "compatibility-check":
            return compatibility_check(args.directory, args.matrix, args.evidence)
        elif args.command == "export":
            export_evidence(args.evidence, args.destination)
        elif args.command == "import":
            import_evidence(args.bundle, args.destination)
        elif args.command == "record-defect":
            record_defect(
                args.ledger,
                defect_id=args.id,
                affected_version=args.affected_version,
                context=args.context,
                fix_revision=args.fix_revision,
                regression_test=args.regression_test,
            )
    except (OSError, ValueError, KeyError) as error:
        print(f"test evidence error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
