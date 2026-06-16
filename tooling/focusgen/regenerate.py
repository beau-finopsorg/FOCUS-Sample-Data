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
    prev_failed = None
    report: Optional[ValidationReport] = None

    for i in range(1, max_iters + 1):
        cfg = GenConfig(version=version, rows=rows, seed=seed, providers=providers,
                        period=period, overrides=overrides)
        Generator(spec, cfg).write_csv(out_path)
        report = validate(out_path, version, dataset=dataset, rule_set_path=rule_set_path)

        if report.error:
            # engine/model error (e.g. dependency cycle) - cannot iterate
            history.append(Iteration(index=i, failed=-1, failing_rules=[report.error[:80]]))
            break

        history.append(Iteration(index=i, failed=report.failed,
                                  failing_rules=[f.rule_id for f in report.failures]))
        if report.compliant:
            break

        new_overrides = _derive_overrides(report, overrides)
        # stop if a full pass produced no new corrective action or no improvement
        no_new_action = new_overrides == overrides
        no_improvement = prev_failed is not None and report.failed >= prev_failed
        if no_new_action or (no_improvement and i > 1):
            break
        overrides = new_overrides
        prev_failed = report.failed

    persistent = [f.rule_id for f in (report.failures if report else [])]
    return RegenResult(
        version=version,
        out_path=str(out_path),
        compliant=bool(report and report.compliant),
        iterations=len(history),
        final=report,  # type: ignore[arg-type]
        history=history,
        persistent_failures=persistent,
    )
