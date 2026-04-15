from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "saudi_health_hub"
    redis_url: str = "redis://localhost:6379"
    jina_api_key: str = ""
    anthropic_api_key: str = ""

    # Chunking
    chunk_size: int = 512
    chunk_overlap: int = 64
    max_chunks_per_doc: int = 2000

    # Embedding
    embedding_model: str = "jina-embeddings-v3"
    embedding_batch_size: int = 96
    bm25_model: str = "Qdrant/bm25"

    class Config:
        env_file = (".env", "../.env")  # works from both project root and pipeline/
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
