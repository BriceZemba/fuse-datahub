"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    gms_url: str = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
    gms_token: str = os.getenv("DATAHUB_GMS_TOKEN", "")
    mutations_enabled: bool = os.getenv("TOOLS_IS_MUTATION_ENABLED", "true").lower() == "true"
    llm_provider: str = os.getenv("FUSE_LLM_PROVIDER", "none")
    hops: int = int(os.getenv("FUSE_HOPS", "3"))
    fail_on: str = os.getenv("FUSE_FAIL_ON", "BREAKING")
    dialect: str = os.getenv("FUSE_DIALECT", "snowflake")
    fixtures_dir: Path = Path(os.getenv("FUSE_FIXTURES", "fixtures"))
    out_dir: Path = Path(os.getenv("FUSE_OUT", "out"))
    # The MCP server logs every GraphQL query it builds at DEBUG, which buries Fuse's
    # own output in a live run. Loguru reads this for its default handler; set
    # FUSE_MCP_LOG_LEVEL=DEBUG to get the raw traffic back when diagnosing.
    mcp_log_level: str = os.getenv("FUSE_MCP_LOG_LEVEL", "WARNING")

    def mcp_env(self) -> dict[str, str]:
        return {
            "DATAHUB_GMS_URL": self.gms_url,
            "DATAHUB_GMS_TOKEN": self.gms_token,
            "TOOLS_IS_MUTATION_ENABLED": "true" if self.mutations_enabled else "false",
            "TOOLS_IS_USER_ENABLED": "true",
            "LOGURU_LEVEL": self.mcp_log_level,
        }


settings = Settings()
