from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from radon.complexity import cc_rank, cc_visit
from radon.metrics import h_visit, mi_rank, mi_visit
from radon.raw import analyze
from radon.visitors import Class, Function

from .json_schema import (
    JsonDocumentError,
    JsonObject,
    JsonSemanticError,
    JsonValue,
    load_object,
    write_json,
)

HALSTEAD_FIELDS = (
    "h1",
    "h2",
    "N1",
    "N2",
    "vocabulary",
    "length",
    "calculated_length",
    "volume",
    "difficulty",
    "effort",
    "time",
    "bugs",
)
RATCHET_HALSTEAD_FIELDS = ("volume", "difficulty", "effort", "bugs")
EPSILON = 1e-9


@dataclass(frozen=True)
class Thresholds:
    cyclomatic_ratchet: int = 11
    cyclomatic_ceiling: int = 21
    cyclomatic_tolerance: int = 0
    raw_sloc_ratchet: int = 400
    raw_sloc_ceiling: int = 800
    raw_sloc_tolerance: int = 5
    maintainability_ratchet: float = 20.0
    maintainability_tolerance: float = 0.25
    halstead_volume_ratchet: float = 1000.0
    halstead_volume_ceiling: float = 4000.0
    halstead_volume_tolerance: float = 5.0
    halstead_difficulty_ratchet: float = 10.0
    halstead_difficulty_ceiling: float = 15.0
    halstead_difficulty_tolerance: float = 0.1
    halstead_effort_ratchet: float = 10000.0
    halstead_effort_ceiling: float = 30000.0
    halstead_effort_tolerance: float = 100.0
    halstead_bugs_ratchet: float = 0.33
    halstead_bugs_ceiling: float = 1.25
    halstead_bugs_tolerance: float = 0.005


@dataclass(frozen=True)
class RawMetrics:
    loc: int
    lloc: int
    sloc: int
    comments: int
    multi: int
    blank: int
    single_comments: int


@dataclass(frozen=True)
class Snapshot:
    cyclomatic: dict[str, int]
    raw: dict[str, RawMetrics]
    maintainability: dict[str, float]
    halstead: dict[str, dict[str, float]]


@dataclass(frozen=True)
class Baseline:
    thresholds: Thresholds
    cyclomatic: dict[str, int]
    raw_sloc: dict[str, int]
    maintainability: dict[str, float]
    halstead: dict[str, dict[str, float]]


def _block_key(path: str, block: Function | Class) -> str:
    if isinstance(block, Function) and block.classname:
        name = f"{block.classname}.{block.name}"
    else:
        name = block.name
    kind = "method" if isinstance(block, Function) and block.is_method else "block"
    return f"{path}:{kind}:{name}"


def _complexity_blocks(source: str) -> list[Function | Class]:
    return list(cc_visit(source))


def collect_snapshot(source_dir: Path, root: Path) -> Snapshot:
    cyclomatic: dict[str, int] = {}
    raw: dict[str, RawMetrics] = {}
    maintainability: dict[str, float] = {}
    halstead: dict[str, dict[str, float]] = {}

    for file_path in sorted(source_dir.rglob("*.py")):
        path = file_path.relative_to(root).as_posix()
        source = file_path.read_text(encoding="utf-8")

        blocks = _complexity_blocks(source)
        block_keys = [_block_key(path, block) for block in blocks]
        duplicate_keys = {key for key, count in Counter(block_keys).items() if count > 1}
        for block, _key in zip(blocks, block_keys, strict=True):
            key = f"{_key}@{block.lineno}" if _key in duplicate_keys else _key
            cyclomatic[key] = block.complexity

        raw_report = analyze(source)
        raw[path] = RawMetrics(*raw_report)
        maintainability[path] = mi_visit(source, multi=True)

        halstead_report = h_visit(source).total
        halstead[path] = {
            field: float(getattr(halstead_report, field)) for field in HALSTEAD_FIELDS
        }

    return Snapshot(cyclomatic, raw, maintainability, halstead)


def build_baseline(snapshot: Snapshot, thresholds: Thresholds) -> Baseline:
    cyclomatic = {
        key: score
        for key, score in snapshot.cyclomatic.items()
        if score >= thresholds.cyclomatic_ratchet
    }
    raw_sloc = {
        path: report.sloc
        for path, report in snapshot.raw.items()
        if report.sloc >= thresholds.raw_sloc_ratchet
    }
    maintainability = {
        path: score
        for path, score in snapshot.maintainability.items()
        if score < thresholds.maintainability_ratchet
    }
    halstead: dict[str, dict[str, float]] = {}
    for field in RATCHET_HALSTEAD_FIELDS:
        threshold = getattr(thresholds, f"halstead_{field}_ratchet")
        halstead[field] = {
            path: metrics[field]
            for path, metrics in snapshot.halstead.items()
            if metrics[field] >= threshold
        }
    return Baseline(thresholds, cyclomatic, raw_sloc, maintainability, halstead)


