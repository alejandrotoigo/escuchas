from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    project_name: str = "Escuchas"
    database_url: str = "sqlite:///./escuchas.db"
    storage_dir: Path = Path("storage")
    ads_dir_name: str = "ads"
    normalized_dir_name: str = "normalized"
    monitoring_dir_name: str = "monitoring"
    evidence_dir_name: str = "evidence"
    sample_rate: int = 16_000

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
