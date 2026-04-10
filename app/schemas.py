from typing import Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    ffmpeg_available: bool


class UploadResponse(BaseModel):
    ad_id: int
    title: str
    processing_status: str
    fingerprint_preview: Optional[str] = None
    message: str


class MonitoringWindow(BaseModel):
    stream_id: int
    started_at: str
    duration_seconds: int = Field(default=10, ge=1, le=120)


class MonitorRunRequest(BaseModel):
    stream_id: int
    window_seconds: int = Field(default=15, ge=5, le=300)
    iterations: int = Field(default=1, ge=1, le=500)
    similarity_threshold: float = Field(default=0.03, ge=0.001, le=1.0)
    cooldown_seconds: int = Field(default=60, ge=0, le=600)
    window_step_seconds: Optional[float] = Field(default=None, ge=1.0, le=300.0)
    pause_between_windows_seconds: float = Field(default=0.0, ge=0.0, le=30.0)
    keep_evidence: bool = True


class MonitorMatchResponse(BaseModel):
    ad_id: int
    ad_title: str
    confidence: float
    offset_seconds: float
    evidence_path: Optional[str] = None
    created_detection: bool


class MonitorIterationResponse(BaseModel):
    iteration: int
    source_url: str
    window_seconds: int
    captured_at: str
    matches: list[MonitorMatchResponse]


class MonitorRunResponse(BaseModel):
    stream_id: int
    stream_name: str
    iterations: int
    total_detections_created: int
    results: list[MonitorIterationResponse]


class MonitorJobCreateResponse(BaseModel):
    job_id: str
    status: str
    stream_id: int
    stream_name: str
    iterations: int
    window_seconds: int
    window_step_seconds: float
    started_at: str


class MonitorJobStatusResponse(BaseModel):
    job_id: str
    status: str
    stream_id: int
    stream_name: str
    iterations: int
    completed_iterations: int
    progress_percent: float
    window_seconds: int
    window_step_seconds: float
    similarity_threshold: float
    cooldown_seconds: int
    keep_evidence: bool
    total_detections_created: int
    started_at: str
    updated_at: str
    finished_at: Optional[str] = None
    error: Optional[str] = None
    cancel_requested: bool = False
    results: list[MonitorIterationResponse]


class MonitorJobCancelResponse(BaseModel):
    job_id: str
    status: str
    cancel_requested: bool
