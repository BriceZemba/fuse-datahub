import pytest

from fuse.risk.engine import RiskEngine
from fuse.state import Change

DROP = Change(kind="drop_column", file="models/marts/orders.sql", model="orders",
              column="discount_code")
RETYPE_NARROWING = Change(kind="retype_column", file="f.sql", model="orders",
                          column="order_amount", from_type="FLOAT", to_type="INT")
ADD = Change(kind="add_column", file="f.sql", model="orders", column="new_col")


@pytest.fixture
def engine():
    return RiskEngine()


def test_hard_reference_on_a_tier1_dashboard_is_breaking(engine):
    score, severity, reasons = engine.score(
        change=DROP, entity_type="dashboard", hops=1, references_column=True,
        tier="Tier1", owners=["urn:li:corpuser:ana"], recently_queried=True,
    )
    assert severity == "BREAKING"
    assert score >= 60
    assert any("selects the changed column" in r for r in reasons)


def test_ml_model_outranks_a_plain_dataset_at_the_same_distance(engine):
    ml, _, _ = engine.score(change=DROP, entity_type="mlModel", hops=2,
                            references_column=False, owners=["x"])
    dataset, _, _ = engine.score(change=DROP, entity_type="dataset", hops=2,
                                 references_column=False, owners=["x"])
    assert ml > dataset


def test_a_direct_child_carrying_the_column_is_breaking(engine):
    """The commonest real case in the showcase catalog: a mart one hop downstream whose
    own schema has the dropped column. Reporting that as merely RISKY understates it."""
    score, severity, reasons = engine.score(
        change=DROP, entity_type="dataset", hops=1, references_column=False,
        schema_contains_column=True, owners=["urn:li:corpuser:ana"],
    )
    assert severity == "BREAKING"
    assert score >= 60
    assert any("directly from the changed table" in r for r in reasons)


def test_distance_reduces_score(engine):
    near, _, _ = engine.score(change=DROP, entity_type="dataset", hops=1,
                              references_column=True, owners=["x"])
    far, _, _ = engine.score(change=DROP, entity_type="dataset", hops=4,
                             references_column=True, owners=["x"])
    assert far < near


def test_additive_change_is_safe(engine):
    _, severity, _ = engine.score(change=ADD, entity_type="dashboard", hops=1,
                                  references_column=True, tier="Tier1", owners=["x"])
    assert severity == "SAFE"


def test_narrowing_type_change_is_not_discounted(engine):
    narrowing, _, reasons = engine.score(change=RETYPE_NARROWING, entity_type="dataset",
                                         hops=1, references_column=True, owners=["x"])
    widening = RETYPE_NARROWING.model_copy(update={"from_type": "INT", "to_type": "FLOAT"})
    widened, _, _ = engine.score(change=widening, entity_type="dataset", hops=1,
                                 references_column=True, owners=["x"])
    assert narrowing > widened
    assert any("lossy" in r for r in reasons)


def test_unowned_assets_score_higher(engine):
    owned, _, _ = engine.score(change=DROP, entity_type="dataset", hops=1,
                               references_column=True, owners=["urn:li:corpuser:ana"])
    orphan, _, _ = engine.score(change=DROP, entity_type="dataset", hops=1,
                                references_column=True, owners=[])
    assert orphan > owned


def test_evidence_is_ranked_and_only_one_applies(engine):
    """A schema-name hit is an inference; a proven SQL reference is not. The score has
    to reflect that ordering, and the reason must name which evidence fired."""
    proven, _, why_proven = engine.score(
        change=DROP, entity_type="dataset", hops=1, references_column=True, owners=["x"]
    )
    edge, _, _ = engine.score(
        change=DROP, entity_type="dataset", hops=1, references_column=False,
        column_lineage_edge=True, owners=["x"],
    )
    schema, _, why_schema = engine.score(
        change=DROP, entity_type="dataset", hops=1, references_column=False,
        schema_contains_column=True, owners=["x"],
    )
    table_only, _, _ = engine.score(
        change=DROP, entity_type="dataset", hops=1, references_column=False, owners=["x"]
    )

    assert proven > edge > schema > table_only
    assert any("selects the changed column" in r for r in why_proven)
    assert any("field with that name" in r for r in why_schema)
    assert not any("selects the changed column" in r for r in why_schema)


def test_schema_hit_on_a_tier1_dashboard_is_actionable(engine):
    """The common real case: no query history, no column lineage, but the consumer's
    own schema carries the column. That must not come out as SAFE."""
    _, severity, _ = engine.score(
        change=DROP, entity_type="dashboard", hops=1, references_column=False,
        schema_contains_column=True, tier="Tier1", owners=[],
    )
    assert severity == "BREAKING"


def test_every_score_is_explained(engine):
    score, _, reasons = engine.score(change=DROP, entity_type="mlModel", hops=2,
                                     references_column=True, tier="Tier1", owners=[])
    assert reasons[-1].startswith(f"= {score}")
