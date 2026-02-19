#!/bin/bash
cd /var/www/yakit_analiz
export PYTHONPATH=/var/www/yakit_analiz
exec .venv/bin/streamlit run dashboard/app.py --server.port 8101 --server.address 127.0.0.1 --server.headless true
