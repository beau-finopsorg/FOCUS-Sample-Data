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

from . import (
    BACKPORTED_VERSIONS,
    DATASETS_BY_VERSION,
    DEFAULT_DATASET,
    SUPPORTED_VERSIONS,
)
from .generator import GenConfig, Generator
from .model import ModelSpec
from .regenerate import regenerate
from .validate import validate

SPECS_DIR = Path(__file__).resolve().parent.parent / "specs"


def _sample_filename(version: str, dataset: str) -> str:
    """Sample CSV name for a (version, dataset).

    Single-dataset versions (1.0-1.2) use ``focus_sample.csv``. Multi-dataset
    versions (1.3+) name every dataset explicitly, e.g.
    ``focus_sample_costandusage.csv`` / ``focus_sample_contractcommitment.csv``.
    """
    if len(DATASETS_BY_VERSION.get(version, (DEFAULT_DATASET,))) <= 1:
        return "focus_sample.csv"
    return f"focus_sample_{dataset.lower()}.csv"


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
    # Default: generate 1.1-1.4. FOCUS-1.0 holds anonymized real-world data, so
    # we never overwrite it unless explicitly listed in --versions.
    versions = args.versions or [v for v in SUPPORTED_VERSIONS if v != "1.0"]
    for version in versions:
        for dataset in DATASETS_BY_VERSION.get(version, (DEFAULT_DATASET,)):
            out = base / f"FOCUS-{version}" / _sample_filename(version, dataset)
            if version == "1.0" and dataset == DEFAULT_DATASET and out.exists() and not args.force:
                print(f"\n=== Skipping FOCUS 1.0 CostAndUsage (preserving real-world data; use --force) ===")
                continue
            label = version if dataset == DEFAULT_DATASET else f"{version}/{dataset}"
            print(f"\n=== Building FOCUS {label} ===")
            result = regenerate(
                version=version, model_path=_model_path(version, None), out_path=str(out),
                rows=args.rows, seed=args.seed, period=args.period, dataset=dataset,
                max_iters=args.max_iters, rule_set_path=str(SPECS_DIR),
            )
            print(result.summary())
            if not result.compliant and not args.allow_persistent:
                rc = 1
    return rc


def _dataset_from_filename(version: str, fname: str) -> str:
    if fname == "focus_sample.csv":
        return DEFAULT_DATASET
    suffix = fname[len("focus_sample_"):-len(".csv")]
    for ds in DATASETS_BY_VERSION.get(version, (DEFAULT_DATASET,)):
        if ds.lower() == suffix:
            return ds
    return DEFAULT_DATASET


def cmd_validate_all(args) -> int:
    base = Path(args.base)
    reports_dir = Path(args.reports) if args.reports else (SPECS_DIR.parent / "reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    rc = 0
    found = False
    for version in SUPPORTED_VERSIONS:
        vdir = base / f"FOCUS-{version}"
        if not vdir.is_dir():
            continue
        for csv in sorted(vdir.glob("focus_sample*.csv")):
            found = True
            dataset = _dataset_from_filename(version, csv.name)
            report = validate(str(csv), version, dataset=dataset, rule_set_path=str(SPECS_DIR))
            tag = version if dataset == DEFAULT_DATASET else f"{version}-{dataset.lower()}"
            (reports_dir / f"validation-{tag}.json").write_text(report.to_json())
            status = "OK" if report.compliant else ("ENGINE-ERROR" if report.error else f"FAIL({report.failed})")
            print(f"  FOCUS {version:4} {dataset:18} {csv.name:42} -> {status} "
                  f"(pass={report.passed} skip={report.skipped})")
            if not report.compliant and not report.error and not args.allow_persistent:
                rc = 1
    if not found:
        print("No FOCUS-*/focus_sample*.csv files found.")
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
    b.add_argument("--force", action="store_true", help="overwrite FOCUS-1.0 real-world data")
    b.set_defaults(func=cmd_build_all)

    va = sub.add_parser("validate-all", help="discover & validate every FOCUS-<v>/focus_sample*.csv")
    va.add_argument("--base", default="..", help="repo root containing FOCUS-<version>/ dirs")
    va.add_argument("--reports", default=None, help="directory for JSON reports (default: tooling/reports)")
    va.add_argument("--allow-persistent", action="store_true",
                    help="exit 0 even if persistent (upstream) failures remain")
    va.set_defaults(func=cmd_validate_all)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
