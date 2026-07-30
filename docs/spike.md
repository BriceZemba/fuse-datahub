# Day-2 capability spike

Answer these against a live local DataHub **before** finishing `nodes/lineage.py`,
`nodes/resolve.py` and `nodes/writeback.py`. Each answer either confirms a `TODO(spike)`
in the code or changes the design. Record raw response shapes — the normalisers in
`resolve.py` and `lineage.py` are written defensively precisely because these are unknown.

| # | Question | Answer | Consequence |
|---|---|---|---|
| 1 | Does `get_lineage` return column-level edges, or table-level only? | **`get_lineage` takes a `column` argument natively.** | `datahub/graphql.py` deleted — the fallback was dead weight |
| 2 | Default and maximum hop count for `get_lineage`? | `max_hops` argument; results carry `degree` per hit | `--hops` maps straight onto `max_hops` |
| 3 | Exact JSON shape of a `search` response? | `{"searchResults": [{"entity": {"urn", "properties": {"name"}}}], "total", "facets"}` — mixes datasets, schema fields, charts, data jobs, glossary terms | `resolve` filters on the `urn:li:dataset:` prefix before ranking |
| 4 | Exact JSON shape of `get_lineage`? | `{"downstreams": {"searchResults": [{"entity": {...}, "degree": N}], "total", "facets"}}` — **`degree` sits on the result, not the entity**; `type` is `SCREAMING_SNAKE` | `shapes.lineage_results` + `shapes.entity_type` |
| 5 | Does `list_schema_fields` return `fieldPath` and native types? | Yes: `{"urn", "fields": [{"fieldPath", "nativeDataType", "nullable", "editedGlossaryTerms"}], "totalFields"}` | `validate.known_columns` and the codegen prompt read `fieldPath` |
| 6 | Does `get_dataset_queries` return parseable SQL for showcase tables? | **No — `{"start": 0, "total": 0, "count": 10}`.** The datapack ships no query history | `references_column` cannot be the only evidence; column-lineage edges carry the weight, and the report says which applied |
| 7 | Does `showcase-ecommerce` contain `mlModel` / `mlFeature` entities? | No | `demo/seed_ml_lineage.py` is mandatory, not optional |
| 8 | Do `add_tags` / `add_structured_properties` / `update_description` actually write to OSS GMS (check the UI)? | Tools **register** on OSS (`is_oss=True`, "Mutation Tools ENABLED"). Writes still to be confirmed in the UI. | Determines what write-back can promise |
| 9 | Does `save_document` work on OSS, and where does the document appear? | Tool **registers** on OSS ("Save Document ENABLED"). Placement in the UI still to be confirmed. | If unsupported, fall back to a structured property holding the report |
| 10 | Are structured properties usable without pre-registering the property definition? | | May require a one-time `datahub` CLI bootstrap step in SETUP |

## Write-back, confirmed on a live instance

Verified 2026-07-30 against DataHub 1.5.0.6 OSS, non-dry-run: **9 assets tagged, 9 with
structured properties, 1 column description annotated**, all visible in the UI. The
column note shows up in search as *"Column description: See the Fuse impact report"*.

Two parameter details worth recording:

- `save_document(document_type=...)` accepts only `Insight`, `Decision`, `FAQ`,
  `Analysis`, `Summary`, `Recommendation`, `Note`, `Context`. `Overview` — which *is* a
  valid document **subtype** in the showcase datapack — fails validation. Fuse uses
  `Analysis`.
- `add_structured_properties` works on OSS without pre-registering property
  definitions, contrary to the initial assumption.

## Reaching ML entities: three separate obstacles

Resolved 2026-07-30. Each of these was a distinct dead end, and all three had to be
cleared before a column change could be traced to a deployed model.

1. **`get_lineage` covers ML entities only partially, and says nothing about columns.**
   Measured twice, and the second measurement corrected the first.

   Immediately after seeding, downstream of the dbt `customers` dataset returned 30
   entities and **zero** ML. Re-measured later against the same dataset, lineage
   returned **4 `mlFeature`s and the `mlModel`** — but still **not** the
   `mlFeatureTable`, the `mlModelDeployment` or the `mlModelGroup`. The likely
   explanation for the change is indexing catching up.

   So the honest claim is narrower than "ML is invisible to lineage", and still worth
   making:
   - the **deployment** — the thing actually serving traffic — is not returned;
   - lineage never says **which feature**, and therefore **which column**, is the one
     that breaks. It returns four features whether you dropped one of them or none.

   Fuse reads `MLFeature.sources` directly, so it can name the feature built on the
   dropped column and separate it from its siblings. The report marks which entities
   lineage returned and which came only from the aspects.
