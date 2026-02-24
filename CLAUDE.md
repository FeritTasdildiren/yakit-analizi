# CLAUDE.md - Yakıt Analizi Proje Kayıt Dosyası

> Bu dosya projenin "hafızası"dır. Orkestrasyon sırasında ve sonrasında bağımsız geliştirme için kullanılır.

---

## ⛔ Proje Hafıza Sistemi — İLK OKUNAN BÖLÜM

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

**⚠️ Bu dosyalar olmadan geliştirmeye başlama. Yoksa oluştur, varsa oku.**

---

## Proje Bilgileri

| Alan | Değer |
|------|-------|
| **Proje Adı** | Yakıt Analizi — Türkiye Akaryakıt Zam Öngörü Sistemi |
| **Açıklama** | Akaryakıt fiyat değişimlerini önceden tahmin eden erken uyarı ve maliyet optimizasyon sistemi |
| **Oluşturma Tarihi** | 2026-02-15 |
| **Teknoloji Stack** | Python 3.12+, FastAPI, PostgreSQL (asyncpg), Redis, Celery, LightGBM, Streamlit, python-telegram-bot |
| **Proje Durumu** | FAZ 1+2 TAMAMLANDI (Sprint S0-S5, 24 görev, 531 test) |
| **Son Güncelleme** | 2026-02-16 |
| **GitHub** | https://github.com/FeritTasdildiren/yakit-analizi |

---

## Teknoloji Kararları

| Teknoloji | Seçim | Gerekçe |
|-----------|-------|---------|
| Backend | FastAPI + Uvicorn | Async native, otomatik OpenAPI docs, yüksek performans |
| Veritabanı | PostgreSQL 16 + asyncpg | JSONB (SHAP verileri), ENUM (fuel_type), temporal tablolar, async driver |
| ORM | SQLAlchemy 2.0 (async) | Alembic migration desteği, repository pattern uyumu |
| Task Queue | Celery + Redis | Periyodik veri toplama, ML tahmin, bildirim zamanlaması |
| ML | LightGBM + scikit-learn | Hızlı eğitim, düşük bellek, SHAP uyumu, TimeSeriesSplit |
| Açıklanabilirlik | SHAP | Feature importance, tahmin gerekçelendirme |
| Dashboard | Streamlit | Hızlı prototipleme, Plotly entegrasyonu, cache desteği |
| Telegram Bot | python-telegram-bot 21+ | Async polling, ConversationHandler, modern API |
| Veri Hassasiyeti | Python Decimal | float YASAK — finansal hesaplamalarda hassasiyet kaybı önlenir |
| Migration | Alembic (async) | asyncpg driver ile uyumlu, zincirli revision'lar |

---

## Mimari — 5 Katmanlı Yapı

```
┌─────────────────────────────────────────┐
│ KATMAN 5: SUNUM                         │
│ Telegram Bot │ Streamlit Dashboard      │
│ Celery Beat (zamanlama)                 │
├─────────────────────────────────────────┤
│ KATMAN 4: ML TAHMİN                     │
│ LightGBM (3-class + regresyon)          │
│ SHAP │ Circuit Breaker │ Feature Eng.   │
├─────────────────────────────────────────┤
│ KATMAN 3: RİSK / EŞİK                  │
│ Risk Engine (5 bileşen)                 │
│ Politik Gecikme SM │ Threshold Mgr      │
├─────────────────────────────────────────┤
│ KATMAN 2: MBE HESAPLAMA                 │
│ NC_forward │ NC_base │ MBE Delta        │
│ SMA │ CostSnapshot │ Rejim parametreleri│
├─────────────────────────────────────────┤
│ KATMAN 1: VERİ TOPLAMA                  │
│ Brent (yfinance) │ FX (TCMB+Yahoo)     │
│ EPDK (XML) │ ÖTV (temporal seed)        │
└─────────────────────────────────────────┘
```

---

## Geliştirme Kuralları

