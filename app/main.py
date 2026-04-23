import secrets
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
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
from app.services.media import ensure_storage_dirs, ffmpeg_available
from app.services.monitor_jobs import job_registry
from app.services.monitoring import StreamMonitor
from app.services.uploads import build_upload_response, default_ad_title, process_uploaded_ad


app = FastAPI(title=settings.project_name, version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_https_only,
)
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _redirect_home(*, message: str | None = None, error: str | None = None, job_id: str | None = None) -> RedirectResponse:
    query_params = {key: value for key, value in {"message": message, "error": error, "job_id": job_id}.items() if value}
    target = "/"
    if query_params:
        target = f"/?{urlencode(query_params)}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


def _safe_next_path(raw_next: str | None) -> str:
    if not raw_next:
        return "/"
    if not raw_next.startswith("/") or raw_next.startswith("//"):
        return "/"
    return raw_next


def _is_ui_authenticated(request: Request) -> bool:
    if not settings.ui_auth_enabled:
        return True
    return bool(request.session.get("ui_authenticated"))


def _build_login_redirect(request: Request, *, error: str | None = None) -> RedirectResponse:
    next_path = _safe_next_path(
        request.url.path + (f"?{request.url.query}" if request.url.query else "")
    )
    query_params = {"next": next_path}
    if error:
        query_params["error"] = error
    return RedirectResponse(url=f"/login?{urlencode(query_params)}", status_code=status.HTTP_303_SEE_OTHER)


def _require_ui_auth(request: Request) -> RedirectResponse | None:
    if _is_ui_authenticated(request):
        return None
    return _build_login_redirect(request)


def _credentials_are_valid(username: str, password: str) -> bool:
    return secrets.compare_digest(username, settings.ui_username) and secrets.compare_digest(password, settings.ui_password)


@app.on_event("startup")
def on_startup() -> None:
    ensure_storage_dirs()
    create_db_and_tables()
    if settings.job_runner_enabled:
        job_registry.resume_pending_jobs()


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(
    request: Request,
    error: str | None = Query(default=None),
    next: str | None = Query(default="/"),
) -> HTMLResponse:
    if not settings.ui_auth_enabled:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    next_path = _safe_next_path(next)
    if _is_ui_authenticated(request):
        return RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error,
            "next_path": next_path,
            "ui_username": settings.ui_username,
        },
    )


@app.post("/login", include_in_schema=False)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_path: str = Form(default="/"),
) -> RedirectResponse:
    if not settings.ui_auth_enabled:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    safe_next_path = _safe_next_path(next_path)
    if not _credentials_are_valid(username.strip(), password):
        return RedirectResponse(
            url=f"/login?{urlencode({'error': 'Credenciales invalidas.', 'next': safe_next_path})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    request.session.clear()
    request.session["ui_authenticated"] = True
    request.session["ui_username"] = username.strip()
    return RedirectResponse(url=safe_next_path, status_code=status.HTTP_303_SEE_OTHER)


@app.post("/logout", include_in_schema=False)
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    job_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    auth_redirect = _require_ui_auth(request)
    if auth_redirect:
        return auth_redirect

    detections = list(session.exec(select(Detection).order_by(Detection.detected_at.desc())).all())
    ad_map = {ad.id: ad for ad in session.exec(select(Ad)).all()}
    stream_map = {stream.id: stream for stream in session.exec(select(Stream)).all()}
    detection_rows = [
        {
            "id": detection.id,
            "detected_at": detection.detected_at.isoformat(),
            "confidence": round(detection.confidence, 4),
            "offset_seconds": round(detection.offset_seconds or 0.0, 2),
            "ad_title": ad_map.get(detection.ad_id).title if ad_map.get(detection.ad_id) else f"Ad {detection.ad_id}",
            "stream_name": stream_map.get(detection.stream_id).name if stream_map.get(detection.stream_id) else f"Stream {detection.stream_id}",
            "has_evidence": bool(detection.evidence_path),
        }
        for detection in detections[:20]
    ]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "message": message,
            "error": error,
            "job_id": job_id,
            "jobs": job_registry.list_jobs(),
            "detections": detection_rows,
            "ffmpeg_ready": ffmpeg_available(),
            "job_runner_enabled": settings.job_runner_enabled,
            "ui_auth_enabled": settings.ui_auth_enabled,
            "authenticated_user": request.session.get("ui_username"),
        },
    )


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
    try:
        ad = process_uploaded_ad(session, campaign_id, title, file)
    except ValueError as exc:
        status_code = 404 if str(exc) == "Campana no encontrada." else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return build_upload_response(ad)


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