2. **Keyword `search` never returns ML entity types**, so discovery by search finds
   nothing. Typed GraphQL works:
   `searchAcrossEntities(types: [MLFEATURE, MLFEATURE_TABLE, MLMODEL, MLMODEL_GROUP])`
   returns all 11. Note `MLMODEL_DEPLOYMENT` is **not** a valid `EntityType` — including
   it fails validation for the entire query. Deployments come from
   `MLModelProperties.deployments` instead.
3. **`get_entities` does not project ML aspects.** For an `mlFeature` it returns only
   `urn`, `name`, `description` and `relatedDocuments` — no `sources`, no `mlFeatures`,
   no `deployments` (see `docs/spike-raw/11-ml-entities.json`). The aspects are intact in
   GMS, so Fuse reads them with `DataHubGraph.get_aspect` using the same generated
   classes the seed emitted.

The resulting design: **GraphQL for discovery, typed SDK for hydration, MCP for
everything else.** Worth reporting upstream — points 2 and 3 look like gaps in the MCP
server's coverage rather than intentional limits, and they are good material for the
hackathon feedback survey.

## Previously open (kept for the record)

Status as of 2026-07-25. This is the one unproven claim in the project and it carries
the Production ML Agents challenge, so it is worth finishing properly.

**Established:**

- `demo/seed_ml_lineage.py` emits successfully — 11 aspects, no errors.
- The entities are really in GMS. `datahub get --urn "urn:li:mlModel:(urn:li:dataPlatform:mlflow,customer_churn_model,PROD)"`
  returns a full `mlModelProperties` with `deployments`, `groups`, `hyperParams` and
  the seeded custom properties.
- **`get_lineage` does not traverse `MLFeature.sources`.** Downstream of the dbt
  `customers` dataset: 30 entities, zero ML — while four features name that dataset
  as their source. The dependency is in the catalog; lineage does not expose it.
- Keyword `search` never returns ML entity types, so discovery by search finds
  nothing (`0 ML entities in the catalog`).

**Untested:** typed GraphQL discovery — `searchAcrossEntities(types: [MLFEATURE,
MLFEATURE_TABLE, MLMODEL, MLMODEL_GROUP, MLMODEL_DEPLOYMENT])`, implemented in
`datahub/ml_graph.py::_urns_via_graphql`. The probe that prints its result was added
but its output has not been read yet.

**Next step:** run and read the middle of the output, not the tail:

```bash
fuse spike --urn "urn:li:dataset:(urn:li:dataPlatform:dbt,b2fd91.order_entry_db.order_entry.customers,PROD)" 2>/dev/null | grep -A 25 "ML URNs via GraphQL"
```

Three outcomes and their fixes:

1. GraphQL returns URNs → discovery works; check `get_entities` returns `sources` in a
   shape `shapes.ml_feature_sources` reads, and the chain completes.
2. GraphQL returns nothing → the entity-type names in the query are wrong for this
   server version. Introspect: `{"query": "{ __type(name: \"EntityType\") { enumValues { name } } }"}`
   against `/api/graphql`.
3. GraphQL errors → read `payload["errors"]`; `_urns_via_graphql` currently swallows
   exceptions and returns `[]`, which hides the reason. Log it before trusting the result.

Worth knowing: the search-based fallback is not the answer, and neither is generic
lineage. Reading the ML aspects directly is the design, and the gap it works around is
the project's strongest claim.

## The finding that mattered most

Every MCP tool answers with **content blocks**, not JSON:

```json
[{"id": "lc_81644a80-...", "type": "text", "text": "{\"searchResults\": [...]}"}]
```

The payload is a JSON *string* one level down. Reading the wrapper returns nothing and
looks exactly like an empty catalog — which is what "first URN from search: NONE FOUND"
actually was. `mcp_client._coerce` now unwraps it, and `tests/test_shapes.py` reads
these recordings directly so a server-side change fails a test instead of silently
emptying the graph.

## Confirmed from the MCP server's own startup log (2026-07-25, local OSS quickstart)

```
mcp_server_datahub.mcp_server:register_all_tools - Registering MCP tools (is_oss=True)
mcp_server_datahub.mcp_server:register_mutation_tools - Mutation Tools ENABLED MCP Server.
mcp_server_datahub.mcp_server:register_mutation_tools - Save Document ENABLED - registering save_document tool
mcp_server_datahub.mcp_server:register_user_tools - User Tools ENABLED MCP Server.
mcp_server_datahub.mcp_server:register_data_quality_tools - Data Quality Tools DISABLED MCP Server.
```

Consequences already applied:

- Write-back can rely on tags, descriptions, structured properties and `save_document` on **open-source** DataHub — no Cloud dependency.
- There is a **data quality tool group**, disabled here. Worth one line in the README limitations rather than a silent omission.
- The MCP server connects to GMS at startup and exits with a full stack trace if it can't, which is why `DataHubMCP.__aenter__` probes `/config` first and raises `GMSUnreachable` instead.

## Raw responses

Paste trimmed real responses here — they become the first entries in `fixtures/`.

```json
```
