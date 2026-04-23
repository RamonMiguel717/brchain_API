from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from api.app import create_app
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
)


def _article_payload(article_id: str = "article-1") -> dict:
    return {
        "id": article_id,
        "title": "Sono melhora a saude mental",
        "description": "Resumo",
        "content": None,
        "url": f"https://example.com/{article_id}",
        "source_name": "Example",
        "published_at": datetime.now(timezone.utc),
        "categories": ["Sono"],
        "dominant_category": "Sono",
        "score": 0.9,
        "raw_score": 0.91,
        "click_count": 2,
        "impression_count": 5,
        "normalized_category_scores": {"Sono": 1.0},
    }


class FakeService:
    def healthcheck(self) -> HealthResponse:
        return HealthResponse(
            status="ok",
            mongodb="connected",
            checked_at=datetime.now(timezone.utc),
            collections={"articles": 3, "user_profiles": 1, "user_events": 2},
        )

    async def get_feed(self, user_id, limit, refresh) -> FeedResponse:
        return FeedResponse(
            user_id=user_id,
            limit=limit,
            refresh=refresh,
            generated_at=datetime.now(timezone.utc),
            ingestion=IngestionStatsResponse(fetched=10, unique=7, inserted=4),
            items=[ArticleResponse(**_article_payload())],
        )

    async def ingest(self, user_id) -> IngestionResponse:
        return IngestionResponse(
            user_id=user_id,
            stats=IngestionStatsResponse(fetched=10, unique=8, inserted=5),
            executed_at=datetime.now(timezone.utc),
        )

    def list_articles(self, limit, category, source_name) -> ArticleListResponse:
        return ArticleListResponse(limit=limit, category=category, source_name=source_name, items=[])

    def get_profile(self, user_id, events_limit) -> ProfileResponse:
        return ProfileResponse(
            user_id=user_id,
            preferences={"Sono": 2.0},
            normalized_preferences={"Sono": 1.0},
            updated_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            recent_events=[],
        )

    def submit_feedback(self, user_id, article_id, action) -> FeedbackResponse:
        return FeedbackResponse(
            user_id=user_id,
            article_id=article_id,
            action=action,
            dominant_category="Sono",
            ranking=[RankingEntryResponse(category="Sono", score=0.8)],
            updated_at=datetime.now(timezone.utc),
        )

    def close(self) -> None:
        pass


@pytest.fixture()
def client():
    with TestClient(create_app(FakeService())) as c:
        yield c


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mongodb"] == "connected"


def test_feed_endpoint(client):
    response = client.get("/feed/user-123?limit=5&refresh=true")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "user-123"
    assert payload["limit"] == 5
    assert payload["refresh"] is True
    assert payload["items"][0]["dominant_category"] == "Sono"


def test_feed_default_limit(client):
    response = client.get("/feed/user-abc")
    assert response.status_code == 200


def test_ingest_endpoint(client):
    response = client.post("/ingest?user_id=demo-user")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == "demo-user"
    assert payload["stats"]["fetched"] == 10


def test_articles_endpoint(client):
    response = client.get("/articles?limit=10")
    assert response.status_code == 200
    assert "items" in response.json()


def test_articles_with_category_filter(client):
    response = client.get("/articles?category=Sono")
    assert response.status_code == 200


def test_profile_endpoint(client):
    response = client.get("/profiles/user-123")
    assert response.status_code == 200
    assert response.json()["preferences"]["Sono"] == 2.0


def test_feedback_gostei(client):
    response = client.post(
        "/feed/user-123/feedback",
        json={"article_id": "article-1", "action": "gostei"},
    )
    assert response.status_code == 200
    assert response.json()["action"] == "gostei"


def test_feedback_nao_gostei(client):
    response = client.post(
        "/feed/user-123/feedback",
        json={"article_id": "article-1", "action": "nao_gostei"},
    )
    assert response.status_code == 200
    assert response.json()["action"] == "nao_gostei"


def test_feedback_acao_invalida(client):
    response = client.post(
        "/feed/user-123/feedback",
        json={"article_id": "article-1", "action": "curtir"},
    )
    assert response.status_code == 422


def test_click_endpoint(client):
    response = client.post(
        "/feed/user-123/click",
        json={"article_id": "article-1"},
    )
    assert response.status_code == 200
    assert response.json()["action"] == "gostei"


def test_cors_headers_present(client):
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert "access-control-allow-origin" in response.headers
