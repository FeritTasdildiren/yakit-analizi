#!/bin/bash
cd /var/www/yakit_analiz
export PYTHONPATH=/var/www/yakit_analiz
exec .venv/bin/celery -A src.celery_app.celery_config:celery_app worker --beat --loglevel=info --concurrency=2
