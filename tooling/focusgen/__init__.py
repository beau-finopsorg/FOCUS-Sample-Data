"""focusgen - model-driven FOCUS sample-data generation and validation tooling.

Components
----------
- model:      parse an assembled FOCUS requirements-model JSON into per-column constraints
- providers:  realistic per-provider value profiles (AWS / Azure / GCP / Oracle)
- generator:  synthesise spec-compliant sample rows for a dataset/version
- validate:   run the FOCUS validator and return a structured, machine-readable report
- regenerate: closed feedback loop (generate -> validate -> adjust -> regenerate)

The same assembled ``model-<version>.json`` artefact drives both generation and
validation, so the generator and the validator always agree on what "compliant"
means for a given FOCUS version.
"""

__version__ = "0.1.0"

# Versions with an official machine-readable requirements model.
OFFICIAL_VERSIONS = ("1.2", "1.3", "1.4")
# Versions whose model is an unofficial back-port (see backport.py / FINDINGS.md).
BACKPORTED_VERSIONS = ("1.0", "1.1")
SUPPORTED_VERSIONS = BACKPORTED_VERSIONS + OFFICIAL_VERSIONS

# Datasets available per version (in the requirements model).
DATASETS_BY_VERSION = {
    "1.0": ("CostAndUsage",),
    "1.1": ("CostAndUsage",),
    "1.2": ("CostAndUsage",),
    "1.3": ("CostAndUsage", "ContractCommitment"),
    "1.4": ("CostAndUsage", "ContractCommitment", "InvoiceDetail", "BillingPeriod"),
}

DEFAULT_DATASET = "CostAndUsage"
