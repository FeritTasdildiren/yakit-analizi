#!/bin/bash
# ============================================================================
# Yakıt Analizi — Servis Yönetim Scripti
# Kullanım:
#   bash manage.sh start        — Tüm servisleri başlat
#   bash manage.sh stop         — Tüm servisleri durdur
#   bash manage.sh restart      — Durdur + başlat
#   bash manage.sh status       — Servis durumlarını göster
#   bash manage.sh restart-celery — Sadece Celery'yi yeniden başlat
# ============================================================================

set -euo pipefail

PROJECT_DIR="/var/www/yakit_analiz"
VENV="$PROJECT_DIR/.venv/bin"
PID_DIR="$PROJECT_DIR/pids"
LOG_DIR="/var/log"

mkdir -p "$PID_DIR"

# PID dosyaları
API_PID="$PID_DIR/api.pid"
DASHBOARD_PID="$PID_DIR/dashboard.pid"
CELERY_PID="$PID_DIR/celery.pid"

# ── Yardımcı fonksiyonlar ────────────────────────────────────────────────────

stop_service() {
    local name="$1"
    local pidfile="$2"

    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "[$name] Durduruluyor (PID=$pid)..."
            # Önce SIGTERM ile nazikçe sor
            kill "$pid" 2>/dev/null || true
            # 5 saniye bekle
            for i in $(seq 1 5); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    echo "[$name] Durduruldu."
                    rm -f "$pidfile"
                    return 0
                fi
                sleep 1
            done
            # Hâlâ yaşıyorsa SIGKILL
            echo "[$name] SIGTERM yetmedi, SIGKILL gönderiliyor..."
            kill -9 "$pid" 2>/dev/null || true
            sleep 1
            rm -f "$pidfile"
            echo "[$name] Zorla durduruldu."
        else
            echo "[$name] PID=$pid artık çalışmıyor, PID dosyası temizleniyor."
            rm -f "$pidfile"
        fi
    else
        echo "[$name] PID dosyası yok, çalışmıyor."
    fi
}

stop_celery() {
    # Celery özel: child process'ler var, PID grubu olarak öldür
    local pidfile="$CELERY_PID"

    if [ -f "$pidfile" ]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            echo "[Celery] Durduruluyor (PID=$pid + children)..."
            # Process grubunun tamamını SIGTERM ile durdur
            kill -- -"$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
            for i in $(seq 1 5); do
                if ! kill -0 "$pid" 2>/dev/null; then
                    echo "[Celery] Durduruldu."
                    rm -f "$pidfile"
                    # Arta kalan orphan'ları temizle
                    _cleanup_orphan_celery
                    return 0
                fi
                sleep 1
            done
            # SIGKILL
            echo "[Celery] SIGTERM yetmedi, SIGKILL gönderiliyor..."
            kill -9 -- -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
            sleep 1
            rm -f "$pidfile"
            _cleanup_orphan_celery
            echo "[Celery] Zorla durduruldu."
        else
            echo "[Celery] PID=$pid artık çalışmıyor, temizleniyor."
            rm -f "$pidfile"
            _cleanup_orphan_celery
        fi
    else
        echo "[Celery] PID dosyası yok."
        _cleanup_orphan_celery
    fi
}

_cleanup_orphan_celery() {
    # PID dosyası dışında kalan orphan celery process'lerini temizle
    local orphans
    orphans=$(pgrep -f "celery.*celery_config" 2>/dev/null || true)
    if [ -n "$orphans" ]; then
        echo "[Celery] Orphan process'ler bulundu: $orphans"
        echo "$orphans" | while read -r opid; do
            kill -9 "$opid" 2>/dev/null || true
        done
        sleep 1
        echo "[Celery] Orphan'lar temizlendi."
    fi
}

start_api() {
    if [ -f "$API_PID" ] && kill -0 "$(cat "$API_PID")" 2>/dev/null; then
        echo "[API] Zaten çalışıyor (PID=$(cat "$API_PID"))"
        return 0
    fi

    echo "[API] Başlatılıyor (port 8100)..."
    cd "$PROJECT_DIR"
    export PYTHONPATH="$PROJECT_DIR"
    nohup "$VENV/uvicorn" src.main:app \
        --host 127.0.0.1 --port 8100 --workers 1 \
        >> "$LOG_DIR/yakit_api.log" 2>&1 &
    echo $! > "$API_PID"
    echo "[API] Başlatıldı (PID=$!)"
}

