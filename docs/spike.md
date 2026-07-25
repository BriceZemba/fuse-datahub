# Day-2 capability spike

Answer these against a live local DataHub **before** finishing `nodes/lineage.py`,
`nodes/resolve.py` and `nodes/writeback.py`. Each answer either confirms a `TODO(spike)`
in the code or changes the design. Record raw response shapes — the normalisers in
`resolve.py` and `lineage.py` are written defensively precisely because these are unknown.

| # | Question | Answer | Consequence |
|---|---|---|---|
| 1 | Does `get_lineage` return column-level edges, or table-level only? | | If table-level only, keep `datahub/graphql.py`; otherwise delete it |
| 2 | Default and maximum hop count for `get_lineage`? | | Sets the `--hops` ceiling |
| 3 | Exact JSON shape of a `search` response (top-level key, entity keys)? | | Pins `resolve._entities` |
| 4 | Exact JSON shape of `get_lineage` (key holding downstream nodes, is degree/hops present)? | | Pins `lineage._nodes` and `_hops` |
| 5 | Does `list_schema_fields` return `fieldPath` and native types? | | Pins `validate.known_columns` and the codegen prompt |
| 6 | Does `get_dataset_queries` return parseable SQL for showcase Snowflake tables? | | Without it, `references_column` degrades to lineage-only evidence |
| 7 | Does `showcase-ecommerce` contain `mlModel` / `mlFeature` entities? | | If not, `demo/seed_ml_lineage.py` is mandatory, not optional |
| 8 | Do `add_tags` / `add_structured_properties` / `update_description` actually write to OSS GMS (check the UI)? | Tools **register** on OSS (`is_oss=True`, "Mutation Tools ENABLED"). Writes still to be confirmed in the UI. | Determines what write-back can promise |
| 9 | Does `save_document` work on OSS, and where does the document appear? | Tool **registers** on OSS ("Save Document ENABLED"). Placement in the UI still to be confirmed. | If unsupported, fall back to a structured property holding the report |
| 10 | Are structured properties usable without pre-registering the property definition? | | May require a one-time `datahub` CLI bootstrap step in SETUP |

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
