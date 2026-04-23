from pathlib import Path
import os

from pydantic import BaseModel
from dotenv import load_dotenv


load_dotenv()


def _normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseModel):
    project_name: str = os.getenv("PROJECT_NAME", "Escuchas")
    database_url: str = _normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/escuchas",
        )
    )
    postgres_admin_database: str = os.getenv("POSTGRES_ADMIN_DATABASE", "postgres")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", "storage"))
    ads_dir_name: str = "ads"
    normalized_dir_name: str = "normalized"
    monitoring_dir_name: str = "monitoring"
    evidence_dir_name: str = "evidence"
    sample_rate: int = int(os.getenv("SAMPLE_RATE", "16000"))
    job_runner_enabled: bool = _env_bool("JOB_RUNNER_ENABLED", True)
    job_runner_poll_seconds: float = float(os.getenv("JOB_RUNNER_POLL_SECONDS", "5"))
    ui_auth_enabled: bool = _env_bool("UI_AUTH_ENABLED", False)
    ui_username: str = os.getenv("UI_USERNAME", "admin")
    ui_password: str = os.getenv("UI_PASSWORD", "admin")
    session_secret: str = os.getenv("SESSION_SECRET", "dev-session-secret-change-me")
    session_https_only: bool = _env_bool("SESSION_HTTPS_ONLY", False)

    @property
    def ads_dir(self) -> Path:
        return self.storage_dir / self.ads_dir_name

    @property
    def normalized_dir(self) -> Path:
        return self.storage_dir / self.normalized_dir_name

    @property
    def monitoring_dir(self) -> Path:
        return self.storage_dir / self.monitoring_dir_name

    @property
    def evidence_dir(self) -> Path:
        return self.storage_dir / self.evidence_dir_name


settings = Settings()