start_dashboard() {
    if [ -f "$DASHBOARD_PID" ] && kill -0 "$(cat "$DASHBOARD_PID")" 2>/dev/null; then
        echo "[Dashboard] Zaten çalışıyor (PID=$(cat "$DASHBOARD_PID"))"
        return 0
    fi

    echo "[Dashboard] Başlatılıyor (port 8101)..."
    cd "$PROJECT_DIR"
    export PYTHONPATH="$PROJECT_DIR"
    nohup "$VENV/streamlit" run dashboard/app.py \
        --server.port 8101 --server.address 127.0.0.1 --server.headless true \
        >> "$LOG_DIR/yakit_dashboard.log" 2>&1 &
    echo $! > "$DASHBOARD_PID"
    echo "[Dashboard] Başlatıldı (PID=$!)"
}

start_celery() {
    if [ -f "$CELERY_PID" ] && kill -0 "$(cat "$CELERY_PID")" 2>/dev/null; then
        echo "[Celery] Zaten çalışıyor (PID=$(cat "$CELERY_PID"))"
        return 0
    fi

    # Eski schedule dosyalarını temizle
    rm -f "$PROJECT_DIR/celerybeat-schedule"*
    rm -f "$PROJECT_DIR/celerybeat.pid"

    echo "[Celery] Başlatılıyor (worker + beat)..."
    cd "$PROJECT_DIR"
    export PYTHONPATH="$PROJECT_DIR"
    # setsid ile yeni session grubu oluştur — SSH'dan bağımsız
    setsid "$VENV/celery" -A src.celery_app.celery_config:celery_app \
        worker --beat --loglevel=info --concurrency=2 \
        >> "$LOG_DIR/celery_yakit.log" 2>&1 &
    echo $! > "$CELERY_PID"
    echo "[Celery] Başlatıldı (PID=$!)"
}

show_status() {
    echo "════════════════════════════════════════"
    echo "  Yakıt Analizi Servis Durumu"
    echo "════════════════════════════════════════"

    for svc in API:$API_PID Dashboard:$DASHBOARD_PID Celery:$CELERY_PID; do
        local name="${svc%%:*}"
        local pidfile="${svc#*:}"
        if [ -f "$pidfile" ]; then
            local pid
            pid=$(cat "$pidfile")
            if kill -0 "$pid" 2>/dev/null; then
                echo "  ✅ $name — çalışıyor (PID=$pid)"
            else
                echo "  ❌ $name — PID=$pid ölü (stale PID dosyası)"
            fi
        else
            echo "  ⚫ $name — çalışmıyor"
        fi
    done

    # Orphan kontrol
    local celery_count
    celery_count=$(pgrep -cf "celery.*celery_config" 2>/dev/null || echo 0)
    echo ""
    echo "  Celery process sayısı: $celery_count (beklenen: 4)"
    echo "════════════════════════════════════════"
}

# ── Ana komut ────────────────────────────────────────────────────────────────

case "${1:-help}" in
    start)
        start_api
        start_dashboard
        start_celery
        sleep 3
        show_status
        ;;
    stop)
        stop_service "API" "$API_PID"
        stop_service "Dashboard" "$DASHBOARD_PID"
        stop_celery
        echo "Tüm servisler durduruldu."
        ;;
    restart)
        echo "=== Durduruluyor ==="
        stop_service "API" "$API_PID"
        stop_service "Dashboard" "$DASHBOARD_PID"
        stop_celery
        sleep 2
        echo ""
        echo "=== Başlatılıyor ==="
        start_api
        start_dashboard
        start_celery
        sleep 3
        show_status
        ;;
    restart-celery)
        stop_celery
        sleep 2
        start_celery
        sleep 3
        show_status
        ;;
    status)
        show_status
        ;;
    *)
        echo "Kullanım: bash manage.sh {start|stop|restart|restart-celery|status}"
        exit 1
        ;;
esac
