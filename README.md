# FOCUS-Sample-Data

Sample datasets for the FinOps Open Cost and Usage Specification (FOCUS™), plus
tooling to generate and validate them against the FOCUS requirements model.

## Contents

| Directory | FOCUS version | Datasets | Source | Validation |
|-----------|---------------|----------|--------|------------|
| [`FOCUS-1.0`](FOCUS-1.0) | 1.0 | CostAndUsage | Anonymized real-world data | Not fully compliant (see findings) |
| [`FOCUS-1.1`](FOCUS-1.1) | 1.1 | CostAndUsage | Generated (back-ported model) | Compliant (unofficial model) |
| [`FOCUS-1.2`](FOCUS-1.2) | 1.2 | CostAndUsage | Generated | Compliant except 1 upstream-model issue |
| [`FOCUS-1.3`](FOCUS-1.3) | 1.3 | CostAndUsage, ContractCommitment | Generated | ContractCommitment clean; CostAndUsage has known upstream issues |
| [`FOCUS-1.4`](FOCUS-1.4) | 1.4 | CostAndUsage, ContractCommitment, InvoiceDetail, BillingPeriod | Generated | New datasets clean; CostAndUsage blocked upstream |

### File naming

Single-dataset versions (1.0, 1.1, 1.2) use `focus_sample.csv`. Multi-dataset
versions (1.3, 1.4) name each dataset explicitly:

```
FOCUS-1.4/focus_sample_costandusage.csv
FOCUS-1.4/focus_sample_contractcommitment.csv
FOCUS-1.4/focus_sample_invoicedetail.csv
FOCUS-1.4/focus_sample_billingperiod.csv
```

The original anonymized `FOCUS-1.0` data is preserved as-is and is never
regenerated.

## Tooling: `focusgen`

[`tooling/`](tooling) contains `focusgen`, a model-driven toolkit that generates
and validates FOCUS sample data. Its design principle: the generator and the
validator are both driven by the same assembled `model-<version>.json`, so the
data produced and the rules it is checked against come from one source and
cannot drift.

It does four things:

1. **Generate** spec-compliant sample rows for a FOCUS version and dataset,
   using realistic per-provider profiles (AWS, Azure, GCP, Oracle) and a
   coherence layer that enforces FOCUS invariants (cost equals unit price times
   quantity, RFC 3339 UTC timestamps, valid currencies, period ordering,
   commitment-discount and capacity-reservation coherence, one ServiceCategory
   per ServiceName, and so on).
2. **Validate** any sample against the requirements model and emit a
   machine-readable JSON report.
3. **Regenerate** in a closed feedback loop (generate, validate, adjust,
   regenerate), classifying any leftover failures as persistent so genuine
   upstream issues are surfaced rather than hidden.
4. **Back-port** unofficial 1.0/1.1 models from the 1.2 model (see caveats
   below).

### Built on

* [FOCUS requirements model](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/tree/working_draft/specification/requirements_model)
  — the machine-readable form of the spec. The assembled `model-<version>.json`
  for 1.2, 1.3, and 1.4 is vendored under `tooling/specs/`.
* [FOCUS validator](https://github.com/finopsfoundation/focus_validator) — the
  official DuckDB-based validation engine that `focusgen` wraps.
* FOCUS column catalogue (focus.finops.org) — authoritative per-version column
  membership, used to scope the 1.0/1.1 back-ports.

### Quickstart

```bash
pip install -r tooling/requirements.txt
cd tooling

# generate every version/dataset (FOCUS-1.0 real data is left untouched)
python -m focusgen build-all --base .. --rows 1000 --allow-persistent

# validate everything and write JSON reports to tooling/reports/
python -m focusgen validate-all --base .. --allow-persistent

# validate a single file
python -m focusgen validate --version 1.4 \
    --data-file ../FOCUS-1.4/focus_sample_contractcommitment.csv
```

See [`tooling/README.md`](tooling/README.md) for full command reference.

## What validation revealed

Detailed in [`tooling/FINDINGS.md`](tooling/FINDINGS.md):

* The existing **FOCUS-1.0 sample data is not fully compliant**, even against a
  1.0-scoped model (10 rule failures: `ContractedCost` nulls, `PricingUnit`
  format, `ServiceName` cardinality, and the `BilledCost` third-party rule).
  Its timestamps also predate the RFC 3339 format later checks expect.
* The **FOCUS 1.4 working-draft model cannot be loaded for CostAndUsage** due to
  a dependency cycle in the `CommitmentDiscount*` rules. The other three 1.4
  datasets are unaffected.
* Several **upstream model-rule quirks** in 1.2/1.3 (malformed
  `CapacityReservationStatus` conditions, an inverted
  `PricingCurrencyContractedUnitPrice` condition, and the cosmetic `InvoiceId`
  rule line that is working-as-intended). These account for the only residual
  failures on otherwise-compliant generated CostAndUsage data, and all are
  tracked upstream (see FINDINGS.md for issue links).

### Note on 1.0 / 1.1

FOCUS has no official machine-readable requirements model for 1.0 or 1.1, so the
models under `tooling/specs/model-1.0.json` and `model-1.1.json` are
**unofficial back-ports** filtered from the 1.2 model to each version's column
set. They inherit 1.2 rule logic for retained columns and are intended for
round-tripping and smoke-testing, not authoritative conformance. No change to
the FOCUS spec is proposed here.

## Continuous integration

* [`validate-sample-data.yml`](.github/workflows/validate-sample-data.yml) runs
  the unit tests and validates every `FOCUS-<version>/focus_sample*.csv` on push
  and pull request, uploading reports.
* [`generate-sample-data.yml`](.github/workflows/generate-sample-data.yml)
  regenerates the samples on demand or monthly and opens a pull request.

## Want to contribute

Reach out to [focus@finops.org](mailto:focus@finops.org) to help with more
sample data, especially for platforms not yet represented.
