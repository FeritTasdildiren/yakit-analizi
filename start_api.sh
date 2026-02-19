#!/bin/bash
cd /var/www/yakit_analiz
export PYTHONPATH=/var/www/yakit_analiz
exec .venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8100 --workers 1
