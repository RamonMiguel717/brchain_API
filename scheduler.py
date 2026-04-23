import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from api.config import DEFAULT_USER_ID, SCHEDULER_INTERVAL_MINUTES
from api.service import NewsService

logger = logging.getLogger(__name__)


def run_ingestion_job(service: NewsService, user_id: str = DEFAULT_USER_ID) -> None:
    """Funcao executada pelo scheduler para manter o banco atualizado.

    O APScheduler nao e async-aware por padrao, entao executamos a corotina
    de ingestao dentro de um event loop dedicado para esta thread.
    """
    import asyncio
    result = asyncio.run(service.ingest(user_id=user_id))
    logger.info("Ingestao agendada concluida: %s", result.stats)


def build_background_scheduler(service: NewsService, user_id: str = DEFAULT_USER_ID) -> BackgroundScheduler:
    """Cria um scheduler em background para ser anexado a API."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_ingestion_job,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        kwargs={"service": service, "user_id": user_id},
        id="news-ingestion",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )
    return scheduler


def main() -> None:
    """Modo standalone do scheduler para execucao separada da API."""
    import asyncio

    logging.basicConfig(level=logging.INFO)
    service = NewsService.build_default()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_ingestion_job,
        trigger="interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
        kwargs={"service": service, "user_id": DEFAULT_USER_ID},
        id="news-ingestion",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
    )

    try:
        logger.info(
            "Scheduler standalone iniciado com intervalo de %s minutos.",
            SCHEDULER_INTERVAL_MINUTES,
        )
        scheduler.start()
    finally:
        service.close()


if __name__ == "__main__":
    main()
