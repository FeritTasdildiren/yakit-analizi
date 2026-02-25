# reports.md - Yakıt Analizi Kronolojik Kayıt Dosyası

> Bu dosya proje geliştirme sürecinin kronolojik kaydıdır.
> Her oturumda ne yapıldığını, hangi kararların alındığını ve yarım kalan işleri gösterir.

---

## 2026-02-15 — Proje Oluşturma ve Planlama

### Oturum 1: Stratejik Heyet Değerlendirmesi
- **Yapılan:** 3 farklı AI altyapısı (Claude, Gemini, Codex) ile Delphi metodu iteratif yakınsama
- **Tur 1:** Bağımsız analiz — her agent farklı perspektiften değerlendirdi
- **Tur 2:** Çapraz değerlendirme — kısmi uzlaşı sağlandı
- **Sonuç:** Koşullu onay. CIF veri erişimi, yasal çerçeve ve gelir modeli kritik riskler
- **Çıktı:** `Arsiv-Planlama/Stratejik Heyet Değerlendirme Raporu.md`

### Oturum 2: Planlama Pipeline'ı
- **Stratejik Yol Haritası (TASK-004):** 3 faz (PoC → MVP → Ürün) + Faz 0 ön koşullar
- **Ürün Backlog (TASK-005):** 7 Epic, 25 User Story, 116 Story Point, MoSCoW önceliklendirme
- **Operasyonel Sprint Planı (TASK-006):** 10 sprint, 26 görev, bağımlılık grafiği
- **Çıktı:** `Arsiv-Planlama/Birlesik Proje Plani.md`

### Oturum 3: Mimari Tasarım
- **TASK-007:** 5 katmanlı teknik mimari + 13 tabloluk PostgreSQL schema
- **TASK-008:** MBE formülü, eşik metodolojisi, politik gecikme metriği, ML feature set (47 feature)
- **Kararlar:** Decimal zorunluluğu, UPSERT pattern, hysteresis alert, temporal tax tracking

---

## 2026-02-15 ~ 2026-02-16 — Sprint S0-S1: Temel Altyapı

### Sprint S0: Ön Koşullar
- **TASK-009 (Yasal Çerçeve):** KOŞULLU GO — SPK/EPDK engeli yok, KVKK+disclaimer zorunlu
- **TASK-010 (B2B Pazar):** 20-100 araçlık filolar sweet spot, %51.2 akaryakıt gider payı

### Sprint S1: Katman 1 — Veri Toplama (3 agent paralel)
- **TASK-011 (Brent+FX):** TCMB EVDS + Yahoo Finance, 4 katmanlı retry+fallback
- **TASK-012 (EPDK Pompa):** EPDK XML servisi, Newton-Raphson Decimal sqrt
- **TASK-013 (ÖTV Takip):** Temporal lock pattern, idempotent seed
- **Toplam:** 34 dosya, 106 test

---

## 2026-02-16 — Sprint S2: Deterministik Çekirdek

### Katman 2: MBE Hesaplama Motoru
- **TASK-014:** 10 fonksiyonlu MBE calculator (tamamı Decimal), 3 DB modeli, 8 API endpoint
- **76 test:** PASS

### Katman 3: Risk/Eşik Motoru
- **TASK-015:** Risk engine (5 bileşen), politik gecikme state machine (5 durum), hysteresis
- **68 test:** PASS

### Backtest Doğrulaması
- **TASK-016:** Sentetik veri (3 senaryo), deterministik SHA-256 random walk
- **34 test:** PASS — ML'ye geçiş onayı

### Bug Fix
- **TASK-017:** SQLAlchemy model mapper hatası — models/__init__.py düzeltmesi
- **309 test:** PASS (toplu çalıştırma)

---

## 2026-02-16 — Sprint S3: ML Katmanı

### Katman 4: Machine Learning
- **TASK-018:** 47 feature engineering, LightGBM sınıflandırma+regresyon, SHAP, circuit breaker
- **TimeSeriesSplit:** 5-fold, gap=7 (data leakage önleme)
- **396 test:** PASS (87 yeni ML testi)

---

## 2026-02-16 — Sprint S4: Sunum Katmanı (3 agent paralel)

### Katman 5: Sunum
- **TASK-019 (Telegram Bot):** /start, /rapor, /iptal, /yardim + admin API + KVKK disclaimer
- **TASK-020 (Dashboard):** Streamlit 6 sayfa — MBE gauge, risk heatmap, ML tahmin, SHAP, kullanıcı yönetimi
- **TASK-021 (Celery Scheduler):** 4 periyodik görev (18:00 veri, 18:30 ML, 07:00 bildirim, */30 health)
- **523 test:** PASS

---

## 2026-02-16 — Sprint S4-FIX + S5: Güvenlik ve Büyüme

### Güvenlik Düzeltmeleri
- **TASK-022:** Hardcoded Telegram token kaldırıldı, .env.example güncellendi, .gitignore oluşturuldu

