from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from coverage import Coverage

from . import check_metrics, check_quality
from .json_schema import JsonObject, load_object

DIFF_COVERAGE_PATTERN = re.compile(r"^Coverage: (?P<percentage>\d+(?:\.\d+)?)%$", re.MULTILINE)


@dataclass(frozen=True)
class SummaryRow:
    metric: str
    current: str
    reference: str


@dataclass(frozen=True)
class TestHealth:
    duration_seconds: float
    scope_counts: dict[str, int]
    flaky_tests: tuple[str, ...]
    requirements_complete: int
    requirements_total: int


def _percentage(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def build_rows(
    metrics: check_metrics.Snapshot,
    metrics_baseline: check_metrics.Baseline,
    quality: check_quality.Snapshot,
    quality_baseline: check_quality.Baseline,
    *,
    diff_coverage: float,
    diff_coverage_floor: float,
    test_health: TestHealth | None = None,
) -> list[SummaryRow]:
    complexity_scores = list(metrics.cyclomatic.values())
    complexity_average = (
        sum(complexity_scores) / len(complexity_scores) if complexity_scores else 0.0
    )
    total_sloc = sum(report.sloc for report in metrics.raw.values())
    low_maintainability = sum(
        score < metrics_baseline.thresholds.maintainability_ratchet
        for score in metrics.maintainability.values()
    )
    significant_halstead = {
        path
        for field in check_metrics.RATCHET_HALSTEAD_FIELDS
        for path in check_metrics.build_baseline(metrics, metrics_baseline.thresholds).halstead[
            field
        ]
    }
    source_duplication = quality.duplication["source"]
    test_duplication = quality.duplication["tests"]
    rows = [
        SummaryRow(
            "Source SLOC",
            str(total_sloc),
            f"file ceiling {metrics_baseline.thresholds.raw_sloc_ceiling}",
        ),
        SummaryRow(
            "Cyclomatic complexity",
            f"avg {complexity_average:.2f}, max {max(complexity_scores, default=0)}",
            f"block ceiling {metrics_baseline.thresholds.cyclomatic_ceiling}",
        ),
        SummaryRow(
            "Low maintainability files",
            str(low_maintainability),
            f"MI < {metrics_baseline.thresholds.maintainability_ratchet:.0f}",
        ),
        SummaryRow(
            "Significant Halstead files", str(len(significant_halstead)), "baseline tracked"
        ),
        SummaryRow(
            "Statement coverage",
            _percentage(quality.coverage_global.statements),
            f"floor {quality_baseline.thresholds.coverage_statement_floor:.0f}%",
        ),
        SummaryRow(
            "Branch coverage",
            _percentage(quality.coverage_global.branches),
            f"floor {quality_baseline.thresholds.coverage_branch_floor:.0f}%",
        ),
        SummaryRow(
            "Changed-line coverage",
            _percentage(diff_coverage),
            f"floor {diff_coverage_floor:.0f}%",
        ),
        SummaryRow(
            "Dead-code findings", str(len(quality.dead_code)), str(len(quality_baseline.dead_code))
        ),
        SummaryRow(
            "Source duplication",
            f"{source_duplication.percentage:.2f}%, {source_duplication.clones} clones",
            f"ceiling {quality_baseline.thresholds.duplication_percentage_ceiling:.0f}%",
        ),
        SummaryRow(
            "Test duplication",
            f"{test_duplication.percentage:.2f}%, {test_duplication.clones} clones",
            f"ceiling {quality_baseline.thresholds.duplication_percentage_ceiling:.0f}%",
        ),
        SummaryRow(
            "Pytest skips/xfails", str(len(quality.outcomes)), str(len(quality_baseline.outcomes))
        ),
    ]
    if test_health is not None:
        scopes = ", ".join(f"{scope}={count}" for scope, count in test_health.scope_counts.items())
        rows.extend(
            [
                SummaryRow(
                    "Full-suite runtime", f"{test_health.duration_seconds:.2f}s", "current run"
                ),
                SummaryRow("Structural scope cases", scopes or "none", "exactly one per case"),
                SummaryRow("Flaky quarantines", str(len(test_health.flaky_tests)), "0 preferred"),
                SummaryRow(
                    "Critical requirements",
                    f"{test_health.requirements_complete}/{test_health.requirements_total}",
                    "all required scopes passing",
                ),
            ]
        )
    if quality.mutation is None:
        rows.append(SummaryRow("Mutation", "n/a", "run just mutation"))
    else:
        rows.append(
            SummaryRow(
                "Mutation",
                f"{quality.mutation.score:.2f}%, {len(quality.mutation.bad_mutants)} bad",
                f"floor {quality_baseline.thresholds.mutation_score_floor:.0f}%",
            )
        )
    return rows


def print_table(rows: list[SummaryRow]) -> None:
    headers = SummaryRow("Metric", "Current", "Reference")
    metric_width = max(len(headers.metric), *(len(row.metric) for row in rows))
    current_width = max(len(headers.current), *(len(row.current) for row in rows))
    reference_width = max(len(headers.reference), *(len(row.reference) for row in rows))
    print(
        f"{headers.metric:<{metric_width}}  "
        f"{headers.current:<{current_width}}  "
        f"{headers.reference:<{reference_width}}"
    )
    print(f"{'-' * metric_width}  {'-' * current_width}  {'-' * reference_width}")
    for row in rows:
        print(
            f"{row.metric:<{metric_width}}  "
            f"{row.current:<{current_width}}  "
            f"{row.reference:<{reference_width}}"
        )


def collect_diff_coverage(coverage_data: Path, diff_cover: Path) -> float:
    with tempfile.NamedTemporaryFile(suffix=".xml") as report_file:
        coverage = Coverage(data_file=str(coverage_data))
        coverage.load()
        coverage.xml_report(outfile=report_file.name)
        result = subprocess.run(
            [str(diff_cover), report_file.name, "--total-percent-float"],
            capture_output=True,
            check=False,
            text=True,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"diff-cover failed with exit code {result.returncode}: {detail}")
    match = DIFF_COVERAGE_PATTERN.search(result.stdout)
    if match is None:
        if "No lines with coverage information in this diff." in result.stdout:
            return 100.0
        raise ValueError("diff-cover output did not contain total coverage")
    return float(match.group("percentage"))


def mutation_artifacts_available(stats: Path, results: Path) -> bool:
    return stats.exists() and results.exists()


def read_test_health(path: Path) -> TestHealth:
    data = load_object(path, "pytest-outcomes.schema.json")
    if data["full_suite"] is not True:
        raise ValueError("pytest health requires a full-suite evidence artifact")
    scopes = cast(dict[str, int], data["scope_counts"])
    flaky = cast(list[str], data["flaky_tests"])
    requirements = cast(JsonObject, data["requirement_coverage"])
    complete = sum(cast(JsonObject, value)["complete"] is True for value in requirements.values())
    return TestHealth(
        float(cast(int | float, data["duration_seconds"])),
        dict(scopes),
        tuple(flaky),
        complete,
        len(requirements),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Display a compact code-quality summary.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--tests", type=Path, required=True)
    parser.add_argument("--metrics-baseline", type=Path, required=True)
    parser.add_argument("--quality-baseline", type=Path, required=True)
    parser.add_argument("--coverage-data", type=Path, required=True)
    parser.add_argument("--pytest-outcomes", type=Path, required=True)
    parser.add_argument("--duplication-source", type=Path, required=True)
    parser.add_argument("--duplication-tests", type=Path, required=True)
    parser.add_argument("--vulture", type=Path, required=True)
    parser.add_argument("--diff-cover", type=Path, required=True)
    parser.add_argument("--diff-cover-min", type=float, required=True)
    parser.add_argument("--mutation-stats", type=Path, required=True)
    parser.add_argument("--mutation-results", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        mutation = mutation_artifacts_available(args.mutation_stats, args.mutation_results)
        check_quality.require_fresh(args.duplication_source, (args.source,), "source duplication")
        check_quality.require_fresh(args.duplication_tests, (args.tests,), "test duplication")
        quality_args = argparse.Namespace(
            source=args.source,
            tests=args.tests,
            coverage_data=args.coverage_data,
            pytest_outcomes=args.pytest_outcomes,
            duplication_source=args.duplication_source,
            duplication_tests=args.duplication_tests,
            vulture=args.vulture,
            mutation=mutation,
            mutation_stats=args.mutation_stats,
            mutation_results=args.mutation_results,
        )
        metrics = check_metrics.collect_snapshot(args.source.resolve(), Path.cwd())
        metrics_baseline = check_metrics.read_baseline(args.metrics_baseline)
        quality = check_quality.collect_snapshot(quality_args)
        quality_baseline = check_quality.read_baseline(args.quality_baseline)
        test_health = read_test_health(args.pytest_outcomes)
        diff_coverage = collect_diff_coverage(args.coverage_data, args.diff_cover)
        rows = build_rows(
            metrics,
            metrics_baseline,
            quality,
            quality_baseline,
            diff_coverage=diff_coverage,
            diff_coverage_floor=args.diff_cover_min,
            test_health=test_health,
        )
        print_table(rows)
        metric_errors = check_metrics.check_snapshot(metrics, metrics_baseline)
        quality_errors = check_quality.check_snapshot(quality, quality_baseline, mutation=mutation)
        gate_errors = [*metric_errors, *quality_errors]
        if diff_coverage < args.diff_cover_min:
            gate_errors.append(
                f"changed-line coverage is below {args.diff_cover_min}: {diff_coverage}"
            )
        ratchet_errors = [
            *check_metrics.check_snapshot(metrics, metrics_baseline, ratchet=True),
            *check_quality.check_snapshot(
                quality, quality_baseline, mutation=mutation, ratchet=True
            ),
        ]
        print()
        print(
            f"Regression gate: {'PASS' if not gate_errors else f'FAIL ({len(gate_errors)} findings)'}"
        )
        ratchet_label = (
            "CURRENT" if not ratchet_errors else f"STALE ({len(ratchet_errors)} findings)"
        )
        print(f"Baseline ratchet: {ratchet_label}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"quality summary error: {exc}", file=sys.stderr)
        print(
            "Run `just check` to refresh standard artifacts and `just mutation` for mutation data.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
