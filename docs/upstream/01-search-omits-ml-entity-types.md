# Issue draft — `search` never returns ML entity types

**Repository:** `acryldata/mcp-server-datahub`
**Type:** bug / gap

---

**Title:** `search` does not return MLFeature, MLModel or MLFeatureTable entities

### Environment

- DataHub OSS `v1.5.0.6` (quickstart), `is_oss=True`
- `mcp-server-datahub` via `uvx mcp-server-datahub`
- Catalog: `showcase-ecommerce` datapack plus 11 ML entities emitted with the Python SDK

### What happens

`search` returns datasets, schema fields, charts, dashboards, data jobs and glossary
terms, but never ML entities — not for a keyword matching their name, and not for
`query="*"`.

```python
await call("search", query="*", num_results=200)
# no urn:li:mlFeature:, urn:li:mlModel:, urn:li:mlFeatureTable: in the results
```

The entities exist and are correctly stored:

```bash
datahub get --urn "urn:li:mlModel:(urn:li:dataPlatform:mlflow,customer_churn_model,PROD)"
# returns a full mlModelProperties with deployments, groups, hyperParams
```

And GMS returns them when asked by type:

```bash
curl -s -X POST http://localhost:8080/api/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"{ searchAcrossEntities(input:{query:\"*\",count:50,start:0,types:[MLFEATURE,MLFEATURE_TABLE,MLMODEL,MLMODEL_GROUP]}) { total searchResults { entity { urn } } } }"}'
# {"data":{"searchAcrossEntities":{"total":11, ...}}}
```

### Expected

Either ML entities appear in `search` results, or `search` exposes an entity-type
filter so an agent can ask for them explicitly.

### Why it matters

An agent that can only discover entities through the MCP surface cannot see the ML half
of the catalog at all. It will conclude a feature store does not exist. Working around
it means going outside MCP to GMS GraphQL, which defeats the point of the MCP server as
a complete agent interface.

### Workaround

Query `searchAcrossEntities` with an explicit `types` list, then hydrate through
`get_entities`. See also the companion issue on `get_entities` not projecting ML
aspects — both are needed for the workaround to be useful.

### Repro

Minimal script and recorded responses:
https://github.com/BriceZemba/fuse-datahub/blob/main/docs/spike.md
