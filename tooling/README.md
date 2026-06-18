# FOCUS sample-data tooling (`focusgen`)

Model-driven generation and validation of FOCUS™ sample datasets across FOCUS
versions **1.0 – 1.4** and all of their datasets.

| Version | Datasets modelled | Model source |
|---------|-------------------|--------------|
| 1.0 | CostAndUsage | back-ported (unofficial) |
| 1.1 | CostAndUsage | back-ported (unofficial) |
| 1.2 | CostAndUsage | official |
| 1.3 | CostAndUsage, ContractCommitment | official |
| 1.4 | CostAndUsage, ContractCommitment, InvoiceDetail, BillingPeriod | official |

File naming: single-dataset versions (1.0-1.2) use `focus_sample.csv`;
multi-dataset versions (1.3+) name every dataset explicitly, e.g.
`FOCUS-1.4/focus_sample_costandusage.csv`,
`FOCUS-1.4/focus_sample_contractcommitment.csv`. See [`FINDINGS.md`](FINDINGS.md)
for the back-port caveats and the upstream model issues this surfaced (including
the 1.4 CostAndUsage model cycle).

The tooling does four things:

1. **Generate** spec-compliant sample data for a FOCUS version and dataset.
2. **Validate** any sample (generated or existing) against the FOCUS
   requirements model using the official
   [FOCUS validator](https://github.com/finopsfoundation/focus_validator), and
   produce a machine-readable report.
3. **Regenerate** in a closed feedback loop: generate, validate, adjust, repeat
   until the data is compliant or only upstream-model failures remain.
4. **Back-port** unofficial 1.0/1.1 models from the 1.2 model (see caveats in
   [`FINDINGS.md`](FINDINGS.md)).

## Why this design

The FOCUS [requirements model](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/tree/working_draft/specification/requirements_model)
is the machine-readable form of the spec: each column's type, nullability,
allowed values, formats, and cross-column rules are expressed as JSON rules.
The validator consumes the assembled `model-<version>.json`; **so does the
generator**. Driving both sides from the same artefact means "what we generate"
and "what we validate against" can never drift apart, and adding a new FOCUS
version is mostly a matter of dropping in its model file.

```
            assembled model-<version>.json  (the FOCUS spec, machine-readable)
                       /                         \
        focusgen.model (parse)            focus_validator (enforce)
                 |                                  |
        focusgen.generator  --- CSV --->  focusgen.validate --> report
                 \                                  /
                  \------ focusgen.regenerate ------/   (feedback loop)
```

Versions with an official machine-readable model (1.2 through 1.4) are generated
and validated directly. 1.0 and 1.1 have no official model, so they use
unofficial back-ported models (see [`FINDINGS.md`](FINDINGS.md)) for
round-tripping and smoke-testing.

## Layout

| Path | Purpose |
|------|---------|
| `focusgen/model.py` | Parse an assembled model JSON into per-column constraints |
| `focusgen/providers.py` | Realistic AWS / Azure / GCP / Oracle value profiles |
| `focusgen/generator.py` | Synthesise compliant rows for a version/dataset |
| `focusgen/validate.py` | Run the FOCUS validator, return a structured report |
| `focusgen/regenerate.py` | Generate → validate → adjust → regenerate loop |
| `focusgen/backport.py` | Build unofficial 1.0 / 1.1 models from the 1.2 model |
| `focusgen/cli.py` | `gen` / `validate` / `regen` / `build-all` / `validate-all` |
| `specs/model-<version>.json` | Assembled models (1.2-1.4 official, 1.0/1.1 back-ported) |
| `reports/` | Saved validation reports |

## Install

Requires **Python 3.12+** (the FOCUS validator requires 3.12).

```bash
pip install -r tooling/requirements.txt
```

## Usage

All commands are modules under `tooling/`; run them from that directory.

```bash
# Generate a 1.3 sample (1000 rows, all four providers)
python -m focusgen gen --version 1.3 --rows 1000 --out ../FOCUS-1.3/focus_sample_costandusage.csv

# Validate a CSV against a version (human-readable, then JSON)
python -m focusgen validate --version 1.3 --data-file ../FOCUS-1.3/focus_sample_costandusage.csv
python -m focusgen validate --version 1.3 --data-file ../FOCUS-1.3/focus_sample_costandusage.csv --json

# Generate + validate + self-correct, writing a JSON report
python -m focusgen regen --version 1.3 --rows 1000 \
    --out ../FOCUS-1.3/focus_sample_costandusage.csv --report reports/validation-1.3.json --allow-persistent

# Generate a non-CostAndUsage dataset
python -m focusgen gen --version 1.4 --dataset ContractCommitment \
    --out ../FOCUS-1.4/focus_sample_contractcommitment.csv

# Build samples for all versions/datasets (skips FOCUS-1.0 real-world data)
python -m focusgen build-all --base .. --rows 1000 --allow-persistent

# Discover & validate every FOCUS-<v>/focus_sample*.csv, writing reports
python -m focusgen validate-all --base .. --allow-persistent

# (Re)build the back-ported 1.0/1.1 models from the 1.2 model
python -m focusgen.backport
```

Useful flags: `--providers aws,azure`, `--seed N` (reproducible),
`--period 2024-09`, `--max-iters N`, `--model path/to/model.json`.

## Regeneration feedback loop

`regen` reads the validator's structured report and derives generation
overrides from the failing rules (e.g. a rule stating a column *MUST be null*
forces that column to null), then regenerates and re-validates. It stops when
the sample is compliant, when an iteration yields no corrective action, or when
no further improvement is made.

Remaining failures are classified as **persistent** — failures no data change
could clear within the loop. These are strong candidates for upstream
spec/model issues and are reported explicitly rather than hidden. See
[`FINDINGS.md`](FINDINGS.md) for the issues this surfaced.

## Validation reports

`reports/` contains JSON reports with this shape:

```json
{
  "version": "1.3", "model_version": "1.3.0.3",
  "data_file": "...", "row_count": 1000,
  "total": 764, "passed": 338, "failed": 4, "skipped": 422,
  "compliant": false,
  "failures": [{"rule_id": "...", "must_satisfy": "...", "violations": 9, "column": "..."}]
}
```

## Updating to a new FOCUS version

1. Assemble the model with the spec repo's `build_json.py`
   (`python build_json.py --build-only --version 1.5`).
2. Copy the result to `tooling/specs/model-1.5.json`.
3. Add `"1.5"` to `SUPPORTED_VERSIONS` (and `DATASETS_BY_VERSION`) in
   `focusgen/__init__.py`. CI reads the version list from there, so no workflow
   change is needed.
4. Run `python -m focusgen regen --version 1.5 ...` and address any failures the
   generator's coherence layer does not already cover.

## CI

* **`validate-sample-data.yml`** — runs the unit tests, then one `validate-all`
  step over every `FOCUS-<version>/focus_sample*.csv` (versions discovered from
  `SUPPORTED_VERSIONS`) on push/PR, uploading reports.
* **`generate-sample-data.yml`** — on-demand/monthly regeneration that opens a PR
  with refreshed samples and reports.
