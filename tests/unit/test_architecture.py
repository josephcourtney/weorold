from __future__ import annotations

import ast
from pathlib import Path

_FORBIDDEN_ROOTS = {
    "gecweme",
    "weorold.domain",
    "weorold.environment",
    "weorold.route",
}


def test_source_package_has_no_consumer_domain_dependencies() -> None:
    violations: list[str] = []

    for path in Path("src/weorold").rglob("*.py"):
        tree = ast.parse(
            path.read_text(),
            filename=str(path),
        )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue

            for module in modules:
                if any(
                    module == root or module.startswith(f"{root}.") for root in _FORBIDDEN_ROOTS
                ):
                    violations.append(f"{path}: {module}")

    assert not violations, "\n".join(violations)
