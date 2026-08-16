"""Verify built distributions and record content digests."""

from __future__ import annotations

import argparse
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import cast

from .json_schema import JsonObject, write_json

FORBIDDEN_PARTS = {".cache", ".git", ".pytest_cache", "__pycache__", "tests"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def members(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            return tuple(member.name for member in archive.getmembers() if member.isfile())
    raise ValueError(f"unsupported distribution: {path}")


def verify(dist: Path) -> dict[str, object]:
    names = members(dist)
    forbidden = sorted(
        name
        for name in names
        if FORBIDDEN_PARTS.intersection(PurePosixPath(name).parts)
        or PurePosixPath(name).suffix in FORBIDDEN_SUFFIXES
    )
    if forbidden:
        raise ValueError(f"forbidden distribution members: {', '.join(forbidden)}")
    if not any(name.endswith(("METADATA", "PKG-INFO")) for name in names):
        raise ValueError(f"distribution lacks package metadata: {dist}")
    return {
        "path": dist.name,
        "sha256": hashlib.sha256(dist.read_bytes()).hexdigest(),
        "members": len(names),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        distributions = [
            path
            for path in sorted(args.dist.iterdir())
            if path.suffix == ".whl" or path.name.endswith(".tar.gz")
        ]
        artifacts = [verify(path) for path in distributions]
        if not artifacts or not any(cast(str, item["path"]).endswith(".whl") for item in artifacts):
            raise ValueError("no wheel was built")
        write_json(
            args.output,
            cast(JsonObject, {"version": 1, "decision": "pass", "artifacts": artifacts}),
            "distribution-report.schema.json",
        )
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"distribution verification error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
