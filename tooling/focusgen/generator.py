"""Model-driven synthesis of spec-compliant FOCUS sample rows.

Generation has two layers:

1. A *coherence layer* that builds the well-known FOCUS columns together so the
   cross-column invariants hold by construction (cost ordering, period ordering,
   currency validity, commitment-discount block coherence, ServiceName ->
   ServiceCategory cardinality, RFC 3339 UTC datetimes, etc.).

2. A *generic layer*, driven purely by the parsed ``ModelSpec``, that fills any
   remaining emit column according to its type / enum / nullability. This keeps
   the output schema-complete even as new columns appear in later versions.

Anything the layers get wrong is surfaced by the validation feedback loop, which
can re-run generation with adjusted constraints. See ``regenerate.py``.
"""

from __future__ import annotations

import csv
import json
import random
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Dict, List, Optional

getcontext().prec = 28

# Complex JSON-object columns are situational; emit them as null so their
# nested object-structure rules stay inapplicable rather than half-populated.
COMPLEX_JSON_COLUMNS = {
    "ContractApplied", "AllocatedMethodDetails", "SkuPriceDetails",
    "CommitmentProgramEligibilityDetails", "SkuPriceMap",
}

from .model import ColumnSpec, ModelSpec
from .providers import PROVIDERS, TAG_KEYS, TAG_VALUES, Provider

UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"

CHARGE_CATEGORIES = (["Usage"] * 80 + ["Purchase"] * 8 + ["Tax"] * 4
                     + ["Credit"] * 4 + ["Adjustment"] * 4)
PRICING_CATEGORIES = ["Standard", "Standard", "Standard", "Dynamic", "Committed", "Other"]


