from datetime import datetime
from typing import Optional

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
