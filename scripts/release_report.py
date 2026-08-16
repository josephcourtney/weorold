"""Create a complete release decision report from composite-gate step results."""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .json_schema import (
    JsonObject,
    JsonValue,
    canonical_json,
    load_object,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", action="append", default=[])
    args = parser.parse_args()
    try:
        steps: dict[str, str] = {}
        for raw in args.step:
            name, separator, status = raw.partition("=")
            if not separator or status not in {"pass", "fail", "skipped"}:
                raise ValueError(f"invalid release step: {raw}")
            steps[name] = status
        waivers = load_object(args.root / "testing-waivers.json", "testing-waivers.schema.json")
        active = cast(list[JsonValue], waivers["waivers"])
        waiver_errors: list[str] = []
        today = datetime.now(UTC).date().isoformat()
        for waiver_value in active:
            waiver = cast(JsonObject, waiver_value)
            if cast(str, waiver["expires"]) < today:
                waiver_errors.append(f"expired waiver: {waiver['scope']}")
        failed = sorted(name for name, status in steps.items() if status != "pass")
        artifact_candidates = (
            args.root / ".cache" / "quality" / "pytest-outcomes.json",
            args.root / ".cache" / "distribution.json",
            args.root / ".cache" / "wheel-system.json",
            args.root / ".cache" / "performance.json",
        )
        artifacts = {
            path.relative_to(args.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifact_candidates
            if path.exists()
        }
        report = {
            "version": 1,
            "kind": "weorold-release-evidence",
            "steps": dict(sorted(steps.items())),
            "waivers": active,
            "artifacts": artifacts,
            "findings": [*(f"failed release step: {name}" for name in failed), *waiver_errors],
            "decision": "pass" if not failed and not waiver_errors else "fail",
        }
        canonical = canonical_json(cast(JsonObject, report))
        report["run_id"] = hashlib.sha256(canonical.encode()).hexdigest()
        write_json(
            args.output,
            cast(JsonObject, report),
            "release-report.schema.json",
        )
        print(f"Release decision: {report['decision'].upper()}")
        return 0 if report["decision"] == "pass" else 1
    except (OSError, ValueError) as error:
        print(f"release report error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
