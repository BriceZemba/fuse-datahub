"""Writes that the MCP mutation tools don't cover, via the DataHub Python SDK.

Used for entity upserts (the ML lineage seed) and for bulk custom properties.
Kept separate from mcp_client so it is obvious in review which write went where.
"""

from __future__ import annotations

from typing import Any

from fuse.config import settings


def client() -> Any:
    from datahub.sdk import DataHubClient

    return DataHubClient(server=settings.gms_url, token=settings.gms_token or None)


def upsert(entity: Any) -> None:
    client().entities.upsert(entity)


def emit_mcps(mcps: Any) -> None:
    client()._emit_mcps(mcps)


# Every entity type Fuse ever scores. A structured property rejects a value on an
# entity type its definition does not list, so this has to be the full set.
PROPERTY_ENTITY_TYPES = (
    "dataset",
    "dashboard",
    "chart",
    "mlFeature",
    "mlFeatureTable",
    "mlModel",
    "mlModelDeployment",
    "mlModelGroup",
)


def ensure_vocabulary(tags: dict[str, str], properties: tuple[tuple[str, str, str], ...]) -> None:
    """Create the tags and structured-property definitions Fuse writes with.

    DataHub refuses to apply a tag whose urn does not exist yet, and refuses a
    structured property that was never defined - in both cases by returning an
    error rather than creating the missing thing. The MCP mutation tools apply
    labels; they do not define them, so the definitions are emitted here.

    Idempotent: emitting the same aspect again is a no-op upsert.
    """
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import (
        StructuredPropertyDefinitionClass,
        TagPropertiesClass,
    )

    mcps: list[Any] = [
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=TagPropertiesClass(name=urn.rsplit(":", 1)[-1], description=description),
        )
        for urn, description in tags.items()
    ]

    for urn, value_type, description in properties:
        qualified_name = urn.rsplit(":", 1)[-1]
        mcps.append(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=StructuredPropertyDefinitionClass(
                    qualifiedName=qualified_name,
                    displayName=qualified_name.split(".")[-1].replace("_", " ").title(),
                    valueType=f"urn:li:dataType:datahub.{value_type}",
                    entityTypes=[
                        f"urn:li:entityType:datahub.{t}" for t in PROPERTY_ENTITY_TYPES
                    ],
                    cardinality="SINGLE",
                    description=description,
                ),
            )
        )

    emit_mcps(mcps)
