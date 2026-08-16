# Monorepo-aware justfile (uv workspace)
# ======================================================================
# Global shell + environment
# ======================================================================

set shell := ["bash", "-euo", "pipefail", "-c"]
set dotenv-load := true
set export := true

# ----------------------------------------------------------------------
# Config (overridable via env/.env)
# ----------------------------------------------------------------------

MODE          := env("MODE", "dev")  # dev | debug | ci
ROOT_DIR       := justfile_directory()
PACKAGE        := file_stem(ROOT_DIR)
PYTHON_PACKAGE := env("PYTHON_PACKAGE", "weorold")
VERBOSE        := env("VERBOSE", "0")
REPO_CACHE_DIR := ROOT_DIR + "/.cache"
UV_CACHE_DIR   := REPO_CACHE_DIR + "/uv"
RUFF_CACHE_DIR := REPO_CACHE_DIR + "/ruff"

PY_TESTPATH    := "tests "
PY_SRC         := "src "
PY_TOOLING     := "scripts "

# ----------------------------------------------------------------------
# Tool wrappers
# ----------------------------------------------------------------------

UV                  := "uv --cache-dir " + UV_CACHE_DIR
PYTHON              := ROOT_DIR + "/.venv/bin/python"
RUFF                := ROOT_DIR + "/.venv/bin/ruff"
PYTEST              := ROOT_DIR + "/.venv/bin/pytest"
TY                  := ROOT_DIR + "/.venv/bin/ty"
SHOWCOV             := ROOT_DIR + "/.venv/bin/showcov"
MUTMUT              := ROOT_DIR + "/.venv/bin/mutmut"
WILY                := ROOT_DIR + "/.venv/bin/wily"
WILY_CACHE          := ROOT_DIR + "/.wily"
WILY_CONFIG         := ROOT_DIR + "/wily.cfg"
VULTURE             := ROOT_DIR + "/.venv/bin/vulture"
RADON               := ROOT_DIR + "/.venv/bin/radon"
METRICS_BASELINE    := ROOT_DIR + "/scripts/metrics-baseline.json"
METRICS_CHECK       := "scripts.check_metrics"
QUALITY_BASELINE    := ROOT_DIR + "/scripts/quality-baseline.json"
QUALITY_CHECK       := "scripts.check_quality"
QUALITY_CACHE       := REPO_CACHE_DIR + "/quality"
PYTEST_JSON_REPORT  := QUALITY_CACHE + "/pytest-report.json"
PYTEST_OUTCOMES     := QUALITY_CACHE + "/pytest-outcomes.json"
PYTEST_PARTIAL_JSON_REPORT := QUALITY_CACHE + "/pytest-report-partial.json"
PYTEST_PARTIAL_OUTCOMES    := QUALITY_CACHE + "/pytest-outcomes-partial.json"
PYTEST_PARTIAL_COVERAGE    := QUALITY_CACHE + "/coverage-partial"
DUP_SOURCE_REPORT   := QUALITY_CACHE + "/dup-source/jscpd-report.json"
DUP_TEST_REPORT     := QUALITY_CACHE + "/dup-tests/jscpd-report.json"
TEST_HISTORY        := REPO_CACHE_DIR + "/test-history"
COMPATIBILITY_DIR   := REPO_CACHE_DIR + "/compatibility"
PERFORMANCE_HISTORY := REPO_CACHE_DIR + "/performance-history"
PERFORMANCE_REPORT  := REPO_CACHE_DIR + "/performance.json"
PERFORMANCE_BASELINE := ROOT_DIR + "/performance-baseline.json"
DIST_REPORT         := REPO_CACHE_DIR + "/distribution.json"
WHEEL_REPORT        := REPO_CACHE_DIR + "/wheel-system.json"
RELEASE_REPORT      := REPO_CACHE_DIR + "/release.json"
DEFECT_LEDGER       := REPO_CACHE_DIR + "/defects.json"
COVERAGE_XML        := ROOT_DIR + "/coverage.xml"
JSCPD               := "npx --yes jscpd@4.0"
DIFF_COVER          := ROOT_DIR + "/.venv/bin/diff-cover"
DIFF_COVER_MIN      := env("DIFF_COVER_MIN", "85")
IMPORTLINTER        := ROOT_DIR + "/.venv/bin/lint-imports"
IMPORTLINTER_CONFIG := ROOT_DIR + "/import-linter.toml"

# ======================================================================
# pytest options
# ======================================================================

PYTEST_DEV_WORKERS := env("PYTEST_DEV_WORKERS", "auto")
PYTEST_DEV_DIST    := env("PYTEST_DEV_DIST", "loadscope")

# Shared option bundles
PYTEST_QUIET_OPTS     := "-q --tb=short -r fE --show-capture=no -o log_cli=false"
PYTEST_DEBUG_OPTS     := "-vv --tb=long -l --show-capture=all -o log_cli=true"
PYTEST_LOG_OPTS       := "-q --tb=short -r fE --show-capture=no -o log_cli=true --log-cli-level=INFO"
PYTEST_FAST_EXPR      := "-m 'not slow'"
PYTEST_FAILING_OPTS   := "--lf"
PYTEST_DEV_THRESHOLD  := env("PYTEST_DEV_THRESHOLD", "80")
PYTEST_DEV_BASE_OPTS  := "--testmon --no-cov"
PYTEST_DEV_XDIST_OPTS := "-n '" + PYTEST_DEV_WORKERS + "' --dist '" + PYTEST_DEV_DIST + "'"

