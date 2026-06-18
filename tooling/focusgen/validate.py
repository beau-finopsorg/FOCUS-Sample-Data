"""Run the FOCUS validator and return a structured, machine-readable report.

This wraps the ``focus_validator`` package (https://github.com/finopsfoundation/focus_validator).
It prefers the in-process Python API (fast, structured) and falls back to the
CLI via subprocess if only the executable is available.

The report is a plain dict (JSON-serialisable) so it can drive the regeneration
feedback loop, be written to disk for CI artefacts, and be diffed across runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


@dataclass
class Failure:
    rule_id: str
    must_satisfy: str = ""
    violations: int = 0
    message: str = ""
    reason: str = ""
    column: str = ""


@dataclass
class ValidationReport:
    version: str
    model_version: str
    data_file: str
    row_count: int = 0
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: List[Failure] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def compliant(self) -> bool:
        return self.error is None and self.failed == 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["compliant"] = self.compliant
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def _failing_columns(report: ValidationReport) -> Dict[str, int]:
    """Aggregate failure counts by column, for the feedback loop."""
    out: Dict[str, int] = {}
    for f in report.failures:
        col = f.column or _column_from_rule_id(f.rule_id)
        out[col] = out.get(col, 0) + 1
    return out


def _column_from_rule_id(rule_id: str) -> str:
    # rule ids look like CAU-ChargeCategory-C-003-M or ChargeCategory-C-001-M
    parts = rule_id.split("-")
    if len(parts) >= 2:
        return parts[1] if parts[0].isupper() and len(parts[0]) == 3 else parts[0]
    return rule_id


# ---------------------------------------------------------------------- #
def validate(
    data_file: str,
    version: str,
    dataset: str = "CostAndUsage",
    rule_set_path: Optional[str] = None,
    block_download: bool = True,
) -> ValidationReport:
    rule_set_path = rule_set_path or str(SPECS_DIR)
    try:
        return _validate_inprocess(data_file, version, dataset, rule_set_path, block_download)
    except ImportError:
        return _validate_subprocess(data_file, version, dataset, rule_set_path, block_download)


# ---------------------------------------------------------------------- #
@contextlib.contextmanager
def _chdir(path: Path):
    """Temporarily change CWD.

    The validator resolves ``focus_validator/rules/currency_codes.csv`` relative
    to the current working directory, so we run from the package's parent dir.
    """
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _validate_inprocess(data_file, version, dataset, rule_set_path, block_download) -> ValidationReport:
    import focus_validator  # type: ignore
    from focus_validator.validator import Validator  # type: ignore

    display_name = str(data_file)
    data_file = str(Path(data_file).resolve())
    rule_set_path = str(Path(rule_set_path).resolve())
    pkg_parent = Path(focus_validator.__file__).resolve().parent.parent

    report = ValidationReport(version=version, model_version="unknown", data_file=display_name)
    buf = io.StringIO()
    # The whole block - running the validator AND reading its results - is
    # guarded, so an engine error *or* an unexpected result shape (e.g. a future
    # validator build that drops `by_rule_id`) is recorded in report.error
    # rather than crashing the run. This matters while the validator tracks a
    # moving branch.
    try:
        with contextlib.redirect_stdout(buf), _chdir(pkg_parent):
            validator = Validator(
                data_filename=str(data_file),
                output_destination=None,
                output_type="console",
                rule_set_path=rule_set_path,
                rules_version=version,
                focus_dataset=dataset,
                rules_block_remote_download=block_download,
            )
            results = validator.validate()

        report.model_version = getattr(results, "model_version", "unknown")
        report.row_count = getattr(results, "data_row_count", 0)
        rules = getattr(results, "rules", {}) or {}

        for rule_id, entry in results.by_rule_id.items():
            details = entry.get("details") or {}
            if details.get("skipped"):
                report.skipped += 1
                continue
            if entry.get("ok"):
                report.passed += 1
                continue
            report.failed += 1
            report.failures.append(
                Failure(
                    rule_id=rule_id,
                    must_satisfy=_must_satisfy(rules.get(rule_id)),
                    violations=int(details.get("violations", 0) or 0),
                    message=str(details.get("message", "") or ""),
                    reason=str(details.get("reason", "") or ""),
                    column=_column_from_rule_id(rule_id),
                )
            )
        report.total = report.passed + report.failed + report.skipped
    except Exception as exc:  # noqa: BLE001 - surface engine/model/result errors in the report
        report.error = f"{type(exc).__name__}: {exc}"
    return report


def _must_satisfy(rule: Any) -> str:
    if rule is None:
        return ""
    for path in ("validation_criteria", "ValidationCriteria"):
        vc = getattr(rule, path, None)
        if vc is not None:
            ms = getattr(vc, "must_satisfy", None) or getattr(vc, "MustSatisfy", None)
            if ms:
                return str(ms)
    if isinstance(rule, dict):
        return str(rule.get("ValidationCriteria", {}).get("MustSatisfy", ""))
    return ""


# ---------------------------------------------------------------------- #
def _validate_subprocess(data_file, version, dataset, rule_set_path, block_download) -> ValidationReport:
    report = ValidationReport(version=version, model_version="unknown", data_file=str(data_file))
    cmd = [
        sys.executable, "-m", "focus_validator.main",
        "--data-file", str(data_file),
        "--validate-version", version,
        "--focus-dataset", dataset,
        "--rule-set-path", rule_set_path,
        "--output-type", "console",
    ]
    if block_download:
        cmd.append("--block-download")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Total:") and "Pass:" in s:
            # "Total: 578 | Pass: 114 | Fail: 23 | Skipped: 441"
            try:
                parts = {kv.split(":")[0].strip().lower(): int(kv.split(":")[1])
                         for kv in s.split("|")}
                report.total = parts.get("total", 0)
                report.passed = parts.get("pass", 0)
                report.failed = parts.get("fail", 0)
                report.skipped = parts.get("skipped", 0)
            except (ValueError, IndexError):
                pass
        if ("❌" in line or "[FAIL]" in line):
            rid = s.split()[1].rstrip(":") if len(s.split()) > 1 else s
            report.failures.append(Failure(rule_id=rid, message=s, column=_column_from_rule_id(rid)))
    # Reconcile: the parsed summary line and the parsed failure lines can
    # disagree; trust whichever reports more failures so a problem is not hidden.
    if len(report.failures) > report.failed:
        report.failed = len(report.failures)
    if proc.returncode != 0 and report.total == 0:
        report.error = out[-2000:]
    return report
