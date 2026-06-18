"""Tests for focusgen.

Runnable two ways:
  * plain:  python tooling/tests/test_focusgen.py   (used by CI)
  * pytest: python -m pytest tooling/tests

Tests that need the FOCUS validator skip themselves when it is not installed, so
the model/generator/back-port logic is always exercised.
"""

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from focusgen import DATASETS_BY_VERSION, SUPPORTED_VERSIONS  # noqa: E402
from focusgen.backport import backport  # noqa: E402
from focusgen.cli import _dataset_from_filename, _sample_filename  # noqa: E402
from focusgen.generator import GenConfig, Generator, _fprod  # noqa: E402
from focusgen.model import ModelSpec  # noqa: E402
from focusgen.providers import PROVIDERS  # noqa: E402
from focusgen.regenerate import _derive_overrides  # noqa: E402
from focusgen.validate import Failure, ValidationReport  # noqa: E402

SPECS = ROOT / "specs"


def _has_validator() -> bool:
    try:
        import focus_validator  # noqa: F401
        return True
    except ImportError:
        return False


# --------------------------------------------------------------------- model & generation
def test_models_load_and_extract():
    for v in SUPPORTED_VERSIONS:
        spec = _spec_v(v)
        assert spec.focus_version == v
        assert len(spec.columns) > 30
        cc = spec.column("ChargeCategory")
        assert cc and cc.presence == "required" and cc.allowed and "Usage" in cc.allowed


def _spec_v(v, dataset="CostAndUsage"):
    return ModelSpec.load(SPECS / f"model-{v}.json", dataset=dataset)


def test_generation_row_count_and_header():
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "s.csv"
        spec = _spec_v("1.3")
        n = Generator(spec, GenConfig(version="1.3", rows=50, seed=1)).write_csv(out)
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert n == 50 and len(rows) == 50
        for r in rows:
            assert r["ChargeCategory"] in {"Usage", "Purchase", "Tax", "Credit", "Adjustment"}
            assert r["BilledCost"] not in ("", "NULL")
            assert r["BillingCurrency"] == "USD"
            assert "T" in r["ChargePeriodStart"] and r["ChargePeriodStart"].endswith("Z")


def test_determinism():
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.csv", Path(d) / "b.csv"
        for p in (a, b):
            Generator(_spec_v("1.2"), GenConfig(version="1.2", rows=100, seed=99)).write_csv(p)
        assert a.read_text() == b.read_text()


def test_cost_product_repr_roundtrips():
    assert float(_fprod("0.0234", "12.50")) == 0.0234 * 12.50


def test_tax_rows_costs_are_coherent_not_random():
    # tax rows: no unit price, but cost columns present, non-null, and all equal
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "s.csv"
        Generator(_spec_v("1.2"), GenConfig(version="1.2", rows=500, seed=3)).write_csv(out)
        tax = [r for r in csv.DictReader(out.read_text().splitlines()) if r["ChargeCategory"] == "Tax"]
        assert tax
        for r in tax:
            assert r["ListUnitPrice"] == "NULL" and r["SkuId"] == "NULL"
            assert r["BilledCost"] not in ("", "NULL")
            # cost columns coherent (equal) for tax, not independent random values
            assert r["ListCost"] == r["BilledCost"] == r["ContractedCost"] == r["EffectiveCost"]


def test_invalid_period_raises():
    for bad in ("2024-13", "2024", "24-09", "bad"):
        try:
            Generator(_spec_v("1.2"), GenConfig(version="1.2", rows=1, period=bad))
            raise AssertionError(f"expected ValueError for period {bad!r}")
        except ValueError:
            pass


# --------------------------------------------------------------------- providers
def test_service_name_maps_to_single_category():
    # the one-ServiceName-to-one-ServiceCategory invariant must hold by construction
    mapping = {}
    for prov in PROVIDERS.values():
        for name, category, *_ in prov.services:
            assert mapping.setdefault(name, category) == category, name


