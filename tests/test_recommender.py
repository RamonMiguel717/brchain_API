from datetime import datetime, timezone

import pytest

from api.classifier import NewsClassifier
from api.deduplication import NewsDeduplicator
from api.recommender import NewsRecommender
from api.user_profile import UserProfile


# ---------------------------------------------------------------------------
# Helpers / fixtures compartilhados
# ---------------------------------------------------------------------------

def categorias_base() -> list[dict]:
    return [
        {"nome": "Nutrição", "keywords": ["nutrição", "dieta"], "sinonimos": [], "ativa": True, "peso_global": 1.0},
        {"nome": "Sono", "keywords": ["sono", "dormir"], "sinonimos": [], "ativa": True, "peso_global": 1.0},
        {"nome": "Treino", "keywords": ["treino", "exercício"], "sinonimos": [], "ativa": True, "peso_global": 1.0},
    ]


def make_article(title: str, dominant_category: str, strength: float = 0.8) -> dict:
    return {
        "title": title,
        "dominant_category": dominant_category,
        "normalized_category_scores": {dominant_category: 1.0},
        "classifier_strength": strength,
        "published_at": datetime.now(timezone.utc),
        "click_count": 0,
        "impression_count": 0,
    }


class DummyClient:
    async def get_news(self, query: str) -> list:
        return []


class DummyRepository:
    def __init__(self, preferences: dict | None = None):
        self._preferences = preferences or {}
        self._saved_profile = None

    def get_profile(self, user_id: str, categorias: list) -> UserProfile:
        return UserProfile(categorias, preferences=self._preferences)

    def get_recent_dedup_candidates(self) -> list:
        return []

    def upsert_articles(self, articles: list) -> int:
        return len(articles)

    def get_recent_articles(self, limit: int = 100) -> list:
        return []

    def save_profile(self, user_id: str, profile: UserProfile) -> None:
        self._saved_profile = profile


def build_recommender(preferences: dict | None = None) -> NewsRecommender:
    categorias = categorias_base()
    return NewsRecommender(
        DummyClient(),
        NewsClassifier(categorias),
        DummyRepository(preferences=preferences),
        NewsDeduplicator(),
    )


# ---------------------------------------------------------------------------
# UserProfile
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_preferencias_iniciais_sao_zero(self):
        profile = UserProfile(categorias_base())
        assert all(v == 0.0 for v in profile.preferences.values())

    def test_atualizar_gostei_aumenta_score(self):
        profile = UserProfile(categorias_base())
        profile.atualizar({"Sono": 2.0}, "gostei")
        assert profile.preferences["Sono"] > 0

    def test_atualizar_nao_gostei_diminui_score(self):
        profile = UserProfile(categorias_base())
        profile.atualizar({"Sono": 2.0}, "nao_gostei")
        assert profile.preferences["Sono"] < 0

    def test_acao_invalida_levanta_value_error(self):
        profile = UserProfile(categorias_base())
        with pytest.raises(ValueError):
            profile.atualizar({"Sono": 1.0}, "curtir")

    def test_aplicar_decay_reduz_preferencias(self):
        profile = UserProfile(categorias_base(), preferences={"Sono": 10.0, "Treino": 5.0})
        profile.aplicar_decay(fator=0.9)
        assert profile.preferences["Sono"] == pytest.approx(9.0)
        assert profile.preferences["Treino"] == pytest.approx(4.5)

    def test_pesos_normalizados_somam_um(self):
        profile = UserProfile(categorias_base(), preferences={"Nutrição": 5.0, "Sono": 2.0, "Treino": 1.0})
        weights = profile.pesos_normalizados()
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)

    def test_normalizacao_limita_dominancia_de_um_topico(self):
        profile = UserProfile(categorias_base())
        profile.preferences.update({"Nutrição": 500.0, "Sono": 2.0, "Treino": 2.0})
        normalized = dict(profile.ranking())
        assert normalized["Nutrição"] < 0.5
        assert normalized["Sono"] > 0.2
        assert normalized["Treino"] > 0.2

    def test_ranking_ordenado_decrescente(self):
        profile = UserProfile(categorias_base(), preferences={"Nutrição": 3.0, "Sono": 5.0, "Treino": 1.0})
        ranking = profile.ranking()
        scores = [s for _, s in ranking]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# NewsClassifier
# ---------------------------------------------------------------------------

