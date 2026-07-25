"""Seed an end-to-end ML lineage chain into a local DataHub.

    customer_features (dataset)
        -> customer_churn_features (MLFeatureTable + MLFeatures)
        -> churn_model v3 (MLModel in an MLModelGroup)
        -> production deployment

Scenario 03 drops a column that feeds one of those features; Fuse then traces the
change all the way to a deployed model. The `showcase-ecommerce` datapack gives us a
rich dataset graph but no ML entities, so we create that half ourselves.

    python demo/seed_ml_lineage.py --check
    python demo/seed_ml_lineage.py
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

FEATURES = [
    ("order_count", "Number of orders placed by the customer"),
    ("lifetime_value", "Total revenue attributed to the customer"),
    ("discounted_orders", "Orders that used a discount code"),
    ("days_since_last_order", "Recency signal, strongest predictor in the churn model"),
]

MODEL_ID = "customer_churn_model"
GROUP_ID = "customer_churn_models"
FEATURE_TABLE_ID = "customer_churn_features"
PLATFORM = "mlflow"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.getenv("DATAHUB_GMS_URL", "http://localhost:8080"))
    parser.add_argument("--token", default=os.getenv("DATAHUB_GMS_TOKEN", ""))
    parser.add_argument(
        "--upstream",
        default=(
            "urn:li:dataset:(urn:li:dataPlatform:snowflake,"
            "shop.marts.customer_features,PROD)"
        ),
        help="Dataset URN the feature table reads from",
    )
    parser.add_argument("--check", action="store_true", help="Print what would be created")
    args = parser.parse_args()

    if args.check:
        print("Would create:")
        print(f"  MLFeatureTable {FEATURE_TABLE_ID} with {len(FEATURES)} features")
        print(f"  MLModelGroup   {GROUP_ID}")
        print(f"  MLModel        {MODEL_ID} v3 + training run + prod deployment")
        print(f"  upstream       {args.upstream}")
        return

    from datahub.metadata.schema_classes import (
        MLHyperParamClass,
        MLMetricClass,
        MLTrainingRunPropertiesClass,
    )
    from datahub.sdk import DataHubClient, MLModel, MLModelGroup

    client = DataHubClient(server=args.server, token=args.token or None)

    group = MLModelGroup(
        id=GROUP_ID,
        platform=PLATFORM,
        name="Customer Churn Models",
        description="Churn scoring models served to the retention service.",
        custom_properties={"team": "growth", "seeded_by": "fuse-demo"},
    )
    client._emit_mcps(group.as_mcps())

    model = MLModel(
        id=MODEL_ID,
        platform=PLATFORM,
        name="Customer Churn Model v3",
        version="3",
        description="Gradient-boosted churn classifier. Serving in production.",
        hyper_params={"learning_rate": "0.05", "max_depth": "6"},
        training_metrics={"auc": "0.87", "recall_at_10": "0.42"},
        custom_properties={
            "deployment": "prod-retention-service",
            "deployed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seeded_by": "fuse-demo",
        },
    )
    model.add_group(group.urn)
    client._emit_mcps(model.as_mcps())

    run_id = f"{MODEL_ID}_run_2026_07"
    client.create_training_run(
        run_id=run_id,
        training_run_properties=MLTrainingRunPropertiesClass(
            trainingMetrics=[MLMetricClass(name="auc", value="0.87")],
            hyperParams=[MLHyperParamClass(name="learning_rate", value="0.05")],
        ),
    )
    client.add_input_datasets_to_run(run_urn=_run_urn(run_id), dataset_urns=[args.upstream])

    print(f"Seeded ML lineage. Open {args.server.replace('8080', '9002')} and search "
          f"'{MODEL_ID}' to see the chain.")
    print("Features created:", ", ".join(name for name, _ in FEATURES))


def _run_urn(run_id: str) -> str:
    return f"urn:li:dataProcessInstance:{run_id}"


if __name__ == "__main__":
    main()
