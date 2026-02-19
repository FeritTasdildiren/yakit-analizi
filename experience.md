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

## Production Deployment (TASK-025)

- [HATA] `data_quality_flag="partial"` → PostgreSQL ENUM'da "partial" değeri yok → `"estimated"` olarak düzeltildi. ENUM tanımını her zaman kontrol et: `SELECT unnest(enum_range(NULL::data_quality_enum))`
- [HATA] `MarketDataResponse.created_at: str` → DB'den `datetime` geldiği için Pydantic validation hatası → `datetime` tipine düzeltildi. Pydantic response modellerinde DB kolon tipleriyle uyum kontrol edilmeli
- [PATTERN] Sunucuya deploy öncesi collector'ları ayrı ayrı test et → Bağımsız çalıştığını doğrula, sonra task'ı tetikle
- [PATTERN] Threshold config seed: genel (fuel_type=NULL) + yakıt tipine özel — her ikisini de ekle, risk engine hangi önceliğe bakarsa baksın veri bulunsun
- [UYARI] EPDK XML servisi sunucudan 418 "I'm a teapot" dönüyor — WAF/Cloudflare bot koruması sunucu IP'sini engelliyor. Yerel bilgisayardan çalışıyor, sunucudan çalışmıyor
- [UYARI] tasks.py'de DB upsert yaparken ENUM değerlerini kontrol et — PostgreSQL ENUM'a olmayan değer veremezsin, String'den farklı
- [UYARI] Sunucudaki tasks.py ve lokal tasks.py arasında senkronizasyon kopukluğu olabilir — deploy öncesi dosya boyutunu/satır sayısını karşılaştır
- [KARAR] TCMB EVDS API key boşken FX collector 3 retry bekliyor (toplam ~6sn) → FX collector ilk denemede key boşsa doğrudan fallback'e geçebilir (gelecek optimizasyon)

## Backfill Script (TASK-026)

- [KARAR] Backfill scriptte mevcut async collector'ları asyncio.run() ile kullandık, psycopg2 ile sync DB yazımı yaptık → Hybrid async/sync yaklaşım standalone script'ler için en pratik
- [KARAR] UPSERT'te COALESCE kullandık → Mevcut veriyi koruyup sadece NULL alanları dolduruyor, tekrar çalıştırmada veri kaybı yok
- [HATA] SSH heredoc ile Python script gönderme → format string'deki parantezler bash syntax hatası veriyor → Dosyayı lokalde oluşturup SCP ile gönder
- [PATTERN] fetch_brent_range() toplu çekimde (~1sn) çok hızlı, fetch_usd_try_range() gün gün fallback'te (~12dk) çok yavaş → Backfill scriptlerinde TCMB key yoksa FX için doğrudan yfinance range sorgusu düşünülmeli
- [UYARI] FX collector TCMB key yokken gün başına 3×retry + 3×fallback retry = ~18sn × 91 gün = ~27 dakika → Backfill'lerde RETRY_COUNT override edilmeli veya key eklenmeli
- [UYARI] Hafta sonu tarihleri için Brent ve FX verisi gelmeyebilir — yfinance "possibly delisted" uyarısı veriyor, bu hafta sonu/tatil günü demek, hata değil
- [PATTERN] Brent 61 iş günü, FX 63 iş günü veri döndü → Farklı piyasalar farklı tatil takvimlerine sahip, build_rows() fonksiyonunda union ile birleştirme doğru yaklaşım

## EPDK WAF Bypass (TASK-027)