### Görev Yaşam Döngüsü Kaydı
1. **İŞ ÖNCESİ**: Görev "Aktif Görevler" tablosuna `PLANLANMIŞ` durumunda eklenir
2. **İŞ BAŞLANDIĞINDA**: Durum `DEVAM EDİYOR` olarak güncellenir
3. **İŞ TAMAMLANDIĞINDA**: Durum `TAMAMLANDI` olarak güncellenir
4. **SORUN ÇIKTIĞINDA**: Durum `BLOKE` olarak güncellenir

### Çalışma Raporu Sistemi (reports.md) — ZORUNLU
Her yapılan iş `reports.md`'ye kayıt edilir. Format:
```markdown
## [RAPOR-XXX] Kısa Başlık
| Alan | Değer |
|------|-------|
| **Durum** | 🟡 BAŞLANDI / 🔵 DEVAM EDİYOR / 🟢 TAMAMLANDI / 🔴 BAŞARISIZ |
| **Başlangıç** | YYYY-MM-DD HH:MM |
| **Etkilenen Dosyalar** | dosya1.py, dosya2.py |
### Yapılanlar
- [x] Tamamlanan adım
### Sonuç
İşin son durumu.
```

### Tecrübe Kayıt Sistemi (experience.md) — ZORUNLU
Her görev sonrası öğrenimler yazılır:
```markdown
## [Tarih] - [Kısa Başlık]
- [KARAR] Ne kararı verildi → Sonuç
- [HATA] Hangi hata → Çözüm
- [PATTERN] Hangi yaklaşım işe yaradı → Neden
- [UYARI] Nelere dikkat edilmeli → Neden
```

### Kod Standartları
- **Linter**: ruff (line-length: 100, target: py312)
- **Tip Güvenliği**: Decimal zorunlu (float YASAK), Pydantic v2 modeller
- **Async**: Tüm DB işlemleri async (asyncpg)
- **Test**: pytest + pytest-asyncio, asyncio_mode = "auto"
- **Import sırası**: stdlib → 3rd party → local (ruff otomatik düzenler)

### ⛔ Sürekli Güncelleme Talimatları
Bu CLAUDE.md canlı bir dokümandır. Kod değişikliği yapıp CLAUDE.md'yi güncellememek YASAKTIR.

### ⛔ Git & Deployment Güvenlik Kuralları
- `.env` → Git'e YÜKLENMEMELİ (.gitignore'da)
- `.env.example` → Git'e yüklenir
- `CLAUDE.md`, `reports.md`, `experience.md` → Git'e yüklenir, sunucuya deploy edilmez

---

## Aktif Görevler

| Task ID | Açıklama | Durum | Notlar |
|---------|----------|-------|--------|
| - | Aktif görev yok | - | - |

---

## Tamamlanan Görevler (Özet)

| Sprint | Görevler | Test |
|--------|----------|------|
| S0 | Yasal çerçeve (KOŞULLU GO), B2B pazar araştırması | - |
| S1 | Brent+FX veri servisi, EPDK pompa fiyatı, ÖTV takip | 106 test |
| S2 | MBE hesaplama motoru, Risk/Eşik motoru, Backtest pipeline, Bug fix | 178 test |
| S3 | ML pipeline (LightGBM + SHAP + Circuit Breaker) | 396 test |
| S4 | Telegram Bot MVP, Streamlit Dashboard, Celery Scheduler | 523 test |
| S5 | LPG entegrasyonu, Fintech bilgi sayfası, güvenlik düzeltmesi | 531 test |

**Toplam: 24 görev, 531 test PASSED, 0 fail**

---

## Bilinen Sorunlar ve Teknik Borç

| # | Açıklama | Öncelik | Durum |
|---|----------|---------|-------|
| 1 | ML tahmin placeholder feature kullanıyor — gerçek DB verisiyle hesaplama entegrasyonu yapılmalı | YÜKSEK | AÇIK |
| 2 | CORS allow_origins=["*"] — production'da kısıtlanmalı | ORTA | AÇIK |
| 3 | Celery task'larda sadece benzin/motorin tahmin — LPG ML tahmini eklenmeli | ORTA | AÇIK |
| 4 | TCMB EVDS API key boş — FX sadece Yahoo fallback'ten geliyor | DÜŞÜK | AÇIK |
| 5 | Faz 3 görevleri (B2B API, ödeme, RBAC, retrain pipeline) yapılmadı | GELECEK | PLANLI |

