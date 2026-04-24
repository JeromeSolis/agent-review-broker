from enum import StrEnum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute root of this repo. We need it as a literal so git_helper can
# resolve reasoning-file paths regardless of where the agent is launched.
REPO_ROOT = Path(__file__).resolve().parents[2]


class LLMMode(StrEnum):
    LOCAL = "local"
    FRONTIER = "frontier"
    AUTO = "auto"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Which agent's config directory to load. Chooses:
    #   agent_configs/<agent_name>/system_prompt.md
    #   agent_configs/<agent_name>/.api_key
    #   agent_configs/<agent_name>/config.json
    agent_name: str = "broker"

    # Filled at runtime from agent_configs/<agent_name>/.api_key. We also
    # accept COALESCENCE_API_KEY from env for parity with the reference repo.
    koala_api_key: str = ""
    koala_base_url: str = "https://koala.science"

    openreview_id: str = ""  # cosmetic: echoed into trajectory logs
    github_repo_url: str = "https://github.com/JeromeSolis/agent-review-broker"

    # Frontier (Anthropic) — drives the agent loop.
    anthropic_api_key: str = ""
    frontier_model: str = "claude-sonnet-4-6"

    # Local (DGX Ollama) — used by internal tools for bulk paper scoring.
    llm_mode: LLMMode = LLMMode.AUTO
    llm_kill_switch_to_local: bool = False
    local_llm_base_url: str = "http://promaxgb10-f285.local:11434/v1"
    local_llm_api_key: str = "ollama"
    local_model: str = "gemma4:31b"

    # Runtime caps.
    session_timeout_s: int = 900  # per-invocation; supervisor restarts
    max_turns: int = 2000  # hard cap on messages.create calls per invocation
    max_tokens_per_turn: int = 8192

    db_path: Path = Field(default=Path("./data/broker.db"))
    trajectory_dir: Path = Field(default=Path("./trajectories"))
    log_level: str = "INFO"

    @property
    def koala_mcp_url(self) -> str:
        return f"{self.koala_base_url.rstrip('/')}/mcp"


settings = Settings()


def load_api_key(agent_name: str) -> str:
    """Read the per-agent Koala API key from agent_configs/<name>/.api_key.

    Falls back to the COALESCENCE_API_KEY env var (matches the reference repo).
    """
    key_path = REPO_ROOT / "agent_configs" / agent_name / ".api_key"
    if key_path.exists():
        key = key_path.read_text().strip()
        if key:
            return key
    import os
    env_key = os.environ.get("COALESCENCE_API_KEY", "")
    if env_key:
        return env_key
    return settings.koala_api_key
