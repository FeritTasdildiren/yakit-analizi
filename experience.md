# experience.md - Yakıt Analizi Birikimli Tecrübe Dosyası

> Bu dosya proje geliştirme sürecinde öğrenilen derslerin toplu özetidir.
> 8 farklı agent'ın tecrübelerinden derlenmiştir.
> Aynı hataların tekrarlanmaması, iyi pattern'lerin korunması için her oturumda okunmalıdır.

---

## Mimari ve Genel Kararlar

- [KARAR] Decimal zorunluluğu — float YASAK. Tüm parasal/oran hesaplamalarında `Decimal` kullanılır. `_safe_decimal(value)`: float→str→Decimal dönüşüm yolu hassasiyet kaybını önler
- [KARAR] Deterministik çekirdek ML'den bağımsız — ML opsiyonel, Circuit Breaker ile graceful degradation
- [KARAR] NUMERIC(18,8) tüm parasal/oran kolonlarında — Float kümülatif yuvarlama hatası yapar
- [KARAR] UPSERT (ON CONFLICT DO UPDATE) pattern'i tüm repository'lerde — Idempotent yazım, tekrar çekme durumunda veri kaybı yok
- [KARAR] Benzin ve motorin için AYRI MBE hesaplaması — Farklı CIF referansları, ÖTV oranları, katsayılar
- [KARAR] Hysteresis (çift eşik) alert sistemi — Tek eşik alert storm yaratır, açma/kapama ayrımı çözer
- [KARAR] Temporal (valid_from/valid_to) tax_parameters tasarımı — ÖTV sık değişir, tarihsel doğruluk için gerekli

## Veri Toplama (Katman 1)

- [PATTERN] Retry + fallback: Her collector 2 kaynak, her kaynak kendi retry döngüsü → 4 katmanlı dayanıklılık
- [PATTERN] TCMB EVDS API Türkçe virgül kullanıyor (36,25) → replace(",", ".") zorunlu
- [PATTERN] EPDK XML'inde de virgüllü sayılar var → Türkiye kaynaklarında her zaman virgül kontrolü yap
- [PATTERN] yfinance senkron kütüphanesini asyncio.to_thread() ile sarmalama → Async pattern'e uyumlu
- [UYARI] TCMB EVDS API anahtarı olmadan FX verisi sadece Yahoo fallback'ten gelir — production'da zorunlu
- [UYARI] EPDK servisi yavaş olabilir (devlet altyapısı), timeout 60s+ olmalı
- [UYARI] Dağıtıcı adları EPDK'da tutarsız — UPPER + STRIP normalizasyonu zorunlu

## MBE Hesaplama (Katman 2)

- [PATTERN] Calculator ve repository ayrı modüller → Calculator'ü DB'siz test edebilirsin
- [PATTERN] Rejim parametrelerini REGIME_PARAMS dict'inde merkezi tutmak → Yeni rejim eklemek tek satır
- [PATTERN] SMA pencere genişliği rejim bazlı değişiyor → Rejim geçişlerinde smooth blending uygulanmalı
- [UYARI] Alembic migration down_revision gerçek hash olmalı → Yanlış hash = migration zinciri kırılır
- [UYARI] direction_enum PostgreSQL ENUM olarak migration'da CREATE edilmeli

## Risk/Eşik Motoru (Katman 3)

- [PATTERN] Politik gecikme state machine: IDLE → WATCHING → CLOSED/ABSORBED geçişleri
- [PATTERN] Terminal durumlardan (CLOSED/ABSORBED) sonra IDLE'a manuel reset gerekiyor
- [PATTERN] Capture rate ve false alarm rate'te pencere parametresi kritik — 7 gün makul denge
- [UYARI] Paralel migration'larda branch_labels zorunlu, yoksa Alembic "multiple heads" hatası

## ML Katmanı (Katman 4)

