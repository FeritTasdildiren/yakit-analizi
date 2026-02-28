#!/bin/bash
# Geriye uyumluluk — yeni manage.sh'a yönlendirir
echo "⚠️  Bu script artık kullanılmıyor. Yeni script:"
echo "    bash /var/www/yakit_analiz/scripts/manage.sh restart-celery"
echo ""
exec bash "$(dirname "$0")/scripts/manage.sh" restart-celery
