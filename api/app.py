import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.config import (
    AUTO_INGEST_ON_STARTUP,
    DEFAULT_ARTICLE_LIMIT,
    DEFAULT_EVENT_LIMIT,
    DEFAULT_FEED_LIMIT,
    DEFAULT_USER_ID,
    ENABLE_SCHEDULER,
)
from api.schemas import (
    ArticleListResponse,
    ClickRequest,
    FeedbackRequest,
    FeedbackResponse,
    FeedResponse,
    HealthResponse,
    IngestionResponse,
    ProfileResponse,
)
from api.service import NewsService
from scheduler import build_background_scheduler

logger = logging.getLogger(__name__)


def create_app(service=None) -> FastAPI:
    """Cria a API FastAPI com injecao opcional de servico para testes."""
    external_service = service is not None

    @asynccontextmanager
    async def lifespan(app_instance):
        """Controla startup e shutdown da API, incluindo scheduler e conexoes."""
        current_service = service or NewsService.build_default()
        scheduler = None
        app_instance.state.news_service = current_service

        if not external_service and ENABLE_SCHEDULER:
            scheduler = build_background_scheduler(current_service)
            scheduler.start()
            logger.info("Scheduler de ingestao iniciado.")

        if not external_service and AUTO_INGEST_ON_STARTUP:
            try:
                await current_service.ingest(DEFAULT_USER_ID)
                logger.info("Ingestao inicial executada no startup.")
            except Exception:
                logger.exception("Falha na ingestao automatica de startup.")

        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            if not external_service:
                current_service.close()

    app = FastAPI(
        title="BRChain News API",
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS — permite que frontends em qualquer origem consumam a API em desenvolvimento.
    # Em producao, restrinja `allow_origins` ao dominio do seu frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_service() -> NewsService:
        return app.state.news_service

    @app.get("/health", response_model=HealthResponse)
    async def health():
        """Endpoint de healthcheck usado para validar API e banco."""
        try:
            return get_service().healthcheck()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/feed/{user_id}", response_model=FeedResponse)
    async def get_feed(
        user_id: str,
        limit: int = Query(DEFAULT_FEED_LIMIT, ge=1, le=100),
        refresh: bool = False,
    ):
        """Retorna o feed ranqueado do usuario."""
        try:
            return await get_service().get_feed(user_id=user_id, limit=limit, refresh=refresh)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/ingest", response_model=IngestionResponse)
    async def ingest(user_id: str = DEFAULT_USER_ID):
        """Dispara uma ingestao manual para facilitar testes e operacao."""
        try:
            return await get_service().ingest(user_id=user_id)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/articles", response_model=ArticleListResponse)
    async def list_articles(
        limit: int = Query(DEFAULT_ARTICLE_LIMIT, ge=1, le=100),
        category: str | None = None,
        source_name: str | None = None,
    ):
        """Lista artigos persistidos com filtros simples."""
        try:
            return get_service().list_articles(
                limit=limit,
                category=category,
                source_name=source_name,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/profiles/{user_id}", response_model=ProfileResponse)
    async def get_profile(
        user_id: str,
        events_limit: int = Query(DEFAULT_EVENT_LIMIT, ge=1, le=50),
    ):
        """Expoe as preferencias e os eventos recentes do usuario."""
        try:
            return get_service().get_profile(user_id=user_id, events_limit=events_limit)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/feed/{user_id}/feedback", response_model=FeedbackResponse)
    async def submit_feedback(user_id: str, payload: FeedbackRequest):
        """Recebe feedback explicito e atualiza o perfil do usuario."""
        try:
            return get_service().submit_feedback(
                user_id=user_id,
                article_id=payload.article_id,
                action=payload.action,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/feed/{user_id}/click", response_model=FeedbackResponse)
    async def register_click(user_id: str, payload: ClickRequest):
        """Atalho para tratar clique como um sinal positivo de interesse."""
        try:
            return get_service().submit_feedback(
                user_id=user_id,
                article_id=payload.article_id,
                action="gostei",
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


app = create_app()
