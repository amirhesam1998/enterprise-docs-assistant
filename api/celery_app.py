"""Celery app for asynchronous document ingestion.

Runtime configuration comes from api.config like every other api module, rather
than being read from the environment here — one place defines a setting.
"""
from celery import Celery

from api.config import REDIS_URL

celery_app = Celery(
    "eda",
    broker=REDIS_URL,       # کارها به اینجا می‌روند
    backend=REDIS_URL,      # نتیجه‌ها اینجا ذخیره می‌شوند
    include=["api.tasks"],
)

celery_app.conf.update(
    task_track_started=True,       # وضعیت "started" را هم ثبت کن
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
