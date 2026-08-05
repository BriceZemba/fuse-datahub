# Upstream findings

Three reproducible gaps found while building Fuse against DataHub OSS `v1.5.0.6`. Each
one blocked a real feature, each has a minimal reproduction, and each is written up here
before being filed so the measurement travels with the report.

Together they mean there is currently no path **through the MCP surface alone** from a
dataset column to the ML model that depends on it - which is why Fuse reaches outside it
for two specific things, documented in [../spike.md](../spike.md).

| # | Finding | Repository | Filed |
|---|---|---|---|
| 1 | [`search` never returns ML entity types](01-search-omits-ml-entity-types.md) | `acryldata/mcp-server-datahub` | _pending_ |
| 2 | [`get_entities` omits ML aspects](02-get-entities-omits-ml-aspects.md) | `acryldata/mcp-server-datahub` | _pending_ |
| 3 | [`MLMODEL_DEPLOYMENT` is not a valid `EntityType`](03-mlmodel-deployment-not-searchable.md) | `datahub-project/datahub` | _pending_ |

Replace _pending_ with the issue URL once filed.
