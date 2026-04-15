from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "saudi_health_hub"
    redis_url: str = "redis://localhost:6379"
    anthropic_api_key: str
    jina_api_key: str
    cors_origins: str = "http://localhost:3000"

    # RAG
    retrieval_top_k: int = 30          # candidates before reranking
    rerank_top_n: int = 7              # passed to LLM after reranking (fewer = higher precision)
    use_hybrid_search: bool = True     # dense+BM25 RRF — sparse vectors already indexed in Qdrant
    llm_model: str = "claude-sonnet-4-6"
    embed_cache_ttl: int = 3600        # seconds to cache query embeddings in Redis

    # Auth
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 1 week

    class Config:
        env_file = (".env", "../.env")
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