# --------------------------------------------------------------------- cli helpers
def test_sample_filename_is_version_aware():
    assert _sample_filename("1.2", "CostAndUsage") == "focus_sample.csv"
    assert _sample_filename("1.4", "CostAndUsage") == "focus_sample_costandusage.csv"
    assert _sample_filename("1.4", "InvoiceDetail") == "focus_sample_invoicedetail.csv"


def test_dataset_from_filename_flags_unknown():
    assert _dataset_from_filename("1.2", "focus_sample.csv") == "CostAndUsage"
    assert _dataset_from_filename("1.4", "focus_sample_billingperiod.csv") == "BillingPeriod"
    # a typo must not silently resolve to CostAndUsage
    assert _dataset_from_filename("1.4", "focus_sample_invoicedetial.csv") is None


# --------------------------------------------------------------------- regeneration
def test_derive_overrides_never_nulls_invoiceid():
    report = ValidationReport(version="1.2", model_version="x", data_file="x")
    report.failures = [
        Failure(rule_id="InvoiceId-C-004-C", must_satisfy="InvoiceId MUST be null ...", column="InvoiceId"),
        Failure(rule_id="Foo-C-003-M", must_satisfy="Foo MUST be null when ...", column="Foo"),
    ]
    ov = _derive_overrides(report, {})
    assert "InvoiceId" not in ov          # cosmetic rule, must stay populated
    assert ov.get("Foo") == {"value": None}


# --------------------------------------------------------------------- back-port
def test_backport_builds_sized_models():
    with tempfile.TemporaryDirectory() as d:
        info10 = backport(SPECS / "model-1.2.json", "1.0", Path(d) / "model-1.0.json")
        info11 = backport(SPECS / "model-1.2.json", "1.1", Path(d) / "model-1.1.json")
        assert info10["columns"] == 43 and info11["columns"] == 50
        # the pruned model must load and expose the expected column counts
        assert len(ModelSpec.load(Path(d) / "model-1.0.json").columns) == 43
        assert len(ModelSpec.load(Path(d) / "model-1.1.json").columns) == 50


def test_all_datasets_generate_nonempty():
    for version, datasets in DATASETS_BY_VERSION.items():
        for ds in datasets:
            with tempfile.TemporaryDirectory() as d:
                spec = _spec_v(version, ds)
                out = Path(d) / "s.csv"
                n = Generator(spec, GenConfig(version=version, rows=10, seed=2)).write_csv(out)
                assert n == 10
                header = out.read_text().splitlines()[0]
                assert header.count(",") + 1 >= len(spec.emit_columns())


# --------------------------------------------------------------------- validator-dependent (guarded)
def test_generated_samples_validate_when_validator_present():
    if not _has_validator():
        print("  (skipped: focus_validator not installed)")
        return
    from focusgen.validate import validate
    with tempfile.TemporaryDirectory() as d:
        # BillingPeriod is fully clean and cheap to validate
        spec = _spec_v("1.4", "BillingPeriod")
        out = Path(d) / "bp.csv"
        Generator(spec, GenConfig(version="1.4", rows=50, seed=4)).write_csv(out)
        rep = validate(str(out), "1.4", dataset="BillingPeriod", rule_set_path=str(SPECS))
        assert rep.error is None and rep.compliant, (rep.error, [f.rule_id for f in rep.failures])


def test_regen_loop_keeps_invoiceid_populated():
    if not _has_validator():
        print("  (skipped: focus_validator not installed)")
        return
    from focusgen.regenerate import regenerate
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "cau.csv"
        regenerate("1.2", str(SPECS / "model-1.2.json"), str(out), rows=100, seed=7,
                   max_iters=4, rule_set_path=str(SPECS))
        rows = list(csv.DictReader(out.read_text().splitlines()))
        assert any(r["InvoiceId"] not in ("", "NULL") for r in rows), "InvoiceId should stay populated"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
