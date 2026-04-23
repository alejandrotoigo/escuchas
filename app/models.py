from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.time_utils import now_local


class CampaignBase(SQLModel):
    name: str = Field(index=True)
    brand: Optional[str] = None
    notes: Optional[str] = None


class Campaign(CampaignBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=now_local, nullable=False)


class CampaignCreate(CampaignBase):
    pass


class AdBase(SQLModel):
    campaign_id: int = Field(foreign_key="campaign.id", index=True)
    title: str
    media_type: str
    original_filename: str
    duration_seconds: Optional[float] = None
    normalized_audio_path: Optional[str] = None
    fingerprint: Optional[str] = None
    processing_status: str = "pending"
    processing_error: Optional[str] = None


class Ad(AdBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    uploaded_at: datetime = Field(default_factory=now_local, nullable=False)


class AdRead(AdBase):
    id: int
    uploaded_at: datetime


class StreamBase(SQLModel):
    name: str = Field(index=True)
    source_url: str
    description: Optional[str] = None
    is_active: bool = True


class Stream(StreamBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=now_local, nullable=False)


class StreamCreate(StreamBase):
    pass


class DetectionBase(SQLModel):
    ad_id: int = Field(foreign_key="ad.id", index=True)
    stream_id: int = Field(foreign_key="stream.id", index=True)
    detected_at: datetime = Field(default_factory=now_local, nullable=False)
    confidence: float
    offset_seconds: Optional[float] = None
    evidence_path: Optional[str] = None


class Detection(DetectionBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)


class DetectionRead(DetectionBase):
    id: int


class MonitorJob(SQLModel, table=True):
    __tablename__ = "monitor_job"

    job_id: str = Field(primary_key=True)
    status: str = Field(index=True)
    stream_id: int = Field(foreign_key="stream.id", index=True)
    stream_name: str
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaign.id", index=True)
    iterations: Optional[int] = None
    run_forever: bool = False
    window_seconds: int
    window_step_seconds: float
    pause_between_windows_seconds: float = 0.0
    similarity_threshold: float
    cooldown_seconds: int
    keep_evidence: bool
    started_at: datetime = Field(default_factory=now_local, nullable=False)
    updated_at: datetime = Field(default_factory=now_local, nullable=False)
    completed_iterations: int = 0
    progress_percent: float = 0.0
    total_detections_created: int = 0
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    cancel_requested: bool = False


class MonitorJobIteration(SQLModel, table=True):
    __tablename__ = "monitor_job_iteration"
    __table_args__ = (
        UniqueConstraint("job_id", "iteration", name="uq_monitor_job_iteration_job_iteration"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="monitor_job.job_id", index=True)
    iteration: int = Field(index=True)
    source_url: str
    window_seconds: int
    captured_at: datetime = Field(nullable=False)
    matches_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
