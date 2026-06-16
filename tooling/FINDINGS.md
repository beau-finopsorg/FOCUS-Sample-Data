# Findings

Issues surfaced by running the generate → validate pipeline against both the
existing FOCUS-1.0 sample data and freshly generated samples. Validation uses
the official [FOCUS validator](https://github.com/finopsfoundation/focus_validator)
against the assembled requirements models for 1.2, 1.3, and 1.4.

## 1. The existing FOCUS-1.0 sample data is not compliant

`FOCUS-1.0/focus_sample.csv` (1,000-row sample) was never machine-validated.
Running it through the validator:

| Validated against | Pass | Fail | Skipped |
|-------------------|------|------|---------|
| FOCUS 1.2 model   | 114  | 23   | 441     |
| FOCUS 1.3 model   | 178  | 164  | 422     |

Some failures are expected version drift (1.2+ added columns such as
`InvoiceId` and `ServiceSubcategory`; 1.3 added ~20 columns including
`HostProviderName`, `ServiceProviderName`, the `PricingCurrency*` family, and
the split-cost-allocation columns). But several are genuine content issues even
against 1.2:

* **`ContractedCost` is null in 7 rows** — `ContractedCost MUST NOT be null`.
* **`PricingUnit` unit-format** — 9 rows do not conform to the Unit Format
  attribute (a SHOULD).
* **`BilledCost` must be 0 for third-party charges (615 rows)** — triggered
  because `ProviderName` (`"AWS"`) differs from `InvoiceIssuerName`
  (`"Amazon Web Services, Inc."`). The rule `BilledCost-C-005-C` treats any row
  where `ProviderName != InvoiceIssuerName` as a marketplace/third-party charge
  and requires `BilledCost = 0`. The 1.0 data uses different strings for these
  two columns on first-party charges, so it trips the rule.
* **`ServiceName` → `ServiceCategory` / `ServiceSubcategory` cardinality** — a
  `ServiceName` maps to more than one category/subcategory across rows.
* **Datetime format** — 1.0 uses `2024-09-01 00:00:00` (space separator, no
  timezone). The validator's DateTime format check requires
  `YYYY-MM-DDTHH:MM:SSZ`, so 1.0's timestamps would not pass the format rule.

Full reports: `reports/focus-1.0-vs-1.2.json`, `reports/focus-1.0-vs-1.3.json`.

## 2. FOCUS 1.4 working-draft model breaks the validator

The assembled 1.4 model (`working_draft`) cannot be loaded by the validator:

```
ValueError: Active-edge cycle detected; blocked nodes:
  ['CAU-CostAndUsage-D-000-M', 'CAU-CommitmentDiscountUnit-C-000-C',
   'CAU-CommitmentDiscountQuantity-C-000-C', ...]
```

There is a dependency cycle among the `CommitmentDiscountQuantity` /
`CommitmentDiscountUnit` rules. Until it is resolved upstream, 1.4 sample data
can be **generated** but not **validated**; the pipeline reports this as an
engine error rather than crashing.

## 3. Suspected upstream model-rule defects (1.2 / 1.3)

These are the only failures remaining on freshly generated, otherwise-compliant
samples. They persist regardless of data content, which points at the rules
themselves.

* **`InvoiceId-C-004-C` vs `InvoiceId-C-005-C` (1.2) — contradictory pair.**
  C-004 requires `InvoiceId` be null "when not associated with an invoice";
  C-005 requires it be non-null "when associated". Both have an **empty
  `Condition`**, so each applies to every row unconditionally. No value can
  satisfy both — exactly one always fails.

* **`CapacityReservationStatus-C-003-C` / `-C-004-C` (1.3) — malformed condition
  JSON.** The conditions are written as `{"AND": {...}}` / `{"AND": [...]}`
  instead of the schema's `{"CheckFunction": "AND", "Items": [...]}`. The
  validator does not recognise the shorthand, drops the condition, and fires the
  rule unconditionally (e.g. `CapacityReservationStatus MUST NOT be null` for
  every row, even when `CapacityReservationId` is null).

* **`PricingCurrencyContractedUnitPrice-C-012-C` (1.3) — inverted condition.**
  The text says "MUST NOT be null when `SkuPriceId` is **not** null", but the
  `Condition` JSON is `CheckValue(SkuPriceId, null)` — i.e. it executes on
  `SkuPriceId` being null, the opposite of the prose.

* **Missing `FormatJSON` generator (validator).** Rules using the `FormatJSON`
  check function (`ContractApplied`, `AllocatedMethodDetails`) are skipped by
  the validator with "Missing generator for CheckFunction 'FormatJSON'". This is
  a validator gap, not a model issue, but it means those JSON-object rules are
  currently unchecked.

## Generated-sample status (1000 rows each)

| Version | Pass | Fail | Skipped | Residual failures |
|---------|------|------|---------|-------------------|
| 1.2     | 136  | 1    | 441     | `InvoiceId` contradiction (item 3) |
| 1.3     | 338  | 4    | 422     | `CapacityReservationStatus` + `PricingCurrencyContractedUnitPrice` (item 3) |
| 1.4     | n/a  | n/a  | n/a     | model cannot be loaded (item 2) |

All residual failures trace to the upstream issues above, not to the generator.