# ======================================================================
# Meta / defaults
# ======================================================================

[private]
default: help

[doc("""
Show the workflow guide and the recipe list.

Use this as the primary entry point. It explains which recipe to run for
iteration, measurement, regression gating, baseline maintenance, and release
validation.
""")]
help:
  @just _log_start help
  @printf '%s\n' 'Workflow:'
  @printf '%s\n' '  Daily edit loop:        just test --dev [selection]'
  @printf '%s\n' '  Apply safe fixes:       just fix'
  @printf '%s\n' '  Full local gate:        just check'
  @printf '%s\n' '  Health report:          just measure'
  @printf '%s\n' '  Longitudinal health:    just health'
  @printf '%s\n' '  Installed wheel test:   just test-wheel'
  @printf '%s\n' '  Baseline freshness:     just ratchet'
  @printf '%s\n' '  Accept reviewed debt:   just update-baselines'
  @printf '%s\n' '  Release validation:     just release-check'
  @printf '%s\n' ''
  @printf '%s\n' 'Common focused commands:'
  @printf '%s\n' '  just lint               Ruff check with safe fixes'
  @printf '%s\n' '  just format             Ruff format'
  @printf '%s\n' '  just test --fast        Skip tests marked slow'
  @printf '%s\n' '  just test --marker unit Run a pytest marker expression'
  @printf '%s\n' '  just test --durations 25 Report the slowest tests'
  @printf '%s\n' '  just test --failing     Re-run last failing tests'
  @printf '%s\n' '  just test --logs        Compact output with live logs'
  @printf '%s\n' '  just test --debug       Verbose output and local variables'
  @printf '%s\n' '  just quality            Refresh tests + quality artifacts and report debt'
  @printf '%s\n' '  just complexity --raw   Detailed Radon report'
  @printf '%s\n' ''
  @printf '%s\n' 'Recipes:'
  @just --list --unsorted --list-prefix '  '
  @just _log_end help

[doc("""
Print effective paths, tool locations, cache locations, and selected versions.

Use when a recipe is failing because a tool, virtual environment, or generated
artifact is not where the justfile expects it to be.
""")]
env:
  @just _log_start env
  @echo "MODE={{MODE}}"
  @echo "PACKAGE={{PACKAGE}}"
  @echo "PYTHON_PACKAGE={{PYTHON_PACKAGE}}"
  @echo "PY_TESTPATH={{PY_TESTPATH}}"
  @echo "PY_SRC={{PY_SRC}}"
  @echo "UV={{UV}}"
  @echo "RUFF={{RUFF}}"
  @echo "PYTEST={{PYTEST}}"
  @echo "TY={{TY}}"
  @echo "SHOWCOV={{SHOWCOV}}"
  @echo "MUTMUT={{MUTMUT}}"
  @{{UV}} --version || true
  @{{PYTEST}} --version || true
  @{{RUFF}} --version || true
  @echo "WILY={{WILY}}"
  @echo "WILY_CACHE={{WILY_CACHE}}"
  @echo "WILY_CONFIG={{WILY_CONFIG}}"
  @echo "VULTURE={{VULTURE}}"
  @echo "RADON={{RADON}}"
  @echo "QUALITY_CACHE={{QUALITY_CACHE}}"
  @echo "PYTEST_JSON_REPORT={{PYTEST_JSON_REPORT}}"
  @echo "PYTEST_OUTCOMES={{PYTEST_OUTCOMES}}"
  @echo "JSCPD={{JSCPD}}"
  @echo "COVERAGE_XML={{COVERAGE_XML}}"
  @echo "DIFF_COVER={{DIFF_COVER}}"
  @echo "DIFF_COVER_MIN={{DIFF_COVER_MIN}}"
  @just _log_end env

# ----------------------------------------------------------------------
# Logging/cache helpers
# ----------------------------------------------------------------------

[private]
_log_start NAME:
  @bash -euo pipefail -c 'if [ "{{VERBOSE}}" != "0" ]; then printf "\n=== START: %s ===\n" "{{NAME}}"; fi'

[private]
_log_end NAME:
  @bash -euo pipefail -c 'if [ "{{VERBOSE}}" != "0" ]; then printf "=== END: %s ===\n\n" "{{NAME}}"; fi'

[private]
_cache_dirs:
  @mkdir -p {{REPO_CACHE_DIR}} {{UV_CACHE_DIR}} {{RUFF_CACHE_DIR}} {{QUALITY_CACHE}}

# ======================================================================
# Bootstrap
# ======================================================================

[group('bootstrap')]
[arg("all", long, value="true")]
[doc("""
Refresh the virtual environment with uv.

Default installs the default dependency groups. Use --all for all dependency
groups.
""")]
setup all="false":
  @just _log_start setup
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=({{UV}} sync); \
    if [ "{{all}}" = "true" ]; then args+=(--all-groups); fi; \
    "${args[@]}" \
  '
  @just _log_end setup

# ======================================================================
# lint / format / type-check
# ======================================================================