- [KARAR] EPDK XML 418 hatası IP bazlı bloklama — User-Agent, cookie, cloudscraper, Playwright, Tor hiçbiri işe yaramadı → Sorun TLS fingerprint veya JS challenge değil, doğrudan IP kara listesi
- [KARAR] Petrol Ofisi (petrolofisi.com.tr) alternatif veri kaynağı olarak eklendi → Tek HTTP GET ile 82 ilin benzin+motorin+LPG fiyatları HTML tablosunda geliyor, sunucudan erişilebilir
- [KARAR] Fallback zinciri: PO (birincil, en güvenilir) → Bildirim Portal (JSF, kırılgan) → EPDK XML (WAF engelli) → Birden fazla kaynak IP engeli gibi sorunları atlatır
- [HATA] Bildirim portal JSF AJAX sorguları 200 dönüyor ama 0 kayıt → Form field ID'leri (j_idt49, j_idt29_input vb.) EPDK siteyi güncellediğinde değişiyor, kırılgan
- [PATTERN] Devlet sitelerinde (gov.tr) WAF genelde IP bazlı kara liste + belirli URL pattern'leri hedefler → Ana sayfa erişilebilir ama /DownloadXMLData gibi veri endpointleri engelli
- [PATTERN] Türk devlet siteleri Tor exit node'larını da engelliyor → "Host unreachable" hatası, SOCKS proxy ile bile geçilemiyor
- [PATTERN] PO HTML yapısı: `<tr data-disctrict-name="CITY">` + `<span class="with-tax">PRICE</span>` → Standart CSS class'lı HTML tablo, düz regex ile parse edilebilir
- [PATTERN] İstanbul PO'da ikiye ayrılmış (Avrupa+Anadolu) → Ortalamasını alarak tek il kodu (34) olarak birleştir
- [HATA] LPG bildirim portal tablo kolon sırası petrolden farklı: Petrol=Tarih,İl,Dağıtıcı,Ürün,Fiyat / LPG=İl,Dağıtıcı,YakıtTipi,Fiyat,Tarih → Ayrı parse fonksiyonu zorunlu
- [HATA] LPG form render target `@all` kullanmak çalışmıyor → Doğru render: `akaryakitSorguSonucu messages lpgFiyatlariKriterleriForm` (butonun onclick'inden alınmalı)
- [PATTERN] JSF formlarında render target'ı butonun `onclick` attribute'ünden çıkart: `PrimeFaces.ab({...,u:"RENDER_TARGET",...})` → `u:` parametresi doğru render target
- [PATTERN] LPG verisi benzin/motorinden 1 gün gecikmeli olabilir → Fallback olarak bir önceki günü deneme mekanizması ekle
- [UYARI] LPG bildirim portalda ürün "Otogaz" olarak geçiyor, "LPG" değil → Sabit `Otogaz` kullan
- [UYARI] JSF form field ID'leri (`j_idt29`, `j_idt46` vb.) EPDK siteyi güncellediğinde değişebilir → Mümkünse HTML'den dinamik keşif yap, ama son çare olarak hardcoded ID'ler ile
- [UYARI] PO fiyatları tek dağıtıcının (Petrol Ofisi) fiyatlarıdır, EPDK tüm dağıtıcıların ortalamasıdır → Küçük fark olabilir ama trendi yakalamak için yeterli
- [UYARI] PO sadece güncel fiyat sunar, tarih filtresi yok → Geçmiş tarih istendiğinde boş dönüyor
- [UYARI] PO HTML yapısı değişirse scraper kırılır → Düzenli monitoring veya test gerekli
- [UYARI] SSH üzerinden Python kodu çalıştırırken bash escape sorunları → Script'i dosyaya yazıp SCP ile gönder, heredoc kullanma

## Backfill Prediction v5 (TASK-060)

- [KARAR] Backfill modellerini ayrı dizine (models/backfill/) kaydet → Production modelleri (models/v5/) bozulmaz, iki set bağımsız yaşar
- [KARAR] model_version kolonu ile backfill/gerçek ayrımı → Aynı tabloda iki veri seti, tek sorgu ile birleştirilebilir
- [KARAR] DB unique constraint'i (run_date, fuel_type) → (run_date, fuel_type, model_version) genişletildi → Aynı gün+yakıt için hem backfill hem gerçek kayıt olabilir
- [HATA] PostgreSQL Boolean kolona Python int(0/1) yazılamıyor → `column "stage1_label" is of type boolean but expression is of type integer` hatası. Çözüm: `bool()` ile cast et, int kullanma
- [HATA] DB constraint adı değişince hem repository.py UPSERT hem SQLAlchemy model güncellenmeli → Yoksa gerçek tahminlerin UPSERT'i kırılır. Constraint adı değişikliği 3 yerde senkronize edilmeli: DB, repository, model
- [PATTERN] Backfill script'te --skip-train ve --skip-schema flag'leri → Hata düzeltme sonrası sadece ilgili faz çalıştırılabilir, tüm pipeline tekrar çalışmaz
- [PATTERN] Dashboard'da backfill verisi için ayrı stil (dashed line, düşük opacity) → Kullanıcı gerçek tahminle simülasyonu ayırt edebilir
- [PATTERN] `_fetch_latest_prediction_v5` sorgusunda backfill filtresi → `model_version != "v5-backfill"` koşulu ile son gerçek tahmin alınır, backfill karışmaz
- [UYARI] SSH heredoc ile Python kodu gönderirken emoji karakterleri bash syntax hatası veriyor → Lokal dosya oluşturup SCP ile gönder, heredoc kullanma (aynı sorun TASK-026/027'de de var)
- [UYARI] LightGBM feature names uyarısı (X does not have valid feature names) → Prediction'da numpy array kullanılıyor, training'de DataFrame — uyarı zararsız ama feature sırası garantilenmeli
- [UYARI] Backfill modelleri daha az veri ile eğitildiğinden (cutoff öncesi) production modellerinden farklı davranabilir → Prob değerleri doğrudan karşılaştırılmamalı
