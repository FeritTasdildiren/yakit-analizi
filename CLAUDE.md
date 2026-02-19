# CLAUDE.md - Yakıt Analizi Proje Kayıt Dosyası

> Bu dosya projenin "hafızası"dır. Orkestrasyon sırasında ve sonrasında bağımsız geliştirme için kullanılır.

---

## Proje Hafıza Sistemi

**Bu projeye devam eden her LLM ve geliştirici aşağıdaki 3 dosyayı birlikte kullanmak ZORUNDADIR:**

| Dosya | Konum | Amaç | Güncelleme Sıklığı |
|-------|-------|------|-------------------|
| **CLAUDE.md** | `CLAUDE.md` | Projenin güncel durumu, talimatlar, teknik dokümantasyon | Her yeni özellik, endpoint, bağımlılık, mimari değişiklikte |
| **reports.md** | `reports.md` | İş bazlı kronolojik kayıt (ne yapıldı, ne zaman) | Her işe başlarken, devam ederken ve bitirince |
| **experience.md** | `experience.md` | Birikimli tecrübe ve öğrenimler (kararlar, hatalar, pattern'ler) | Her görev tamamlandığında |

**Başlangıç Prosedürü (her oturum başında):**
1. `CLAUDE.md`'yi oku — projeyi, kuralları ve güncel durumu öğren
2. `reports.md`'yi oku — son yapılan işi ve yarım kalan şeyleri kontrol et
3. `experience.md`'yi oku — önceki tecrübelerden faydalan, aynı hataları tekrarlama

---

## Proje Bilgileri

| Alan | Değer |
|------|-------|
| **Proje Adı** | Yakıt Analizi — Türkiye Akaryakıt Zam Öngörü Sistemi |
| **Açıklama** | Akaryakıt fiyat değişimlerini önceden tahmin eden erken uyarı ve maliyet optimizasyon sistemi. Brent petrol, USD/TRY döviz kuru, EPDK pompa fiyatları, ÖTV ve MBE (Maliyet Baz Etki) analiziyle yakıt zamlarını 1-3 gün önceden tespit eder. |
| **Oluşturma Tarihi** | 2026-02-15 |
| **Teslim Tarihi** | 2026-02-20 |
| **Teknoloji Stack** | Python 3.13, FastAPI, Streamlit, Celery+Redis, PostgreSQL, LightGBM, python-telegram-bot |
| **Proje Durumu** | TESLİM EDİLDİ |
| **Son Güncelleme** | 2026-02-20 |
| **Toplam Görev** | 80 (TASK-001 ~ TASK-080) |
| **Toplam Sprint** | 21 (S0 ~ S21) |
| **GitHub** | https://github.com/FeritTasdildiren/yakit-analizi |

---

## Teknoloji Kararları

| Teknoloji | Seçim | Gerekçe |
|-----------|-------|---------|
| Backend API | FastAPI (Python 3.13) | Async I/O, otomatik OpenAPI, Pydantic v2 doğrulama |
| Dashboard | Streamlit | Hızlı prototipleme, data viz, admin paneli için ideal |
| ML Model | LightGBM | Hızlı eğitim, az veriyle iyi performans, SHAP uyumu |
| ML Pipeline | v5 (2 aşamalı: Stage-1 sınıflandırma + Stage-2 regresyon) | Purged walk-forward CV, Platt/Beta kalibrasyon |
| Veritabanı | PostgreSQL 16 (port 5433) | Async (asyncpg), güçlü JSON/time series desteği |
| ORM | SQLAlchemy 2.0 (async) | Modern async session, Alembic migration |
| Task Queue | Celery + Redis | Periyodik veri toplama, tahmin, bildirim pipeline |
| Bot | python-telegram-bot v21 | Async, ConversationHandler, ReplyKeyboard |
| Veri Kaynakları | EPDK (PO scraping), Yahoo Finance (Brent), TCMB (FX) | 3 katmanlı fallback, WAF bypass |
| Deployment | PM2 (3 process) | API + Celery + Dashboard ayrı yönetim |

---

## Mimari Kararlar

### 5 Katmanlı Mimari
1. **Katman 1 — Veri Toplama**: Brent petrol, USD/TRY, EPDK pompa fiyatları, ÖTV oranları
2. **Katman 2 — MBE Hesaplama**: Maliyet Baz Etkisi (cost_base, mbe_value, mbe_components)
3. **Katman 3 — Risk/Eşik Motoru**: Risk skoru, eşik yönetimi (hysteresis), politik gecikme state machine
4. **Katman 4 — ML Tahmin (v5)**: LightGBM 3-class sınıflandırma → regresyon, SHAP, circuit breaker
5. **Katman 5 — Sunum**: Telegram Bot + Streamlit Dashboard + API

### MBE (Maliyet Baz Etkisi) Formülü
```
cost_base = (brent_usd × usd_try × çevrim_katsayısı + ÖTV) × (1 + KDV)
mbe_value = (pump_price - cost_base) / cost_base × 100
```
- MBE > 0: Kâr marjı yüksek (zam baskısı düşük)
- MBE < 0: Maliyet baskısı (zam riski yüksek)

### Streak-Based Sinyal Sistemi (Telegram Bot)
- predictions_v5 tablosundan ardışık gün sinyali sayılır
- 0 gün sinyal → Sabit (değişim beklenmiyor)
- 1 gün → %33 olasılık
- 2 gün ardışık → %66 olasılık
- 3+ gün ardışık → %99 olasılık
- Beklenen tutar = streak günlerinin first_event_amount ortalaması

---

## Geliştirme Kuralları

### Görev Yaşam Döngüsü Kaydı
1. **İŞ ÖNCESİ**: Görev `reports.md`'ye `PLANLANMIŞ` olarak eklenir
2. **İŞ BAŞLANDIĞINDA**: Durum `DEVAM EDİYOR` güncellenir
3. **İŞ TAMAMLANDIĞINDA**: Durum `TAMAMLANDI` güncellenir
4. **SORUN ÇIKTIĞINDA**: Durum `BLOKE` güncellenir

### Çalışma Raporu Sistemi (reports.md) — ZORUNLU

Proje üzerinde yapılan **her değişiklik** kayıt altına alınmalıdır.

#### Kayıt Formatı
```markdown
## [RAPOR-XXX] Kısa Başlık
| Alan | Değer |
|------|-------|
| **Durum** | BAŞLANDI / DEVAM EDİYOR / TAMAMLANDI / BAŞARISIZ |
| **Başlangıç** | YYYY-MM-DD HH:MM |
| **Bitiş** | YYYY-MM-DD HH:MM |
| **Etkilenen Dosyalar** | dosya1.py, dosya2.py |

### Yapılanlar
- [x] Tamamlanan adım
### Kararlar ve Notlar
- Neden X tercih edildi?
### Sonuç
İşin son durumu.
```

### Tecrübe Kayıt Sistemi (experience.md) — ZORUNLU

```markdown
## [Tarih] - [Kısa Başlık]
### Görev: [Ne yapıldığı]
- [KARAR] Ne kararı verildi → Sonuç
- [HATA] Hangi hata → Çözüm
- [PATTERN] Hangi yaklaşım işe yaradı → Neden
- [UYARI] Dikkat edilmesi gereken → Neden
```

### Sürekli Güncelleme Talimatları

| Değişiklik Türü | Güncellenecek CLAUDE.md Bölümü |
|-----------------|-------------------------------|
| Yeni API endpoint | Detaylı Teknik Dokümantasyon → API |
| Yeni ortam değişkeni | Ortam Değişkenleri |
| Yeni bağımlılık | Ön Gereksinimler |
| DB şema değişikliği | Veritabanı Yönetimi |
| Yeni servis/port | Servisleri Çalıştırma |

### Git & Deployment Güvenlik Kuralları

**Git'e yüklenmeli:** CLAUDE.md, reports.md, experience.md, .env.example, tüm kaynak kod
**Sunucuya gönderilmemeli:** CLAUDE.md, reports.md, experience.md (geliştirme dokümantasyonu)

### Kod Standartları
- Python 3.13, type hints zorunlu
- Pydantic v2 şemalar (BaseModel)
- SQLAlchemy 2.0 async session
- Decimal kullanımı (float DEĞİL) — parasal hesaplamalar için
- Repository pattern (her tablo için ayrı repository)
- UPSERT idempotent yazım (tekrar çalıştırılabilirlik)

---

## Bilinen Sorunlar ve Teknik Borç

| # | Açıklama | Öncelik | Durum |
|---|----------|---------|-------|
| 1 | Celery async event loop hatası ("Event loop is closed") — asyncpg+Celery fork uyumsuzluğu | DÜŞÜK | Açık — bildirimler yine de gönderiliyor |
| 2 | ML model AUC değerleri düşük (benzin 0.57, motorin 0.50, LPG 0.63) — veri yetersizliği | ORTA | Bekleniyor — veri biriktikçe iyileşecek |
| 3 | v1 ML pipeline hâlâ çalışıyor (tasks.py'de) — kullanılmıyor ama kaynak harcıyor | DÜŞÜK | v1 kaldırılabilir |
| 4 | Akşam bildirim (18:00) akşam pipeline (18:00) ile aynı saatte — sabah tahminlerini gösterir | DÜŞÜK | 19:00'e alınabilir |
| 5 | Health check'te ml_model: False dönüyor — model dosyası yolu kontrol edilmeli | ORTA | Açık |

---

## Handoff Bilgileri

### Geliştirmeye Devam Etme — Öncelikli Yapılacaklar
1. **Model performansı iyileştirme**: Veri biriktikçe (6+ ay) modeli yeniden eğit. AUC hedefi: 0.70+
2. **v1 ML pipeline temizliği**: tasks.py'den v1 tahmin görevlerini kaldır, gereksiz model dosyalarını sil
3. **Akşam bildirim saatini 19:00'e al**: Akşam tahminleri hazır olduktan sonra gönderilsin
4. **KVKK uyum paketi**: Kullanıcı veri silme endpointi, gizlilik politikası sayfası
5. **B2B filo yönetimi modülü**: 20-100 araçlık filolar için toplu tahmin ve raporlama

### Dikkat Edilmesi Gerekenler
- **Celery timezone karmaşası**: `timezone="Europe/Istanbul"` + `enable_utc=True` → crontab saatleri İstanbul saati olarak yorumlanıyor, UTC DEĞİL. Tüm saat değerlerini TSİ olarak yaz.
- **EPDK veri çekme**: WAF koruması var, PO (Petrol Ofisi) scraping birincil kaynak. 3 katmanlı fallback: PO → Bildirim Portal → EPDK XML
- **Python venv yolu**: `.venv/` (venv/ DEĞİL)
- **DB portu**: 5433 (5432 DEĞİL)
- **Streamlit portu**: 8101 (8501 DEĞİL) — PM2 show'dan kontrol et
- **Bot dosya yolu**: `/var/www/yakit_analiz/src/telegram/` (telegram_bot DEĞİL)
- **PM2 restart sonrası 8-10 saniye bekle** (Streamlit cold start)
- **Sunucu timezone'u Europe/Berlin** (UTC+1), Türkiye UTC+3 — 2 saat fark

---

## Detaylı Teknik Dokümantasyon

### 1. Ön Gereksinimler (Prerequisites)

| Yazılım | Minimum Versiyon | Kurulum Notu |
|---------|-----------------|--------------|
| Python | 3.12+ (mevcut: 3.13.5) | `uv` ile yönetiliyor |
| PostgreSQL | 16 | Port 5433'te çalışıyor |
| Redis | 7+ | Port 6379, DB 0 |
| PM2 | 5+ | Node.js process manager |
| uv | latest | Python paket yöneticisi (pip yerine) |

### 2. Projeyi Sıfırdan Kurma (Fresh Setup)

```bash
# 1. Projeyi klonla
cd /var/www
git clone <repo-url> yakit_analiz
cd yakit_analiz

# 2. Python sanal ortam oluştur (uv ile)
uv venv .venv
source .venv/bin/activate

# 3. Bağımlılıkları kur
uv sync

# 4. .env dosyasını oluştur
cp .env.example .env
# .env dosyasını düzenle: DATABASE_URL, REDIS_URL, TELEGRAM_BOT_TOKEN, TCMB_EVDS_API_KEY

# 5. Veritabanı oluştur
createdb -p 5433 yakit_analizi
psql -p 5433 -c "CREATE USER yakit_analizi WITH PASSWORD 'yakit2026secure';"
psql -p 5433 -c "GRANT ALL PRIVILEGES ON DATABASE yakit_analizi TO yakit_analizi;"

# 6. Migration'ları çalıştır
alembic upgrade head

# 7. Seed data (başlangıç verileri)
python3 scripts/backfill_historical_data.py  # Tarihi pompa fiyatları
python3 scripts/rebuild_derived_tables.py     # MBE, risk, cost_base hesapla

# 8. ML modellerini eğit
python3 train_v5_po.py  # ~45 dakika sürer, 9 model (3 yakıt × 3 stage)

# 9. PM2 ile başlat
pm2 start ecosystem.config.js
pm2 save
```

### 3. Ortam Değişkenleri (Environment Variables)

| Değişken | Açıklama | Örnek Değer | Zorunlu |
|----------|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async bağlantı | `postgresql+asyncpg://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi` | Evet |
| `REDIS_URL` | Redis bağlantı | `redis://localhost:6379/0` | Evet |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | `7xxx:AAHxxx` | Evet |
| `TCMB_EVDS_API_KEY` | TCMB EVDS döviz kuru API anahtarı | `xxx` | Hayır (fallback var) |
| `DATA_FETCH_HOUR` | Akşam veri toplama saati (TSİ) | `18` | Hayır (default: 18) |
| `PREDICTION_HOUR` | Akşam tahmin saati (TSİ) | `18` | Hayır (default: 18) |
| `PREDICTION_MINUTE` | Akşam tahmin dakikası | `30` | Hayır (default: 30) |
| `NOTIFICATION_HOUR` | Sabah bildirim saati (TSİ) | `10` | Hayır (default: 10) |
| `MORNING_DATA_FETCH_HOUR` | Sabah veri toplama saati (TSİ) | `8` | Hayır (default: 8) |
| `MORNING_PREDICTION_HOUR` | Sabah tahmin saati (TSİ) | `8` | Hayır (default: 8) |
| `MORNING_PREDICTION_MINUTE` | Sabah tahmin dakikası | `30` | Hayır (default: 30) |
| `TELEGRAM_DAILY_NOTIFICATION_HOUR` | Sabah Telegram bildirimi (TSİ) | `10` | Hayır (default: 10) |
| `TELEGRAM_EVENING_NOTIFICATION_HOUR` | Akşam Telegram bildirimi (TSİ) | `18` | Hayır (default: 18) |

### 4. Veritabanı Yönetimi

#### Bağlantı Bilgileri
```
Host: localhost
Port: 5433
DB: yakit_analizi
User: yakit_analizi
Password: yakit2026secure
URL: postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi
```

#### Tablolar (15 tablo)

| Tablo | Açıklama |
|-------|----------|
| `daily_market_data` | Günlük piyasa verileri (Brent, FX, pompa fiyatı) |
| `price_changes` | Fiyat değişim geçmişi |
| `tax_parameters` | ÖTV oranları (yakıt tipi bazında) |
| `threshold_config` | Risk eşik konfigürasyonu |
| `cost_base_snapshots` | Maliyet tabanı snapshot'ları |
| `mbe_calculations` | MBE hesaplamaları |
| `risk_scores` | Risk skorları |
| `ml_predictions` | v1 ML tahminleri |
| `predictions_v5` | v5 ML tahminleri (aktif) |
| `feature_snapshots_v5` | v5 feature snapshot'ları |
| `regime_events` | Rejim olayları |
| `political_delay_history` | Politik gecikme geçmişi |
| `alerts` | Alarm kayıtları |
| `telegram_users` | Telegram kullanıcıları |
| `alembic_version` | Migration versiyon takibi |

#### Migration Komutları
```bash
alembic upgrade head          # Tüm migration'ları çalıştır
alembic revision -m "açıklama" # Yeni migration oluştur
alembic downgrade -1           # Son migration'ı geri al
```

### 5. Servisleri Çalıştırma

#### PM2 ile (Production)
```bash
pm2 start ecosystem.config.js    # Tüm servisleri başlat
pm2 status                        # Durum kontrol
pm2 restart yakit-api yakit-celery yakit-dashboard  # Restart
pm2 logs yakit-celery --lines 50  # Log izle
```

#### Manuel Çalıştırma (Development)
```bash
# API
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# Celery
celery -A src.celery_app.celery_config:celery_app worker -B -l info -Q default,notifications

# Dashboard
streamlit run dashboard/app.py --server.port 8101 --server.address 0.0.0.0
```

#### Port Haritası
| Servis | Port | URL |
|--------|------|-----|
| FastAPI | 8000 | http://localhost:8000 |
| Streamlit Dashboard | 8101 | http://localhost:8101 |
| PostgreSQL | 5433 | localhost:5433 |
| Redis | 6379 | localhost:6379 |

### 6. API Dokümantasyonu (58 endpoint)

| Grup | Prefix | Endpoint Sayısı | Açıklama |
|------|--------|-----------------|----------|
| Market Data | `/api/v1/market-data` | 4 | Günlük piyasa verileri |
| MBE | `/api/v1/mbe` | 5 | Maliyet Baz Etkisi |
| Risk | `/api/v1/risk` | 4 | Risk skorları |
| Price Changes | `/api/v1/price-changes` | 3 | Fiyat değişimleri |
| Tax | `/api/v1/tax` | 6 | ÖTV parametreleri |
| ML v1 | `/api/v1/ml` | 6 | v1 tahminleri |
| Predictor v5 | `/api/v1/predictor-v5` | 5 | v5 tahminleri (aktif) |
| Backtest | `/api/v1/backtest` | 3 | Backtest sonuçları |
| Alerts | `/api/v1/alerts` | 4 | Alarm yönetimi |
| Regime | `/api/v1/regime` | 4 | Rejim olayları |
| Delay | `/api/v1/delay` | 3 | Politik gecikme |
| EPDK | `/api/v1/epdk` | 4 | EPDK veri çekme |
| Telegram | `/api/v1/telegram` | 6 | Kullanıcı yönetimi |

#### Önemli Endpoint'ler
```bash
curl http://localhost:8000/api/v1/predictor-v5/latest           # Güncel v5 tahminler
curl http://localhost:8000/api/v1/predictor-v5/history?fuel_type=benzin&days=30
curl -X POST http://localhost:8000/api/v1/predictor-v5/retrain  # Model yeniden eğitim
curl http://localhost:8000/health                                # Sağlık kontrolü
curl http://localhost:8000/api/v1/mbe/history?fuel_type=benzin&days=30
```

### 7. Proje Klasör Yapısı

```
/var/www/yakit_analiz/
├── .env, .env.example            # Ortam değişkenleri
├── ecosystem.config.js           # PM2 konfigürasyonu
├── pyproject.toml               # Bağımlılıklar (uv)
├── alembic.ini                  # Alembic konfigürasyonu
├── _alembic_migrations/versions/ # 7 migration + 1 merge
├── src/
│   ├── main.py                  # FastAPI entry point
│   ├── api/                     # 14 route dosyası, 58 endpoint
│   ├── config/                  # database.py + settings.py
│   ├── core/                    # MBE, risk, threshold, political delay
│   ├── data_collectors/         # Brent, FX, EPDK collector'ları
│   ├── models/                  # 15 SQLAlchemy model
│   ├── repositories/            # Repository pattern
│   ├── ml/                      # v1 ML pipeline
│   ├── predictor_v5/            # v5 ML pipeline (aktif, 12 modül)
│   ├── celery_app/              # Celery config + 14 periyodik görev
│   ├── telegram/                # Bot + handlers + notifications
│   └── backtest/                # v1 backtest
├── dashboard/                   # Streamlit (6 sayfa)
├── models/v5/                   # Aktif ML modeller (12 joblib)
├── scripts/                     # Yardımcı script'ler
├── tests/                       # 30+ test dosyası
└── data/                        # CSV, SQL backup
```

### 8. Üçüncü Parti Servisler

| Servis | Amaç | Credential |
|--------|------|------------|
| Yahoo Finance | Brent petrol fiyatı | Gerekmez |
| TCMB EVDS | USD/TRY döviz kuru | `TCMB_EVDS_API_KEY` |
| Petrol Ofisi (PO) | Pompa fiyatları (scraping) | Gerekmez |
| EPDK | Yedek pompa fiyatı | Gerekmez |
| Telegram Bot API | Kullanıcı bildirimleri | `TELEGRAM_BOT_TOKEN` |
| Redis | Celery broker | Local, credential yok |

### 9. Celery Zamanlama (TSİ)

| Saat | Görev |
|------|-------|
| 08:00 | Sabah veri toplama |
| 08:10-08:20 | Sabah MBE + risk |
| 08:30-08:35 | Sabah v1+v5 tahmin |
| **10:00** | **Sabah Telegram bildirimi** |
| 18:00 | Akşam veri toplama + **akşam bildirimi** |
| 18:10-18:20 | Akşam MBE + risk |
| 18:30-18:35 | Akşam v1+v5 tahmin |
| */30 dk | Sağlık kontrolü |

### 10. Deployment

#### Sunucu Bilgileri
| Alan | Değer |
|------|-------|
| Host | 157.173.116.230 |
| SSH | `ssh root@157.173.116.230` (şifre: E3Ry8H#bWkMGJc6y) |
| Web Panel | https://cloud.skystonetech.com (admin / SFj353!*?dd) |
| Sunucu Timezone | Europe/Berlin (CET, UTC+1) |
| Proje Yolu | `/var/www/yakit_analiz/` |

#### Deployment Adımları
```bash
ssh root@157.173.116.230
cd /var/www/yakit_analiz
git pull                          # Değişiklikleri çek
source .venv/bin/activate
uv sync                           # Bağımlılık güncelle
alembic upgrade head              # Migration (varsa)
pm2 restart yakit-api yakit-celery yakit-dashboard
sleep 10 && pm2 status            # Kontrol
```

### 11. Sık Karşılaşılan Sorunlar

| Sorun | Çözüm |
|-------|-------|
| DB bağlantı hatası | Port 5433 kullan (5432 DEĞİL) |
| ModuleNotFoundError | `source .venv/bin/activate` (.venv/ venv/ DEĞİL) |
| EPDK 418 hatası | PO fallback otomatik devreye girer |
| Bot cevap vermiyor | `pm2 restart yakit-api` |
| Streamlit 404 | Port 8101 (8501 DEĞİL) |
| Celery saat yanlış | Saatleri TSİ yaz (enable_utc+Istanbul=TSİ yorumlanır) |
| PM2 sonrası erişilemez | 8-10 saniye bekle |

### 12. Geliştirme İpuçları

- **Dosya değişikliği**: Base64 encoded Python exact-string-replace kullan
- **Model yeniden eğitim**: `python3 train_v5_po.py` (~45 dk)
- **Derived tablolar**: `python3 scripts/rebuild_derived_tables.py`
- **Log izleme**: `pm2 logs yakit-celery --lines 100`

---

## İşlem Geçmişi (Özet)

| Sprint | Tarih | Açıklama | Görev |
|--------|-------|----------|-------|
| S0 | 15 Şub | Yasal çerçeve + B2B pazar araştırması | 2 |
| S1 | 16 Şub | Katman 1 — Veri Toplama | 3 |
| S2 | 16 Şub | Katman 2+3 — MBE + Risk + Backtest | 3 |
| S3 | 16 Şub | Katman 4 — ML | 1 |
| S4 | 16 Şub | Katman 5 — Bot + Dashboard + Celery | 3 |
| S5-S6 | 16 Şub | Güvenlik + Veri Aktivasyonu | 6 |
| S7-S9 | 17 Şub | UI/UX + Bug fix'ler | 9 |
| S11 | 17-18 Şub | ML Predictor v5 (7 dalga) | 14 |
| S12-S15 | 18-19 Şub | Dashboard v5 + Kalibrasyon + PO Rebuild | 12 |
| S16-S21 | 19-20 Şub | ML perf + Telegram refactor + Celery fix | 11 |
| **TOPLAM** | **5 gün** | **80 görev, 21 sprint** | **80** |