[group('code quality')]
[arg("no_fix", long, value="true")]
[doc("""
Run `ruff check` over source, tests, and tooling.

By default this applies Ruff's safe automatic fixes. Use --no-fix when you want
a check-only lint pass without modifying files.
""")]
lint no_fix="false":
  @just _log_start lint
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=("{{RUFF}}" check --cache-dir "{{RUFF_CACHE_DIR}}"); \
    if [ "{{no_fix}}" = "true" ]; then \
      args+=(--no-fix); \
    else \
      args+=(--fix); \
    fi; \
    args+=({{PY_SRC}} {{PY_TESTPATH}} {{PY_TOOLING}}); \
    "${args[@]}" \
  '
  @just _log_end lint

[group('code quality')]
[doc("Run Ruff linting in check-only mode for CI and regression gates.")]
lint-check:
  @just _log_start lint-check
  @just _cache_dirs
  @bash -euo pipefail -c '"{{RUFF}}" check --cache-dir "{{RUFF_CACHE_DIR}}" --no-fix {{PY_SRC}} {{PY_TESTPATH}} {{PY_TOOLING}}'
  @just _log_end lint-check

[group('code quality')]
[doc("Validate import-linter architecture contracts from import-linter.toml.")]
lint-imports:
  @just _log_start lint-imports
  @bash -euo pipefail -c 'if [ ! -x "{{IMPORTLINTER}}" ]; then echo "[lint-imports] ERROR: lint-imports not found ({{IMPORTLINTER}}); run '\''just setup'\''" >&2; exit 1; fi; set +e; output="$("{{IMPORTLINTER}}" --verbose --config "{{IMPORTLINTER_CONFIG}}" 2>&1)"; status=$?; set -e; if [ "$status" -ne 0 ]; then echo "[lint-imports] FAILED"; echo; echo "$output"; exit "$status"; else echo "[lint-imports] no import-linter contract violations detected."; fi'
  @just _log_end lint-imports

[group('code quality')]
[arg("check", long, value="true")]
[doc("""
Run `ruff format` over source, tests, and tooling.

By default this rewrites files. Use --check for a non-mutating formatting gate.
""")]
format check="false":
  @just _log_start format
  @just _cache_dirs
  @bash -euo pipefail -c '\
    args=("{{RUFF}}" format --cache-dir "{{RUFF_CACHE_DIR}}"); \
    if [ "{{check}}" = "true" ]; then args+=(--check); fi; \
    args+=({{PY_SRC}} {{PY_TESTPATH}} {{PY_TOOLING}}); \
    "${args[@]}" \
  '
  @just _log_end format

[group('code quality')]
[doc("Run ty over source, tests, and scripts. Missing ty fails in MODE=ci and skips locally.")]
typecheck:
  @just _log_start typecheck
  @bash -euo pipefail -c '\
    if [ -x "{{TY}}" ]; then \
      "{{TY}}" check {{PY_SRC}} {{PY_TESTPATH}} {{PY_TOOLING}}; \
      exit 0; \
    fi; \
    if [ "{{MODE}}" = "ci" ]; then \
      echo "[typecheck] ERROR: ty not found ({{TY}}) and MODE=ci requires typechecking" >&2; \
      exit 1; \
    fi; \
    echo "[typecheck] skipping: ty not found ({{TY}}) (MODE={{MODE}})" \
  '
  @just _log_end typecheck

[group('code quality')]
[doc("Run a raw vulture dead-code scan. This is exploratory; baseline gating is handled by `just quality`.")]
dead-code:
  @just _log_start dead-code
  @bash -euo pipefail -c 'if [ ! -x "{{VULTURE}}" ]; then echo "[dead-code] ERROR: vulture not found ({{VULTURE}}); run just setup" >&2; exit 1; fi; "{{VULTURE}}" --min-confidence 61 {{PY_SRC}} {{PY_TESTPATH}}'
  @just _log_end dead-code

[group('code quality')]
[arg("raw", long, value="true")]
[arg("strict", long, value="true")]
[arg("ratchet", long, value="true")]
[arg("update_baseline", long="update-baseline", value="true")]
[doc("""
Report or gate Radon complexity and maintainability metrics.

Default prints the compact tracked-debt report. Use --raw for full Radon output,
--strict for regression gating, --ratchet to require baseline refresh after
improvements, and --update-baseline only after reviewing intentional changes.
The mode flags are mutually exclusive.
""")]
complexity raw="false" strict="false" ratchet="false" update_baseline="false":
  @just _log_start complexity
  @bash -euo pipefail -c '\
    selected=0; \
    [ "{{raw}}" = "true" ] && selected=$((selected + 1)); \
    [ "{{strict}}" = "true" ] && selected=$((selected + 1)); \
    [ "{{ratchet}}" = "true" ] && selected=$((selected + 1)); \
    [ "{{update_baseline}}" = "true" ] && selected=$((selected + 1)); \
    if [ "$selected" -gt 1 ]; then \
      echo "[complexity] ERROR: choose at most one of --raw, --strict, --ratchet, or --update-baseline" >&2; \
      exit 2; \
    fi; \
    if [ "{{raw}}" = "true" ]; then \
      echo "== Cyclomatic complexity =="; \
      "{{RADON}}" cc -s -a -o SCORE {{PY_SRC}}; \
      echo; echo "== Raw metrics =="; \
      "{{RADON}}" raw -s {{PY_SRC}}; \
      echo; echo "== Maintainability index =="; \
      "{{RADON}}" mi -s --sort {{PY_SRC}}; \
      echo; echo "== Halstead metrics =="; \
      "{{RADON}}" hal {{PY_SRC}}; \
    elif [ "{{strict}}" = "true" ]; then \
      "{{PYTHON}}" -m "{{METRICS_CHECK}}" --strict {{PY_SRC}} "{{METRICS_BASELINE}}"; \
    elif [ "{{ratchet}}" = "true" ]; then \
      "{{PYTHON}}" -m "{{METRICS_CHECK}}" --ratchet {{PY_SRC}} "{{METRICS_BASELINE}}"; \
    elif [ "{{update_baseline}}" = "true" ]; then \
      "{{PYTHON}}" -m "{{METRICS_CHECK}}" --update-baseline {{PY_SRC}} "{{METRICS_BASELINE}}"; \
    else \
      "{{PYTHON}}" -m "{{METRICS_CHECK}}" {{PY_SRC}} "{{METRICS_BASELINE}}"; \
    fi \
  '
  @just _log_end complexity

