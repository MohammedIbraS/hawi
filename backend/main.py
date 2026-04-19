from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from qdrant_client import AsyncQdrantClient

from backend.config import get_settings
from backend.api.routes import chat, documents, auth, sessions, feedback
from backend.services.rag import RAGService


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Saudi Health Hub API")
    # Create service singletons once — shared across all requests
    rag = RAGService()
    app.state.rag = rag
    yield
    # Clean shutdown: close persistent HTTP connections
    await rag.retrieval.close()
    logger.info("Shutting down")


app = FastAPI(
    title="Saudi Health Hub API",
    description="AI-powered search across Saudi Arabian open healthcare data",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/full")
async def health_full():
    """Check connectivity to all external dependencies."""
    results: dict[str, dict] = {}

    # Qdrant
    try:
        qdrant = AsyncQdrantClient(url=settings.qdrant_url)
        info = await qdrant.get_collection(settings.qdrant_collection)
        results["qdrant"] = {"status": "ok", "vectors": info.points_count}
    except Exception as e:
        results["qdrant"] = {"status": "error", "detail": str(e)}

    # Jina (embeddings)
    async with httpx.AsyncClient(timeout=10) as http:
        try:
            resp = await http.post(
                "https://api.jina.ai/v1/embeddings",
                headers={"Authorization": f"Bearer {settings.jina_api_key}"},
                json={
                    "model": "jina-embeddings-v3",
                    "input": ["health check"],
                    "task": "retrieval.query",
                    "dimensions": 1024,
                },
            )
            resp.raise_for_status()
            dims = len(resp.json()["data"][0]["embedding"])
            results["jina"] = {"status": "ok", "embedding_dims": dims}
        except Exception as e:
            results["jina"] = {"status": "error", "detail": str(e)}

    # Anthropic
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        await client.messages.create(
            model=settings.llm_model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        results["anthropic"] = {"status": "ok", "model": settings.llm_model}
    except Exception as e:
        results["anthropic"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(v["status"] == "ok" for v in results.values()) else "degraded"
    return {"status": overall, "services": results}
