"""Command-line interface for the FOCUS sample-data tooling.

Examples
--------
  # generate a 1.3 sample
  python -m focusgen gen --version 1.3 --rows 1000 --out FOCUS-1.3/focus_sample.csv

  # validate any CSV against a version
  python -m focusgen validate --version 1.3 --data-file FOCUS-1.3/focus_sample.csv

  # generate, validate and self-correct in a loop
  python -m focusgen regen --version 1.3 --rows 1000 --out FOCUS-1.3/focus_sample.csv

  # build the full set of samples for all supported versions
  python -m focusgen build-all --rows 1000 --base .
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import DEFAULT_DATASET, SUPPORTED_VERSIONS
from .generator import GenConfig, Generator
from .model import ModelSpec
from .regenerate import regenerate
from .validate import validate

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


def _model_path(version: str, override: str | None) -> str:
    if override:
        return override
    return str(SPECS_DIR / f"model-{version}.json")


def _providers(arg: str | None):
    return [p.strip() for p in arg.split(",")] if arg else None


def cmd_gen(args) -> int:
    spec = ModelSpec.load(_model_path(args.version, args.model), dataset=args.dataset)
    cfg = GenConfig(version=args.version, rows=args.rows, seed=args.seed,
                    providers=_providers(args.providers), period=args.period)
    n = Generator(spec, cfg).write_csv(args.out)
    print(f"Generated {n} rows of FOCUS {args.version} -> {args.out}")
    return 0


def cmd_validate(args) -> int:
    report = validate(args.data_file, args.version, dataset=args.dataset,
                      rule_set_path=args.rule_set_path or str(SPECS_DIR))
    if args.json:
        print(report.to_json())
    else:
        status = "COMPLIANT" if report.compliant else "NON-COMPLIANT"
        print(f"{status}: FOCUS {report.version} (model {report.model_version})")
        print(f"  {args.data_file}: {report.row_count} rows")
        print(f"  pass={report.passed} fail={report.failed} skipped={report.skipped}")
        if report.error:
            print(f"  ERROR: {report.error}")
        for f in report.failures:
            print(f"  FAIL {f.rule_id} (violations={f.violations}): {f.must_satisfy}")
    return 0 if report.compliant else 1


def cmd_regen(args) -> int:
    result = regenerate(
        version=args.version, model_path=_model_path(args.version, args.model),
        out_path=args.out, rows=args.rows, seed=args.seed,
        providers=_providers(args.providers), period=args.period,
        max_iters=args.max_iters, dataset=args.dataset,
        rule_set_path=args.rule_set_path or str(SPECS_DIR),
    )
    print(result.summary())
    if args.report:
        Path(args.report).write_text(json.dumps({
            "version": result.version, "compliant": result.compliant,
            "iterations": result.iterations, "persistent_failures": result.persistent_failures,
            "final": result.final.to_dict() if result.final else None,
        }, indent=2))
        print(f"  report -> {args.report}")
    # exit 0 when compliant OR when only persistent (upstream) failures remain and allowed
    if result.compliant:
        return 0
    return 0 if args.allow_persistent else 1


def cmd_build_all(args) -> int:
    base = Path(args.base)
    rc = 0
    for version in (args.versions or list(SUPPORTED_VERSIONS)):
        out = base / f"FOCUS-{version}" / "focus_sample.csv"
        print(f"\n=== Building FOCUS {version} ===")
        result = regenerate(
            version=version, model_path=_model_path(version, None), out_path=str(out),
            rows=args.rows, seed=args.seed, period=args.period,
            max_iters=args.max_iters, rule_set_path=str(SPECS_DIR),
        )
        print(result.summary())
        if not result.compliant and not args.allow_persistent:
            rc = 1
    return rc


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="focusgen", description="FOCUS sample-data generation & validation tooling")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("--version", required=True, choices=SUPPORTED_VERSIONS)
        sp.add_argument("--dataset", default=DEFAULT_DATASET)
        sp.add_argument("--model", default=None, help="override path to model-<version>.json")

    g = sub.add_parser("gen", help="generate a sample CSV")
    common(g)
    g.add_argument("--out", required=True)
    g.add_argument("--rows", type=int, default=1000)
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--providers", default=None, help="comma-separated: aws,azure,gcp,oracle")
    g.add_argument("--period", default="2024-09")
    g.set_defaults(func=cmd_gen)

    v = sub.add_parser("validate", help="validate a CSV against a FOCUS version")
    v.add_argument("--version", required=True, choices=SUPPORTED_VERSIONS)
    v.add_argument("--dataset", default=DEFAULT_DATASET)
    v.add_argument("--data-file", required=True)
    v.add_argument("--rule-set-path", default=None)
    v.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    v.set_defaults(func=cmd_validate)

    r = sub.add_parser("regen", help="generate + validate + self-correct loop")
    common(r)
    r.add_argument("--out", required=True)
    r.add_argument("--rows", type=int, default=1000)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--providers", default=None)
    r.add_argument("--period", default="2024-09")
    r.add_argument("--max-iters", type=int, default=5)
    r.add_argument("--rule-set-path", default=None)
    r.add_argument("--report", default=None, help="write a JSON report to this path")
    r.add_argument("--allow-persistent", action="store_true",
                   help="exit 0 even if only persistent (upstream) failures remain")
    r.set_defaults(func=cmd_regen)

    b = sub.add_parser("build-all", help="build samples for all supported versions")
    b.add_argument("--base", default=".", help="repo root under which FOCUS-<version>/ dirs are written")
    b.add_argument("--versions", nargs="*", default=None)
    b.add_argument("--rows", type=int, default=1000)
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--period", default="2024-09")
    b.add_argument("--max-iters", type=int, default=5)
    b.add_argument("--allow-persistent", action="store_true")
    b.set_defaults(func=cmd_build_all)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
