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


def test_every_score_is_explained(engine):
    score, _, reasons = engine.score(change=DROP, entity_type="mlModel", hops=2,
                                     references_column=True, tier="Tier1", owners=[])
    assert reasons[-1].startswith(f"= {score}")
