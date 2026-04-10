from dataclasses import asdict, dataclass, field
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from sqlmodel import Session

from app.db import engine
from app.models import Stream
from app.schemas import MonitorRunRequest
from app.services.monitoring import StreamMonitor
from app.time_utils import now_local


@dataclass
class MonitorJobState:
    job_id: str
    status: str
    stream_id: int
    stream_name: str
    iterations: int
    window_seconds: int
    window_step_seconds: float
    similarity_threshold: float
    cooldown_seconds: int
    keep_evidence: bool
    started_at: str
    updated_at: str
    completed_iterations: int = 0
    progress_percent: float = 0.0
    total_detections_created: int = 0
    finished_at: str | None = None
    error: str | None = None
    cancel_requested: bool = False
    results: list[dict[str, Any]] = field(default_factory=list)


class MonitorJobRegistry:
    def __init__(self):
        self._jobs: dict[str, MonitorJobState] = {}
        self._lock = Lock()

    def create_job(self, stream: Stream, payload: MonitorRunRequest) -> MonitorJobState:
        job_id = uuid4().hex
        started_at = now_local().isoformat()
        step_seconds = payload.window_step_seconds or float(payload.window_seconds)
        job = MonitorJobState(
            job_id=job_id,
            status="queued",
            stream_id=stream.id,
            stream_name=stream.name,
            iterations=payload.iterations,
            window_seconds=payload.window_seconds,
            window_step_seconds=step_seconds,
            similarity_threshold=payload.similarity_threshold,
            cooldown_seconds=payload.cooldown_seconds,
            keep_evidence=payload.keep_evidence,
            started_at=started_at,
            updated_at=started_at,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def list_jobs(self) -> list[MonitorJobState]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.started_at, reverse=True)

    def get_job(self, job_id: str) -> MonitorJobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def request_cancel(self, job_id: str) -> MonitorJobState | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            job.cancel_requested = True
            job.updated_at = now_local().isoformat()
            if job.status in {"queued", "running"}:
                job.status = "cancel_requested"
            return job

    def start_job(self, job: MonitorJobState, payload: MonitorRunRequest) -> None:
        worker = Thread(target=self._run_job, args=(job.job_id, payload), daemon=True)
        worker.start()

    def _run_job(self, job_id: str, payload: MonitorRunRequest) -> None:
        self._set_status(job_id, "running")
        try:
            with Session(engine) as session:
                stream = session.get(Stream, payload.stream_id)
                if not stream:
                    raise RuntimeError("Stream no encontrado.")
                if not stream.is_active:
                    raise RuntimeError("El stream esta inactivo.")

                monitor = StreamMonitor(session)
                results = monitor.run(
                    stream,
                    window_seconds=payload.window_seconds,
                    window_step_seconds=payload.window_step_seconds or float(payload.window_seconds),
                    iterations=payload.iterations,
                    similarity_threshold=payload.similarity_threshold,
                    cooldown_seconds=payload.cooldown_seconds,
                    keep_evidence=payload.keep_evidence,
                    progress_callback=lambda item: self._append_iteration(job_id, item),
                    should_cancel=lambda: self._should_cancel(job_id),
                )

                if self._should_cancel(job_id):
                    self._finish_job(job_id, "cancelled")
                    return

                # Aseguramos que el estado final refleje todo lo que se procesó.
                self._finish_job(job_id, "completed", results=results)
        except Exception as exc:
            self._finish_job(job_id, "failed", error=str(exc))

    def _append_iteration(self, job_id: str, iteration_result: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.results.append(iteration_result)
            job.completed_iterations = len(job.results)
            job.progress_percent = round((job.completed_iterations / max(job.iterations, 1)) * 100, 2)
            job.total_detections_created = sum(
                1
                for result in job.results
                for match in result["matches"]
                if match["created_detection"]
            )
            job.updated_at = now_local().isoformat()

    def _set_status(self, job_id: str, status: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = status
            job.updated_at = now_local().isoformat()

    def _finish_job(
        self,
        job_id: str,
        status: str,
        *,
        results: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if results is not None:
                job.results = results
                job.completed_iterations = len(results)
                job.total_detections_created = sum(
                    1
                    for result in results
                    for match in result["matches"]
                    if match["created_detection"]
                )
            job.progress_percent = round((job.completed_iterations / max(job.iterations, 1)) * 100, 2)
            job.status = status
            job.error = error
            timestamp = now_local().isoformat()
            job.updated_at = timestamp
            job.finished_at = timestamp

    def _should_cancel(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs[job_id].cancel_requested

    def serialize_job(self, job_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        return asdict(job)


job_registry = MonitorJobRegistry()