def _compare_higher_is_worse(
    label: str,
    current: dict[str, int] | dict[str, float],
    expected: dict[str, int] | dict[str, float],
    *,
    ratchet: bool,
    tolerance: float = 0,
) -> list[str]:
    errors: list[str] = []
    for key in sorted(current.keys() | expected.keys()):
        current_value = current.get(key)
        expected_value = expected.get(key)
        if expected_value is None:
            errors.append(f"{label}: new problem: {key} = {current_value}")
        elif current_value is None:
            if ratchet:
                errors.append(f"{label}: improved or removed: {key}; refresh the baseline")
        elif current_value > expected_value + tolerance + EPSILON:
            errors.append(
                f"{label}: regression beyond tolerance {tolerance}: "
                f"{key} increased from {expected_value} to {current_value}"
            )
        elif ratchet and current_value < expected_value - tolerance - EPSILON:
            errors.append(
                f"{label}: improvement beyond tolerance {tolerance}: "
                f"{key} decreased from {expected_value} to {current_value}; refresh the baseline"
            )
    return errors


def _compare_lower_is_worse(
    label: str,
    current: dict[str, float],
    expected: dict[str, float],
    *,
    ratchet: bool,
    tolerance: float = 0.0,
) -> list[str]:
    errors: list[str] = []
    for key in sorted(current.keys() | expected.keys()):
        current_value = current.get(key)
        expected_value = expected.get(key)
        if expected_value is None:
            errors.append(f"{label}: new problem: {key} = {current_value}")
        elif current_value is None:
            if ratchet:
                errors.append(f"{label}: improved or removed: {key}; refresh the baseline")
        elif current_value < expected_value - tolerance - EPSILON:
            errors.append(
                f"{label}: regression beyond tolerance {tolerance}: "
                f"{key} decreased from {expected_value} to {current_value}"
            )
        elif ratchet and current_value > expected_value + tolerance + EPSILON:
            errors.append(
                f"{label}: improvement beyond tolerance {tolerance}: "
                f"{key} increased from {expected_value} to {current_value}; refresh the baseline"
            )
    return errors


def check_snapshot(snapshot: Snapshot, baseline: Baseline, *, ratchet: bool = False) -> list[str]:
    thresholds = baseline.thresholds
    errors: list[str] = []

    current_cyclomatic = build_baseline(snapshot, thresholds).cyclomatic
    errors.extend(
        _compare_higher_is_worse(
            "cyclomatic",
            current_cyclomatic,
            baseline.cyclomatic,
            ratchet=ratchet,
            tolerance=thresholds.cyclomatic_tolerance,
        )
    )
    for key, score in sorted(snapshot.cyclomatic.items()):
        if score >= thresholds.cyclomatic_ceiling:
            errors.append(
                f"cyclomatic: absolute ceiling {thresholds.cyclomatic_ceiling} exceeded: {key} = {score}"
            )

    current_raw = build_baseline(snapshot, thresholds).raw_sloc
    errors.extend(
        _compare_higher_is_worse(
            "raw SLOC",
            current_raw,
            baseline.raw_sloc,
            ratchet=ratchet,
            tolerance=thresholds.raw_sloc_tolerance,
        )
    )
    for path, report in sorted(snapshot.raw.items()):
        if report.sloc >= thresholds.raw_sloc_ceiling:
            errors.append(
                f"raw SLOC: absolute ceiling {thresholds.raw_sloc_ceiling} exceeded: {path} = {report.sloc}"
            )

    current_mi = build_baseline(snapshot, thresholds).maintainability
    errors.extend(
        _compare_lower_is_worse(
            "maintainability",
            current_mi,
            baseline.maintainability,
            ratchet=ratchet,
            tolerance=thresholds.maintainability_tolerance,
        )
    )

    current_halstead = build_baseline(snapshot, thresholds).halstead
    for field in RATCHET_HALSTEAD_FIELDS:
        errors.extend(
            _compare_higher_is_worse(
                f"Halstead {field}",
                current_halstead[field],
                baseline.halstead[field],
                ratchet=ratchet,
                tolerance=getattr(thresholds, f"halstead_{field}_tolerance"),
            )
        )
        ceiling = getattr(thresholds, f"halstead_{field}_ceiling")
        for path, metrics in sorted(snapshot.halstead.items()):
            if metrics[field] >= ceiling:
                errors.append(
                    f"Halstead {field}: absolute ceiling {ceiling} exceeded: {path} = {metrics[field]}"
                )
    return errors