### Sprint S5: Büyüme Faz 2
- **TASK-023 (LPG Entegrasyonu):** Tax seed 3→12, dashboard dinamik N-kolon, 8 yeni test
- **TASK-024 (Fintech Bilgi):** Tasarruf hesaplayıcı, tanklama önerisi, yakıt kartı karşılaştırma
- **531 test:** PASS

---

## 2026-02-16 — Teslim

### Teslim Prosedürü
- Proje CLAUDE.md oluşturuldu (handoff dokümanı)
- reports.md oluşturuldu (kronolojik kayıt)
- experience.md oluşturuldu (birikimli tecrübe)
- GitHub repo oluşturuldu ve push edildi
- Sunucuya aktarım yapıldı

---

## Yarım Kalan / Gelecek İşler

| # | Konu | Öncelik | Not |
|---|------|---------|-----|
| 1 | ML modeli ilk eğitim | YÜKSEK | 30+ günlük veri birikince `POST /api/v1/ml/train` |
| 2 | CIF Med gerçek veri kaynağı | ORTA | Platts/Argus lisansı veya proxy hesaplama refinement |
| 3 | TCMB EVDS API anahtarı | YÜKSEK | Production'da Yahoo fallback yeterli değil |
| 4 | Celery task: LPG tahmin | DÜŞÜK | `run_daily_prediction` sadece benzin/motorin yapıyor |
| 5 | Alembic migration merge | ORTA | 004 branching migration, production'da `alembic merge heads` |

---

## 2026-02-24 — Zamanlama Denetimi ve Düzeltmeleri

| Alan | Değer |
|------|-------|
| **Durum** | 🟢 TAMAMLANDI |
| **Başlangıç** | 2026-02-24 |
| **Etkilenen Dosyalar** | `src/celery_app/tasks.py`, `src/celery_app/beat_schedule.py`, `src/config/settings.py`, `CLAUDE.md` |

### Yapılanlar
- [x] Celery zamanlama yapılandırması incelendi (beat_schedule.py, tasks.py, settings.py, celery_config.py)
- [x] CLAUDE.md'deki zamanlama tablosu düzeltildi (yanlış UTC → doğru TSİ, sabah/akşam pipeline eklendi)
- [x] Task docstring'lerdeki 5 yanlış UTC referansı TSİ olarak düzeltildi
- [x] Hardcoded DB URL (şifre dahil) `_calculate_mbe_sync()` ve `_calculate_risk_sync()` içinden kaldırıldı → `settings.sync_database_url` kullanıldı
- [x] Akşam bildirim saati 18:00 → 18:45'e alındı (pipeline bitmeden bildirim gitmesini önlemek için)
- [x] `TELEGRAM_EVENING_NOTIFICATION_MINUTE` ayarı settings.py'ye eklendi

### Sonuç
4 sorun tespit edilip düzeltildi. 710 test başarılı, mevcut test sonuçlarını değiştiren bir etki yok.

---

## 2026-02-25 — MBE Reset, Alarm Confidence ve Çift Bildirim Düzeltmeleri

| Alan | Değer |
|------|-------|
| **Durum** | 🟢 TAMAMLANDI |
| **Başlangıç** | 2026-02-25 |
| **Etkilenen Dosyalar** | `src/celery_app/tasks.py`, `src/predictor_v5/alarm.py`, sunucu restart scripti |

### Yapılanlar

#### Bug Fix: Fiyat değişimi sonrası MBE reset (tasks.py)
- [x] `since_last_change_days` sayacı fiyat değişiminde 1'e sıfırlanıyor (önceden hiç reset yok)
- [x] `nc_base` fiyat değişiminde SMA-5 ile güncelleniyor (önceden önceki günü kopyalıyordu)
- [x] Fiyat değişimi tespiti: `daily_market_data`'dan önceki günün pompa fiyatıyla karşılaştırma (>0.01 TL)
- [x] SMA hesaplaması `nc_base`'den önceye taşındı (dependency fix)

#### Bug Fix: Alarm confidence (alarm.py)
- [x] `already_happened` alarm'da `confidence` ML olasılığı yerine `1.0` yapıldı

#### Ops: Çift Telegram bildirimi (sunucu)
- [x] Kök neden: Dünkü 2 deploy'da `kill` sadece 1 PID öldürdü, child process'ler zombie kaldı → 2 beat scheduler çalıştı
- [x] Tüm zombie Celery process grupları temizlendi, tek instance başlatıldı
- [x] `/var/www/yakit_analiz/restart_celery.sh` scripti oluşturuldu — `pkill -9 -f` ile tüm grubu öldürür

### Sonuç
3 bug düzeltildi. MBE benzin/motorin 0.776→0.0, risk 0.276→0.006 (fiyat değişimi doğru yansıtıldı). Çift bildirim sorunu çözüldü.
