import json
from datetime import datetime, timezone

from api.classifier import NewsClassifier
from api.config import (
    DEFAULT_ARTICLE_LIMIT,
    DEFAULT_EVENT_LIMIT,
    DEFAULT_FEED_LIMIT,
    DEFAULT_USER_ID,
    TAGS_FILE,
)
from api.deduplication import NewsDeduplicator
from api.gnews_client import GNewsClient
from api.mongo_repository import MongoRepository
from api.recommender import NewsRecommender
from api.schemas import (
    ArticleListResponse,
    ArticleResponse,
    FeedbackResponse,
    FeedResponse,
    HealthResponse,
    IngestionResponse,
    IngestionStatsResponse,
    ProfileResponse,
    RankingEntryResponse,
    UserEventResponse,
)


def load_categories() -> list[dict]:
    """Carrega e valida as categorias base usadas na classificacao das noticias."""
    with TAGS_FILE.open("r", encoding="utf-8") as file:
        categories = json.load(file)

    required_keys = {"nome", "keywords", "sinonimos", "ativa", "peso_global"}
    for i, category in enumerate(categories):
        missing = required_keys - set(category.keys())
        if missing:
            raise ValueError(
                f"Categoria no indice {i} do Tags.json esta incompleta. "
                f"Campos ausentes: {missing}"
            )

    return categories


class NewsService:
    """Orquestra o fluxo da aplicacao entre cliente, ranking e persistencia."""

    def __init__(self, repository, client=None, classifier=None, deduplicator=None, categories=None):
        self.categories = categories or load_categories()
        self.repository = repository
        self.client = client or GNewsClient()
        self.classifier = classifier or NewsClassifier(self.categories)
        self.deduplicator = deduplicator or NewsDeduplicator()
        self.recommender = NewsRecommender(
            self.client,
            self.classifier,
            self.repository,
            self.deduplicator,
        )

    @classmethod
    def build_default(cls) -> "NewsService":
        """Monta a configuracao padrao do projeto usando o MongoDB local/configurado."""
        repository = MongoRepository().connect()
        return cls(repository=repository)

    def healthcheck(self) -> HealthResponse:
        """Retorna um retrato rapido da saude da API e do banco."""
        self.repository.ping()
        return HealthResponse(
            status="ok",
            mongodb="connected",
            checked_at=datetime.now(timezone.utc),
            collections=self.repository.get_collection_counts(),
        )

    async def ingest(self, user_id: str = DEFAULT_USER_ID) -> IngestionResponse:
        """Executa uma rodada de ingestao e devolve estatisticas resumidas."""
        stats = await self.recommender.ingestir_noticias(user_id=user_id)
        return IngestionResponse(
            user_id=user_id,
            stats=IngestionStatsResponse(**stats),
            executed_at=datetime.now(timezone.utc),
        )

    async def get_feed(
        self,
        user_id: str,
        limit: int = DEFAULT_FEED_LIMIT,
        refresh: bool = False,
        track_impressions: bool = True,
    ) -> FeedResponse:
        """Gera o feed final do usuario e opcionalmente registra impressoes."""
        articles = await self.recommender.buscar_noticias(
            user_id=user_id,
            limit=limit,
            refresh=refresh,
        )

        if track_impressions:
            self.repository.increment_article_impressions(
                [article.get("_id") for article in articles if article.get("_id")]
            )
            for article in articles:
                article["impression_count"] = int(article.get("impression_count", 0) or 0) + 1

        return FeedResponse(
            user_id=user_id,
            limit=limit,
            refresh=refresh,
            generated_at=datetime.now(timezone.utc),
            ingestion=IngestionStatsResponse(**self.recommender.last_ingestion),
            items=[self._serialize_article(a) for a in articles],
        )

    def list_articles(
        self,
        limit: int = DEFAULT_ARTICLE_LIMIT,
        category: str | None = None,
        source_name: str | None = None,
    ) -> ArticleListResponse:
        """Lista artigos persistidos com filtros simples para exploracao e debug."""
        articles = self.repository.list_articles(
            limit=limit,
            category=category,
            source_name=source_name,
        )
        return ArticleListResponse(
            limit=limit,
            category=category,
            source_name=source_name,
            items=[self._serialize_article(a) for a in articles],
        )

    def get_profile(self, user_id: str, events_limit: int = DEFAULT_EVENT_LIMIT) -> ProfileResponse:
        """Expoe o estado atual do perfil e o historico recente de interacoes."""
        profile_document = self.repository.get_profile_document(user_id) or {}
        profile = self.repository.get_profile(user_id, self.categories)
        recent_events = self.repository.get_user_events(user_id, limit=events_limit)

        return ProfileResponse(
            user_id=user_id,
            preferences=profile.preferences,
            normalized_preferences=profile.pesos_normalizados(),
            updated_at=profile_document.get("updated_at"),
            created_at=profile_document.get("created_at"),
            recent_events=[self._serialize_event(e) for e in recent_events],
        )

    def submit_feedback(self, user_id: str, article_id: str, action: str) -> FeedbackResponse:
        """Aplica feedback ao perfil, ajusta engajamento e registra auditoria do evento."""
        article = self.repository.get_article_by_id(article_id)
        if article is None:
            raise LookupError("Artigo nao encontrado para o feedback informado.")

        ranking = self.recommender.processar_feedback(
            article,
            acao=action,
            user_id=user_id,
        )

        if action == "gostei":
            self.repository.increment_article_clicks(article_id)

        self.repository.record_user_event(
            user_id=user_id,
            article=article,
            action=action,
            metadata={
                "top_categories_after_feedback": [
                    {"category": cat, "score": round(score, 4)}
                    for cat, score in ranking[:5]
                ]
            },
        )

        return FeedbackResponse(
            user_id=user_id,
            article_id=article_id,
            action=action,
            dominant_category=article.get("dominant_category", "Geral"),
            ranking=[
                RankingEntryResponse(category=cat, score=round(score, 4))
                for cat, score in ranking[:10]
            ],
            updated_at=datetime.now(timezone.utc),
        )

    def close(self) -> None:
        """Fecha a conexao do repositorio quando a aplicacao encerra."""
        self.repository.close()

    # ------------------------------------------------------------------
    # Serializadores privados — convertem documentos Mongo em modelos Pydantic
    # ------------------------------------------------------------------

    def _serialize_article(self, article: dict) -> ArticleResponse:
        return ArticleResponse(
            id=str(article.get("_id")) if article.get("_id") else article.get("url_hash", ""),
            title=article.get("title"),
            description=article.get("description"),
            content=article.get("content"),
            url=article.get("url"),
            source_name=article.get("source_name") or (article.get("source") or {}).get("name"),
            published_at=article.get("published_at"),
            categories=article.get("categories", []),
            dominant_category=article.get("dominant_category", "Geral"),
            score=article.get("score"),
            raw_score=article.get("raw_score"),
            click_count=int(article.get("click_count", 0) or 0),
            impression_count=int(article.get("impression_count", 0) or 0),
            normalized_category_scores=article.get("normalized_category_scores", {}),
        )

    def _serialize_event(self, event: dict) -> UserEventResponse:
        return UserEventResponse(
            id=str(event.get("_id")) if event.get("_id") else "",
            action=event.get("action"),
            article_id=event.get("article_id"),
            article_title=event.get("article_title"),
            dominant_category=event.get("dominant_category"),
            categories=event.get("categories", []),
            created_at=event.get("created_at"),
            metadata=event.get("metadata", {}),
        )
