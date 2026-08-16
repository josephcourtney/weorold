from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = (
    ROOT / "DESIGN.md",
    ROOT / "PLAN.md",
    ROOT / "STATUS.md",
    ROOT / "POLICY.md",
)
DEFAULT_GLOBS = (
    ROOT / "docs" / "adr",
    ROOT / "notes" / "design",
)

MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
BACKTICK_RE = re.compile(r"`([^`]+)`")
FILE_SUFFIXES = (
    ".cfg",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yml",
)
KNOWN_FILE_NAMES = {
    "AGENTS.md",
    "CHANGELOG.md",
    "DESIGN.md",
    "PLAN.md",
    "POLICY.md",
    "README.md",
    "STATUS.md",
    "justfile",
}


def _default_docs() -> list[Path]:
    docs = [path for path in DEFAULT_PATHS if path.exists()]
    for directory in DEFAULT_GLOBS:
        if directory.exists():
            docs.extend(sorted(directory.glob("*.md")))
    return docs


def _strip_anchor(target: str) -> str:
    return target.split("#", 1)[0]


def _is_external_or_anchor(target: str) -> bool:
    return (
        not target
        or "<" in target
        or ">" in target
        or target.startswith(("#", "mailto:", "tel:"))
        or "://" in target
    )


def _is_file_like_code_span(text: str) -> bool:
    if text in KNOWN_FILE_NAMES:
        return True
    if text.startswith(("./", "../", "docs/", "notes/", "scripts/", "src/", "tests/")):
        return True
    return text.endswith(FILE_SUFFIXES)


def _iter_reference_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip()
        if not _is_external_or_anchor(target):
            targets.append(target)
    for match in BACKTICK_RE.finditer(text):
        target = match.group(1).strip()
        if not _is_external_or_anchor(target) and _is_file_like_code_span(target):
            targets.append(target)
    return targets


def _resolve_reference(doc: Path, target: str) -> Path:
    target = _strip_anchor(target)
    if target.startswith("/"):
        return ROOT / target.removeprefix("/")
    relative_to_doc = (doc.parent / target).resolve()
    if relative_to_doc.exists():
        return relative_to_doc
    return (ROOT / target).resolve()


def _validate_doc(doc: Path) -> list[str]:
    errors: list[str] = []
    text = doc.read_text(encoding="utf-8")
    for target in _iter_reference_targets(text):
        stripped = _strip_anchor(target)
        if not stripped:
            continue
        resolved = _resolve_reference(doc, stripped)
        if not resolved.exists():
            try:
                display_doc = doc.relative_to(ROOT)
            except ValueError:
                display_doc = doc
            errors.append(f"{display_doc}: missing local reference {target!r}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local file references in markdown docs.")
    parser.add_argument("paths", nargs="*", type=Path, help="Markdown files to inspect.")
    args = parser.parse_args(argv)

    docs = args.paths or _default_docs()
    errors: list[str] = []
    for doc in docs:
        errors.extend(_validate_doc(doc.resolve()))

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"documentation reference check passed for {len(docs)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