---

## Handoff Bilgileri

### Geliştirmeye Devam Etme
Öncelikli yapılacaklar:
1. **ML Feature Integration**: `_get_placeholder_features()` yerine `compute_all_features()` bağlantısı (src/celery_app/tasks.py:200)
2. **LPG ML Tahmini**: `run_daily_prediction` task'ına lpg ekle (şu an sadece benzin/motorin)
3. **CORS Kısıtlama**: Production domain'leri belirle
4. **Faz 3**: B2B REST API, ödeme entegrasyonu, otomatik retrain, RBAC

### Dikkat Edilmesi Gerekenler
- Tüm fiyat hesaplamalarında **Decimal** kullan, float YASAK
- DB migration'larında `down_revision` gerçek hash olmalı
- `models/__init__.py`'ye her yeni model import edilmeli (SQLAlchemy relationship resolver)
- Celery task'larda async fonksiyonlar `asyncio.run()` wrapper ile çağrılmalı
- EPDK XML servisi yavaş olabilir, timeout 60s+
- Telegram bot token `.env`'de, settings.py'de boş string default

---

## Detaylı Teknik Dokümantasyon

### 1. Ön Gereksinimler (Prerequisites)

| Yazılım | Minimum Versiyon | Kurulum Notu |
|---------|-----------------|--------------|
| Python | 3.12+ | `uv` paket yöneticisi önerilir |
| PostgreSQL | 16+ | asyncpg driver ile |
| Redis | 7+ | Celery broker + result backend |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### 2. Projeyi Sıfırdan Kurma (Fresh Setup)

```bash
# 1. Repo'yu klonla
git clone https://github.com/FeritTasdildiren/yakit-analizi.git
cd yakit-analizi

# 2. Python ortamı oluştur
uv venv --python 3.12
source .venv/bin/activate

# 3. Bağımlılıkları kur
uv pip install -e ".[dev]"

# 4. .env dosyasını oluştur
cp .env.example .env
# .env'deki değerleri düzenle:
# - DATABASE_URL → gerçek PostgreSQL bağlantısı
# - REDIS_URL → gerçek Redis bağlantısı
# - TELEGRAM_BOT_TOKEN → BotFather'dan alınan token
# - TCMB_EVDS_API_KEY → evds2.tcmb.gov.tr'den alınan anahtar

# 5. PostgreSQL veritabanı oluştur
createdb yakit_analizi

# 6. Migration'ları çalıştır
alembic upgrade head

# 7. Seed data (ÖTV oranları)
python -c "
from src.data_collectors.tax_seed import seed_tax_parameters
import asyncio
asyncio.run(seed_tax_parameters())
"

# 8. Testleri çalıştır
uv run pytest tests/ -q
# Beklenen: 531 passed
```

### 3. Ortam Değişkenleri (Environment Variables)

| Değişken | Açıklama | Örnek Değer | Zorunlu? |
|----------|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL async bağlantısı | `postgresql+asyncpg://user:pass@localhost:5432/yakit_analizi` | EVET |
| `REDIS_URL` | Redis bağlantısı | `redis://localhost:6379/0` | EVET |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | `8402077908:AAG4-Hjp...` | EVET (bot için) |
| `TCMB_EVDS_API_KEY` | TCMB EVDS API anahtarı | `abc123...` | HAYIR (Yahoo fallback var) |
| `TELEGRAM_DAILY_NOTIFICATION_HOUR` | Bildirim saati (UTC) | `7` | HAYIR (default: 7) |
| `DATA_FETCH_HOUR` | Veri çekme saati (UTC) | `18` | HAYIR (default: 18) |
| `PREDICTION_HOUR` | ML tahmin saati (UTC) | `18` | HAYIR (default: 18) |
| `PREDICTION_MINUTE` | ML tahmin dakikası | `30` | HAYIR (default: 30) |
| `NOTIFICATION_HOUR` | Bildirim saati (UTC) | `7` | HAYIR (default: 7) |
| `RETRY_COUNT` | Yeniden deneme sayısı | `3` | HAYIR (default: 3) |
| `RETRY_BACKOFF` | Yeniden deneme bekleme çarpanı | `2.0` | HAYIR (default: 2.0) |

