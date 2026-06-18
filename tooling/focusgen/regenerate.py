"""Closed feedback loop: generate -> validate -> adjust -> regenerate.

The loop reads the validator's structured report, derives generation overrides
from the failing rules, regenerates, and re-validates - repeating until the
sample is compliant, no further progress is made, or a maximum number of
iterations is reached.

A key output is the classification of any remaining failures:

* ``fixed``      - failures cleared by regeneration
* ``persistent`` - failures that no data change could clear within the loop.
                   These are strong candidates for upstream spec/model issues
                   (e.g. contradictory or malformed rules) and are reported as
                   such rather than silently tolerated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .generator import GenConfig, Generator
from .model import ModelSpec
from .validate import ValidationReport, validate

# Heuristics mapping a rule's MustSatisfy text to a generation override.
_MUST_BE_NULL = re.compile(r"\bMUST be null\b", re.IGNORECASE)

# Columns the loop must never force to null, even if a rule's text says so.
# InvoiceId-C-004 ("MUST be null ...") and C-005 ("MUST NOT be null ...") sit
# under an always-passing OR; the engine's per-rule red line is cosmetic
# (FOCUS_Spec#2394). Nulling InvoiceId only trades C-004 for C-005 and makes the
# sample less realistic, so we keep it populated.
_NEVER_FORCE_NULL = {"InvoiceId"}


@dataclass
class Iteration:
    index: int
    failed: int
    failing_rules: List[str] = field(default_factory=list)


@dataclass
class RegenResult:
    version: str
    out_path: str
    compliant: bool
    iterations: int
    final: ValidationReport
    history: List[Iteration] = field(default_factory=list)
    persistent_failures: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"FOCUS {self.version}: compliant={self.compliant} after {self.iterations} iteration(s)",
            f"  final: pass={self.final.passed} fail={self.final.failed} skip={self.final.skipped}",
        ]
        for it in self.history:
            lines.append(f"  iter {it.index}: failed={it.failed}")
        if self.persistent_failures:
            lines.append("  persistent (likely upstream model issues):")
            for rid in self.persistent_failures:
                lines.append(f"    - {rid}")
        return "\n".join(lines)


def _derive_overrides(report: ValidationReport, existing: Dict[str, dict]) -> Dict[str, dict]:
    """Translate failing rules into generation overrides.

    Conservative strategy: when a rule states a column MUST be null, force that
    column to null. (Failures requiring a *specific non-null* value are left to
    the column's coherence logic; if they persist they are flagged as upstream.)
    """
    overrides = dict(existing)
    for f in report.failures:
        if f.column in _NEVER_FORCE_NULL:
            continue
        if _MUST_BE_NULL.search(f.must_satisfy) and f.column:
            overrides[f.column] = {"value": None}
    return overrides


def regenerate(
    version: str,
    model_path: str,
    out_path: str,
    rows: int = 1000,
    seed: int = 42,
    providers: Optional[List[str]] = None,
    period: str = "2024-09",
    max_iters: int = 5,
    dataset: str = "CostAndUsage",
    rule_set_path: Optional[str] = None,
) -> RegenResult:
    spec = ModelSpec.load(model_path, dataset=dataset)
    overrides: Dict[str, dict] = {}
    history: List[Iteration] = []
    report: Optional[ValidationReport] = None

    # Track the best (fewest failures) iteration so we always ship the best
    # output, not whatever the last iteration happened to produce.
    best_failed = None
    best_overrides: Dict[str, dict] = {}
    best_report: Optional[ValidationReport] = None

    for i in range(1, max_iters + 1):
        cfg = GenConfig(version=version, rows=rows, seed=seed, providers=providers,
                        period=period, overrides=overrides)
        Generator(spec, cfg).write_csv(out_path)
        report = validate(out_path, version, dataset=dataset, rule_set_path=rule_set_path)

        if report.error:
            # engine/model error (e.g. dependency cycle) - cannot iterate
            history.append(Iteration(index=i, failed=-1, failing_rules=[report.error[:80]]))
            best_report = best_report or report
            break

        history.append(Iteration(index=i, failed=report.failed,
                                  failing_rules=[f.rule_id for f in report.failures]))
        # strictly-better keeps the earliest minimal result on ties
        if best_failed is None or report.failed < best_failed:
            best_failed, best_overrides, best_report = report.failed, dict(overrides), report
        if report.compliant:
            break

        new_overrides = _derive_overrides(report, overrides)
        if new_overrides == overrides:  # no further corrective action available
            break
        overrides = new_overrides

    # Ensure the file on disk corresponds to the best iteration.
    if best_report is not None and not best_report.error and best_overrides != overrides:
        cfg = GenConfig(version=version, rows=rows, seed=seed, providers=providers,
                        period=period, overrides=best_overrides)
        Generator(spec, cfg).write_csv(out_path)
        best_report = validate(out_path, version, dataset=dataset, rule_set_path=rule_set_path)

    final = best_report if best_report is not None else report
    persistent = [f.rule_id for f in (final.failures if final else [])]
    return RegenResult(
        version=version,
        out_path=str(out_path),
        compliant=bool(final and final.compliant),
        iterations=len(history),
        final=final,  # type: ignore[arg-type]
        history=history,
        persistent_failures=persistent,
    )