[group('code quality')]
[doc("Generate jscpd duplication reports for source and tests for `just quality`.")]
dup:
  @just _log_start dup
  @mkdir -p {{QUALITY_CACHE}} {{REPO_CACHE_DIR}}/npm
  @rm -rf {{QUALITY_CACHE}}/dup-source {{QUALITY_CACHE}}/dup-tests
  NPM_CONFIG_CACHE={{REPO_CACHE_DIR}}/npm {{JSCPD}} src --format python --min-lines 10 --reporters console,json --output {{QUALITY_CACHE}}/dup-source --silent
  NPM_CONFIG_CACHE={{REPO_CACHE_DIR}}/npm {{JSCPD}} tests --format python --min-lines 10 --reporters console,json --output {{QUALITY_CACHE}}/dup-tests --silent
  @just _log_end dup

[group('code quality')]
[arg("strict", long, value="true")]
[arg("ratchet", long, value="true")]
[arg("update_baseline", long="update-baseline", value="true")]
[arg("mutation", long, value="true")]
[arg("use_existing_test", long="use-existing-test", value="true")]
[doc("""
Report or gate test-quality metrics: coverage, dead code, duplication, pytest
skips/xfails, and optionally mutation results.

By default this refreshes full test coverage/outcome artifacts and duplication
reports before reading them. Use --use-existing-test inside composite flows that
already ran `just test`; duplication is still refreshed. Use --strict to fail on
regressions, --ratchet to require baseline refresh after improvements, and
--update-baseline only after reviewing intentional changes.
""")]
quality strict="false" ratchet="false" update_baseline="false" mutation="false" use_existing_test="false":
  @just _log_start quality
  @bash -euo pipefail -c '\
    selected=0; \
    [ "{{strict}}" = "true" ] && selected=$((selected + 1)); \
    [ "{{ratchet}}" = "true" ] && selected=$((selected + 1)); \
    [ "{{update_baseline}}" = "true" ] && selected=$((selected + 1)); \
    if [ "$selected" -gt 1 ]; then \
      echo "[quality] ERROR: choose at most one of --strict, --ratchet, or --update-baseline" >&2; \
      exit 2; \
    fi \
  '
  @bash -euo pipefail -c 'if [ "{{use_existing_test}}" != "true" ]; then just test; fi'
  @just dup
  @bash -euo pipefail -c '\
    args=("{{PYTHON}}" -m "{{QUALITY_CHECK}}" \
      --source src --tests tests \
      --baseline "{{QUALITY_BASELINE}}" \
      --coverage-data "{{ROOT_DIR}}/.coverage" \
      --pytest-outcomes "{{PYTEST_OUTCOMES}}" \
      --duplication-source "{{DUP_SOURCE_REPORT}}" \
      --duplication-tests "{{DUP_TEST_REPORT}}" \
      --vulture "{{VULTURE}}"); \
    [ "{{strict}}" = "true" ] && args+=(--strict); \
    [ "{{ratchet}}" = "true" ] && args+=(--ratchet); \
    [ "{{update_baseline}}" = "true" ] && args+=(--update-baseline); \
    [ "{{mutation}}" = "true" ] && args+=(--mutation); \
    "${args[@]}" \
  '
  @just _log_end quality

# ======================================================================
# Security / supply chain
# ======================================================================

[group('security')]
[doc("Run trufflehog secret scanning. Fails if trufflehog is missing or the scan fails.")]
sec-secrets:
  @just _log_start sec-secrets
  @"{{PYTHON}}" -m scripts.run_secret_scan
  @just _log_end sec-secrets

[group('security')]
[doc("Run pip-audit against the local virtual environment.")]
sec-deps:
  @just _log_start sec-deps
  @bash -euo pipefail -c 'if [ -x .venv/bin/pip-audit ]; then PIP_NO_CACHE_DIR=1 .venv/bin/pip-audit; else echo "[sec-deps] ERROR: .venv/bin/pip-audit not found; run '\''just setup'\''" >&2; exit 1; fi'
  @just _log_end sec-deps

[group('security')]
[doc("Run all security checks.")]
security:
  @just _log_start security
  @just sec-secrets
  @just sec-deps
  @just _log_end security

# ======================================================================
# Testing
# ======================================================================

