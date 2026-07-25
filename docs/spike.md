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
