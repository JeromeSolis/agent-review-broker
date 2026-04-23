from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentRole(StrEnum):
    BROKER = "broker"
    SCOUT = "scout"
    MARKETER = "marketer"


class LLMMode(StrEnum):
    LOCAL = "local"
    FRONTIER = "frontier"
    AUTO = "auto"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    agent_role: AgentRole = AgentRole.BROKER
    agent_id: str = ""

    koala_mcp_url: str = "https://koala.science/mcp"
    koala_api_key: str = ""
    openreview_id: str = ""

    llm_mode: LLMMode = LLMMode.AUTO
    llm_kill_switch_to_local: bool = False

    anthropic_api_key: str = ""
    frontier_model: str = "claude-sonnet-4-6"

    local_llm_base_url: str = "http://localhost:8000/v1"
    local_llm_api_key: str = "not-used"
    local_model: str = "meta-llama/Llama-3.3-70B-Instruct"

    db_path: Path = Field(default=Path("./data/broker.db"))
    trajectory_dir: Path = Field(default=Path("./trajectories"))

    log_level: str = "INFO"


settings = Settings()
