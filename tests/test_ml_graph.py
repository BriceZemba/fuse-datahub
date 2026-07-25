"""The ML traversal exists because `get_lineage` does not cover it.

Verified against a live DataHub 1.5.0.6: a dataset with four MLFeatures derived from
it returned thirty downstream entities through `get_lineage`, none of them ML. These
tests pin the aspect-reading behaviour that replaces it.
"""

from __future__ import annotations

from fuse.datahub import ml_graph, shapes

DATASET = "urn:li:dataset:(urn:li:dataPlatform:dbt,db.schema.customers,PROD)"
OTHER = "urn:li:dataset:(urn:li:dataPlatform:dbt,db.schema.orders,PROD)"

FEATURE = "urn:li:mlFeature:(customer_churn,credit_limit)"
UNRELATED_FEATURE = "urn:li:mlFeature:(other,unrelated)"
TABLE = "urn:li:mlFeatureTable:(urn:li:dataPlatform:feast,customer_churn_features)"
MODEL = "urn:li:mlModel:(urn:li:dataPlatform:mlflow,customer_churn_model,PROD)"
DEPLOYMENT = "urn:li:mlModelDeployment:(urn:li:dataPlatform:mlflow,prod,PROD)"

CATALOG = [
    {"urn": FEATURE, "properties": {"sources": [DATASET], "description": "credit limit"}},
    {"urn": UNRELATED_FEATURE, "properties": {"sources": [OTHER]}},
    {"urn": TABLE, "properties": {"mlFeatures": [FEATURE, UNRELATED_FEATURE]}},
    {"urn": MODEL, "properties": {"mlFeatures": [FEATURE], "deployments": [DEPLOYMENT]}},
    {"urn": DEPLOYMENT, "properties": {"description": "prod"}},
]


def test_sources_are_read_from_the_properties_aspect():
    assert shapes.ml_feature_sources(CATALOG[0]) == [DATASET]


def test_sources_are_also_read_when_flat():
    assert shapes.ml_feature_sources({"urn": FEATURE, "sources": [DATASET]}) == [DATASET]


def test_a_column_reaches_the_deployed_model():
    found = {urn: hops for urn, hops in
             ((e["urn"], h) for e, h in ml_graph.dependents_of(DATASET, CATALOG))}
    assert found[FEATURE] == 1
    assert found[TABLE] == 2
    assert found[MODEL] == 2
    assert found[DEPLOYMENT] == 3


def test_unrelated_features_are_not_dragged_in():
    found = {e["urn"] for e, _ in ml_graph.dependents_of(DATASET, CATALOG)}
    assert UNRELATED_FEATURE not in found


def test_a_dataset_with_no_features_has_no_ml_impact():
    unrelated = "urn:li:dataset:(urn:li:dataPlatform:dbt,db.schema.nothing,PROD)"
    assert ml_graph.dependents_of(unrelated, CATALOG) == []


def test_ml_entity_types_are_recognised_from_their_urns():
    assert shapes.entity_type({"urn": FEATURE}) == "mlFeature"
    assert shapes.entity_type({"urn": MODEL}) == "mlModel"
    assert shapes.entity_type({"urn": DEPLOYMENT}) == "mlModelDeployment"
