"""
Celery application instance.

All tasks import from here so there is a single shared app object.
The broker and backend both use Redis (already running in docker-compose).
"""
from celery import Celery
from pipeline.config import get_settings


def _make_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "saudi_health_hub",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=["pipeline.tasks.pipeline_tasks"],
    )
    app.config_from_object("pipeline.tasks.celery_config")
    return app


celery_app = _make_app()
