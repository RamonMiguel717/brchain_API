import math
from collections import Counter
from datetime import datetime, timezone

from api.config import (
    DEFAULT_USER_ID,
    FRESHNESS_HALF_LIFE_HOURS,
    RECENT_ARTICLES_LIMIT,
    TOPIC_DIVERSITY_PENALTY,
    TOP_QUERY_CATEGORIES,
)

# Queries de fallback usadas quando o perfil do usuario ainda esta vazio (cold-start).
COLD_START_QUERIES = [
    "saude bem-estar",
    "nutricao alimentacao",
    "exercicio atividade fisica",
]


class NewsRecommender:
    """Concentra ingestao, enriquecimento e ranking final da timeline."""

    def __init__(self, client, classifier, repository, deduplicator):
        self.client = client
        self.classifier = classifier
        self.repository = repository
        self.deduplicator = deduplicator
        self.last_ingestion: dict = {
            "fetched": 0,
            "unique": 0,
            "inserted": 0,
        }

    def gerar_queries(self, user_profile, top_n: int = TOP_QUERY_CATEGORIES) -> list[str]:
        """Transforma os temas mais fortes do usuario em consultas para a GNews.

        Quando o perfil esta vazio ou sem preferencias claras, retorna queries
        de cold-start genericas para garantir que o feed nunca chegue vazio.
        """
        ranking = user_profile.ranking()

        # Detecta cold-start: todos os scores sao identicos (perfil virgem).
        scores = [score for _, score in ranking]
        is_cold_start = len(set(round(s, 6) for s in scores)) <= 1

        if is_cold_start:
            return list(COLD_START_QUERIES)

        queries = []
        for categoria_nome, _ in ranking[:top_n]:
            categoria_obj = next(
                (c for c in self.classifier.categorias if c["nome"] == categoria_nome),
                None,
            )
            if not categoria_obj:
                continue

            keywords = categoria_obj["keywords"][:3]
            if keywords:
                queries.append(" OR ".join(keywords))

        return queries or list(COLD_START_QUERIES)

    async def buscar_noticias(self, user_id: str = DEFAULT_USER_ID, limit: int = 10, refresh: bool = True) -> list[dict]:
        """Busca o feed pronto do usuario e opcionalmente roda ingestao antes."""
        user_profile = self.repository.get_profile(user_id, self.classifier.categorias)

        if refresh:
            await self._ingestir_noticias(user_profile)

        recent_articles = self.repository.get_recent_articles(limit=max(limit * 5, RECENT_ARTICLES_LIMIT))
        return self.ranquear_timeline(user_profile, recent_articles, limit=limit)

    async def ingestir_noticias(self, user_id: str = DEFAULT_USER_ID) -> dict:
        """Expoe a ingestao para chamadas externas mantendo estatisticas da ultima rodada."""
        user_profile = self.repository.get_profile(user_id, self.classifier.categorias)
        await self._ingestir_noticias(user_profile)
        return dict(self.last_ingestion)

    async def _ingestir_noticias(self, user_profile) -> None:
        """Consulta a fonte, elimina duplicatas, enriquece e persiste os artigos novos."""
        queries = self.gerar_queries(user_profile)
        fetched_articles: list[dict] = []

        for query in queries:
            fetched_articles.extend(await self.client.get_news(query=query))

        known_articles = self.repository.get_recent_dedup_candidates()
        unique_articles = self.deduplicator.deduplicate(fetched_articles, known_articles)
        enriched_articles = [self._enrich_article(article) for article in unique_articles]
        inserted = self.repository.upsert_articles(enriched_articles)

        self.last_ingestion = {
            "fetched": len(fetched_articles),
            "unique": len(unique_articles),
            "inserted": inserted,
        }

    def _enrich_article(self, article: dict) -> dict:
        """Completa a noticia crua com metadados usados pelo ranking e pela API."""
        category_scores = self.classifier.classificar(article)
        normalized_category_scores = self.classifier.normalizar_scores(category_scores)
        dominant_category = self.classifier.categoria_principal_por_scores(category_scores)
        published_at = self._parse_datetime(article.get("publishedAt"))
        now = datetime.now(timezone.utc)

        return {
            "title": article.get("title"),
            "description": article.get("description"),
            "content": article.get("content"),
            "url": article.get("url"),
            "url_normalized": article.get("url_normalized"),
            "url_hash": article.get("url_hash"),
            "image": article.get("image"),
            "source": article.get("source"),
            "source_name": (article.get("source") or {}).get("name"),
            "published_at": published_at,
            "publishedAt": article.get("publishedAt"),
            "title_tokens": article.get("title_tokens", []),
            "category_scores": category_scores,
            "normalized_category_scores": normalized_category_scores,
            "categories": list(category_scores.keys()) or [dominant_category],
            "dominant_category": dominant_category,
            "classifier_strength": self._classifier_strength(category_scores),
            "created_at": now,
            "last_seen_at": now,
        }

    def _classifier_strength(self, category_scores: dict[str, float]) -> float:
        """Comprime a forca do classificador para um intervalo estavel de ranking."""
        total = sum(category_scores.values())
        if total <= 0:
            return 0.0
        return total / (total + 3)

    def _freshness_score(self, published_at) -> float:
        """Calcula decaimento temporal usando meia-vida configuravel."""
        published_at = self._parse_datetime(published_at)
        age_seconds = max((datetime.now(timezone.utc) - published_at).total_seconds(), 0)
        age_hours = age_seconds / 3600
        return math.exp(-(math.log(2) * age_hours) / max(FRESHNESS_HALF_LIFE_HOURS, 1))

    def _topic_match_score(self, article: dict, user_weights: dict[str, float]) -> float:
        """Mede o encaixe entre o artigo e as preferencias atuais do usuario."""
        normalized_category_scores = article.get("normalized_category_scores") or {}
        if normalized_category_scores:
            return sum(
                user_weights.get(category, 0.0) * weight
                for category, weight in normalized_category_scores.items()
            )

        dominant_category = article.get("dominant_category")
        if dominant_category:
            return user_weights.get(dominant_category, 0.0)

        return 0.0

    def _base_score(self, article: dict, user_weights: dict[str, float]) -> float:
        """Combina afinidade, classificacao, recencia e engajamento num score base."""
        topic_match = self._topic_match_score(article, user_weights)
        freshness = self._freshness_score(article.get("published_at"))
        strength = article.get("classifier_strength", 0.0)
        engagement = self._engagement_score(article)

        return (
            (topic_match * 0.50) +
            (strength * 0.20) +
            (freshness * 0.20) +
            (engagement * 0.10)
        )

    def _engagement_score(self, article: dict) -> float:
        """Extrai um sinal leve de popularidade a partir de impressoes e cliques."""
        impressions = max(int(article.get("impression_count", 0) or 0), 0)
        clicks = max(int(article.get("click_count", 0) or 0), 0)

        if impressions <= 0:
            return min(clicks / 5, 1.0) * 0.5

        ctr = clicks / impressions
        magnitude = min(clicks / 20, 0.25)
        return min((ctr * 0.75) + magnitude, 1.0)

    def ranquear_timeline(self, user_profile, articles: list[dict], limit: int = 10) -> list[dict]:
        """Monta o feed final aplicando diversidade para evitar monopolio de tema."""
        user_weights = user_profile.pesos_normalizados()
        scored_articles = []

        for article in articles:
            article_copy = dict(article)
            article_copy["raw_score"] = self._base_score(article_copy, user_weights)
            scored_articles.append(article_copy)

        remaining = sorted(
            scored_articles,
            key=lambda article: article["raw_score"],
            reverse=True,
        )

        selected: list[dict] = []
        exposures: Counter = Counter()

        while remaining and len(selected) < limit:
            best_index = 0
            best_score = -1.0

            for index, article in enumerate(remaining):
                dominant_category = article.get("dominant_category") or "Geral"
                diversity_factor = 1 / (1 + (exposures[dominant_category] * TOPIC_DIVERSITY_PENALTY))
                consecutive_factor = (
                    0.85
                    if selected and dominant_category == selected[-1].get("dominant_category")
                    else 1.0
                )
                adjusted_score = article["raw_score"] * diversity_factor * consecutive_factor

                if adjusted_score > best_score:
                    best_score = adjusted_score
                    best_index = index

            chosen = dict(remaining.pop(best_index))
            chosen["score"] = round(best_score, 4)
            chosen["raw_score"] = round(chosen["raw_score"], 4)
            selected.append(chosen)
            exposures[chosen.get("dominant_category") or "Geral"] += 1

        return selected

    def processar_feedback(self, noticia: dict, acao: str, user_id: str = DEFAULT_USER_ID) -> list[tuple[str, float]]:
        """Atualiza o perfil do usuario com base no feedback explicito recebido.

        Aplica decay antes de atualizar para que preferencias antigas nao
        dominem indefinidamente o perfil.
        """
        user_profile = self.repository.get_profile(user_id, self.classifier.categorias)
        category_scores = noticia.get("category_scores") or self.classifier.classificar(noticia)

        # Decay suave antes de cada atualizacao para evitar perfis congelados.
        user_profile.aplicar_decay(fator=0.98)
        user_profile.atualizar(category_scores, acao)
        self.repository.save_profile(user_id, user_profile)
        return user_profile.ranking()

    def _parse_datetime(self, value) -> datetime:
        """Normaliza datas vindas da API ou do banco para UTC."""
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)

        if not value:
            return datetime.now(timezone.utc)

        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)
