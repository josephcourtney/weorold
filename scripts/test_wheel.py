"""Exercise the exact built wheel from outside the repository checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from .json_schema import JsonObject, loads_json, write_json


def run(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float = 30
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"command failed ({result.returncode}): {' '.join(argv)}\n{detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--uv", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    wheels = sorted((root / "dist").glob("weorold-*.whl"))
    if len(wheels) != 1:
        print("wheel-system error: expected exactly one weorold wheel", file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="weorold-wheel-") as raw_directory:
            work = Path(raw_directory)
            environment = work / "venv"
            base_env = dict(os.environ)
            base_env.pop("PYTHONPATH", None)
            base_env["UV_CACHE_DIR"] = str(root / ".cache" / "uv")
            run(
                [args.uv, "venv", "--python", sys.executable, str(environment)],
                cwd=work,
                env=base_env,
            )
            python = environment / "bin" / "python"
            run(
                [
                    args.uv,
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    str(wheels[0]),
                    str(root / "tests" / "fixtures" / "wheel_target"),
                ],
                cwd=work,
                env=base_env,
                timeout=120,
            )
            executable = environment / "bin" / "weorold"
            target = "python:weorold_wheel_target:app"
            common = [target, "--program", "fixture"]
            captured = run(
                [str(executable), "describe", *common, "--format", "json"], cwd=work, env=base_env
            )
            captured_value = loads_json(
                captured.stdout,
                "json-value.schema.json",
                source="installed CLI capture output",
            )
            snapshot = work / "snapshot.json"
            write_json(snapshot, captured_value, "json-value.schema.json")
            reloaded = run(
                [str(executable), "describe", f"artifact:{snapshot}", "--format", "json"],
                cwd=work,
                env=base_env,
            )
            reloaded_value = loads_json(
                reloaded.stdout,
                "json-value.schema.json",
                source="installed CLI reload output",
            )
            if captured_value != reloaded_value:
                raise ValueError("installed artifact reload changed the snapshot")
            run([str(executable), "audit", *common, "--fail-on", "error"], cwd=work, env=base_env)
            documentation = work / "cli.md"
            run(
                [str(executable), "docs", *common, "--output", str(documentation)],
                cwd=work,
                env=base_env,
            )
            run(
                [str(executable), "check-docs", *common, "--output", str(documentation)],
                cwd=work,
                env=base_env,
            )
            run(
                [
                    str(executable),
                    "describe",
                    "python:weorold.cli.app:app",
                    "--program",
                    "weorold",
                    "--format",
                    "json",
                ],
                cwd=work,
                env=base_env,
            )
            consumer = run(
                [
                    str(python),
                    "-c",
                    "import weorold; print(weorold.SNAPSHOT_SCHEMA_VERSION); print(weorold.parse_target('python:weorold_wheel_target:app').kind.value)",
                ],
                cwd=work,
                env=base_env,
            )
            failure = subprocess.run(
                [
                    str(executable),
                    "describe",
                    "python:missing.module:app",
                    "--program",
                    "missing",
                    "--format",
                    "json",
                ],
                cwd=work,
                env=base_env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if failure.returncode != 3 or "Traceback" in failure.stderr:
                raise ValueError("installed CLI did not classify a loading error")
            report = {
                "version": 1,
                "decision": "pass",
                "wheel": wheels[0].name,
                "outside_checkout": not work.is_relative_to(root),
                "workflows": [
                    "self-inspection",
                    "capture",
                    "reload",
                    "audit",
                    "docs",
                    "check-docs",
                    "consumer",
                    "error",
                ],
                "consumer_output": consumer.stdout.splitlines(),
            }
            write_json(
                args.output,
                cast(JsonObject, report),
                "wheel-system-report.schema.json",
            )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"wheel-system error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
