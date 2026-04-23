from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import Session

from app.config import settings
from app.models import Ad, Campaign
from app.schemas import UploadResponse
from app.services.media import (
    compute_fingerprint,
    detect_media_type,
    normalize_media_to_wav,
    save_uploaded_file,
)


def default_ad_title(upload: UploadFile) -> str:
    stem = Path(upload.filename or "spot").stem.strip()
    return stem or f"spot-{uuid4().hex[:8]}"


def process_uploaded_ad(session: Session, campaign_id: int, title: str, upload: UploadFile) -> Ad:
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError("Campana no encontrada.")

    media_type = detect_media_type(upload.filename or "")
    original_extension = Path(upload.filename or "").suffix.lower()
    storage_name = f"{uuid4().hex}{original_extension}"
    stored_media_path = settings.ads_dir / storage_name
    normalized_name = f"{Path(storage_name).stem}.wav"
    normalized_audio_path = settings.normalized_dir / normalized_name

    save_uploaded_file(upload, stored_media_path)

    ad = Ad(
        campaign_id=campaign_id,
        title=title.strip() or default_ad_title(upload),
        media_type=media_type,
        original_filename=upload.filename or storage_name,
        processing_status="uploaded",
    )
    session.add(ad)
    session.commit()
    session.refresh(ad)

    try:
        normalize_media_to_wav(stored_media_path, normalized_audio_path, media_type)
        fingerprint, duration = compute_fingerprint(normalized_audio_path)
        ad.normalized_audio_path = str(normalized_audio_path)
        ad.fingerprint = fingerprint
        ad.duration_seconds = duration
        ad.processing_status = "ready"
        ad.processing_error = None
    except Exception as exc:
        ad.processing_status = "error"
        ad.processing_error = str(exc)

    session.add(ad)
    session.commit()
    session.refresh(ad)
    return ad


def build_upload_response(ad: Ad) -> UploadResponse:
    message = "Spot procesado correctamente." if ad.processing_status == "ready" else "Spot cargado pero con error de procesamiento."
    return UploadResponse(
        ad_id=ad.id,
        title=ad.title,
        processing_status=ad.processing_status,
        fingerprint_preview=ad.fingerprint[:16] if ad.fingerprint else None,
        message=message,
    )