### 4. Veritabanı Yönetimi

#### Migration'lar
```bash
# Tüm migration'ları uygula
alembic upgrade head

# 1 adım geri al
alembic downgrade -1

# Yeni migration oluştur
alembic revision --autogenerate -m "Açıklama"

# Migration durumunu kontrol et
alembic current
alembic history
```

#### Migration Zinciri
```
001_create_enums_and_daily_market_data
  ↓
002_create_tax_parameters
  ↓
003_create_computation_tables (mbe_calculations, cost_base_snapshots, price_changes)
  ↓
004_create_risk_threshold_tables (risk_scores, alerts, regime_events, political_delay, threshold_config)
  ↓
005_create_ml_prediction_tables
  ↓
006_create_telegram_users
```

#### DB Tabloları (12 adet)
| Tablo | Açıklama |
|-------|----------|
| `daily_market_data` | Brent, USD/TRY, CIF Med, pompa fiyatı |
| `tax_parameters` | ÖTV, KDV — temporal (valid_from/valid_to) |
| `mbe_calculations` | MBE değeri, SMA, trend, rejim |
| `cost_base_snapshots` | Maliyet ayrıştırma (CIF, ÖTV, KDV, marj) |
| `price_changes` | Pompa fiyat değişiklikleri |
| `risk_scores` | Bileşik risk skoru (5 bileşen) |
| `ml_predictions` | LightGBM tahminleri + SHAP |
| `alerts` | Sistem uyarıları |
| `regime_events` | Rejim olayları (seçim, kriz, vergi) |
| `political_delay_history` | Politik gecikme günleri |
| `threshold_config` | Risk eşik konfigürasyonu |
| `telegram_users` | Telegram bot kullanıcıları |

### 5. Servisleri Çalıştırma

#### Geliştirme Ortamı
```bash
# Terminal 1: FastAPI (+ Telegram Bot otomatik başlar)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Celery Worker
celery -A src.celery_app.celery_config worker -l info

# Terminal 3: Celery Beat (zamanlayıcı)
celery -A src.celery_app.celery_config beat -l info

# Terminal 4: Streamlit Dashboard
cd dashboard && streamlit run app.py --server.port 8501
```

#### Üretim Ortamı
```bash
# FastAPI (gunicorn ile)
gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000

# Celery Worker + Beat (tek komut)
celery -A src.celery_app.celery_config worker -B -l info -c 4

# Dashboard
streamlit run dashboard/app.py --server.port 8501 --server.headless true
```

#### Port Haritası
| Servis | Port | URL |
|--------|------|-----|
| FastAPI API | 8000 | http://localhost:8000 |
| API Docs (Swagger) | 8000 | http://localhost:8000/docs |
| API Docs (ReDoc) | 8000 | http://localhost:8000/redoc |
| Streamlit Dashboard | 8501 | http://localhost:8501 |
| Telegram Bot | - | @yakithaber_bot (polling) |
| PostgreSQL | 5432 | localhost |
| Redis | 6379 | localhost |

### 6. API Dokümantasyonu (55 Endpoint)

#### Sistem
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/health` | Sağlık kontrolü |
| GET | `/` | API bilgi |

#### Piyasa Verisi (`/api/v1/market-data`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/latest` | En güncel piyasa verisi |
| GET | `/{target_date}` | Tarih bazlı veri |
| POST | `/fetch` | Brent/FX verisi çek (admin) |
| GET | `/gaps` | Veri boşluğu raporu |