[group('testing')]
[arg("fast", long, value="true")]
[arg("failing", long, value="true")]
[arg("dev", long, value="true")]
[arg("quiet", long, value="quiet")]
[arg("logs", long, value="logs")]
[arg("debug", long, value="debug")]
[arg("marker", long)]
[arg("durations", long)]
[doc("""
Run the test suite and fail if pytest fails.

Selection may be a package suffix under tests/, a test path, or a nodeid.
Use --fast to skip slow tests, --marker for a pytest marker expression,
--durations to report slow tests, --failing for pytest --lf, and --dev for
testmon plus conditional xdist. Choose at most one output mode: --quiet,
--logs, or --debug. Only an unfiltered full run refreshes the canonical coverage
and pytest outcome artifacts consumed by `just quality`.
""")]
test fast="false" dev="false" quiet="" logs="" debug="" failing="false" marker="" durations="" *selection:
  @just _test "true" "{{fast}}" "{{dev}}" "{{quiet}}" "{{logs}}" "{{debug}}" "{{failing}}" "{{marker}}" "{{durations}}" {{selection}}

[group('testing')]
[doc("Build and test the exact wheel from outside the checkout with an independent installed target.")]
test-wheel:
  @just _log_start test-wheel
  @just build
  @"{{PYTHON}}" -m scripts.verify_distribution "{{ROOT_DIR}}/dist" "{{DIST_REPORT}}"
  @"{{PYTHON}}" -m scripts.test_wheel --root "{{ROOT_DIR}}" --uv "$(command -v uv)" --output "{{WHEEL_REPORT}}"
  @just _log_end test-wheel

[group('testing')]
[doc("Run the full suite and assess comparable local history for flakes and slow tests.")]
health:
  @just _log_start health
  @just test
  @"{{PYTHON}}" -m scripts.test_evidence health "{{PYTEST_OUTCOMES}}" "{{TEST_HISTORY}}"
  @just _log_end health

[group('testing')]
[doc("Run the full suite and emit portable evidence for the current OS/Python cell.")]
compatibility:
  @just _log_start compatibility
  @just test
  @"{{PYTHON}}" -m scripts.test_evidence compatibility "{{PYTEST_OUTCOMES}}" "{{COMPATIBILITY_DIR}}"
  @just _log_end compatibility

[group('testing')]
[doc("Require passing evidence for every declared OS/Python compatibility cell.")]
compatibility-check directory=COMPATIBILITY_DIR:
  @"{{PYTHON}}" -m scripts.test_evidence compatibility-check "{{directory}}" "{{ROOT_DIR}}/testing-compatibility.json" "{{PYTEST_OUTCOMES}}"

[group('testing')]
[arg("strict", long, value="true")]
[arg("update_baseline", long="update-baseline", value="true")]
[doc("Measure fixed CLI operations; strict mode requires a calibrated comparable baseline.")]
performance strict="false" update_baseline="false":
  @just _log_start performance
  @bash -euo pipefail -c '\
    args=("{{PYTHON}}" -m scripts.performance_check \
      --root "{{ROOT_DIR}}" --executable "{{ROOT_DIR}}/.venv/bin/weorold" \
      --baseline "{{PERFORMANCE_BASELINE}}" --history "{{PERFORMANCE_HISTORY}}" \
      --output "{{PERFORMANCE_REPORT}}"); \
    [ "{{strict}}" = "true" ] && args+=(--strict); \
    [ "{{update_baseline}}" = "true" ] && args+=(--update-baseline); \
    "${args[@]}" \
  '
  @just _log_end performance

[group('testing')]
[doc("Record one escaped defect in ignored local history with its regression test.")]
record-defect id affected_version context fix_revision regression_test:
  @"{{PYTHON}}" -m scripts.test_evidence record-defect "{{DEFECT_LEDGER}}" \
    --id "{{id}}" --affected-version "{{affected_version}}" --context "{{context}}" \
    --fix-revision "{{fix_revision}}" --regression-test "{{regression_test}}"

[group('testing')]
[arg("fast", long, value="true")]
[arg("failing", long, value="true")]
[arg("dev", long, value="true")]
[arg("quiet", long, value="quiet")]
[arg("logs", long, value="logs")]
[arg("debug", long, value="debug")]
[arg("marker", long)]
[arg("durations", long)]
[doc("Run the test suite but do not fail the just invocation when pytest fails. Useful inside exploratory scripts.")]
test-soft fast="false" dev="false" quiet="" logs="" debug="" failing="false" marker="" durations="" *selection:
  @just _test "false" "{{fast}}" "{{dev}}" "{{quiet}}" "{{logs}}" "{{debug}}" "{{failing}}" "{{marker}}" "{{durations}}" {{selection}}

