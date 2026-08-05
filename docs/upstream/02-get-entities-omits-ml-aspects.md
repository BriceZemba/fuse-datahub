# Issue draft - `get_entities` returns no ML aspects

**Repository:** `acryldata/mcp-server-datahub`
**Type:** bug / gap

---

**Title:** `get_entities` omits ML aspects, so ML relationships are invisible to agents

### Environment

- DataHub OSS `v1.5.0.6` (quickstart), `is_oss=True`
- `mcp-server-datahub` via `uvx mcp-server-datahub`

### What happens

`get_entities` on an `mlFeature` or `mlModel` returns only identity fields:

```json
[
  {
    "urn": "urn:li:mlFeature:(customer_churn,credit_limit)",
    "name": "credit_limit",
    "description": "Customer credit limit; strongest single churn predictor",
    "relatedDocuments": {"start": 0, "count": 10, "total": 0}
  },
  {
    "urn": "urn:li:mlModel:(urn:li:dataPlatform:mlflow,customer_churn_model,PROD)",
    "name": "customer_churn_model",
    "description": "Gradient-boosted churn classifier. Serving in production.",
    "platform": {"urn": "urn:li:dataPlatform:mlflow", "name": "mlflow"},
    "relatedDocuments": {"start": 0, "count": 10, "total": 0}
  }
]
```

Missing: `MLFeatureProperties.sources`, `MLFeatureTableProperties.mlFeatures`,
`MLModelProperties.mlFeatures`, `.deployments`, `.groups`.

The aspects are intact in GMS - `datahub get --urn ...` returns all of them, and
`DataHubGraph.get_aspect(urn, MLModelPropertiesClass)` reads them fine.

### Expected

`get_entities` projects the entity-type-appropriate aspects, as it already does for
datasets (`ownership`, `glossaryTerms`, `properties`).

### Why it matters

Those fields *are* the ML graph. Without them an agent can list ML entities but cannot
tell which dataset a feature is derived from, which features a model consumes, or where
a model is deployed - so it cannot answer "does this schema change affect a model in
production?", which is the main reason to ask a catalog about ML at all.

Combined with `get_lineage` not traversing `MLFeature.sources`, there is currently **no
path through the MCP surface** from a dataset column to the model that depends on it.

### Workaround

Read the aspects with the typed SDK:

```python
from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
from datahub.metadata.schema_classes import MLFeaturePropertiesClass

graph = DataHubGraph(DatahubClientConfig(server=..., token=...))
graph.get_aspect(urn, MLFeaturePropertiesClass).sources
```

### Repro

Recorded responses:
https://github.com/BriceZemba/fuse-datahub/blob/main/docs/spike-raw/11-ml-entities.json