- [PATTERN] Feature hesaplama DB'den ayrılmış: _fetch_feature_inputs + compute_all_features → SRP
- [PATTERN] SHAP hesaplaması non-critical, try/except'te → Tahmin başarılı olup SHAP başarısız olabilir
- [PATTERN] Fallback: DB verisi çekilemezse sıfır değerlerle feature hesapla → ML durmuyor
- [UYARI] TimeSeriesSplit kullanılmalı, asla random shuffle → Otokorelasyon nedeniyle data leakage riski
- [UYARI] Class weight'leri aşırı yükseltmek precision'ı düşürür → Optimum 8-12x aralığında
- [UYARI] LightGBM macOS'ta `libomp` runtime bağımlılığı → `brew install libomp`
- [UYARI] shap>=0.46.0 yerine shap>=0.49.1 → Python 3.14 uyumluluğu

## Sunum Katmanı (Katman 5)

### Telegram Bot
- [PATTERN] DB erişimi gerektiren fonksiyonları async_session_factory ile kendi session'larını yönetecek şekilde yaz
- [PATTERN] Rapor formatlama fonksiyonlarını pure function olarak ayır → DB'den bağımsız test edilebilir
- [UYARI] sys.modules manipülasyonu yapan testler (celery) diğer testlerin modül referanslarını bozabilir → Her test body'sinde import yap
- [UYARI] python-telegram-bot Forbidden/BadRequest exception'ları parametresiz kabul etmez

### Dashboard (Streamlit)
- [PATTERN] Streamlit async DB desteği yok → asyncio.run() wrapper ile senkron fonksiyonlar
- [PATTERN] @st.cache_data (TTL=60s) ile DB sorgusu cacheleme
- [UYARI] st.data_editor'da sıralama yapılınca satır indeksleri değişir → id sütunu üzerinden eşleştir

### Celery Scheduler
- [PATTERN] asyncio.run() wrapper: Sync Celery worker'da async fonksiyon çalıştırma
- [PATTERN] Her collector'ı ayrı try/except → Partial failure izolasyonu
- [HATA] Lazy import'larda patch kaynak modülü hedeflemeli, task modülü DEĞİL
- [UYARI] datetime.utcnow() deprecated (Python 3.12+) → datetime.now(UTC) kullan

## SQLAlchemy / Alembic

- [PATTERN] Tüm modelleri __init__.py'den import et → String-based relationship'ler için mapper registry zorunlu
- [PATTERN] Import sırasını bağımlılık grafiğine göre yap → Circular import önleme
- [UYARI] Boş __init__.py'de relationship string referansları çözülemez → Yeni model = __init__.py'ye import ekle
- [UYARI] Paralel agent'lar aynı dosyaları değiştirebilir → Her agent sadece kendi eklemesini yapmalı

## Test Stratejisi

- [PATTERN] Sentetik veri jeneratöründe deterministik SHA-256 hash → Reproducible backtest
- [PATTERN] SQLite in-memory ile test → PostgreSQL-spesifik index'ler testi kırmaz
- [PATTERN] Validator'leri ayrı modül olarak test et → Repository'den bağımsız test edilebilir
- [UYARI] Mevcut telegram_notifications testleri DB bağlantısı gerektirir → CI/CD'de ayrı pipeline

## Yasal ve İş

- [KARAR] SPK 6362/m.107 — pompa fiyatı "sermaye piyasası aracı" değil, manipülasyon riski yok
- [KARAR] EPDK XML web servisi kamuya açık, scraping gerekmiyor
- [UYARI] EPDK XML ticari kullanım şartları belirsiz → Yazılı teyit alınmalı
- [UYARI] KVKK yurt dışı veri aktarımı Telegram için kritik → Sunucular yurt dışı
- [UYARI] Rekabet Kurumu hassasiyeti — platform, dağıtıcılar arası koordinasyon aracı olarak algılanmamalı
- [PATTERN] B2B lojistik: 20-100 araçlık filolar sweet spot, %51.2 akaryakıt gider payı, 29x ROI

## Güvenlik

- [KARAR] Hardcoded token'lar .env'ye taşınmalı, settings.py'de boş string default
- [UYARI] Git geçmişinde hardcoded secret kalır → Token revoke edilmeli
- [UYARI] API key plain text saklama güvenlik açığı → SHA-256 hash + prefix pattern kullan
