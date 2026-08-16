from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import run_secret_scan


def test_secret_scan_runs_worktree_and_history_with_irrelevant_detector_disabled(tmp_path):
    commands = list(run_secret_scan.scan_commands("trufflehog", tmp_path / "exclude.txt"))

    assert [label for label, _command in commands] == ["working tree", "git history"]
    for _label, command in commands:
        assert command[:4] == [
            "trufflehog",
            "--no-update",
            "--fail",
            "--fail-on-scan-errors",
        ]
        assert command[4:6] == ["--exclude-detectors", "Lob"]
    assert commands[0][1][6:8] == ["filesystem", "."]
    assert commands[1][1][6:8] == ["git", "file://."]

    exclusions = "\n".join(run_secret_scan._EXCLUDED_PATHS)
    assert r"^\.git/" in exclusions
    assert r"^\.coverage(?:\..*)?$" in exclusions
    assert r"^\.pytest_cache/" in exclusions
    assert r"(^|/)__pycache__/" in exclusions


def test_secret_scan_preserves_secret_exit_code_when_other_scan_succeeds(monkeypatch, tmp_path):
    returncodes = iter((183, 0))
    seen: list[list[str]] = []

    def fake_run(command, *, check):
        assert check is False
        seen.append(command)
        return SimpleNamespace(returncode=next(returncodes))

    monkeypatch.setattr(run_secret_scan.subprocess, "run", fake_run)

    assert run_secret_scan._scan("trufflehog", Path(tmp_path / "exclude.txt")) == 183
    assert len(seen) == 2
