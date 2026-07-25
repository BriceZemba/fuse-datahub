"""Seed an end-to-end ML lineage chain into a local DataHub.

    customer_features (dataset, already in the catalog)
        -> 4x MLFeature          (each declares the dataset as its source)
        -> customer_churn_features (MLFeatureTable)
        -> training run           (DataProcessInstance, subtype MLFLOW_TRAINING_RUN)
        -> customer_churn_model   (MLModel in an MLModelGroup)
        -> prod deployment        (MLModelDeployment)

Scenario 03 drops a column feeding one of those features, so Fuse traces a dbt diff
all the way to a deployed model. The showcase-ecommerce datapack gives a rich dataset
graph but no ML entities, so this builds that half.

    python demo/seed_ml_lineage.py --check    # build every aspect, emit nothing
    python demo/seed_ml_lineage.py            # emit to DATAHUB_GMS_URL
"""

from __future__ import annotations

import argparse
import os
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore", category=UserWarning)

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DataProcessInstanceInputClass,
    DataProcessInstancePropertiesClass,
    DeploymentStatusClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLHyperParamClass,
    MLMetricClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
    MLTrainingRunPropertiesClass,
    SubTypesClass,
    VersionTagClass,
)
from datahub.metadata.urns import (
    DataProcessInstanceUrn,
    MlFeatureTableUrn,
    MlFeatureUrn,
    MlModelDeploymentUrn,
    MlModelGroupUrn,
    MlModelUrn,
)

NAMESPACE = "customer_churn"
FEATURE_PLATFORM = "feast"
MODEL_PLATFORM = "mlflow"
FEATURE_TABLE = "customer_churn_features"
MODEL_ID = "customer_churn_model"
GROUP_ID = "customer_churn_models"
RUN_ID = "customer_churn_run_2026_07"
DEPLOYMENT_ID = "prod-retention-service"
ACTOR = "urn:li:corpuser:datahub"

# (feature name, description, DataHub feature data type)
#
# Named after real columns of `order_entry.customers` in the showcase catalog, so the
# lineage Fuse traces is literal: drop `credit_limit` upstream and the feature that
# reads it — and the model serving on it — are genuinely affected.
FEATURES: list[tuple[str, str, str]] = [
    ("credit_limit", "Customer credit limit; strongest single churn predictor", "CONTINUOUS"),
    ("customer_class", "Segment the customer belongs to", "NOMINAL"),
    ("customer_since", "Tenure, derived from the signup date", "TIME"),
    ("country_id", "Geography, used for regional churn baselines", "NOMINAL"),
]


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def audit() -> AuditStampClass:
    return AuditStampClass(time=now_ms(), actor=ACTOR)


def build_mcps(upstream_dataset: str) -> list[MetadataChangeProposalWrapper]:
    """Every aspect, in dependency order. Pure construction — nothing is emitted here."""
    feature_urns = [str(MlFeatureUrn(NAMESPACE, name)) for name, _, _ in FEATURES]
    table_urn = str(MlFeatureTableUrn(FEATURE_PLATFORM, FEATURE_TABLE))
    run_urn = str(DataProcessInstanceUrn(RUN_ID))
    model_urn = str(MlModelUrn(MODEL_PLATFORM, MODEL_ID))
    group_urn = str(MlModelGroupUrn(MODEL_PLATFORM, GROUP_ID))
    deployment_urn = str(MlModelDeploymentUrn(MODEL_PLATFORM, DEPLOYMENT_ID))

    mcps: list[MetadataChangeProposalWrapper] = []

    # Features. `sources` is the edge Fuse follows from the changed dataset column.
    for (_name, description, data_type), urn in zip(FEATURES, feature_urns, strict=True):
        mcps.append(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=MLFeaturePropertiesClass(
                    description=description,
                    dataType=data_type,
                    sources=[upstream_dataset],
                ),
            )
        )

    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=table_urn,
            aspect=MLFeatureTablePropertiesClass(
                description="Churn features served to the retention model.",
                mlFeatures=feature_urns,
                customProperties={"seeded_by": "fuse-demo"},
            ),
        )
    )

    # Training run, with the source dataset as an explicit input.
    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstancePropertiesClass(
                name=f"{MODEL_ID} training run",
                created=audit(),
                customProperties={"seeded_by": "fuse-demo"},
            ),
        )
    )
    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=SubTypesClass(typeNames=["MLFLOW_TRAINING_RUN"]),
        )
    )
    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=MLTrainingRunPropertiesClass(
                id=RUN_ID,
                hyperParams=[MLHyperParamClass(name="learning_rate", value="0.05")],
                trainingMetrics=[MLMetricClass(name="auc", value="0.87")],
            ),
        )
    )
    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=run_urn,
            aspect=DataProcessInstanceInputClass(inputs=[upstream_dataset]),
        )
    )

    # The model: one complete properties aspect so nothing written here is clobbered.
    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=model_urn,
            aspect=MLModelPropertiesClass(
                name="Customer Churn Model v3",
                description="Gradient-boosted churn classifier. Serving in production.",
                version=VersionTagClass(versionTag="3"),
                type="classification",
                hyperParams=[
                    MLHyperParamClass(name="learning_rate", value="0.05"),
                    MLHyperParamClass(name="max_depth", value="6"),
                ],
                trainingMetrics=[
                    MLMetricClass(name="auc", value="0.87"),
                    MLMetricClass(name="recall_at_10", value="0.42"),
                ],
                mlFeatures=feature_urns,
                groups=[group_urn],
                trainingJobs=[run_urn],
                deployments=[deployment_urn],
                customProperties={"team": "growth", "seeded_by": "fuse-demo"},
            ),
        )
    )

    mcps.append(
        MetadataChangeProposalWrapper(
            entityUrn=deployment_urn,
            aspect=MLModelDeploymentPropertiesClass(
                description="Retention service, serving live traffic.",
                status=DeploymentStatusClass.IN_SERVICE,
                createdAt=now_ms(),
                customProperties={"seeded_by": "fuse-demo"},
            ),
        )
    )
    return mcps


