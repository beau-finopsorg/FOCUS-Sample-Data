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

SUPPORTED_VERSIONS = ("1.2", "1.3", "1.4")
DEFAULT_DATASET = "CostAndUsage"