#### MBE (`/api/v1/mbe`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/latest` | Tüm yakıt MBE |
| GET | `/latest/{fuel_type}` | Yakıt bazlı MBE |
| GET | `/range/{fuel_type}` | Tarih aralığı MBE |
| GET | `/snapshot/{snapshot_date}` | Maliyet decomposition |
| POST | `/calculate` | MBE hesapla (admin) |

#### Risk (`/api/v1/risk`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/latest` | Tüm yakıt risk skoru |
| GET | `/latest/{fuel_type}` | Yakıt bazlı risk |
| GET | `/range/{fuel_type}` | Tarih aralığı risk |
| POST | `/calculate` | Risk hesapla |

#### ML Tahmin (`/api/v1/ml`)
| Method | Path | Açıklama |
|--------|------|----------|
| POST | `/predict` | Fiyat değişim tahmini |
| POST | `/train` | Model eğit |
| GET | `/model-info` | Model versiyonu |
| GET | `/health` | Circuit breaker durumu |
| GET | `/explain/{prediction_id}` | SHAP açıklama |
| GET | `/backtest-performance` | Accuracy metrikleri |

#### Fiyat Değişim (`/api/v1/price-changes`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/latest` | Son fiyat değişimi |
| GET | `/{fuel_type}` | Yakıt bazlı |
| POST | `/` | Yeni kayıt |

#### Vergi (`/api/v1/taxes`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/current` | Güncel vergi |
| GET | `/current/{fuel_type}` | Yakıt bazlı vergi |
| GET | `/at-date/{ref_date}` | Tarih bazlı |
| GET | `/history/{fuel_type}` | Vergi geçmişi |
| POST | `/` | Yeni vergi (admin) |

#### Alert (`/api/v1/alerts`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/` | Alert listesi |
| GET | `/{fuel_type}` | Yakıt bazlı alert |
| PUT | `/{alert_id}/read` | Okundu işaretle |
| PUT | `/{alert_id}/resolve` | Çözüldü işaretle |

#### Rejim (`/api/v1/regime`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/active` | Aktif rejimler |
| GET | `/history` | Rejim geçmişi |
| POST | `/` | Rejim oluştur |
| PUT | `/{event_id}/deactivate` | Rejimi kapat |

#### Backtest (`/api/v1/backtest`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/scenarios` | Senaryoları listele |
| POST | `/run` | Backtest çalıştır |
| GET | `/report` | Rapor |

#### Gecikme (`/api/v1/delays`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/pending` | Bekleyen gecikmeler |
| GET | `/history/{fuel_type}` | Gecikme geçmişi |
| GET | `/stats/{fuel_type}` | İstatistikler |

#### Telegram Admin (`/api/v1/telegram`)
| Method | Path | Açıklama |
|--------|------|----------|
| GET | `/users` | Kullanıcı listesi |
| POST | `/users/{id}/approve` | Onayla |
| POST | `/users/{id}/reject` | Reddet |
| GET | `/stats` | İstatistikler |
| POST | `/broadcast` | Toplu mesaj |

### 7. Proje Klasör Yapısı

