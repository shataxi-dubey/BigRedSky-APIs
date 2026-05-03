"""Celery application configuration and initialization."""

from celery import Celery
from celery.signals import worker_process_init

from app import settings

redis_url = (
    f"redis://:{settings.REDIS_PASSWORD}@{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"
)

celery_app = Celery(
    "fastapi_app",
    broker=redis_url,
    backend=redis_url,
    include=[
        "app.tasks.resume.resume_task",
        "app.tasks.ranking.ranking_task",
    ],
)

# Recommended Celery configuration
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes
    result_expires=3600,  # 1 hour
)


@worker_process_init.connect
def preload_models(**kwargs):
    from app.tasks.resume.resume_task import _get_dense_model, _get_sparse_model
    _get_dense_model()
    _get_sparse_model()
