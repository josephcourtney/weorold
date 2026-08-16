from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Lob credentials are not used by this project. TruffleHog's Lob detector has
# produced verified false positives for ordinary pytest test names, so keeping it
# enabled makes the security gate noisy without increasing coverage of relevant
# credentials.
EXCLUDED_DETECTORS = ("Lob",)

_EXCLUDED_PATHS = (
    r"^\.git/",
    r"^\.venv/",
    r"^build/",
    r"^dist/",
    r"^\.cache/",
    r"^\.coverage(?:\..*)?$",
    r"^\.pytest_cache/",
    r"(^|/)__pycache__/",
    r"\.pyc$",
    r"^references/pulsecode/nan/.*/fid$",
    r"^references/pulsecode/nan/.*\.zip$",
)


def _global_args(executable: str) -> list[str]:
    args = [
        executable,
        "--no-update",
        "--fail",
        "--fail-on-scan-errors",
    ]
    if EXCLUDED_DETECTORS:
        args.extend(("--exclude-detectors", ",".join(EXCLUDED_DETECTORS)))
    return args


def scan_commands(executable: str, exclusions: Path) -> Iterator[tuple[str, list[str]]]:
    """Yield scans for the working tree and committed history.

    The filesystem scan catches untracked/local files. The git scan covers committed
    history without crawling raw ``.git`` object files as ordinary filesystem data.
    """

    common = _global_args(executable)
    yield (
        "working tree",
        [*common, "filesystem", ".", "--exclude-paths", str(exclusions)],
    )
    yield (
        "git history",
        [*common, "git", "file://.", "--exclude-paths", str(exclusions)],
    )


def describe_failure(returncode: int) -> str | None:
    if returncode == 0:
        return None
    if returncode == 183:
        return "repository secrets were detected"
    return f"scanner setup or execution failed with exit code {returncode}"


def _scan(executable: str, exclusions: Path) -> int:
    result_code = 0
    for label, command in scan_commands(executable, exclusions):
        print(f"[sec-secrets] scanning {label}")
        result = subprocess.run(command, check=False)
        if result.returncode == 183:
            result_code = 183
        elif result.returncode != 0 and result_code == 0:
            result_code = result.returncode
    return result_code


def main() -> int:
    executable = shutil.which("trufflehog")
    if executable is None:
        print("[sec-secrets] ERROR: trufflehog not found on PATH", file=sys.stderr)
        return 1
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as exclusions:
        exclusions.write("\n".join(_EXCLUDED_PATHS))
        exclusions.write("\n")
        exclusions.flush()
        returncode = _scan(executable, Path(exclusions.name))
    failure = describe_failure(returncode)
    if failure is not None:
        print(f"[sec-secrets] ERROR: {failure}", file=sys.stderr)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