```
yakit-analizi/
├── src/
│   ├── main.py                      # FastAPI app + lifespan
│   ├── config/
│   │   ├── settings.py              # Pydantic Settings (.env)
│   │   └── database.py              # Async PostgreSQL engine
│   ├── api/                         # 12 router dosyası (55 endpoint)
│   │   ├── market_data_routes.py
│   │   ├── mbe_routes.py
│   │   ├── price_change_routes.py
│   │   ├── risk_routes.py
│   │   ├── regime_routes.py
│   │   ├── alert_routes.py
│   │   ├── delay_routes.py
│   │   ├── backtest_routes.py
│   │   ├── ml_routes.py
│   │   ├── epdk_routes.py
│   │   ├── tax_routes.py
│   │   └── telegram_admin_routes.py
│   ├── models/                      # SQLAlchemy ORM (12 tablo)
│   │   ├── base.py                  # Base + fuel_type_enum
│   │   ├── __init__.py              # Tüm model import'ları (ZORUNLU)
│   │   ├── market_data.py
│   │   ├── tax_parameters.py
│   │   ├── mbe_calculations.py
│   │   ├── cost_base_snapshots.py
│   │   ├── price_changes.py
│   │   ├── risk_scores.py
│   │   ├── ml_predictions.py
│   │   ├── alerts.py
│   │   ├── regime_events.py
│   │   ├── political_delay_history.py
│   │   ├── threshold_config.py
│   │   └── users.py                 # TelegramUser
│   ├── core/                        # Business logic
│   │   ├── mbe_calculator.py        # MBE hesaplama (Decimal)
│   │   ├── risk_engine.py           # Risk skoru (5 bileşen)
│   │   ├── political_delay_tracker.py # State machine
│   │   ├── threshold_manager.py     # Hysteresis
│   │   └── *_repository.py          # 7 repository
│   ├── data_collectors/             # Katman 1 veri toplama
│   │   ├── brent_collector.py       # yfinance + fallback
│   │   ├── fx_collector.py          # TCMB EVDS + Yahoo
│   │   ├── epdk_collector.py        # EPDK XML (sorguNo=72)
│   │   ├── tax_seed.py             # ÖTV/KDV seed verileri
│   │   └── validators.py
│   ├── ml/                          # Katman 4 ML
│   │   ├── feature_engineering.py   # 47 feature
│   │   ├── trainer.py              # LightGBM eğitim
│   │   ├── predictor.py            # Singleton predictor
│   │   ├── circuit_breaker.py      # CLOSED/OPEN/HALF_OPEN
│   │   └── explainability.py       # SHAP
│   ├── telegram/                    # Katman 5 Bot
│   │   ├── bot.py                  # Application factory
│   │   ├── handlers.py            # /rapor, /iptal, /yardim
│   │   ├── registration.py        # ConversationHandler (/start)
│   │   ├── notifications.py       # Günlük bildirim + broadcast
│   │   └── schemas.py             # Pydantic v2 şemaları
│   ├── celery_app/                  # Task queue
│   │   ├── celery_config.py
│   │   ├── beat_schedule.py
│   │   └── tasks.py               # 4 periyodik görev
│   ├── backtest/                    # Backtest motoru
│   └── repositories/               # ML + Telegram repo'ları
├── dashboard/                       # Streamlit arayüzü
│   ├── app.py                      # Ana sayfa
│   ├── pages/
│   │   ├── 01_📊_Genel_Bakis.py   # MBE gauge, trendler
│   │   ├── 02_📈_ML_Tahminler.py  # Tahmin olasılıkları, SHAP
│   │   ├── 03_🔥_Risk_Analizi.py  # Risk skorları, rejimler
│   │   ├── 04_👥_Kullanici_Yonetimi.py # Telegram kullanıcı yönetimi
│   │   ├── 05_⚙️_Sistem.py       # Servis durumu, circuit breaker
│   │   └── 06_💰_Fintech_Tasarruf.py # Tasarruf hesaplayıcı
│   ├── components/
│   │   ├── charts.py              # Plotly grafikleri
│   │   └── data_fetcher.py        # Async DB + cache
│   └── requirements.txt
├── alembic/                         # Migration'lar
│   ├── env.py                      # Async migration runner
│   └── versions/                   # 6 migration
├── tests/                           # 25+ test dosyası (531 test)
├── Arsiv-Planlama/                  # Planlama dokümanları
├── pyproject.toml                   # Bağımlılıklar + ruff + pytest
├── alembic.ini
├── .env                            # Ortam değişkenleri (GIT'E YÜKLENMEMELİ)
├── .env.example                    # Örnek ortam değişkenleri
├── .gitignore
├── CLAUDE.md                       # Bu dosya
├── reports.md                      # İş kayıtları
└── experience.md                   # Tecrübe bankası
```

### 8. Üçüncü Parti Servisler ve Entegrasyonlar

