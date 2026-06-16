"""Parse an assembled FOCUS requirements-model JSON into per-column constraints.

The assembled model (``model-<version>.json``, produced by the FOCUS_Spec
``build_json.py`` script) is the canonical machine-readable form of the FOCUS
specification. The *validator* consumes it to check data; this module consumes
the same file so the *generator* produces data that already satisfies the rules
the validator will enforce.

We deliberately extract a conservative, generation-oriented view of the model:

* presence  - is the column MUST / RECOMMENDED / conditional in the dataset
* dtype     - string | datetime | decimal | json
* nullable  - is an unconditional "MUST NOT be null" rule present
* allowed   - closed enum of allowed values (from an unconditional OR-of-CheckValue)
* fmt       - format family the value must follow (datetime/numeric/currency/unit/...)

Cross-column relationships (e.g. ListCost >= EffectiveCost, period ordering,
commitment-discount block coherence) are NOT inferred here; they are encoded in
the generator's coherence layer and confirmed by the validation feedback loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Check functions that declare a column's primitive type.
_TYPE_CHECKS = {
    "TypeString": "string",
    "TypeDateTime": "datetime",
    "TypeDecimal": "decimal",
}

# Format check functions -> a coarse format family the generator understands.
_FORMAT_CHECKS = {
    "FormatString": "string",
    "FormatDateTime": "datetime",
    "FormatNumeric": "numeric",
    "FormatCurrency": "currency",
    "FormatUnit": "unit",
    "FormatKeyValue": "keyvalue",
    "FormatJSON": "json",
}

_JSON_CHECKS = {
    "FormatJSON",
    "CheckJSONSchema",
    "JSONCheckPathType",
    "JSONCheckPathKeyExists",
    "FormatKeyValue",
}


@dataclass
class ColumnSpec:
    """Generation-oriented constraints for a single FOCUS column."""

    name: str
    presence: str = "optional"          # required | recommended | conditional | optional
    dtype: str = "string"               # string | datetime | decimal | json
    nullable: bool = True               # False only when an unconditional MUST-NOT-null rule exists
    allowed: Optional[List[str]] = None  # closed enum, if the spec defines one
    fmt: Optional[str] = None           # format family (see _FORMAT_CHECKS)
    introduced: Optional[str] = None     # ModelVersionIntroduced

    @property
    def is_enum(self) -> bool:
        return bool(self.allowed)


@dataclass
class ModelSpec:
    """Parsed view of one assembled model JSON for one dataset."""

    version: str
    focus_version: str
    model_version: str
    dataset: str
    columns: Dict[str, ColumnSpec] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: str | Path, dataset: str = "CostAndUsage") -> "ModelSpec":
        path = Path(path)
        data = json.loads(path.read_text())
        details = data.get("Details", {})
        focus_version = details.get("FOCUSVersion", "unknown")
        spec = cls(
            version=focus_version,
            focus_version=focus_version,
            model_version=details.get("ModelVersion", "unknown"),
            dataset=dataset,
            raw=data,
        )
        spec._extract(data.get("ModelRules", {}))
        return spec

    # ------------------------------------------------------------------ #
    def _extract(self, rules: Dict[str, Any]) -> None:
        dataset = self.dataset

        def in_dataset(rule: Dict[str, Any]) -> bool:
            # 1.4 models tag rules with DatasetId; older single-dataset models
            # may not, in which case we accept everything.
            ds = rule.get("DatasetId")
            return ds is None or ds == dataset

        # 1) Presence: dataset-level ColumnPresent checks.
        for rid, rule in rules.items():
            if not in_dataset(rule):
                continue
            req = rule.get("ValidationCriteria", {}).get("Requirement", {})
            if req.get("CheckFunction") == "ColumnPresent":
                col = req.get("ColumnName")
                if not col:
                    continue
                keyword = (rule.get("ValidationCriteria", {}).get("Keyword") or "").upper()
                cspec = self.columns.setdefault(col, ColumnSpec(name=col))
                cspec.presence = _presence_from_keyword(keyword, rid)
                cspec.introduced = cspec.introduced or rule.get("ModelVersionIntroduced")

        # 2) Per-column type / nullability / enum / format from column rules.
        for rid, rule in rules.items():
            if rule.get("EntityType") != "Column" or not in_dataset(rule):
                continue
            # 1.4 models use EntityId; 1.2/1.3 models use Reference.
            col = rule.get("EntityId") or rule.get("Reference")
            if not col:
                continue
            cspec = self.columns.setdefault(col, ColumnSpec(name=col))
            cspec.introduced = cspec.introduced or rule.get("ModelVersionIntroduced")

            vc = rule.get("ValidationCriteria", {})
            req = vc.get("Requirement", {})
            keyword = (vc.get("Keyword") or "").upper()
            conditional = bool(vc.get("Condition"))  # condition => situational rule
            func = rule.get("Function")

            # Walk the requirement tree for leaf checks.
            leaves = list(_iter_leaves(req))

            # dtype
            if func == "Type" or any(l.get("CheckFunction") in _TYPE_CHECKS for l in leaves):
                for l in leaves:
                    t = _TYPE_CHECKS.get(l.get("CheckFunction"))
                    if t:
                        cspec.dtype = t
                        break

            # json / format family
            for l in leaves:
                cf = l.get("CheckFunction")
                if cf in _JSON_CHECKS:
                    cspec.dtype = "json"
                if cf in _FORMAT_CHECKS and cspec.fmt is None:
                    cspec.fmt = _FORMAT_CHECKS[cf]
                if cf == "CheckNationalCurrency" and cspec.fmt is None:
                    cspec.fmt = "currency"

            # nullability: unconditional MUST-NOT CheckNotValue(null)
            if not conditional and keyword.startswith("MUST NOT"):
                for l in leaves:
                    if l.get("CheckFunction") == "CheckNotValue" and l.get("Value") is None:
                        if l.get("ColumnName", col) == col:
                            cspec.nullable = False

            # enum: unconditional OR-of-CheckValue on this column
            if not conditional and req.get("CheckFunction") == "OR":
                vals = _enum_values(req, col)
                if vals and cspec.allowed is None:
                    cspec.allowed = vals

    # ------------------------------------------------------------------ #
    def required_columns(self) -> List[ColumnSpec]:
        return [c for c in self.columns.values() if c.presence == "required"]

    def emit_columns(self) -> List[ColumnSpec]:
        """Columns to write to the sample file: required + recommended + conditional.

        We populate required and recommended columns. Conditional columns are
        included with mostly-null values so the schema is complete without
        tripping conditional rules.
        """
        order = {"required": 0, "recommended": 1, "conditional": 2, "optional": 3}
        cols = [c for c in self.columns.values() if c.presence in order]
        cols.sort(key=lambda c: (order[c.presence], c.name))
        return cols

    def column(self, name: str) -> Optional[ColumnSpec]:
        return self.columns.get(name)


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #
def _presence_from_keyword(keyword: str, rule_id: str) -> str:
    if keyword.startswith("MUST"):
        return "required"
    if keyword.startswith("RECOMMENDED") or keyword.startswith("SHOULD"):
        return "recommended"
    if keyword.startswith("MAY") or keyword.startswith("CONDITIONAL"):
        return "conditional"
    # fall back to the rule-id suffix convention: -M / -O / -C
    suffix = rule_id.rsplit("-", 1)[-1] if "-" in rule_id else ""
    return {"M": "required", "O": "recommended", "C": "conditional"}.get(suffix, "optional")


def _iter_leaves(node: Any):
    """Yield leaf check dicts from a (possibly nested AND/OR) requirement tree."""
    if isinstance(node, dict):
        if "Items" in node and isinstance(node["Items"], list):
            for item in node["Items"]:
                yield from _iter_leaves(item)
        elif node.get("CheckFunction"):
            yield node
    elif isinstance(node, list):
        for item in node:
            yield from _iter_leaves(item)


def _enum_values(req: Dict[str, Any], col: str) -> List[str]:
    vals: List[str] = []
    for item in req.get("Items", []):
        if item.get("CheckFunction") == "CheckValue" and item.get("ColumnName", col) == col:
            v = item.get("Value")
            if isinstance(v, str):
                vals.append(v)
    return vals