# Warehouse and transformation platforms hold the tables a model trains on; BI
# platforms sit downstream of them. Order matches fuse.nodes.resolve.PLATFORM_RANK on
# purpose: the seed and the agent must land on the same URN, or the features hang off
# a table the agent never looks at.
SOURCE_PLATFORMS = ("dbt", "snowflake", "bigquery", "redshift", "postgres", "spark", "s3")


def _dataset_candidates(client, query: str) -> list[tuple[int, str]]:
    scored: list[tuple[int, str]] = []
    for urn in client.search.get_urns(query=query):
        text = str(urn)
        if not text.startswith("urn:li:dataset:"):
            continue
        platform = text.split("dataPlatform:")[-1].split(",")[0]
        table = text.split(",")[1].split(".")[-1] if "," in text else text
        score = 0
        if platform in SOURCE_PLATFORMS:
            score += 10 - SOURCE_PLATFORMS.index(platform)
        if query.lower() in table.lower():
            score += 5
        scored.append((score, text))
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored


def resolve_upstream(client, explicit: str | None, query: str, show: bool = False) -> str:
    if explicit:
        return explicit

    candidates = _dataset_candidates(client, query)
    if show:
        print(f"candidates for {query!r}:")
        for score, urn in candidates[:20]:
            print(f"  {score:>3}  {urn}")
        raise SystemExit(0)

    if not candidates:
        raise SystemExit(
            f"No dataset matched {query!r}. Load the catalog first "
            "(datahub datapack load showcase-ecommerce) or pass --upstream explicitly."
        )
    return candidates[0][1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:8080"))
    parser.add_argument("--token", default=os.getenv("DATAHUB_GMS_TOKEN", ""))
    parser.add_argument("--upstream", default=None, help="Dataset URN the features read from")
    # Defaults to the table demo/dbt-shop/models/marts/customers.sql resolves to, so
    # scenario 03 traces from the diff into the features seeded here.
    parser.add_argument("--query", default="customers", help="Search term used to find it")
    parser.add_argument("--check", action="store_true", help="Build every aspect, emit nothing")
    parser.add_argument("--list", action="store_true", help="Print upstream candidates and exit")
    args = parser.parse_args()

    if args.check:
        mcps = build_mcps("urn:li:dataset:(urn:li:dataPlatform:snowflake,demo.customers,PROD)")
        print(f"built {len(mcps)} aspects, nothing emitted:")
        for mcp in mcps:
            # Serialise here too: an invalid enum only fails at this step, and finding
            # that out mid-emit leaves the catalog half-seeded.
            mcp.to_obj()
            print(f"  {mcp.aspectName:<35} {mcp.entityUrn}")
        print("all aspects serialised successfully")
        return

    from datahub.emitter.rest_emitter import DatahubRestEmitter
    from datahub.sdk import DataHubClient, MLModelGroup

    client = DataHubClient(server=args.server, token=args.token or None)
    upstream = resolve_upstream(client, args.upstream, args.query, show=args.list)
    print(f"upstream dataset: {upstream}")

    client.entities.upsert(
        MLModelGroup(
            id=GROUP_ID,
            platform=MODEL_PLATFORM,
            name="Customer Churn Models",
            description="Churn scoring models served to the retention service.",
            custom_properties={"team": "growth", "seeded_by": "fuse-demo"},
        )
    )

    emitter = DatahubRestEmitter(gms_server=args.server, token=args.token or None)
    mcps = build_mcps(upstream)
    for mcp in mcps:
        emitter.emit(mcp)
    emitter.flush()

    ui = args.server.replace("8080", "9002")
    print(f"emitted {len(mcps)} aspects across features, feature table, run, model, deployment")
    print(f"open {ui} and search '{MODEL_ID}' to see the chain")


if __name__ == "__main__":
    main()