def _dt(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime(UTC_FMT)


def _dec(x: float, places: int = 10) -> str:
    """Format a non-negative decimal as a plain string (no scientific notation)."""
    return f"{x:.{places}f}"


def _ds(d) -> str:
    """Serialise a Decimal/float as a plain decimal string (no sci notation)."""
    if not isinstance(d, Decimal):
        d = Decimal(str(d))
    return format(d, "f")


def _fprod(a: str, b: str) -> str:
    """Round-trip repr of the IEEE-754 product of two decimal strings.

    Stored so that DuckDB's CAST(a AS DOUBLE) * CAST(b AS DOUBLE) == CAST(r) holds
    exactly, since Python float() and DuckDB string->DOUBLE both round-to-nearest.
    """
    return repr(float(a) * float(b))


def _charge_frequency(category: str, rng) -> Optional[str]:
    if category == "Usage":
        return "Usage-Based"
    if category == "Purchase":
        return rng.choice(["One-Time", "Recurring"])
    # Tax / Credit / Adjustment: never Usage-Based
    return "One-Time"


@dataclass
class GenConfig:
    version: str
    rows: int = 1000
    seed: int = 42
    providers: Optional[List[str]] = None   # subset of provider keys; None = all
    period: str = "2024-09"                  # billing month YYYY-MM
    overrides: Optional[Dict[str, dict]] = None  # column -> tuning hints (feedback loop)


class Generator:
    def __init__(self, spec: ModelSpec, config: GenConfig):
        self.spec = spec
        self.config = config
        self.rng = random.Random(config.seed)
        keys = config.providers or list(PROVIDERS.keys())
        self.providers = [PROVIDERS[k] for k in keys if k in PROVIDERS]
        if not self.providers:
            raise ValueError(f"No valid providers among {keys}")
        self.overrides = config.overrides or {}
        y, m = (int(p) for p in config.period.split("-"))
        self.billing_start = datetime(y, m, 1, tzinfo=timezone.utc)
        self.billing_end = (datetime(y + 1, 1, 1, tzinfo=timezone.utc) if m == 12
                            else datetime(y, m + 1, 1, tzinfo=timezone.utc))
        self.emit_cols = self.spec.emit_columns()
        self.emit_names = [c.name for c in self.emit_cols]

    # ------------------------------------------------------------------ #
    def write_csv(self, path: str | Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as fh:
            fh.write(self._serialize_header())
            for _ in range(self.config.rows):
                row = self._build_row()
                fh.write(self._serialize_row(row))
        return self.config.rows

    # ------------------------------------------------------------------ #
    def _serialize_header(self) -> str:
        return ",".join(f'"{n}"' for n in self.emit_names) + "\n"

    def _serialize_row(self, row: Dict[str, object]) -> str:
        cells = []
        for name in self.emit_names:
            v = row.get(name, None)
            cells.append(self._serialize_cell(name, v))
        return ",".join(cells) + "\n"

    def _serialize_cell(self, name: str, v: object) -> str:
        if v is None:
            return "NULL"
        cspec = self.spec.column(name)
        if cspec and cspec.dtype == "decimal" and isinstance(v, (int, float, str)):
            # numeric cells are unquoted
            return str(v)
        s = str(v)
        return '"' + s.replace('"', '""') + '"'

    # ------------------------------------------------------------------ #
    def _build_row(self) -> Dict[str, object]:
        rng = self.rng
        prov: Provider = rng.choice(self.providers)
        service = prov.service(rng)
        svc_name, svc_cat, svc_sub, res_type, unit = service
        region_id, region_name = prov.region(rng)
        sub_id, sub_name = prov.sub_account(rng)

        # period & charge window (1-hour usage window inside the billing month)
        span_hours = max(1, int((self.billing_end - self.billing_start).total_seconds() // 3600) - 1)
        offset = rng.randint(0, span_hours - 1)
        charge_start = self.billing_start + timedelta(hours=offset)
        charge_end = charge_start + timedelta(hours=1)

        charge_category = rng.choice(CHARGE_CATEGORIES)
        charge_class = "Correction" if rng.random() < 0.03 else None
        pricing_category = rng.choice(PRICING_CATEGORIES)
        is_usage = charge_category == "Usage"
        is_tax = charge_category == "Tax"

        # Quantities & coherent cost ladder. The validator reads cost/price
        # columns as strings and casts to DOUBLE, then checks
        # "cost == unit_price * quantity" with EXACT equality. We therefore
        # store each cost as the round-trip repr() of the IEEE-754 product of
        # the *stored operand strings*, so DuckDB's CAST+multiply reproduces the
        # exact same double and equality holds.
        qty_d = Decimal(str(round(rng.uniform(0.01, 500.0), 2))).quantize(Decimal("1.00"))
        list_up_d = Decimal(str(round(rng.uniform(0.0001, 5.0), 4))).quantize(Decimal("1.0000"))
        discount = Decimal(str(round(rng.uniform(0.0, 0.4), 2)))
        contracted_up_d = (list_up_d * (Decimal("1") - discount)).quantize(Decimal("1.0000"))

        qty = float(qty_d)
        qty_s = _ds(qty_d)
        list_unit_price = _ds(list_up_d)
        contracted_unit_price = _ds(contracted_up_d)
        list_cost = _fprod(list_unit_price, qty_s)
        contracted_cost = _fprod(contracted_unit_price, qty_s)
        effective_cost = repr(round(float(contracted_cost) * round(rng.uniform(0.6, 1.0), 2), 10))
        billed_cost = effective_cost  # billed equals effective for first-party charges

        # Purchases intended to cover future charges have EffectiveCost 0.
        if charge_category == "Purchase":
            effective_cost = "0"
            billed_cost = contracted_cost

        if is_tax:
            svc_name, svc_cat, svc_sub, res_type, unit = "Tax", "Other", "Other", None, None

        # commitment-discount block: coherent and mostly absent (never on tax)
        cd = self._commitment_block(rng, pricing_category) if not is_tax else self._commitment_block(rng, "none", force_empty=True)
        cd_unused = cd.get("CommitmentDiscountStatus") == "Unused"

        cur = prov.currency
        tags = self._tags(rng)

        row: Dict[str, object] = {
            # identity / accounts
            "BillingAccountId": prov.billing_account_id,
            "BillingAccountName": prov.billing_account_name,
            "BillingAccountType": _account_type(prov),
            "SubAccountId": sub_id,
            "SubAccountName": sub_name,
            "SubAccountType": _account_type(prov) if sub_id else None,
            # provider naming. For first-party charges ProviderName ==
            # InvoiceIssuerName (a difference flags third-party/marketplace, for
            # which BilledCost MUST be 0 -- see BilledCost-C-005-C).
            "ProviderName": prov.provider_name,
            "PublisherName": prov.provider_name,
            "InvoiceIssuerName": prov.provider_name,
            "ServiceProviderName": prov.provider_name,
            "HostProviderName": prov.provider_name,
            # currency
            "BillingCurrency": cur,
            "PricingCurrency": cur,
            # periods
            "BillingPeriodStart": _dt(self.billing_start),
            "BillingPeriodEnd": _dt(self.billing_end),
            "ChargePeriodStart": _dt(charge_start),
            "ChargePeriodEnd": _dt(charge_end),
            # charge classification
            "ChargeCategory": charge_category,
            "ChargeClass": charge_class,
            "ChargeDescription": f"{svc_name} {res_type or 'charge'} in {region_name}",
            "ChargeFrequency": _charge_frequency(charge_category, rng),
            # service taxonomy (single category per service by construction)
            "ServiceName": svc_name,
            "ServiceCategory": svc_cat,
            "ServiceSubcategory": svc_sub or "Other",
            # region / az
            "RegionId": region_id if not is_tax else None,
            "RegionName": region_name if not is_tax else None,
            "AvailabilityZone": rng.choice(prov.availability_zones)
            if prov.availability_zones and is_usage and rng.random() < 0.5 else None,
            # resource (tax/credit/adjustment have no resource)
            "ResourceId": _resource_id(prov, region_id, rng) if charge_category in ("Usage", "Purchase") else None,
            "ResourceName": None,
            "ResourceType": res_type if charge_category in ("Usage", "Purchase") else None,
            # capacity reservation: left null (matches typical real-world data;
            # the 1.3 CapacityReservationStatus-C-003 condition JSON is malformed
            # upstream, so the pipeline reports it as a known model anomaly).
            "CapacityReservationId": None,
            "CapacityReservationStatus": None,
            # quantities / units. ConsumedQuantity is null unless this is a
            # billed Usage charge (null for non-usage and for unused commitments).
            "ConsumedQuantity": _dec(qty) if (is_usage and not cd_unused) else None,
            "ConsumedUnit": unit if (is_usage and not cd_unused) else None,
            "PricingQuantity": _ds(qty_d) if not is_tax else None,
            "PricingUnit": unit if not is_tax else None,
            "PricingCategory": pricing_category if not is_tax else None,
            # costs
            "BilledCost": billed_cost,
            "EffectiveCost": effective_cost,
            "ListCost": list_cost if not is_tax else None,
            "ContractedCost": contracted_cost if not is_tax else None,
            "ListUnitPrice": list_unit_price if not is_tax else None,
            "ContractedUnitPrice": contracted_unit_price if not is_tax else None,
            # pricing-currency mirrors (PricingCurrency == BillingCurrency here)
            "PricingCurrencyEffectiveCost": effective_cost,
            "PricingCurrencyListUnitPrice": list_unit_price if not is_tax else None,
            # NOTE: the 1.3 PricingCurrencyContractedUnitPrice-C-012 condition is
            # inverted upstream (executes on SkuPriceId IS NULL). We populate it
            # for non-tax rows; the residual tax-row failure is a model bug.
            "PricingCurrencyContractedUnitPrice": contracted_unit_price if not is_tax else None,
            # sku (null for tax)
            "SkuId": _sku(rng) if not is_tax else None,
            "SkuPriceId": (_sku(rng) + "." + _sku(rng, 8)) if not is_tax else None,
            "SkuMeter": f"{svc_name} {unit}" if not is_tax else None,
            # invoice / tags. NOTE: in the 1.2/1.3 model InvoiceId-C-004 and
            # InvoiceId-C-005 are a contradictory pair (both have empty
            # conditions), so exactly one always fails regardless of value. We
            # populate it (satisfying C-005); the residual C-004 failure is an
            # upstream model bug, reported by the pipeline rather than hidden.
            "InvoiceId": f"INV-{self.config.period.replace('-', '')}-{rng.randint(10000, 99999)}",
            "InvoiceIssuer": prov.provider_name,
            "Tags": tags,
        }
        row.update(cd)

        # complex JSON-object columns stay null (situational)
        for col in COMPLEX_JSON_COLUMNS:
            if col in self.spec.columns:
                row[col] = None

        # fill any remaining emit columns generically from the model
        for cspec in self.emit_cols:
            if cspec.name not in row:
                row[cspec.name] = self._generic_value(cspec, charge_start)

        # enforce model constraints (enums/nullability) as a safety net
        self._enforce(row, charge_start)

        # apply feedback-loop overrides last so they win (see regenerate.py)
        for name, hint in self.overrides.items():
            if name in row and "value" in hint:
                row[name] = hint["value"]
        return row

    # ------------------------------------------------------------------ #
    def _commitment_block(self, rng, pricing_category, force_empty: bool = False) -> Dict[str, object]:
        has = (not force_empty) and (pricing_category == "Committed" or rng.random() < 0.12)
        if not has:
            return {
                "CommitmentDiscountId": None, "CommitmentDiscountName": None,
                "CommitmentDiscountCategory": None, "CommitmentDiscountType": None,
                "CommitmentDiscountStatus": None, "CommitmentDiscountQuantity": None,
                "CommitmentDiscountUnit": None,
            }
        cid = f"cd-{rng.randint(100000, 999999)}"
        return {
            "CommitmentDiscountId": cid,
            "CommitmentDiscountName": f"commit-{cid[-4:]}",
            "CommitmentDiscountCategory": rng.choice(["Spend", "Usage"]),
            "CommitmentDiscountType": rng.choice(["Reserved Instance", "Savings Plan", "Committed Use Discount"]),
            "CommitmentDiscountStatus": rng.choice(["Used", "Unused"]),
            # Quantity left null: its presence is gated by situational rules
            # (CommitmentDiscountQuantity-C-007/016) that require null otherwise.
            "CommitmentDiscountQuantity": None,
            "CommitmentDiscountUnit": None,
        }

    def _tags(self, rng) -> Optional[str]:
        if rng.random() < 0.2:
            return None
        n = rng.randint(1, 3)
        keys = rng.sample(TAG_KEYS, n)
        obj = {k: rng.choice(TAG_VALUES[k]) for k in keys}
        return json.dumps(obj)

    # ------------------------------------------------------------------ #
    def _generic_value(self, cspec: ColumnSpec, charge_start: datetime) -> object:
        rng = self.rng
        hint = self.overrides.get(cspec.name, {})
        if "force_value" in hint:
            return hint["force_value"]

        # conditional/recommended nullable columns default to null to avoid
        # tripping situational rules unless the column must be populated.
        must_populate = (not cspec.nullable) or cspec.presence == "required"
        if cspec.is_enum:
            if not must_populate and rng.random() < 0.5:
                return None
            return rng.choice(cspec.allowed)
        if not must_populate:
            return None

        if cspec.dtype == "datetime" or cspec.fmt == "datetime":
            return _dt(charge_start)
        if cspec.dtype == "decimal" or cspec.fmt == "numeric":
            return _dec(round(rng.uniform(0, 100), 6))
        if cspec.fmt == "currency":
            return "USD"
        if cspec.dtype == "json" or cspec.fmt in ("json", "keyvalue"):
            return "{}"
        # plain string
        return f"{cspec.name}-{rng.randint(1000, 9999)}"

    # ------------------------------------------------------------------ #
    def _enforce(self, row: Dict[str, object], charge_start: datetime) -> None:
        """Final pass: required non-null columns must not be null; enums respected."""
        for cspec in self.emit_cols:
            v = row.get(cspec.name)
            if cspec.is_enum and v is not None and v not in cspec.allowed:
                # Deterministic coercion: map a given invalid value to a stable
                # allowed value so per-column cardinality is preserved (e.g.
                # one ServiceSubcategory per ServiceName).
                idx = zlib.crc32(str(v).encode()) % len(cspec.allowed)
                row[cspec.name] = cspec.allowed[idx]
            if v is None and not cspec.nullable and cspec.presence == "required":
                row[cspec.name] = self._generic_value(
                    ColumnSpec(cspec.name, cspec.presence, cspec.dtype, False,
                               cspec.allowed, cspec.fmt),
                    charge_start,
                )


# ---------------------------------------------------------------------- #
def _account_type(prov: Provider) -> str:
    return {"aws": "BillingAccount", "azure": "BillingProfile",
            "gcp": "BillingAccount", "oracle": "Tenancy"}.get(prov.key, "BillingAccount")


def _resource_id(prov: Provider, region_id: str, rng) -> str:
    n = rng.randint(10 ** 11, 10 ** 12 - 1)
    if prov.key == "aws":
        return f"arn:aws:ec2:{region_id}:{prov.billing_account_id}:instance/i-{n:012x}"
    if prov.key == "azure":
        return f"/subscriptions/{prov.billing_account_id}/resourceGroups/rg-{n % 1000}/providers/Microsoft.Compute/virtualMachines/vm-{n % 9999}"
    if prov.key == "gcp":
        return f"//compute.googleapis.com/projects/{prov.billing_account_name}/zones/{region_id}-a/instances/inst-{n % 9999}"
    return f"ocid1.instance.oc1.{region_id}.{n:012x}"


def _sku(rng, length: int = 16) -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(rng.choice(alphabet) for _ in range(length))


def generate(version: str, model_path: str, out_path: str, **kwargs) -> int:
    spec = ModelSpec.load(model_path)
    cfg = GenConfig(version=version, **kwargs)
    return Generator(spec, cfg).write_csv(out_path)