class TestNewsClassifier:
    def test_classificar_noticia_com_keyword(self):
        classifier = NewsClassifier(categorias_base())
        noticia = {"title": "Como o sono profundo afeta a memoria", "description": ""}
        scores = classifier.classificar(noticia)
        assert "Sono" in scores
        assert scores["Sono"] > 0

    def test_classificar_sem_match_retorna_vazio(self):
        classifier = NewsClassifier(categorias_base())
        noticia = {"title": "Resultado do campeonato de futebol", "description": ""}
        scores = classifier.classificar(noticia)
        assert scores == {}

    def test_normalizar_scores_soma_um(self):
        classifier = NewsClassifier(categorias_base())
        scores = {"Sono": 3.0, "Nutrição": 1.0}
        normalized = classifier.normalizar_scores(scores)
        assert sum(normalized.values()) == pytest.approx(1.0)

    def test_normalizar_scores_vazio_retorna_vazio(self):
        classifier = NewsClassifier(categorias_base())
        assert classifier.normalizar_scores({}) == {}

    def test_categoria_principal_escolhe_maior_score(self):
        classifier = NewsClassifier(categorias_base())
        scores = {"Sono": 0.7, "Nutrição": 0.2, "Treino": 0.1}
        assert classifier.categoria_principal_por_scores(scores) == "Sono"

    def test_categoria_principal_sem_scores_retorna_geral(self):
        classifier = NewsClassifier(categorias_base())
        assert classifier.categoria_principal_por_scores({}) == "Geral"


# ---------------------------------------------------------------------------
# NewsRecommender
# ---------------------------------------------------------------------------

class TestNewsRecommender:
    def test_ranking_aplica_diversidade_entre_temas(self):
        recommender = build_recommender({"Nutrição": 100.0, "Sono": 4.0, "Treino": 3.0})
        profile = DummyRepository({"Nutrição": 100.0}).get_profile("u", categorias_base())
        articles = [
            make_article("Nutrição 1", "Nutrição"),
            make_article("Nutrição 2", "Nutrição"),
            make_article("Nutrição 3", "Nutrição"),
            make_article("Sono 1", "Sono"),
            make_article("Treino 1", "Treino"),
        ]
        ranked = recommender.ranquear_timeline(profile, articles, limit=3)
        dominant_categories = [item["dominant_category"] for item in ranked]
        assert dominant_categories[0] == "Nutrição"
        assert len(set(dominant_categories)) >= 2
        assert dominant_categories.count("Nutrição") < 3

    def test_gerar_queries_cold_start_retorna_fallback(self):
        recommender = build_recommender()
        profile = UserProfile(categorias_base())  # perfil zerado
        queries = recommender.gerar_queries(profile)
        assert len(queries) > 0
        # Deve retornar as queries de cold-start, nao uma lista vazia.
        from api.recommender import COLD_START_QUERIES
        assert queries == list(COLD_START_QUERIES)

    def test_gerar_queries_com_preferencias_usa_categorias(self):
        recommender = build_recommender({"Sono": 10.0})
        profile = UserProfile(categorias_base(), preferences={"Sono": 10.0})
        queries = recommender.gerar_queries(profile)
        assert any("sono" in q.lower() or "dormir" in q.lower() for q in queries)

    def test_processar_feedback_aplica_decay(self):
        """Verifica que o decay e chamado (preferencias nao crescem indefinidamente)."""
        repo = DummyRepository({"Sono": 100.0})
        recommender = NewsRecommender(DummyClient(), NewsClassifier(categorias_base()), repo, NewsDeduplicator())
        noticia = {"category_scores": {"Sono": 1.0}}
        recommender.processar_feedback(noticia, "gostei", user_id="u")
        # Apos decay de 0.98 e adicao de 1.0: 100 * 0.98 + 1.0 = 99.0
        saved = repo._saved_profile
        assert saved is not None
        assert saved.preferences["Sono"] == pytest.approx(100.0 * 0.98 + 1.0, rel=1e-3)

    def test_ranquear_feed_vazio_retorna_vazio(self):
        recommender = build_recommender()
        profile = UserProfile(categorias_base())
        result = recommender.ranquear_timeline(profile, [], limit=10)
        assert result == []

    @pytest.mark.asyncio
    async def test_ingestir_noticias_atualiza_last_ingestion(self):
        recommender = build_recommender()
        await recommender.ingestir_noticias(user_id="u")
        assert recommender.last_ingestion["fetched"] == 0
        assert recommender.last_ingestion["inserted"] == 0
