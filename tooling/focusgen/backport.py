"""Back-port FOCUS 1.0 / 1.1 requirements models from the 1.2 model.

There is no official machine-readable requirements model for FOCUS 1.0 or 1.1
(modeling began at 1.2). This module builds an **unofficial, best-effort** model
for those versions by filtering the assembled 1.2 model down to the columns that
existed in 1.0 / 1.1 (per the authoritative FOCUS column catalogue) and pruning
any rule, dependency, or condition that references a dropped column.

Caveats (documented in FINDINGS.md):
* It inherits 1.2 *rule logic* for retained columns. Where 1.0/1.1 defined a
  column's allowed values, nullability, or relationships differently from 1.2,
  the back-port reflects 1.2, not the original text.
* It is intended for round-tripping generated samples and smoke-testing, not as
  an authoritative 1.0/1.1 conformance reference.

Column membership source: focus.finops.org column catalogue (version flags).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Set

# Authoritative column titles per version (focus.finops.org column catalogue).
_V10_TITLES = [
    "Availability Zone", "Billed Cost", "Billing Account ID", "Billing Account Name",
    "Billing Currency", "Billing Period End", "Billing Period Start", "Charge Category",
    "Charge Class", "Charge Description", "Charge Frequency", "Charge Period End",
    "Charge Period Start", "Commitment Discount Category", "Commitment Discount ID",
    "Commitment Discount Name", "Commitment Discount Status", "Commitment Discount Type",
    "Consumed Quantity", "Consumed Unit", "Contracted Cost", "Contracted Unit Price",
    "Effective Cost", "Invoice Issuer Name", "List Cost", "List Unit Price",
    "Pricing Category", "Pricing Quantity", "Pricing Unit", "Provider Name",
    "Publisher Name", "Region ID", "Region Name", "Resource ID", "Resource Name",
    "Resource Type", "Service Category", "Service Name", "SKU ID", "SKU Price ID",
    "Sub Account ID", "Sub Account Name", "Tags",
]
# v1.1 adds these seven columns to v1.0.
_V11_EXTRA = [
    "Capacity Reservation ID", "Capacity Reservation Status",
    "Commitment Discount Quantity", "Commitment Discount Unit",
    "Service Subcategory", "SKU Meter", "SKU Price Details",
]

VERSION_TITLES = {
    "1.0": _V10_TITLES,
    "1.1": _V10_TITLES + _V11_EXTRA,
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _column_of(rule: dict) -> str:
    return rule.get("EntityId") or rule.get("Reference") or ""


def _referenced_columns(node) -> Set[str]:
    """All ColumnName / ColumnAName / ColumnBName referenced in a check tree."""
    cols: Set[str] = set()
    if isinstance(node, dict):
        for k in ("ColumnName", "ColumnAName", "ColumnBName", "ResultColumnName", "EqualsColumnName"):
            if isinstance(node.get(k), str):
                cols.add(node[k])
        for v in node.values():
            cols |= _referenced_columns(v)
    elif isinstance(node, list):
        for item in node:
            cols |= _referenced_columns(item)
    return cols


def _prune_check_tree(node, kept_rule_ids: Set[str]):
    """Drop CheckModelRule items pointing at removed rules; collapse AND/OR."""
    if isinstance(node, dict):
        if "Items" in node and isinstance(node["Items"], list):
            new_items = []
            for item in node["Items"]:
                if item.get("CheckFunction") == "CheckModelRule" and item.get("ModelRuleId") not in kept_rule_ids:
                    continue
                new_items.append(_prune_check_tree(item, kept_rule_ids))
            node = dict(node)
            node["Items"] = new_items
        return node
    return node


def backport(model_12_path: str | Path, version: str, out_path: str | Path) -> dict:
    if version not in VERSION_TITLES:
        raise ValueError(f"Unsupported back-port version: {version}")
    allowed = {_norm(t) for t in VERSION_TITLES[version]}
    model = json.loads(Path(model_12_path).read_text())
    rules = model.get("ModelRules", {})

    # 1) Decide which rules to keep.
    dataset_ids = {ds_id for ds_id in model.get("ModelDatasets", {})}
    kept: Dict[str, dict] = {}
    for rid, rule in rules.items():
        etype = rule.get("EntityType")
        ref = rule.get("Reference") or ""
        if etype == "Column":
            if _norm(_column_of(rule)) in allowed:
                kept[rid] = rule
        elif etype == "Attribute":
            kept[rid] = rule  # attributes (format families) are version-agnostic
        elif etype == "Dataset":
            # Dataset rules often describe a single column (via Reference). Drop
            # them when that column is not in this version.
            if ref and _norm(ref) not in allowed and ref not in dataset_ids:
                continue
            refs = _referenced_columns(rule.get("ValidationCriteria", {}).get("Requirement", {}))
            refs |= _referenced_columns(rule.get("ValidationCriteria", {}).get("Condition", {}))
            if all(_norm(c) in allowed for c in refs) or not refs:
                kept[rid] = rule
        else:
            kept[rid] = rule

    # 2) Drop rules whose requirement/condition references a dropped column.
    for rid in list(kept):
        vc = kept[rid].get("ValidationCriteria", {})
        refs = _referenced_columns(vc.get("Requirement", {})) | _referenced_columns(vc.get("Condition", {}))
        if any(_norm(c) not in allowed for c in refs):
            del kept[rid]

    # 3) Fixpoint: prune item lists / dependencies to kept rules, then remove
    #    rules that became vacuous (empty AND/OR composite, or a CheckModelRule
    #    pointing at a removed rule). Removing a rule can empty its parent, so
    #    repeat until stable.
    while True:
        kept_ids = set(kept)
        for rule in kept.values():
            vc = rule.get("ValidationCriteria")
            if not vc:
                continue
            deps = vc.get("Dependencies")
            if isinstance(deps, list):
                vc["Dependencies"] = [d for d in deps if d in kept_ids]
            if vc.get("Requirement"):
                vc["Requirement"] = _prune_check_tree(vc["Requirement"], kept_ids)
        removed = False
        for rid in list(kept):
            req = kept[rid].get("ValidationCriteria", {}).get("Requirement", {})
            cf = req.get("CheckFunction")
            if cf in ("AND", "OR") and not req.get("Items"):
                del kept[rid]
                removed = True
            elif cf == "CheckModelRule" and req.get("ModelRuleId") not in kept:
                del kept[rid]
                removed = True
        if not removed:
            break
    kept_ids = set(kept)

    # 4) Rewrite ModelDatasets ModelRules lists.
    for ds in model.get("ModelDatasets", {}).values():
        if isinstance(ds.get("ModelRules"), list):
            ds["ModelRules"] = [r for r in ds["ModelRules"] if r in kept_ids]

    model["ModelRules"] = kept
    details = model.setdefault("Details", {})
    details["FOCUSVersion"] = version
    details["ModelVersion"] = f"{version}-backport"
    details["BackportNote"] = (
        "Unofficial back-port filtered from the FOCUS 1.2 requirements model to the "
        f"v{version} column set. Inherits 1.2 rule logic; not an authoritative "
        "1.0/1.1 conformance reference."
    )

    out_path = Path(out_path)
    out_path.write_text(json.dumps(model, indent=2))
    return {
        "version": version,
        "columns": len({_norm(_column_of(r)) for r in kept.values() if r.get("EntityType") == "Column"}),
        "rules": len(kept),
        "out": str(out_path),
    }


if __name__ == "__main__":
    import sys
    specs = Path(__file__).resolve().parent.parent / "specs"
    src = specs / "model-1.2.json"
    for v in ("1.0", "1.1"):
        info = backport(src, v, specs / f"model-{v}.json")
        print(info)
