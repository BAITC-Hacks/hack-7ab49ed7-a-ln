import hashlib
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "1.4.0"
DEFAULT_DEMO_DIR = Path(__file__).resolve().parents[2] / "sample_data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MG_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./var")
    api_token: str | None = None
    session_secret: str | None = None
    session_ttl_hours: int = Field(12, ge=1)
    cookie_secure: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    login_attempts_per_minute: int = Field(10, ge=1)

    max_upload_mb: int = Field(200, ge=1)
    max_zip_members: int = Field(20, ge=3)
    max_zip_uncompressed_mb: int = Field(1024, ge=1)
    max_nodes: int = Field(500_000, ge=1)
    max_transactions: int = Field(5_000_000, ge=1)
    max_decoded_mb: int = Field(2048, ge=1)
    # Seed-money tracing keeps two nodes × seeds float matrices in memory (16 bytes per cell).
    max_trace_cells: int = Field(50_000_000, ge=1)

    workers: int = Field(2, ge=1)
    job_timeout_s: int = Field(1800, ge=0)
    run_memory_mb: int = Field(3072, ge=256)
    max_attempts: int = Field(2, ge=1)
    lease_s: int = Field(60, ge=5)
    scheduler_enabled: bool = True

    cache_mb: int = Field(1024, ge=0)

    llm_enabled: bool = False
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-5"
    llm_max_steps: int = Field(8, ge=1)
    llm_timeout_s: float = Field(120.0, gt=0)

    log_level: str = "INFO"
    log_json: bool = True
    demo_data_dir: Path = DEFAULT_DEMO_DIR
    seed_demo: bool = True

    @property
    def auth_required(self) -> bool:
        return bool(self.api_token)

    @property
    def llm_available(self) -> bool:
        return bool(self.llm_enabled and self.anthropic_api_key)

    @property
    def signing_key(self) -> bytes:
        # Without an explicit secret the key is derived from the API token, so rotating the token also
        # invalidates every issued session.
        base = self.session_secret or self.api_token or ""
        return hashlib.sha256(("mg-session:" + base).encode()).digest()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "moneygraph.sqlite3"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"
