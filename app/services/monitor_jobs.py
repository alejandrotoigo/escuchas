import hashlib
from datetime import datetime
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlmodel import Session, select

from app.db import engine
from app.models import MonitorJob, MonitorJobIteration, Stream
from app.schemas import MonitorRunRequest
from app.services.monitoring import StreamMonitor
from app.time_utils import ensure_local_datetime, now_local


class MonitorJobRegistry:
    def __init__(self):
        self._lock = Lock()
        self._workers: dict[str, Thread] = {}

    def create_job(self, session: Session, stream: Stream, payload: MonitorRunRequest) -> MonitorJob:
        job_id = uuid4().hex
        started_at = now_local()
        step_seconds = payload.window_step_seconds or float(payload.window_seconds)
        job = MonitorJob(
            job_id=job_id,
            status="queued",
            stream_id=stream.id,
            stream_name=stream.name,
            campaign_id=payload.campaign_id,
            iterations=None if payload.run_forever else payload.iterations,
            run_forever=payload.run_forever,
            window_seconds=payload.window_seconds,
            window_step_seconds=step_seconds,
            pause_between_windows_seconds=payload.pause_between_windows_seconds,
            similarity_threshold=payload.similarity_threshold,
            cooldown_seconds=payload.cooldown_seconds,
            keep_evidence=payload.keep_evidence,
            started_at=started_at,
            updated_at=started_at,
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        with Session(engine) as session:
            jobs = session.exec(select(MonitorJob).order_by(MonitorJob.started_at.desc())).all()
            return [self._serialize_job(job, session) for job in jobs]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with Session(engine) as session:
            job = session.get(MonitorJob, job_id)
            if not job:
                return None
            return self._serialize_job(job, session)

    def request_pause(self, job_id: str) -> dict[str, Any] | None:
        with Session(engine) as session:
            job = session.get(MonitorJob, job_id)
            if not job:
                return None
            job.cancel_requested = True
            job.updated_at = now_local()
            if job.status == "queued":
                job.status = "paused"
                job.finished_at = now_local()
            elif job.status in {"running", "pause_requested"}:
                job.status = "pause_requested"
            session.add(job)
            session.commit()
            session.refresh(job)
            return self._serialize_job(job, session)

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        return self.request_pause(job_id)

    def start_job(self, job_id: str) -> None:
        with self._lock:
            worker = self._workers.get(job_id)
            if worker and worker.is_alive():
                return
            worker = Thread(target=self._run_job, args=(job_id,), daemon=True)
            self._workers[job_id] = worker
        worker.start()

    def start_runnable_jobs(self) -> list[str]:
        with Session(engine) as session:
            runnable_ids = [
                job.job_id
                for job in session.exec(
                    select(MonitorJob)
                    .where(MonitorJob.finished_at.is_(None))
                    .where(MonitorJob.status == "queued")
                    .order_by(MonitorJob.started_at.asc())
                ).all()
            ]

        started_ids: list[str] = []
        for job_id in runnable_ids:
            with self._lock:
                worker = self._workers.get(job_id)
                if worker and worker.is_alive():
                    continue
            self.start_job(job_id)
            started_ids.append(job_id)
        return started_ids

    def resume_pending_jobs(self) -> None:
        with Session(engine) as session:
            jobs = session.exec(select(MonitorJob).where(MonitorJob.finished_at.is_(None))).all()
            resumable_ids: list[str] = []
            timestamp = now_local()
            for job in jobs:
                if job.cancel_requested or job.status in {"paused", "pause_requested"}:
                    job.status = "paused"
                    job.updated_at = timestamp
                    job.finished_at = job.finished_at or timestamp
                elif job.status in {"queued", "running", "cancel_requested"}:
                    job.status = "queued"
                    job.error = None
                    job.updated_at = timestamp
                    resumable_ids.append(job.job_id)
            session.commit()

        for job_id in resumable_ids:
            self.start_job(job_id)

    def _run_job(self, job_id: str) -> None:
        lock_acquired = False
        try:
            with Session(engine) as session:
                lock_acquired = self._try_acquire_job_lock(session, job_id)
                if not lock_acquired:
                    return

                job = session.get(MonitorJob, job_id)
                if not job:
                    return
                if job.cancel_requested:
                    self._finish_job(session, job, "paused")
                    return

                stream = session.get(Stream, job.stream_id)
                if not stream:
                    raise RuntimeError("Stream no encontrado.")
                if not stream.is_active:
                    raise RuntimeError("El stream esta inactivo.")
                if not job.run_forever and job.iterations is not None and job.completed_iterations >= job.iterations:
                    self._finish_job(session, job, "completed")
                    return

                self._set_status(session, job, "running")
                monitor = StreamMonitor(session)
                monitor.run(
                    stream,
                    campaign_id=job.campaign_id,
                    window_seconds=job.window_seconds,
                    window_step_seconds=job.window_step_seconds,
                    iterations=job.iterations or max(job.completed_iterations + 1, 1),
                    run_forever=job.run_forever,
                    similarity_threshold=job.similarity_threshold,
                    cooldown_seconds=job.cooldown_seconds,
                    keep_evidence=job.keep_evidence,
                    pause_between_windows_seconds=job.pause_between_windows_seconds,
                    start_iteration=job.completed_iterations + 1,
                    progress_callback=lambda item: self._append_iteration(session, job_id, item),
                    should_cancel=lambda: self._should_cancel(job_id),
                )

                session.expire_all()
                job = session.get(MonitorJob, job_id)
                if not job:
                    return

                if self._should_cancel(job_id):
                    self._finish_job(session, job, "paused")
                    return

                self._finish_job(session, job, "completed")
        except Exception as exc:
            with Session(engine) as session:
                job = session.get(MonitorJob, job_id)
                if job:
                    self._finish_job(session, job, "failed", error=str(exc))
        finally:
            if lock_acquired:
                with Session(engine) as session:
                    self._release_job_lock(session, job_id)
            with self._lock:
                self._workers.pop(job_id, None)

    def _append_iteration(self, session: Session, job_id: str, iteration_result: dict[str, Any]) -> None:
        job = session.get(MonitorJob, job_id)
        if not job:
            return

        existing_iteration = session.exec(
            select(MonitorJobIteration)
            .where(MonitorJobIteration.job_id == job_id)
            .where(MonitorJobIteration.iteration == iteration_result["iteration"])
        ).first()
        if existing_iteration is None:
            session.add(
                MonitorJobIteration(
                    job_id=job_id,
                    iteration=iteration_result["iteration"],
                    source_url=iteration_result["source_url"],
                    window_seconds=iteration_result["window_seconds"],
                    captured_at=datetime.fromisoformat(iteration_result["captured_at"]),
                    matches_json=iteration_result["matches"],
                )
            )
            job.total_detections_created += sum(
                1 for match in iteration_result["matches"] if match["created_detection"]
            )

        job.completed_iterations = max(job.completed_iterations, iteration_result["iteration"])
        if job.run_forever or job.iterations is None:
            job.progress_percent = 0.0
        else:
            job.progress_percent = round((job.completed_iterations / max(job.iterations, 1)) * 100, 2)
        job.updated_at = now_local()
        job.status = "running"
        session.add(job)
        session.commit()

    def _set_status(self, session: Session, job: MonitorJob, status: str) -> None:
        job.status = status
        job.updated_at = now_local()
        job.error = None
        session.add(job)
        session.commit()

    def _finish_job(
        self,
        session: Session,
        job: MonitorJob,
        status: str,
        *,
        error: str | None = None,
    ) -> None:
        if job.run_forever or job.iterations is None:
            job.progress_percent = 0.0
        else:
            job.progress_percent = round((job.completed_iterations / max(job.iterations, 1)) * 100, 2)
        job.status = status
        job.error = error
        timestamp = now_local()
        job.updated_at = timestamp
        job.finished_at = timestamp
        session.add(job)
        session.commit()

    def _should_cancel(self, job_id: str) -> bool:
        with Session(engine) as session:
            job = session.get(MonitorJob, job_id)
            return job is None or job.cancel_requested

    def _job_lock_key(self, job_id: str) -> int:
        return int(hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:15], 16)

    def _try_acquire_job_lock(self, session: Session, job_id: str) -> bool:
        connection = session.connection()
        if connection.dialect.name != "postgresql":
            return True
        result = connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": self._job_lock_key(job_id)},
        )
        return bool(result.scalar())

    def _release_job_lock(self, session: Session, job_id: str) -> None:
        connection = session.connection()
        if connection.dialect.name != "postgresql":
            return
        connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": self._job_lock_key(job_id)},
        )

    def _serialize_job(self, job: MonitorJob, session: Session) -> dict[str, Any]:
        iterations = session.exec(
            select(MonitorJobIteration)
            .where(MonitorJobIteration.job_id == job.job_id)
            .order_by(MonitorJobIteration.iteration.asc())
        ).all()
        return {
            "job_id": job.job_id,
            "status": job.status,
            "stream_id": job.stream_id,
            "stream_name": job.stream_name,
            "campaign_id": job.campaign_id,
            "iterations": job.iterations,
            "run_forever": job.run_forever,
            "completed_iterations": job.completed_iterations,
            "progress_percent": job.progress_percent,
            "window_seconds": job.window_seconds,
            "window_step_seconds": job.window_step_seconds,
            "pause_between_windows_seconds": job.pause_between_windows_seconds,
            "similarity_threshold": job.similarity_threshold,
            "cooldown_seconds": job.cooldown_seconds,
            "keep_evidence": job.keep_evidence,
            "total_detections_created": job.total_detections_created,
            "started_at": ensure_local_datetime(job.started_at).isoformat(),
            "updated_at": ensure_local_datetime(job.updated_at).isoformat(),
            "finished_at": ensure_local_datetime(job.finished_at).isoformat() if job.finished_at else None,
            "error": job.error,
            "cancel_requested": job.cancel_requested,
            "results": [
                {
                    "iteration": item.iteration,
                    "source_url": item.source_url,
                    "window_seconds": item.window_seconds,
                    "captured_at": ensure_local_datetime(item.captured_at).isoformat(),
                    "matches": item.matches_json,
                }
                for item in iterations
            ],
        }


job_registry = MonitorJobRegistry()
