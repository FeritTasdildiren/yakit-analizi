#!/bin/bash
# Celery Worker + Beat başlatma scripti.
#
# Kullanım:
#   chmod +x src/scripts/start_worker.sh
#   ./src/scripts/start_worker.sh
#
# Worker: Zamanlanmış görevleri çalıştırır (2 concurrent process)
# Beat: Crontab zamanlamasına göre görevleri tetikler

set -e

echo "=== Yakıt Analizi — Celery Pipeline ==="
echo "Başlatılıyor: $(date)"

# Worker başlat (arka planda)
echo "Worker başlatılıyor..."
celery -A src.celery_app.celery_config worker \
    --loglevel=info \
    --concurrency=2 \
    --queues=data_collection,ml_prediction,notifications,default \
    -n worker@%h &

WORKER_PID=$!
echo "Worker PID: $WORKER_PID"

# Beat başlat (arka planda)
echo "Beat zamanlayıcı başlatılıyor..."
celery -A src.celery_app.celery_config beat \
    --loglevel=info &

BEAT_PID=$!
echo "Beat PID: $BEAT_PID"

echo ""
echo "Celery Worker ve Beat başlatıldı."
echo "  Worker PID: $WORKER_PID"
echo "  Beat PID:   $BEAT_PID"
echo ""
echo "Durdurmak için: kill $WORKER_PID $BEAT_PID"

# Her iki process'i de bekle
wait $WORKER_PID $BEAT_PID