def _format_number(value: float) -> str:
    return str(value) if isinstance(value, int) else f"{value:.2f}"


def print_report(snapshot: Snapshot, thresholds: Thresholds) -> None:
    scores = list(snapshot.cyclomatic.values())
    rank_counts = {rank: sum(cc_rank(score) == rank for score in scores) for rank in "ABCDEF"}
    average = sum(scores) / len(scores) if scores else 0.0
    maximum = max(scores, default=0)
    counts = " ".join(f"{rank}={rank_counts[rank]}" for rank in "ABCDEF")
    print(f"Cyclomatic: blocks={len(scores)} average={average:.2f} max={maximum} {counts}")
    for key, score in sorted(snapshot.cyclomatic.items(), key=lambda item: (-item[1], item[0])):
        if score >= thresholds.cyclomatic_ratchet:
            print(f"  {cc_rank(score)} {score:>2} {key}")

    totals = {
        field: sum(getattr(report, field) for report in snapshot.raw.values())
        for field in RawMetrics.__dataclass_fields__
    }
    print(
        "Raw: "
        + " ".join(
            f"{field.upper()}={totals[field]}"
            for field in ("loc", "lloc", "sloc", "comments", "multi", "blank")
        )
    )
    for path, report in sorted(snapshot.raw.items(), key=lambda item: (-item[1].sloc, item[0])):
        if report.sloc >= thresholds.raw_sloc_ratchet:
            print(f"  SLOC={report.sloc:>3} LOC={report.loc:>3} LLOC={report.lloc:>3} {path}")

    print("Maintainability: low-scoring files (<20, A threshold)")
    for path, score in sorted(
        snapshot.maintainability.items(), key=lambda item: (item[1], item[0])
    ):
        if score < thresholds.maintainability_ratchet:
            print(f"  {mi_rank(score)} {score:>5.2f} {path}")

    significant_halstead = {
        path
        for field in RATCHET_HALSTEAD_FIELDS
        for path in build_baseline(snapshot, thresholds).halstead[field]
    }
    print("Halstead: significant modules")
    print("  " + " ".join(HALSTEAD_FIELDS))
    for path in sorted(significant_halstead):
        metrics = snapshot.halstead[path]
        values = " ".join(_format_number(metrics[field]) for field in HALSTEAD_FIELDS)
        print(f"  {path}: {values}")


def _baseline_json(baseline: Baseline) -> JsonObject:
    return cast(
        JsonObject,
        {
            "version": 1,
            "thresholds": asdict(baseline.thresholds),
            "cyclomatic": baseline.cyclomatic,
            "raw_sloc": baseline.raw_sloc,
            "maintainability": baseline.maintainability,
            "halstead": baseline.halstead,
        },
    )


def _validate_threshold_relationships(thresholds: Thresholds) -> None:
    pairs = (
        ("cyclomatic", thresholds.cyclomatic_ratchet, thresholds.cyclomatic_ceiling),
        ("raw_sloc", thresholds.raw_sloc_ratchet, thresholds.raw_sloc_ceiling),
        ("halstead_volume", thresholds.halstead_volume_ratchet, thresholds.halstead_volume_ceiling),
        (
            "halstead_difficulty",
            thresholds.halstead_difficulty_ratchet,
            thresholds.halstead_difficulty_ceiling,
        ),
        ("halstead_effort", thresholds.halstead_effort_ratchet, thresholds.halstead_effort_ceiling),
        ("halstead_bugs", thresholds.halstead_bugs_ratchet, thresholds.halstead_bugs_ceiling),
    )
    invalid = [name for name, ratchet, ceiling in pairs if ratchet > ceiling]
    if invalid:
        raise JsonSemanticError(
            "threshold ratchets must not exceed their absolute ceilings: " + ", ".join(invalid)
        )


def write_baseline(path: Path, baseline: Baseline) -> None:
    _validate_threshold_relationships(baseline.thresholds)
    write_json(path, _baseline_json(baseline), "metrics-baseline.schema.json")


