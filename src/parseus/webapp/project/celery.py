import os

from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "parseus.webapp.project.settings")

app = Celery(__name__)

# Load task modules from all registered Django app configs.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.update(broker_connection_retry_on_startup=True)
app.autodiscover_tasks()
