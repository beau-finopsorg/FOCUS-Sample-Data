# FOCUS 1.0 Sample Data 

## Overview

This sample dataset is anonymized real world FOCUS data, made available for those needing to explore FOCUS data, demonstrate FOCUS tools and reports, and to learn from. Nothing beats your own real world data so go enable FOCUS datasets in your cloud platforms following the instructions made available by the cloud service providers see: [Getting Started with FOCUS™ Datasets](https://focus.finops.org/get-started/).

More details of this dataset can be found in the [FinOps Foundation Insights Article](https://www.finops.org/insights/focus-sandbox/) and explored in the [FOCUS Sandbox](https://focus.finops.org/sandbox/).

> **Validation note.** This anonymized real-world data is preserved as-is and is
> not regenerated. When checked with the tooling in [`../tooling`](../tooling)
> against a back-ported 1.0 model, it is **not fully compliant** (10 rule
> failures: `ContractedCost` nulls, `PricingUnit` unit format, a `ServiceName`
> -> `ServiceCategory` cardinality issue, and the `BilledCost` third-party rule).
> See [`../tooling/FINDINGS.md`](../tooling/FINDINGS.md). Timestamps also use
> `YYYY-MM-DD HH:MM:SS` rather than the RFC 3339 `...T...Z` form later versions expect.


## Data

The sample dataset includes the following:

| Provider | Details |
|----------|---------|
| AWS | Full month billing data |
| Google | Partial month billing data |
| Microsoft | Sample dataset downloaded from: [Microsoft FinOps Toolkit](https://microsoft.github.io/finops-toolkit/) |
| Oracle | Full month billing data |

_Note: the data has been anonymized_

## Datasets

| File Name | Content |
|-----------|---------|
| focus_data_table.csv.gz    | Full sample in CSV format |
| focus_data_table.sql.gz    | Full sample in SQL format |
| focus_sample.csv           | 1,000 line sample in CSV format |
| focus_sample_10000.csv     | 10,000 line sample in CSV format |
| focus_sample_100000.csv.gz | 100,000 line sample in CSV format |


## Want to contribute

Reach out to [focus@finops.org](mailto:focus@finops.org) if you would like to assist with more sample-data especially for platforms not included in this sample dataset already.