def read_baseline(path: Path) -> Baseline:
    data = load_object(path, "metrics-baseline.schema.json")
    threshold_values = cast(dict[str, int | float], data["thresholds"])
    thresholds = Thresholds(
        cyclomatic_ratchet=int(threshold_values["cyclomatic_ratchet"]),
        cyclomatic_ceiling=int(threshold_values["cyclomatic_ceiling"]),
        cyclomatic_tolerance=int(threshold_values["cyclomatic_tolerance"]),
        raw_sloc_ratchet=int(threshold_values["raw_sloc_ratchet"]),
        raw_sloc_ceiling=int(threshold_values["raw_sloc_ceiling"]),
        raw_sloc_tolerance=int(threshold_values["raw_sloc_tolerance"]),
        maintainability_ratchet=float(threshold_values["maintainability_ratchet"]),
        maintainability_tolerance=float(threshold_values["maintainability_tolerance"]),
        halstead_volume_ratchet=float(threshold_values["halstead_volume_ratchet"]),
        halstead_volume_ceiling=float(threshold_values["halstead_volume_ceiling"]),
        halstead_volume_tolerance=float(threshold_values["halstead_volume_tolerance"]),
        halstead_difficulty_ratchet=float(threshold_values["halstead_difficulty_ratchet"]),
        halstead_difficulty_ceiling=float(threshold_values["halstead_difficulty_ceiling"]),
        halstead_difficulty_tolerance=float(threshold_values["halstead_difficulty_tolerance"]),
        halstead_effort_ratchet=float(threshold_values["halstead_effort_ratchet"]),
        halstead_effort_ceiling=float(threshold_values["halstead_effort_ceiling"]),
        halstead_effort_tolerance=float(threshold_values["halstead_effort_tolerance"]),
        halstead_bugs_ratchet=float(threshold_values["halstead_bugs_ratchet"]),
        halstead_bugs_ceiling=float(threshold_values["halstead_bugs_ceiling"]),
        halstead_bugs_tolerance=float(threshold_values["halstead_bugs_tolerance"]),
    )
    _validate_threshold_relationships(thresholds)
    halstead_value = cast(dict[str, JsonValue], data["halstead"])
    return Baseline(
        thresholds=thresholds,
        cyclomatic={
            key: int(value) for key, value in cast(dict[str, int], data["cyclomatic"]).items()
        },
        raw_sloc={key: int(value) for key, value in cast(dict[str, int], data["raw_sloc"]).items()},
        maintainability={
            key: float(value)
            for key, value in cast(dict[str, int | float], data["maintainability"]).items()
        },
        halstead={
            field: {
                key: float(value)
                for key, value in cast(dict[str, int | float], halstead_value[field]).items()
            }
            for field in RATCHET_HALSTEAD_FIELDS
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report and ratchet Radon code metrics.")
    parser.add_argument("source", type=Path, help="Python source tree to analyze")
    parser.add_argument("baseline", type=Path, help="committed metrics baseline")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--strict",
        action="store_true",
        help="fail on metric regressions and hard ceiling violations",
    )
    mode.add_argument(
        "--ratchet",
        action="store_true",
        help="fail on regressions, hard ceiling violations, and baseline improvements",
    )
    mode.add_argument(
        "--update-baseline", action="store_true", help="replace the baseline with current debt"
    )
    args = parser.parse_args(argv)

    root = Path.cwd()
    source_dir = args.source.resolve()
    snapshot = collect_snapshot(source_dir, root)

    if args.update_baseline:
        try:
            thresholds = (
                read_baseline(args.baseline).thresholds if args.baseline.exists() else Thresholds()
            )
        except (OSError, JsonDocumentError) as exc:
            print(f"metrics baseline error: {exc}", file=sys.stderr)
            return 2
        baseline = build_baseline(snapshot, thresholds)
        write_baseline(args.baseline, baseline)
        print(f"updated metrics baseline: {args.baseline}")
        return 0

    try:
        baseline = read_baseline(args.baseline)
    except (OSError, JsonDocumentError) as exc:
        print(f"metrics baseline error: {exc}", file=sys.stderr)
        return 2

    print_report(snapshot, baseline.thresholds)
    if not (args.strict or args.ratchet):
        return 0

    errors = check_snapshot(snapshot, baseline, ratchet=args.ratchet)
    if errors:
        label = "Metrics ratchet failed" if args.ratchet else "Metrics gate failed"
        print(f"{label}:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        if args.ratchet:
            print(
                "Run `just complexity --update-baseline` after reviewing improvements.",
                file=sys.stderr,
            )
        return 1

    if args.ratchet:
        print("Metrics ratchet passed: baseline is current and no regressions were found.")
    else:
        print("Metrics gate passed: no regressions or hard ceiling violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
