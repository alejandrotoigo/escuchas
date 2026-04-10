from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from sqlmodel import Session, select

from app.config import settings
from app.db import create_db_and_tables, get_session
from app.models import Ad, Campaign, CampaignCreate, Detection, Stream, StreamCreate
from app.schemas import (
    HealthResponse,
    MonitorJobCancelResponse,
    MonitorJobCreateResponse,
    MonitorJobStatusResponse,
    MonitorRunRequest,
    MonitorRunResponse,
    UploadResponse,
)
from app.services.media import (
    compute_fingerprint,
    detect_media_type,
    ensure_storage_dirs,
    ffmpeg_available,
    normalize_media_to_wav,
    save_uploaded_file,
)
from app.services.monitor_jobs import job_registry
from app.services.monitoring import StreamMonitor


app = FastAPI(title=settings.project_name, version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    ensure_storage_dirs()
    create_db_and_tables()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ffmpeg_available=ffmpeg_available())


@app.post("/campaigns", response_model=Campaign)
def create_campaign(payload: CampaignCreate, session: Session = Depends(get_session)) -> Campaign:
    campaign = Campaign.model_validate(payload)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


@app.get("/campaigns", response_model=list[Campaign])
def list_campaigns(session: Session = Depends(get_session)) -> list[Campaign]:
    return list(session.exec(select(Campaign).order_by(Campaign.created_at.desc())).all())


@app.post("/ads/upload", response_model=UploadResponse)
def upload_ad(
    campaign_id: int,
    title: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> UploadResponse:
    campaign = session.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campana no encontrada.")

    try:
        media_type = detect_media_type(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    original_extension = Path(file.filename or "").suffix.lower()
    storage_name = f"{uuid4().hex}{original_extension}"
    stored_media_path = settings.ads_dir / storage_name
    normalized_name = f"{Path(storage_name).stem}.wav"
    normalized_audio_path = settings.normalized_dir / normalized_name

    save_uploaded_file(file, stored_media_path)

    ad = Ad(
        campaign_id=campaign_id,
        title=title,
        media_type=media_type,
        original_filename=file.filename or storage_name,
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

    message = "Spot procesado correctamente." if ad.processing_status == "ready" else "Spot cargado pero con error de procesamiento."
    return UploadResponse(
        ad_id=ad.id,
        title=ad.title,
        processing_status=ad.processing_status,
        fingerprint_preview=ad.fingerprint[:16] if ad.fingerprint else None,
        message=message,
    )


@app.get("/ads", response_model=list[Ad])
def list_ads(session: Session = Depends(get_session)) -> list[Ad]:
    return list(session.exec(select(Ad).order_by(Ad.uploaded_at.desc())).all())


@app.post("/streams", response_model=Stream)
def create_stream(payload: StreamCreate, session: Session = Depends(get_session)) -> Stream:
    stream = Stream.model_validate(payload)
    session.add(stream)
    session.commit()
    session.refresh(stream)
    return stream


@app.get("/streams", response_model=list[Stream])
def list_streams(session: Session = Depends(get_session)) -> list[Stream]:
    return list(session.exec(select(Stream).order_by(Stream.created_at.desc())).all())


@app.get("/detections", response_model=list[Detection])
def list_detections(session: Session = Depends(get_session)) -> list[Detection]:
    return list(session.exec(select(Detection).order_by(Detection.detected_at.desc())).all())


@app.post("/monitor/run", response_model=MonitorRunResponse)
def run_monitoring(payload: MonitorRunRequest, session: Session = Depends(get_session)) -> MonitorRunResponse:
    stream = session.get(Stream, payload.stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream no encontrado.")
    if not stream.is_active:
        raise HTTPException(status_code=400, detail="El stream esta inactivo.")

    try:
        monitor = StreamMonitor(session)
        results = monitor.run(
            stream,
            window_seconds=payload.window_seconds,
            window_step_seconds=payload.window_step_seconds or float(payload.window_seconds),
            iterations=payload.iterations,
            similarity_threshold=payload.similarity_threshold,
            cooldown_seconds=payload.cooldown_seconds,
            keep_evidence=payload.keep_evidence,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    total_detections_created = sum(
        1
        for iteration in results
        for match in iteration["matches"]
        if match["created_detection"]
    )
    return MonitorRunResponse(
        stream_id=stream.id,
        stream_name=stream.name,
        iterations=len(results),
        total_detections_created=total_detections_created,
        results=results,
    )


@app.post("/monitor/jobs", response_model=MonitorJobCreateResponse)
def create_monitor_job(payload: MonitorRunRequest, session: Session = Depends(get_session)) -> MonitorJobCreateResponse:
    stream = session.get(Stream, payload.stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream no encontrado.")
    if not stream.is_active:
        raise HTTPException(status_code=400, detail="El stream esta inactivo.")

    job = job_registry.create_job(stream, payload)
    job_registry.start_job(job, payload)
    return MonitorJobCreateResponse(
        job_id=job.job_id,
        status=job.status,
        stream_id=job.stream_id,
        stream_name=job.stream_name,
        iterations=job.iterations,
        window_seconds=job.window_seconds,
        window_step_seconds=job.window_step_seconds,
        started_at=job.started_at,
    )


@app.get("/monitor/jobs", response_model=list[MonitorJobStatusResponse])
def list_monitor_jobs() -> list[MonitorJobStatusResponse]:
    return [MonitorJobStatusResponse(**job_registry.serialize_job(job.job_id)) for job in job_registry.list_jobs()]


@app.get("/monitor/jobs/{job_id}", response_model=MonitorJobStatusResponse)
def get_monitor_job(job_id: str) -> MonitorJobStatusResponse:
    job = job_registry.serialize_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return MonitorJobStatusResponse(**job)


@app.post("/monitor/jobs/{job_id}/cancel", response_model=MonitorJobCancelResponse)
def cancel_monitor_job(job_id: str) -> MonitorJobCancelResponse:
    job = job_registry.request_cancel(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return MonitorJobCancelResponse(
        job_id=job.job_id,
        status=job.status,
        cancel_requested=job.cancel_requested,
    )
