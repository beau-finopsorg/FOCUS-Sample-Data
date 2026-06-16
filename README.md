# FOCUS-Sample-Data

Repository to store and share samples of FOCUS™ datasets.

## Contents

| Directory | FOCUS version | Source | Validated |
|-----------|---------------|--------|-----------|
| [`FOCUS-1.0`](FOCUS-1.0) | 1.0 | Anonymized real-world data | Not compliant (see findings) |
| [`FOCUS-1.2`](FOCUS-1.2) | 1.2 | Generated from the requirements model | Yes (1 known upstream-model failure) |
| [`FOCUS-1.3`](FOCUS-1.3) | 1.3 | Generated from the requirements model | Yes (known upstream-model failures) |
| [`FOCUS-1.4`](FOCUS-1.4) | 1.4 | Generated from the requirements model | Blocked upstream (draft model) |

## Tooling

[`tooling/`](tooling) contains `focusgen`: model-driven generation, validation,
and a self-correcting regeneration loop for FOCUS sample data. It is driven by
the FOCUS [requirements model](https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS_Spec/tree/working_draft/specification/requirements_model)
and the official [FOCUS validator](https://github.com/finopsfoundation/focus_validator),
so generated data and the rules it is checked against come from the same source.

```bash
pip install -r tooling/requirements.txt
cd tooling
python -m focusgen build-all --base .. --rows 1000 --allow-persistent   # generate all versions
python -m focusgen validate --version 1.3 --data-file ../FOCUS-1.3/focus_sample.csv
```

See [`tooling/README.md`](tooling/README.md) for full usage and
[`tooling/FINDINGS.md`](tooling/FINDINGS.md) for what validation revealed —
including that the existing FOCUS-1.0 sample is not spec-compliant.

GitHub Actions validate samples on every push/PR and can regenerate them on
demand (see [`.github/workflows`](.github/workflows)).

## Want to contribute

Reach out to [focus@finops.org](mailto:focus@finops.org) to help with more
sample data, especially for platforms not yet represented.
