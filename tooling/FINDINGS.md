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
| FOCUS 1.0 model (back-port) | 112 | **10** | 295 |
| FOCUS 1.2 model   | 114  | 23   | 441     |
| FOCUS 1.3 model   | 178  | 164  | 422     |

Against a **1.0-scoped** model (the fairest test) it still fails 10 rules. The
version-gap noise disappears, leaving genuine content issues: `ContractedCost`
null in 7 rows, `PricingUnit` unit-format (9), `ServiceName` -> `ServiceCategory`
cardinality, and `BilledCost` must-be-0 (615 rows, see below). The larger fail
counts against 1.2/1.3 are mostly columns those versions added.

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
themselves. All are already tracked upstream (confirmed in PR review): the
CapacityReservationStatus and contradictory-null patterns in
[FOCUS_Spec#2393](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/issues/2393)
and [#2394](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/issues/2394),
the `FormatJSON` gap in
[focus_validator#138](https://github.com/finopsfoundation/focus_validator/issues/138)
(fix [#141](https://github.com/finopsfoundation/focus_validator/pull/141)), and
the 1.4 dependency cycle in
[FOCUS_Spec#2447](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/issues/2447).
`PricingCurrencyContractedUnitPrice-C-012-C` (inverted condition) is still in the
1.4 working draft and does not appear separately filed yet.

* **`InvoiceId-C-004-C` / `InvoiceId-C-005-C` (1.2) — cosmetic, working as
  intended.** C-004 ("MUST be null ...") and C-005 ("MUST NOT be null ...") both
  have an empty `Condition`, so each looks like it applies to every row. They
  sit under an OR that always passes, so the per-rule red line the engine prints
  is cosmetic and needs no fix (triaged in
  [FOCUS_Spec#2394](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/issues/2394)).
  The generator therefore keeps `InvoiceId` populated and the regeneration loop
  is told not to null it.

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

## 4. Dataset coverage (1.3 / 1.4)

In the requirements model, the additional FOCUS datasets were formalised as
follows (not all in the version where they first appeared in the spec text):

* **1.3** models **CostAndUsage** and **ContractCommitment**.
* **1.4** models **CostAndUsage**, **ContractCommitment** (enhanced: 13 -> 30
  columns), **InvoiceDetail**, and **BillingPeriod**.

The generator and validator are dataset-aware. Generated samples for the new
datasets are **fully compliant**:

| Version / dataset            | Pass | Fail |
|------------------------------|------|------|
| 1.3 ContractCommitment       | 75   | 0    |
| 1.4 ContractCommitment       | 162  | 0    |
| 1.4 InvoiceDetail            | 104  | 0    |
| 1.4 BillingPeriod            | 32   | 0    |

Note the 1.4 dependency cycle (item 2) only blocks **CostAndUsage**; the other
1.4 datasets load and validate normally.

## 5. Back-ported 1.0 / 1.1 models

There is no official requirements model for 1.0 / 1.1. `backport.py` builds
unofficial models by filtering the 1.2 model to each version's column set
(43 columns for 1.0, 50 for 1.1, per the focus.finops.org column catalogue) and
pruning rules/dependencies that reference dropped columns.

Caveat: these inherit **1.2 rule logic** for retained columns. Where 1.0/1.1
defined allowed values, nullability, or relationships differently, the back-port
reflects 1.2. They are for round-tripping and smoke-testing, not authoritative
conformance. Generated 1.0/1.1 samples validate clean (1.1: 130 pass / 0 fail;
1.0: 122 pass / 0 fail) — and notably do **not** show the cosmetic `InvoiceId`
rule line because `InvoiceId` is a 1.2 column.

## Generated-sample status (1000 rows each, CostAndUsage unless noted)

| Version | Pass | Fail | Notes |
|---------|------|------|-------|
| 1.0 (CAU, back-port) | 122 | 0 | synthetic; real-world data not overwritten |
| 1.1 (CAU, back-port) | 130 | 0 | |
| 1.2     | 136  | 1    | `InvoiceId-C-004` cosmetic / working-as-intended (item 3) |
| 1.3     | 338  | 4    | `CapacityReservationStatus` + `PricingCurrencyContractedUnitPrice` (item 3) |
| 1.3 ContractCommitment | 75 | 0 | |
| 1.4 CostAndUsage | n/a | n/a | model cannot be loaded (item 2) |
| 1.4 ContractCommitment / InvoiceDetail / BillingPeriod | 162 / 104 / 32 | 0 | |

All CostAndUsage residual failures trace to the upstream issues above, not to
the generator.
