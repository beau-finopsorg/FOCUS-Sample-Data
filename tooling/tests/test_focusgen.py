"""Lightweight tests for focusgen that do not require the FOCUS validator.

Run with: python -m pytest tooling/tests  (or python tooling/tests/test_focusgen.py)
"""

import csv
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from focusgen import SUPPORTED_VERSIONS  # noqa: E402
from focusgen.generator import GenConfig, Generator, _fprod  # noqa: E402
from focusgen.model import ModelSpec  # noqa: E402

SPECS = ROOT / "specs"


def _spec(version):
    return ModelSpec.load(SPECS / f"model-{version}.json")


def test_models_load_and_extract():
    for v in SUPPORTED_VERSIONS:
        spec = _spec(v)
        assert spec.focus_version == v
        assert len(spec.columns) > 30
        # core columns are required and typed
        cc = spec.column("ChargeCategory")
        assert cc is not None and cc.presence == "required"
        assert cc.allowed and "Usage" in cc.allowed


def test_generation_row_count_and_header(tmp_path=None):
    out = Path("/tmp/_fg_test_13.csv")
    spec = _spec("1.3")
    n = Generator(spec, GenConfig(version="1.3", rows=50, seed=1)).write_csv(out)
    assert n == 50
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert len(rows) == 50
    # required non-null columns are populated
    for r in rows:
        assert r["ChargeCategory"] in {"Usage", "Purchase", "Tax", "Credit", "Adjustment"}
        assert r["BilledCost"] not in ("", "NULL")
        assert r["BillingCurrency"] == "USD"
        assert r["ChargePeriodStart"].endswith("Z") and "T" in r["ChargePeriodStart"]


def test_determinism():
    spec = _spec("1.2")
    a = Path("/tmp/_fg_det_a.csv")
    b = Path("/tmp/_fg_det_b.csv")
    Generator(spec, GenConfig(version="1.2", rows=100, seed=99)).write_csv(a)
    Generator(spec, GenConfig(version="1.2", rows=100, seed=99)).write_csv(b)
    assert a.read_text() == b.read_text()


def test_cost_product_repr_roundtrips():
    # the stored product must equal float(a) * float(b) exactly
    assert float(_fprod("0.0234", "12.50")) == 0.0234 * 12.50


def test_tax_rows_have_null_prices():
    spec = _spec("1.3")
    out = Path("/tmp/_fg_tax.csv")
    Generator(spec, GenConfig(version="1.3", rows=500, seed=3)).write_csv(out)
    rows = list(csv.DictReader(out.read_text().splitlines()))
    tax = [r for r in rows if r["ChargeCategory"] == "Tax"]
    assert tax, "expected some tax rows in 500"
    for r in tax:
        assert r["ListUnitPrice"] == "NULL"
        assert r["SkuId"] == "NULL"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
