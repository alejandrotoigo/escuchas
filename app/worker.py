import logging
import time

from app.config import settings
from app.db import create_db_and_tables
from app.services.media import ensure_storage_dirs
from app.services.monitor_jobs import job_registry


logger = logging.getLogger("escuchas.worker")


def run_worker_cycle() -> list[str]:
    return job_registry.start_runnable_jobs()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ensure_storage_dirs()
    create_db_and_tables()

    if not settings.job_runner_enabled:
        logger.warning("JOB_RUNNER_ENABLED=false. Worker detenido sin procesar jobs.")
        return

    logger.info("Iniciando worker dedicado de monitoreo.")
    job_registry.resume_pending_jobs()

    try:
        while True:
            started_jobs = run_worker_cycle()
            if started_jobs:
                logger.info("Jobs encolados iniciados: %s", ", ".join(started_jobs))
            time.sleep(settings.job_runner_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Worker detenido manualmente.")


if __name__ == "__main__":
    main()