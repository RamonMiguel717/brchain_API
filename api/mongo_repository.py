from datetime import datetime, timedelta, timezone

from bson import ObjectId
from bson.errors import InvalidId
import mongomock
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import ServerSelectionTimeoutError

from api.config import (
    DEDUP_CANDIDATE_LIMIT,
    MONGODB_DB_NAME,
    MONGODB_URI,
    RECENT_ARTICLES_LIMIT,
    RECENT_DEDUP_LOOKBACK_DAYS,
    USE_MOCK_DB,
)
from api.user_profile import UserProfile


class MongoRepository:
    """Encapsula todo o acesso ao MongoDB para artigos, perfis e eventos."""

    def __init__(self, uri=MONGODB_URI, db_name=MONGODB_DB_NAME, use_mock=USE_MOCK_DB):
        self.use_mock = use_mock
        self.client = self._build_client(uri)
        self.database = self.client[db_name]
        self.articles = self.database["articles"]
        self.user_profiles = self.database["user_profiles"]
        self.user_events = self.database["user_events"]

    def connect(self):
        """Valida a conexao inicial e garante os indices principais."""
        if not self.use_mock:
            try:
                self.client.admin.command("ping")
            except ServerSelectionTimeoutError as exc:
                raise RuntimeError(
                    "Não foi possível conectar ao MongoDB. "
                    "Configure MONGODB_URI, inicie uma instância local "
                    "ou habilite USE_MOCK_DB=true para desenvolvimento."
                ) from exc

        self.ensure_indexes()
        return self

    def ensure_indexes(self):
        """Cria indices usados para deduplicacao, consulta de feed e perfis."""
        self.articles.create_index([("url_hash", ASCENDING)], unique=True, sparse=True)
        self.articles.create_index([("published_at", DESCENDING)])
        self.articles.create_index([("dominant_category", ASCENDING), ("published_at", DESCENDING)])
        self.user_profiles.create_index([("user_id", ASCENDING)], unique=True)
        self.user_events.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])

    def ping(self):
        """Executa um ping simples no banco para healthcheck."""
        if self.use_mock:
            return True

        self.client.admin.command("ping")
        return True

    def get_recent_dedup_candidates(
        self,
        lookback_days=RECENT_DEDUP_LOOKBACK_DAYS,
        limit=DEDUP_CANDIDATE_LIMIT,
    ):
        """Busca artigos recentes usados como referencia contra novas duplicatas."""
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        cursor = (
            self.articles.find(
                {"published_at": {"$gte": since}},
                {"url_hash": 1, "title_tokens": 1, "title": 1},
            )
            .sort("published_at", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    def upsert_articles(self, articles):
        """Insere noticias novas e apenas atualiza o carimbo de reprocessamento das repetidas."""
        inserted = 0
        now = datetime.now(timezone.utc)

        for article in articles:
            selector = {"url_hash": article.get("url_hash")}
            if not selector["url_hash"]:
                selector = {
                    "title": article.get("title"),
                    "url": article.get("url"),
                }

            payload = dict(article)
            payload.setdefault("click_count", 0)
            payload.setdefault("impression_count", 0)
            payload["last_seen_at"] = now

            result = self.articles.update_one(
                selector,
                {
                    "$setOnInsert": payload,
                    "$set": {"last_seen_at": now},
                },
                upsert=True,
            )

            if result.upserted_id is not None:
                inserted += 1

        return inserted

    def get_recent_articles(self, limit=RECENT_ARTICLES_LIMIT):
        """Mantem compatibilidade com chamadas que pedem apenas os mais recentes."""
        return self.list_articles(limit=limit)

    def list_articles(self, limit=RECENT_ARTICLES_LIMIT, category=None, source_name=None):
        """Lista artigos salvos com filtros simples para API e depuracao."""
        query = {}

        if category:
            query["categories"] = {"$in": [category]}
        if source_name:
            query["source_name"] = source_name

        cursor = (
            self.articles.find(query)
            .sort("published_at", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_profile(self, user_id, categorias):
        """Carrega o perfil persistido ou devolve um perfil vazio para novos usuarios."""
        document = self.user_profiles.find_one({"user_id": user_id})
        preferences = document.get("preferences", {}) if document else {}
        return UserProfile(categorias, preferences=preferences)

    def get_profile_document(self, user_id):
        """Retorna o documento bruto do perfil quando a API precisa de metadados."""
        return self.user_profiles.find_one({"user_id": user_id})

    def save_profile(self, user_id, profile):
        """Persiste o estado agregado de preferencias do usuario."""
        self.user_profiles.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "user_id": user_id,
                    "preferences": profile.preferences,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )

    def get_article_by_id(self, article_id):
        """Busca um artigo pelo ObjectId em rotas de feedback e clique."""
        object_id = self._coerce_object_id(article_id)
        if object_id is None:
            return None

        return self.articles.find_one({"_id": object_id})

    def increment_article_impressions(self, article_ids):
        """Soma impressoes em lote quando um conjunto de itens entra no feed."""
        object_ids = [
            object_id
            for object_id in (self._coerce_object_id(article_id) for article_id in article_ids)
            if object_id is not None
        ]

        if not object_ids:
            return 0

        result = self.articles.update_many(
            {"_id": {"$in": object_ids}},
            {"$inc": {"impression_count": 1}},
        )
        return result.modified_count

    def increment_article_clicks(self, article_id, delta=1):
        """Atualiza o contador de cliques para sinais simples de engajamento."""
        object_id = self._coerce_object_id(article_id)
        if object_id is None:
            return 0

        result = self.articles.update_one(
            {"_id": object_id},
            {"$inc": {"click_count": delta}},
        )
        return result.modified_count

    def record_user_event(self, user_id, article, action, metadata=None):
        """Grava um historico enxuto das interacoes para auditoria e analise futura."""
        payload = {
            "user_id": user_id,
            "action": action,
            "article_id": str(article.get("_id")) if article.get("_id") else None,
            "article_title": article.get("title"),
            "dominant_category": article.get("dominant_category", "Geral"),
            "categories": article.get("categories", []),
            "created_at": datetime.now(timezone.utc),
        }

        if metadata:
            payload["metadata"] = metadata

        self.user_events.insert_one(payload)

    def get_user_events(self, user_id, limit=10):
        """Lista os eventos mais recentes de um usuario."""
        cursor = (
            self.user_events.find({"user_id": user_id})
            .sort("created_at", DESCENDING)
            .limit(limit)
        )
        return list(cursor)

    def get_collection_counts(self):
        """Conta documentos por colecao para uso em healthcheck."""
        return {
            "articles": self.articles.count_documents({}),
            "user_profiles": self.user_profiles.count_documents({}),
            "user_events": self.user_events.count_documents({}),
        }

    def _coerce_object_id(self, value):
        """Converte strings externas em ObjectId sem quebrar o fluxo da API."""
        if isinstance(value, ObjectId):
            return value

        if not value:
            return None

        try:
            return ObjectId(str(value))
        except (InvalidId, TypeError):
            return None

    def close(self):
        """Fecha a conexao com o MongoDB."""
        self.client.close()

    def _build_client(self, uri):
        """Cria um cliente real ou em memoria conforme o modo configurado."""
        if self.use_mock:
            return mongomock.MongoClient(tz_aware=True)

        return MongoClient(
            uri,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )
