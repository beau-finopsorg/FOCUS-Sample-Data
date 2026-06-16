"""Realistic per-provider value profiles.

These supply believable, internally consistent values (service names mapped to a
single ServiceCategory, regions, SKUs, units) so generated samples resemble the
anonymised real-world data in the base repository rather than random noise.

Each ServiceName maps to exactly one ServiceCategory, which satisfies the FOCUS
"one ServiceName -> one ServiceCategory" cardinality requirement by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# (ServiceName, ServiceCategory, ServiceSubcategory, ResourceType, default ConsumedUnit)
ServiceDef = Tuple[str, str, str, str, str]


@dataclass
class Provider:
    key: str
    provider_name: str            # ProviderName / PublisherName / InvoiceIssuerName
    invoice_issuer: str
    billing_account_id: str
    billing_account_name: str
    currency: str
    regions: List[Tuple[str, str]]                # (RegionId, RegionName)
    services: List[ServiceDef]
    sub_accounts: List[Tuple[str, str]] = field(default_factory=list)  # (id, name)
    availability_zones: List[str] = field(default_factory=list)

    def region(self, rng):
        return rng.choice(self.regions)

    def service(self, rng) -> ServiceDef:
        return rng.choice(self.services)

    def sub_account(self, rng):
        return rng.choice(self.sub_accounts) if self.sub_accounts else (None, None)


# ServiceCategory values are drawn from the FOCUS allowed set.
_AWS = Provider(
    key="aws",
    provider_name="AWS",
    invoice_issuer="Amazon Web Services, Inc.",
    billing_account_id="123456789012",
    billing_account_name="SunBird",
    currency="USD",
    regions=[("us-east-1", "US East (N. Virginia)"), ("us-west-2", "US West (Oregon)"),
             ("eu-west-1", "Europe (Ireland)"), ("ap-southeast-2", "Asia Pacific (Sydney)")],
    availability_zones=["us-east-1a", "us-west-2b", "eu-west-1c", "ap-southeast-2a"],
    sub_accounts=[("517389287820", "Atlas Nimbus"), ("438839167390", "Zenith Eclipse"),
                  ("663626350770", "Zenith Apollo")],
    services=[
        ("Amazon Elastic Compute Cloud", "Compute", "Virtual Machines", "Virtual Machine", "Hours"),
        ("Amazon Simple Storage Service", "Storage", "Object Storage", "Bucket", "GB"),
        ("Amazon Relational Database Service", "Databases", "Relational Databases", "Database Instance", "Hours"),
        ("Amazon Simple Queue Service", "Integration", "Messaging", "Queue", "Requests"),
        ("Elastic Load Balancing", "Networking", "Application Networking", "Load Balancer", "LCU-Hours"),
        ("AWS Lambda", "Compute", "Serverless Compute", "Function", "Requests"),
    ],
)

_AZURE = Provider(
    key="azure",
    provider_name="Microsoft",
    invoice_issuer="Microsoft Corporation",
    billing_account_id="8a93b2c1-1234-4abc-9def-0123456789ab",
    billing_account_name="Contoso Cloud",
    currency="USD",
    regions=[("eastus", "East US"), ("westeurope", "West Europe"),
             ("southeastasia", "Southeast Asia"), ("uksouth", "UK South")],
    availability_zones=["eastus-1", "westeurope-2", "uksouth-1"],
    sub_accounts=[("sub-9a1f", "Production"), ("sub-2b7c", "Staging"), ("sub-4d3e", "Sandbox")],
    services=[
        ("Virtual Machines", "Compute", "Virtual Machines", "Virtual Machine", "Hours"),
        ("Azure Blob Storage", "Storage", "Object Storage", "Storage Account", "GB"),
        ("Azure SQL Database", "Databases", "Relational Databases", "SQL Database", "Hours"),
        ("Azure Kubernetes Service", "Compute", "Containers", "Cluster", "Hours"),
        ("Azure Functions", "Compute", "Serverless Compute", "Function App", "Executions"),
        ("Azure Load Balancer", "Networking", "Application Networking", "Load Balancer", "Hours"),
    ],
)

_GCP = Provider(
    key="gcp",
    provider_name="Google",
    invoice_issuer="Google LLC",
    billing_account_id="01ABCD-2345EF-6789GH",
    billing_account_name="Helios Labs",
    currency="USD",
    regions=[("us-central1", "Iowa"), ("europe-west1", "Belgium"),
             ("asia-southeast1", "Singapore"), ("us-east4", "Northern Virginia")],
    availability_zones=["us-central1-a", "europe-west1-b", "asia-southeast1-c"],
    sub_accounts=[("proj-helios-prod", "helios-prod"), ("proj-helios-dev", "helios-dev")],
    services=[
        ("Compute Engine", "Compute", "Virtual Machines", "VM Instance", "Hours"),
        ("Cloud Storage", "Storage", "Object Storage", "Bucket", "GiB"),
        ("Cloud SQL", "Databases", "Relational Databases", "Database Instance", "Hours"),
        ("BigQuery", "Analytics", "Data Warehouses", "Dataset", "GiB"),
        ("Cloud Functions", "Compute", "Serverless Compute", "Function", "Invocations"),
        ("Cloud Load Balancing", "Networking", "Application Networking", "Forwarding Rule", "Hours"),
    ],
)

_ORACLE = Provider(
    key="oracle",
    provider_name="Oracle",
    invoice_issuer="Oracle Corporation",
    billing_account_id="ocid1.tenancy.oc1..aaaa1234",
    billing_account_name="Meridian OCI",
    currency="USD",
    regions=[("us-ashburn-1", "US East (Ashburn)"), ("uk-london-1", "UK South (London)"),
             ("ap-sydney-1", "Australia East (Sydney)")],
    availability_zones=["us-ashburn-1-AD-1", "uk-london-1-AD-2"],
    sub_accounts=[("ocid1.compartment.oc1..prod", "production"),
                  ("ocid1.compartment.oc1..dev", "development")],
    services=[
        ("Oracle Compute", "Compute", "Virtual Machines", "Instance", "Hours"),
        ("Oracle Object Storage", "Storage", "Object Storage", "Bucket", "GB"),
        ("Oracle Autonomous Database", "Databases", "Relational Databases", "Database", "Hours"),
        ("Oracle Functions", "Compute", "Serverless Compute", "Function", "Invocations"),
        ("Oracle Load Balancer", "Networking", "Application Networking", "Load Balancer", "Hours"),
    ],
)

PROVIDERS: Dict[str, Provider] = {p.key: p for p in (_AWS, _AZURE, _GCP, _ORACLE)}

# Tag key pools used to synthesise the Tags JSON object.
TAG_KEYS = ["application", "environment", "business_unit", "team", "cost_center", "owner"]
TAG_VALUES = {
    "application": ["BrightLensMatrix", "BrightSourceCore", "AtlasPortal", "NimbusAPI"],
    "environment": ["prod", "dev", "staging", "qa"],
    "business_unit": ["ViennaAI", "MarseilleSRE", "OsloData", "LisbonOps"],
    "team": ["platform", "payments", "growth", "infra"],
    "cost_center": ["CC-1001", "CC-2042", "CC-3090"],
    "owner": ["a.lovelace", "g.hopper", "k.johnson", "a.turing"],
}