[private]
_test strict fast dev quiet logs debug failing marker durations *selection:
  #!/usr/bin/env bash
  set -euo pipefail

  mkdir -p "{{QUALITY_CACHE}}"

  mode_count=0
  [ -n "{{quiet}}" ] && mode_count=$((mode_count + 1))
  [ -n "{{logs}}" ]  && mode_count=$((mode_count + 1))
  [ -n "{{debug}}" ] && mode_count=$((mode_count + 1))

  if [ "$mode_count" -gt 1 ]; then
    echo "[test] ERROR: choose at most one of --quiet, --logs, or --debug" >&2
    exit 2
  fi

  if [[ -n "{{durations}}" && ! "{{durations}}" =~ ^[1-9][0-9]*$ ]]; then
    echo "[test] ERROR: --durations must be a positive integer" >&2
    exit 2
  fi

  mode="default"
  if [ -n "{{quiet}}" ]; then mode="quiet"; fi
  if [ -n "{{logs}}"  ]; then mode="logs"; fi
  if [ -n "{{debug}}" ]; then mode="debug"; fi

  case "$mode" in
    default) mode_flags="" ;;
    quiet)   mode_flags='{{PYTEST_QUIET_OPTS}}' ;;
    logs)    mode_flags='{{PYTEST_LOG_OPTS}}' ;;
    debug)   mode_flags='{{PYTEST_DEBUG_OPTS}}' ;;
  esac

  extra_flags=()
  if [ "{{fast}}" = "true" ]; then
    extra_flags+=({{PYTEST_FAST_EXPR}})
  fi
  if [ "{{failing}}" = "true" ]; then
    extra_flags+=({{PYTEST_FAILING_OPTS}})
  fi
  if [ -n "{{marker}}" ]; then
    extra_flags+=(-m "{{marker}}")
  fi
  if [ -n "{{durations}}" ]; then
    extra_flags+=("--durations={{durations}}")
  fi

  test_paths=()
  for selected in {{selection}}; do
    if [[ "$selected" == tests/* || "$selected" == ./* || "$selected" == /* || "$selected" == *::* ]]; then
      test_paths+=("$selected")
    else
      test_paths+=("{{ROOT_DIR}}/tests/$selected")
    fi
  done
  selected_count="${#test_paths[@]}"
  if [ "${#test_paths[@]}" -eq 0 ]; then
    test_paths+=("{{ROOT_DIR}}/tests")
  fi

  full_suite="false"
  if [ "$selected_count" -eq 0 ] && [ "{{fast}}" != "true" ] && [ "{{failing}}" != "true" ] && [ "{{dev}}" != "true" ] && [ -z "{{marker}}" ]; then
    full_suite="true"
  fi
  if [ "$full_suite" = "true" ]; then
    report_path="{{PYTEST_JSON_REPORT}}"
    outcomes_path="{{PYTEST_OUTCOMES}}"
    coverage_path="{{ROOT_DIR}}/.coverage"
  else
    report_path="{{PYTEST_PARTIAL_JSON_REPORT}}"
    outcomes_path="{{PYTEST_PARTIAL_OUTCOMES}}"
    coverage_path="{{PYTEST_PARTIAL_COVERAGE}}"
  fi
  rm -f "$report_path"

  args=("{{PYTEST}}")
  if [ -n "$mode_flags" ]; then
    eval "args+=($mode_flags)"
  fi
  args+=(-ra --json-report --json-report-file "$report_path")
  args+=("${extra_flags[@]}")

  if [ "{{dev}}" = "true" ]; then
    eval "args+=({{PYTEST_DEV_BASE_OPTS}})"

    collect_args=("{{PYTEST}}" --collect-only -q)
    collect_args+=("${extra_flags[@]}")
    collect_args+=("${test_paths[@]}")

    set +e
    collect_out="$("${collect_args[@]}" 2>&1)"
    collect_status=$?
    set -e

    if [ "$collect_status" -ne 0 ] && [ "$collect_status" -ne 5 ]; then
      echo "[test] collection failed while deciding whether to use xdist" >&2
      echo "$collect_out" >&2
      exit "$collect_status"
    fi

    test_count="$(printf '%s\n' "$collect_out" | grep -c '::' || true)"
    threshold="{{PYTEST_DEV_THRESHOLD}}"
    if [ "${test_count:-0}" -ge "$threshold" ]; then
      eval "args+=({{PYTEST_DEV_XDIST_OPTS}})"
    fi
  fi

  args+=("${test_paths[@]}")

  set +e
  echo "${args[@]}"
  COVERAGE_FILE="$coverage_path" "${args[@]}"
  status=$?
  set -e

  if [ -f "$report_path" ]; then
    outcome_args=("{{PYTHON}}" -m scripts.pytest_outcomes "$report_path" "$outcomes_path" --root "{{ROOT_DIR}}")
    if [ "$full_suite" = "true" ]; then
      outcome_args+=(--full-suite)
    fi
    "${outcome_args[@]}"
  else
    echo "[test] ERROR: pytest JSON report was not written: $report_path" >&2
    status=1
  fi

  if [ "{{strict}}" = "true" ]; then
    exit "$status"
  fi

# ======================================================================
# Test quality
# ======================================================================

[group('test quality')]
[arg("lines", long, value="true")]
[doc("Show coverage from the current .coverage data. Use --lines for uncovered-line detail.")]
cov lines="false":
  @just _log_start cov
  @just coverage-xml
  @bash -euo pipefail -c '\
    if [ -x "{{SHOWCOV}}" ]; then \
      if [ "{{lines}}" = "true" ]; then \
        "{{SHOWCOV}}" report --lines --code --context 2; \
      else \
        "{{SHOWCOV}}" report --summary --no-lines --no-branches; \
      fi; \
    elif [ "{{MODE}}" = "ci" ]; then \
      echo "[cov] ERROR: showcov not found ({{SHOWCOV}}); run just setup" >&2; \
      exit 1; \
    else \
      echo "[cov] skipping: showcov not found ({{SHOWCOV}})"; \
    fi \
  '
  @just _log_end cov

[group('test quality')]
[doc("Generate coverage.xml from current .coverage data for diff-cover.")]
coverage-xml:
  @just _log_start coverage-xml
  @bash -euo pipefail -c '\
    if [ ! -f "{{ROOT_DIR}}/.coverage" ]; then \
      echo "[coverage-xml] ERROR: .coverage is missing; run just test first" >&2; \
      exit 1; \
    fi; \
    "{{PYTHON}}" -m coverage xml -i -o "{{COVERAGE_XML}}" \
  '
  @just _log_end coverage-xml

[group('test quality')]
[doc("Enforce coverage on changed lines using diff-cover and DIFF_COVER_MIN.")]
diff-cov:
  @just _log_start diff-cov
  @just coverage-xml
  @bash -euo pipefail -c '\
    if [ ! -x "{{DIFF_COVER}}" ]; then \
      echo "[diff-cov] ERROR: diff-cover not found ({{DIFF_COVER}}); run just setup" >&2; \
      exit 1; \
    fi; \
    compare_branch="origin/main"; \
    if ! git rev-parse --verify --quiet "$compare_branch" >/dev/null; then \
      compare_branch="HEAD"; \
    fi; \
    "{{DIFF_COVER}}" "{{COVERAGE_XML}}" --fail-under "{{DIFF_COVER_MIN}}" --compare-branch "$compare_branch" \
  '
  @just _log_end diff-cov

[group('test quality')]
[doc("Run the configured mutmut target set, refresh test artifacts, then gate mutation quality.")]
mutation:
  @just _log_start mutation
  @bash -euo pipefail -c '\
    if [ ! -x "{{MUTMUT}}" ]; then \
      echo "[mutation] ERROR: mutmut not found ({{MUTMUT}}); run '\''just setup'\''" >&2; \
      exit 1; \
    fi; \
    "{{MUTMUT}}" run; \
    "{{MUTMUT}}" export-cicd-stats; \
    mkdir -p "{{QUALITY_CACHE}}"; \
    "{{MUTMUT}}" results --all true > "{{QUALITY_CACHE}}/mutmut-results.txt" \
  '
  @just test
  @just quality --strict --mutation --use-existing-test
  @just _log_end mutation

[group('documentation')]
[doc("Check local documentation references in governing docs, ADRs, and design notes.")]
docs-refs:
  @just _log_start docs-refs
  @bash -euo pipefail -c '"{{PYTHON}}" -m scripts.check_doc_references'
  @just _log_end docs-refs

[group('documentation')]
[doc("Regenerate the exhaustive CLI reference from the live Typer command map.")]
cli-docs:
  @just _log_start cli-docs
  @bash -euo pipefail -c '"{{PYTHON}}" -m scripts.generate_cli_reference'
  @just _log_end cli-docs

# ======================================================================
# Build, packaging, publishing
# ======================================================================

[group('production')]
[doc("Build Python artifacts with uv build.")]
build:
  @just _log_start build
  {{UV}} build
  @just _log_end build

[group('production')]
[doc("Run release validation and then publish to PyPI with uv publish.")]
publish:
  @just _log_start publish
  @just release-check
  {{UV}} publish
  @just _log_end publish

[group('production')]
[doc("Low-level publish command without release validation. Prefer `just publish`.")]
publish-raw:
  @just _log_start publish-raw
  {{UV}} publish
  @just _log_end publish-raw

# ======================================================================
# Cleaning / maintenance
# ======================================================================

[group('cleaning')]
[doc("Remove Python caches, coverage outputs, build artifacts, logs, and local mutation artifacts.")]
clean:
  @just _log_start clean
  find . -name '__pycache__' -type d -prune -exec rm -rf '{}' +
  rm -rf .ruff_cache .pytest_cache .mypy_cache .pytype
  rm -rf .coverage .coverage.* coverage.xml htmlcov
  rm -rf dist build site
  rm -rf logs
  rm -rf .hypothesis .ropeproject .wily mutants
  rm -rf .DS_Store .import_linter_cache .ropefolder
  {{UV}} cache prune
  @just _log_end clean

[group('cleaning')]
[doc("Remove the virtual environment explicitly.")]
clean-venv:
  @just _log_start clean-venv
  rm -rf .venv
  @just _log_end clean-venv

[group('cleaning')]
[doc("Stash untracked non-ignored files. This is separate from `scour` and normally unnecessary.")]
stash-untracked:
  @just _log_start stash-untracked
  @bash -euo pipefail -c '\
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      msg="manual:untracked:$(date -u +%Y%m%dT%H%M%SZ)"; \
      if git ls-files --others --exclude-standard --directory --no-empty-directory | grep -q .; then \
        git ls-files --others --exclude-standard -z | xargs -0 git stash push -m "$msg" -- >/dev/null; \
        echo "Stashed untracked (non-ignored) files as: $msg"; \
      else \
        echo "No untracked (non-ignored) paths to stash."; \
      fi; \
    else \
      echo "[stash-untracked] not a git repository; skipping"; \
    fi \
  '
  @just _log_end stash-untracked

[group('cleaning')]
[doc("Remove git-ignored files and directories while keeping .venv.")]
scour:
  @just _log_start scour
  @just clean
  @bash -euo pipefail -c '\
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      git clean -fXd -e .venv; \
    else \
      echo "[scour] not a git repository; skipping git clean"; \
    fi \
  '
  @just _log_end scour

# ======================================================================
# Composite flows
# ======================================================================

[group('convenience')]
[doc("Run setup, auto-fixes, and broad checks while continuing after failures; print a final summary.")]
fix:
  #!/usr/bin/env bash
  set -euo pipefail
  just _log_start fix
  failed=()
  run_step() {
    local name="$1"
    shift
    local out status
    set +e
    out="$("$@" 2>&1)"
    status=$?
    set -e
    if [ "$status" -eq 0 ]; then
      printf '\033[1;32m✓ %s\033[0m\n' "$name"
    else
      printf '\033[1;31m✗ %s\033[0m\n' "$name"
      printf '%s\n' "$out"
      failed+=("$name")
    fi
  }
  run_step setup just setup
  run_step lint just lint
  run_step format just format
  run_step typecheck just typecheck
  run_step lint-imports just lint-imports
  run_step docs-refs just docs-refs
  run_step complexity just complexity --strict
  run_step test just test --fast
  run_step quality just quality --strict
  run_step cov just cov
  if [ "${#failed[@]}" -gt 0 ]; then
    printf '\nfix completed with failures: %s\n' "${failed[*]}" >&2
    just _log_end fix
    exit 1
  fi
  printf '\nfix completed successfully.\n'
  just _log_end fix

[group('convenience')]
[doc("Produce current measurement reports. Runs tests first so coverage and pytest outcomes are fresh.")]
measure:
  @just _log_start measure
  @just test
  @just complexity --raw
  @just quality --use-existing-test
  @just cov --lines
  @just _log_end measure


# Display a compact summary from fresh quality artifacts without rerunning tests.
[group('convenience')]
summary:
  @just _log_start summary
  @"{{PYTHON}}" -m scripts.quality_summary \
    --source "{{ROOT_DIR}}/src" \
    --tests "{{ROOT_DIR}}/tests" \
    --metrics-baseline "{{METRICS_BASELINE}}" \
    --quality-baseline "{{QUALITY_BASELINE}}" \
    --coverage-data "{{ROOT_DIR}}/.coverage" \
    --pytest-outcomes "{{PYTEST_OUTCOMES}}" \
    --duplication-source "{{DUP_SOURCE_REPORT}}" \
    --duplication-tests "{{DUP_TEST_REPORT}}" \
    --vulture "{{VULTURE}}" \
    --diff-cover "{{DIFF_COVER}}" \
    --diff-cover-min "{{DIFF_COVER_MIN}}" \
    --mutation-stats "{{ROOT_DIR}}/mutants/mutmut-cicd-stats.json" \
    --mutation-results "{{QUALITY_CACHE}}/mutmut-results.txt"
  @just _log_end summary


[group('convenience')]
[doc("Run the full local/CI regression gate without auto-fixing or updating baselines; report all failing steps.")]
check:
  #!/usr/bin/env bash
  set -euo pipefail
  just _log_start check
  failed=()
  run_step() {
    local name="$1"
    shift
    printf '\n== %s ==\n' "$name"
    set +e
    "$@"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
      printf '\033[1;32m✓ %s\033[0m\n' "$name"
    else
      printf '\033[1;31m✗ %s\033[0m\n' "$name"
      failed+=("$name")
    fi
  }
  run_step lint-check just lint-check
  run_step format just format --check
  run_step typecheck just typecheck
  run_step lint-imports just lint-imports
  run_step docs-refs just docs-refs
  run_step sec-secrets just sec-secrets
  run_step complexity just complexity --strict
  run_step test just test
  run_step quality just quality --strict --use-existing-test
  run_step diff-cov just diff-cov
  run_step cov just cov
  if [ "${#failed[@]}" -gt 0 ]; then
    printf '\ncheck failed steps: %s\n' "${failed[*]}" >&2
    just _log_end check
    exit 1
  fi
  printf '\ncheck passed.\n'
  just _log_end check

[group('convenience')]
[doc("Require baselines to reflect both regressions and improvements.")]
ratchet:
  @just _log_start ratchet
  @just complexity --ratchet
  @just test
  @just quality --ratchet --use-existing-test
  @just _log_end ratchet

[group('convenience')]
[doc("Refresh committed baselines after reviewing intentional debt changes.")]
update-baselines:
  @just _log_start update-baselines
  @just complexity --update-baseline
  @just test
  @just quality --update-baseline --use-existing-test
  @just _log_end update-baselines

[group('convenience')]
[doc("Run every production gate, retain all step outcomes, and issue a release decision.")]
release-check evidence=COMPATIBILITY_DIR:
  #!/usr/bin/env bash
  set -euo pipefail
  just _log_start release-check
  step_args=()
  failed=()
  run_step() {
    local name="$1"
    shift
    printf '\n== %s ==\n' "$name"
    set +e
    "$@"
    local status=$?
    set -e
    if [ "$status" -eq 0 ]; then
      step_args+=(--step "$name=pass")
    else
      step_args+=(--step "$name=fail")
      failed+=("$name")
    fi
  }
  run_step setup just setup
  run_step check just check
  run_step mutation just mutation
  run_step security just security
  run_step performance just performance --strict
  run_step wheel just test-wheel
  run_step compatibility just compatibility-check "{{evidence}}"
  set +e
  "{{PYTHON}}" -m scripts.release_report --root "{{ROOT_DIR}}" --output "{{RELEASE_REPORT}}" "${step_args[@]}"
  report_status=$?
  set -e
  just _log_end release-check
  exit "$report_status"

