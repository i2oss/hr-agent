"""Every environment variable the app reads, in one place (SPEC §3.3).

Nothing else in the codebase reads os.environ. `.env.example` lists the same names.
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

# Calibrated in slice 3 by evaluation/calibrate_threshold.py (see evaluation/results/calibration/).
CALIBRATED_EVIDENCE_THRESHOLD = 0.69


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["anthropic", "openai_compat", "fake"] = "anthropic"
    llm_model: str = "claude-haiku-4-5"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    judge_model: str = "claude-sonnet-5-5"

    embeddings_provider: Literal["local", "voyage"] = "local"
    voyage_api_key: SecretStr | None = None

    retrieval_top_k: int = 5
    retrieval_mode: Literal["hybrid", "vector"] = "hybrid"
    evidence_threshold: float = CALIBRATED_EVIDENCE_THRESHOLD

    demo_today: dt.date = dt.date(2026, 11, 2)

    port: int = 8000
    mcp_policy_url: str | None = None
    mcp_hr_url: str | None = None

    rate_limits_enabled: bool = True
    rate_limit_per_ip: int = 20
    max_message_chars: int = 2000
    max_turns_per_session: int = 30
    daily_message_cap: int = 300
    eval_bypass_key: SecretStr | None = None

    render_git_commit: str | None = None

    # Paths are not env vars in the spec; they live here so tests can point elsewhere.
    index_path: Path = ROOT / "index" / "policy_index.sqlite"
    facts_path: Path = ROOT / "corpus" / "_facts.yaml"
    mock_data_dir: Path = ROOT / "mock_data"

    @property
    def policy_url(self) -> str:
        return self.mcp_policy_url or f"http://127.0.0.1:{self.port}/mcp/policy/"

    @property
    def hr_url(self) -> str:
        return self.mcp_hr_url or f"http://127.0.0.1:{self.port}/mcp/hr/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