| Servis | Amaç | Credential Notu |
|--------|------|-----------------|
| PostgreSQL | Ana veritabanı | `.env` → DATABASE_URL |
| Redis | Celery broker + result backend | `.env` → REDIS_URL |
| TCMB EVDS API | USD/TRY döviz kuru | `.env` → TCMB_EVDS_API_KEY (opsiyonel) |
| Yahoo Finance (yfinance) | Brent petrol + FX fallback | API key gerektirmez |
| EPDK XML Web Service | Pompa fiyatları (sorguNo=72) | API key gerektirmez, kamuya açık |
| Telegram Bot API | @yakithaber_bot | `.env` → TELEGRAM_BOT_TOKEN |

### 9. Test Stratejisi

```bash
# Tüm testleri çalıştır
uv run pytest tests/ -q

# Belirli bir modülü test et
uv run pytest tests/test_mbe_calculator.py -v

# Coverage raporu
uv run pytest tests/ --cov=src --cov-report=html
```

**Test dağılımı:**
- Veri toplama testleri (Brent, FX, EPDK, ÖTV)
- MBE hesaplama testleri (8 LPG testi dahil)
- Risk motoru testleri
- Backtest testleri
- ML pipeline testleri
- Telegram bot testleri (kayıt, komutlar, bildirim, admin API)
- Dashboard testleri

### 10. Deployment (Yayına Alma)

#### Sunucu Bilgileri
| Alan | Değer |
|------|-------|
| Domain | ferittasdildiren.com |
| Proje Yolu | /var/www/yakit_analiz/ |
| SSH | `ssh root@157.173.116.230` |

### 11. Sık Karşılaşılan Sorunlar

| Sorun | Olası Neden | Çözüm |
|-------|-------------|-------|
| DB bağlantı hatası | PostgreSQL çalışmıyor | `systemctl start postgresql` |
| Celery task çalışmıyor | Redis çalışmıyor | `systemctl start redis` |
| ML model yüklenemedi | İlk kez çalışıyor, model yok | `POST /api/v1/ml/train` ile eğit |
| Telegram bot başlamıyor | Token boş/yanlış | `.env`'deki TELEGRAM_BOT_TOKEN kontrol et |
| EPDK verisi alınamadı | Devlet servisi yavaş/kapalı | Timeout 60s+, sonraki çekmede yeniden dener |
| Import hatası (relationship) | Yeni model __init__.py'ye eklenmemiş | `src/models/__init__.py`'ye import ekle |
| numba/llvmlite hatası | Python sürüm uyumsuzluğu | `numba>=0.60.0` olmalı |
| LightGBM macOS hatası | libomp eksik | `brew install libomp` |

### 12. Celery Beat Zamanlama

> **Not:** Celery `timezone="Europe/Istanbul"` kullanır. Tüm crontab saatleri doğrudan **TSİ**'dir.

#### Akşam Pipeline (Ana)
| Görev | Saat (TSİ) | Açıklama |
|-------|-----------|----------|
| Veri Toplama (Brent, FX, EPDK) | 18:00 | Piyasalar kapandıktan sonra |
| MBE Hesaplama | 18:10 | Veri toplamadan 10 dk sonra |
| Risk Hesaplama | 18:20 | MBE'den 10 dk sonra |
| ML Tahmin v1 | 18:30 | Benzin, motorin, LPG |
| ML Tahmin v5 | 18:35 | v1'den 5 dk sonra |
| Akşam Bildirim (Telegram) | 18:45 | Pipeline tamamlandıktan sonra |

#### Sabah Pipeline (Güncelleme)
| Görev | Saat (TSİ) | Açıklama |
|-------|-----------|----------|
| Sabah Veri Toplama | 10:15 | Güncel piyasa verisi |
| Sabah MBE Hesaplama | 10:25 | |
| Sabah Risk Hesaplama | 10:35 | |
| Sabah ML Tahmin v1 | 10:45 | |
| Sabah ML Tahmin v5 | 10:50 | |
| Sabah Bildirim (Telegram) | 11:00 | Pipeline tamamlandıktan sonra |

#### Sağlık Kontrolü
| Görev | Zamanlama |
|-------|-----------|
| Sistem Sağlık Kontrolü (DB, Redis, ML) | Her 30 dakikada bir |
