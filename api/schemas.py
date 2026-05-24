from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestionStatsResponse(BaseModel):
    fetched: int
    unique: int
    inserted: int


class ArticleResponse(BaseModel):
    id: str
    title: str | None = None
    description: str | None = None
    content: str | None = None
    url: str | None = None
    image: str | None = None          # ← URL da imagem de capa da notícia
    source_name: str | None = None
    published_at: datetime | None = None
    categories: list[str] = Field(default_factory=list)
    dominant_category: str = "Geral"
    score: float | None = None
    raw_score: float | None = None
    click_count: int = 0
    impression_count: int = 0
    normalized_category_scores: dict[str, float] = Field(default_factory=dict)


class ArticleListResponse(BaseModel):
    limit: int
    category: str | None = None
    source_name: str | None = None
    items: list[ArticleResponse] = Field(default_factory=list)


class FeedResponse(BaseModel):
    user_id: str
    limit: int
    refresh: bool
    generated_at: datetime
    ingestion: IngestionStatsResponse
    items: list[ArticleResponse] = Field(default_factory=list)


class IngestionResponse(BaseModel):
    user_id: str
    stats: IngestionStatsResponse
    executed_at: datetime


class ClickRequest(BaseModel):
    article_id: str


class FeedbackRequest(BaseModel):
    article_id: str
    action: Literal["gostei", "nao_gostei"]


class RankingEntryResponse(BaseModel):
    category: str
    score: float


class FeedbackResponse(BaseModel):
    user_id: str
    article_id: str
    action: str
    dominant_category: str
    ranking: list[RankingEntryResponse] = Field(default_factory=list)
    updated_at: datetime


class UserEventResponse(BaseModel):
    id: str
    action: str | None = None
    article_id: str | None = None
    article_title: str | None = None
    dominant_category: str | None = None
    categories: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProfileResponse(BaseModel):
    user_id: str
    preferences: dict[str, float] = Field(default_factory=dict)
    normalized_preferences: dict[str, float] = Field(default_factory=dict)
    updated_at: datetime | None = None
    created_at: datetime | None = None
    recent_events: list[UserEventResponse] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    mongodb: str
    checked_at: datetime
    collections: dict[str, int] = Field(default_factory=dict)
