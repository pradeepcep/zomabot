web: gunicorn app:app
worker: celery worker -A app.celery --broker=$CELERY_BROKER_URL