@app.get("/ui/detections/{detection_id}/evidence", include_in_schema=False)
def get_detection_evidence(
    detection_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> FileResponse:
    auth_redirect = _require_ui_auth(request)
    if auth_redirect:
        return auth_redirect

    detection = session.get(Detection, detection_id)
    if not detection or not detection.evidence_path:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada.")

    evidence_path = Path(detection.evidence_path)
    if not evidence_path.exists() or not evidence_path.is_file():
        raise HTTPException(status_code=404, detail="El archivo de evidencia no existe.")

    return FileResponse(path=evidence_path, media_type="audio/wav", filename=evidence_path.name)


@app.post("/monitor/run", response_model=MonitorRunResponse)
def run_monitoring(payload: MonitorRunRequest, session: Session = Depends(get_session)) -> MonitorRunResponse:
    stream = session.get(Stream, payload.stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream no encontrado.")
    if not stream.is_active:
        raise HTTPException(status_code=400, detail="El stream esta inactivo.")
    if payload.run_forever:
        raise HTTPException(status_code=400, detail="Para monitoreo infinito usa POST /monitor/jobs.")
    if payload.campaign_id is not None and not session.get(Campaign, payload.campaign_id):
        raise HTTPException(status_code=404, detail="Campana no encontrada.")

    try:
        monitor = StreamMonitor(session)
        results = monitor.run(
            stream,
            campaign_id=payload.campaign_id,
            window_seconds=payload.window_seconds,
            window_step_seconds=payload.window_step_seconds or float(payload.window_seconds),
            iterations=payload.iterations,
            run_forever=False,
            similarity_threshold=payload.similarity_threshold,
            cooldown_seconds=payload.cooldown_seconds,
            keep_evidence=payload.keep_evidence,
            pause_between_windows_seconds=payload.pause_between_windows_seconds,
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
    if payload.campaign_id is not None and not session.get(Campaign, payload.campaign_id):
        raise HTTPException(status_code=404, detail="Campana no encontrada.")

    job = job_registry.create_job(session, stream, payload)
    if settings.job_runner_enabled:
        job_registry.start_job(job.job_id)
    return MonitorJobCreateResponse(
        job_id=job.job_id,
        status=job.status,
        stream_id=job.stream_id,
        stream_name=job.stream_name,
        campaign_id=job.campaign_id,
        iterations=job.iterations,
        run_forever=job.run_forever,
        window_seconds=job.window_seconds,
        window_step_seconds=job.window_step_seconds,
        pause_between_windows_seconds=job.pause_between_windows_seconds,
        started_at=job.started_at.isoformat(),
    )


@app.post("/monitor/jobs/{job_id}/pause", response_model=MonitorJobCancelResponse)
def pause_monitor_job(job_id: str) -> MonitorJobCancelResponse:
    job = job_registry.request_pause(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return MonitorJobCancelResponse(
        job_id=job["job_id"],
        status=job["status"],
        cancel_requested=job["cancel_requested"],
    )


@app.get("/monitor/jobs", response_model=list[MonitorJobStatusResponse])
def list_monitor_jobs() -> list[MonitorJobStatusResponse]:
    return [MonitorJobStatusResponse(**job) for job in job_registry.list_jobs()]


@app.get("/monitor/jobs/{job_id}", response_model=MonitorJobStatusResponse)
def get_monitor_job(job_id: str) -> MonitorJobStatusResponse:
    job = job_registry.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return MonitorJobStatusResponse(**job)


@app.post("/monitor/jobs/{job_id}/cancel", response_model=MonitorJobCancelResponse)
def cancel_monitor_job(job_id: str) -> MonitorJobCancelResponse:
    return pause_monitor_job(job_id)


@app.post("/ui/setup", include_in_schema=False)
def create_campaign_bundle(
    request: Request,
    campaign_name: str = Form(...),
    campaign_brand: str | None = Form(default=None),
    campaign_notes: str | None = Form(default=None),
    stream_name: str = Form(...),
    stream_source_url: str = Form(...),
    stream_description: str | None = Form(default=None),
    ad_titles: str | None = Form(default=None),
    ad_files: list[UploadFile] = File(...),
    window_seconds: int = Form(default=45),
    window_step_seconds: float = Form(default=15.0),
    similarity_threshold: float = Form(default=0.03),
    cooldown_seconds: int = Form(default=60),
    pause_between_windows_seconds: float = Form(default=0.0),
    keep_evidence: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    auth_redirect = _require_ui_auth(request)
    if auth_redirect:
        return auth_redirect

    uploaded_files = [uploaded for uploaded in ad_files if uploaded.filename]
    if not uploaded_files:
        return _redirect_home(error="Tenes que subir al menos un spot para iniciar el monitoreo.")

    campaign = Campaign(name=campaign_name.strip(), brand=campaign_brand, notes=campaign_notes)
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    provided_titles = [line.strip() for line in (ad_titles or "").splitlines() if line.strip()]
    ready_ads = 0
    errored_ads = 0
    for index, uploaded_file in enumerate(uploaded_files):
        try:
            title = provided_titles[index] if index < len(provided_titles) else default_ad_title(uploaded_file)
            ad = process_uploaded_ad(session, campaign.id, title, uploaded_file)
            if ad.processing_status == "ready":
                ready_ads += 1
            else:
                errored_ads += 1
        except Exception:
            errored_ads += 1

    stream = Stream(
        name=stream_name.strip(),
        source_url=stream_source_url.strip(),
        description=stream_description,
        is_active=True,
    )
    session.add(stream)
    session.commit()
    session.refresh(stream)

    if ready_ads == 0:
        return _redirect_home(
            error="Se creo la campana y el stream, pero ningun spot quedo listo. El job no se inicio.",
        )

    payload = MonitorRunRequest(
        stream_id=stream.id,
        campaign_id=campaign.id,
        iterations=1,
        run_forever=True,
        window_seconds=window_seconds,
        window_step_seconds=window_step_seconds,
        pause_between_windows_seconds=pause_between_windows_seconds,
        similarity_threshold=similarity_threshold,
        cooldown_seconds=cooldown_seconds,
        keep_evidence=keep_evidence is not None,
    )
    job = job_registry.create_job(session, stream, payload)
    if settings.job_runner_enabled:
        job_registry.start_job(job.job_id)

    message = (
        f"Campana creada, {ready_ads} spot(s) listos, stream creado y job {job.job_id} iniciado en modo continuo."
    )
    if errored_ads:
        message += f" {errored_ads} spot(s) quedaron con error de procesamiento."
    if not settings.job_runner_enabled:
        message += " El job quedo en cola porque JOB_RUNNER_ENABLED=false."
    return _redirect_home(message=message, job_id=job.job_id)


@app.post("/ui/jobs/{job_id}/pause", include_in_schema=False)
def pause_job_from_ui(job_id: str, request: Request) -> RedirectResponse:
    auth_redirect = _require_ui_auth(request)
    if auth_redirect:
        return auth_redirect

    job = job_registry.request_pause(job_id)
    if not job:
        return _redirect_home(error=f"No se encontro el job {job_id}.")
    return _redirect_home(message=f"Job {job_id} marcado para pausa.", job_id=job_id)
