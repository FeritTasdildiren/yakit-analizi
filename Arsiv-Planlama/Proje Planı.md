# Türkiye Akaryakıt Zam Öngörü Sistemi — Proje Planı

**Versiyon:** 1.0
**Tarih:** 2026-02-15
**Hazırlayanlar:** Claude Opus (Stratejik Planlayıcı) | Gemini 3 (Ürün Yöneticisi) | Codex GPT-5.2 (Operasyonel Planlayıcı)
**Referans:** Stratejik Heyet Değerlendirme Raporu (2 tur Delphi uzlaşısı) + Proje Sahibi Kararları (8 madde)

---

## İçindekiler

1. [Stratejik Vizyon](#1-stratejik-vizyon)
2. [Faz Bazlı Yol Haritası](#2-faz-bazlı-yol-haritası)
3. [Ürün Backlog ve User Story'ler](#3-ürün-backlog-ve-user-storyler)
4. [Sprint Planı ve Görev Dağılımı](#4-sprint-planı-ve-görev-dağılımı)
5. [Risk Matrisi](#5-risk-matrisi)
6. [Başarı Metrikleri](#6-başarı-metrikleri)

---

# 1. Stratejik Vizyon

## Misyon
Türkiye'deki akaryakıt (benzin, motorin, LPG) fiyat değişimlerini küresel ve makroekonomik göstergelere dayalı olarak önceden öngörerek, işletmelerin maliyet planlamasını ve bireylerin tasarruf kararlarını veri odaklı hale getirmek.

## Vizyon
Türkiye'nin en güvenilir akaryakıt erken uyarı platformu olarak, lojistik sektörünün vazgeçilmez maliyet yönetim aracı haline gelmek.

## Değer Önerisi

| Segment | Mevcut Durum | Bizim Çözümümüz | Somut Değer |
|---------|-------------|-----------------|-------------|
| **B2B Lojistik/Filo** | Zamlar geldiğinde haber alıyorlar | 1-7 gün önceden zam olasılık sinyali | Filo başına yıllık %3-5 yakıt tasarrufu |
| **B2C Bireysel** | Sosyal medya dedikodu | Telegram: doğrulanmış olasılık bildirimi | Yılda 3-5 depo tasarrufu (₺500-1.500) |

## Hedef Pazar (Öncelik Sırasıyla)

| Öncelik | Segment | Ödeme Kapasitesi | Faz |
|---------|---------|------------------|-----|
| 1. Birincil | Lojistik/Filo (B2B) | ₺500-2.000/ay | MVP → Ürün |
| 2. İkincil | Akaryakıt İstasyonları (B2B) | ₺500-2.000/ay | Ürün |
| 3. Paralel | Bireysel Sürücüler (B2C) | ₺49-99/ay premium | MVP |
| 4. İleri Faz | Finansal Trader'lar | Proje bazlı | Ürün+ |

## Gelir Modeli (Premium-Only — Ücretsiz Katman YOK)

| Katman | Kitle | Fiyat | Özellikler |
|--------|-------|-------|-----------|
| Premium B2C | Bireysel sürücüler | ₺49-99/ay | Telegram bot: 3 yakıt türü alarmları |
| API Standart B2B | Lojistik firmalar | ₺500-2.000/ay | REST API: günlük sinyal, webhook |
| Enterprise B2B | Büyük filolar | ₺5.000+/ay | Özel dashboard, SLA, dedike destek |
| Veri Analitik | Kurumsal | Proje bazlı | Özel rapor, danışmanlık |

## Gelir Projeksiyonu (Muhafazakâr)

| Dönem | B2C Abone | B2C Gelir | B2B Müşteri | B2B Gelir | Toplam |
|-------|-----------|-----------|-------------|-----------|--------|
| Ay 1-3 | 0 | ₺0 | 0 | ₺0 | ₺0 |
| Ay 4-6 | 200 | ₺14K/ay | 3 | ₺4.5K/ay | ₺18.5K/ay |
| Ay 7-9 | 500 | ₺35K/ay | 8 | ₺12K/ay | ₺47K/ay |
| Ay 10-12 | 1.000 | ₺70K/ay | 15 | ₺22.5K/ay | ₺92.5K/ay |

**Başabaş:** ~30-70 B2C abone veya 2-3 B2B müşteri

## Rekabet Avantajı Stratejisi

| Zaman | Avantaj | Nasıl |
|-------|---------|-------|
| 0-6 ay | First-mover | Piyasadaki ilk platform |
| 6-12 ay | Track record | Şeffaf doğruluk yüzdesi |
| 12-18 ay | Veri derinliği | Tarihsel tahmin-gerçekleşme birikimi |
| 18+ ay | Fintech entegrasyonu | Yakıt harcama verilerine erişim |

## Proje Sahibi Kesin Kararları (8 madde)

1. ✅ CIF Med verisi ücretsiz kaynaklardan scrape edilecek
2. ✅ ÖTV değişimleri sisteme manuel girilebilir
3. ✅ Yasal çerçeve geliştirmeden ÖNCE araştırılacak
4. ✅ MVP'de admin dashboard olacak
5. ✅ Crowdsource ve Fintech dashboard'da açıklamalı yer alacak
6. ✅ LPG (Otogaz) kapsama dahil
7. ✅ Ücretsiz katman YOK — doğrudan premium
8. ✅ Mevcut sunucu proxy havuzu kullanılacak

---

# 2. Faz Bazlı Yol Haritası

```
  Faz 0          Faz 1           Faz 2              Faz 3
  [Ön Koşullar]  [PoC]          [MVP]              [Ürün]
  1 hafta        4 hafta        6 hafta            8 hafta
  Yasal +        Offline        Telegram +          B2B API +
  Veri tespiti   Model Test     Dashboard +         Ölçekleme +
                                Premium Lansman     Monitoring
       │              │               │                │
       ▼              ▼               ▼                ▼
   Go/No-Go       Go/No-Go       Go/No-Go        Büyüme Kararı
   Yasal engel?   %70 doğruluk?  100 abone?       MRR ≥ ₺10K?
```

**Toplam:** ~19 hafta (~5 ay)

### Faz 0: Ön Koşullar (1 hafta) — BLOCKER

| Ön Koşul | Sorumlu | Kriter |
|----------|---------|--------|
| Yasal çerçeve araştırması | claude-web-arastirmaci | "Devam edilebilir" kararı |
| CIF Med veri kaynağı tespiti | claude-web-arastirmaci | ≥2 ücretsiz kaynak |
| B2B müşteri görüşmeleri | gemini-urun-yoneticisi | 10 görüşme, fiyat doğrulaması |

⛔ **Yasal araştırma "engel var" sonucu verirse proje DURDURULUR.**

### Faz 1: PoC (4 hafta)

| Deliverable | Açıklama |
|-----------|----------|
| Veri toplama scriptleri | Brent, USD/TRY (TCMB), CIF Med (scrape), EPDK pompa fiyatları |
| Tarihsel veri seti | 2 yıllık temizlenmiş veri (benzin+motorin+LPG) |
| XGBoost modeli | Sınıflandırma (zam/indirim/sabit) + Regresyon (TL değişim) |
| Backtesting raporu | Jupyter notebook: yön accuracy, MAE, confusion matrix |

**Go/No-Go:** ≥%70 yön doğruluğu, ≤±0.50 TL MAE, CIF proxy R²≥0.85

### Faz 2: MVP (6 hafta)

| Deliverable | Açıklama |
|-----------|----------|
| Canlı veri pipeline | Cron ile günlük veri çekimi, PostgreSQL |
| Karar motoru | Dual-model: nowcast (1-3g) + trend (1-4 hafta) |
| Telegram botu | Admin onaylı, premium, 3 yakıt türü, disclaimer |
| Admin dashboard | Veri grafikleri, tahmin izleme, abone onay/red |
| Ödeme sistemi | iyzico/Stripe entegrasyonu |

**Go/No-Go:** ≥%65 canlı doğruluk, ≥100 abone, ≥5 B2B pilot

### Faz 3: Ürün (8 hafta)

| Deliverable | Açıklama |
|-----------|----------|
| B2B REST API | Token auth, rate limiting, webhook |
| Otomatik ML pipeline | Haftalık retraining, drift detection |
| Monitoring sistemi | Health check, performance tracking |
| Crowdsource/Fintech modülleri | Dashboard açıklama bölümleri |

**Go/No-Go:** ≥10 müşteri, MRR≥₺10K, ≥%70 doğruluk, ≥%99 uptime

---

# 3. Ürün Backlog ve User Story'ler

## Epic Listesi

| ID | Başlık | Hedef Faz |
|----|--------|-----------|
| E01 | Temel & Yasal Uyumluluk | Faz 0 |
| E02 | Veri Altyapısı (ETL) | Faz 1 |
| E03 | Tahmin Motoru (AI Core) | Faz 1 |
| E04 | Telegram Bot Arayüzü | Faz 2 |
| E05 | Admin Dashboard | Faz 2 |
| E06 | B2B API Servisleri | Faz 3 |
| E07 | Ticari & Ödeme Altyapısı | Faz 3 |

## User Story'ler (25 adet)

### Must Have (14 story — 74 SP)

| ID | Epic | User Story | SP | Faz |
|----|------|-----------|-----|-----|
| US-001 | E01 | Proje sahibi olarak, yasal risk raporu istiyorum | 3 | 0 |
| US-002 | E01 | Proje sahibi olarak, B2B müşteri görüşme sonuçları istiyorum | 5 | 0 |
| US-003 | E02 | Sistem olarak, günlük Brent+kur verisi çekmek istiyorum | 3 | 1 |
| US-004 | E02 | Sistem olarak, pompa fiyatlarını scrape etmek istiyorum | 5 | 1 |
| US-006 | E03 | Data scientist olarak, XGBoost modelini eğitmek istiyorum | 8 | 1 |
| US-007 | E03 | Data scientist olarak, backtesting yapmak istiyorum | 5 | 1 |
| US-008 | E05 | Admin olarak, kullanıcı onay/red ekranı istiyorum | 5 | 2 |
| US-009 | E05 | Admin olarak, tahmin grafikleri görmek istiyorum | 8 | 2 |
| US-010 | E04 | B2C kullanıcı olarak, bot'a kayıt olmak istiyorum | 3 | 2 |
| US-011 | E04 | Sistem olarak, %70+ olasılıkta mesaj göndermek istiyorum | 5 | 2 |
| US-016 | E06 | B2B müşteri olarak, REST API'den tahmin çekmek istiyorum | 8 | 3 |
| US-017 | E06 | Admin olarak, API anahtarı yönetimi istiyorum | 3 | 3 |
| US-018 | E07 | B2C kullanıcı olarak, kart ile abonelik başlatmak istiyorum | 8 | 3 |
| US-019 | E07 | Admin olarak, ödemesi geçeni otomatik durdurmak istiyorum | 5 | 3 |

### Should Have (7 story — 27 SP)

| ID | Epic | User Story | SP | Faz |
|----|------|-----------|-----|-----|
| US-005 | E02 | Admin olarak, ÖTV'yi manuel girmek istiyorum | 2 | 1 |
| US-012 | E05 | Admin olarak, kur/ÖTV parametrelerini izlemek istiyorum | 3 | 2 |
| US-013 | E04 | B2C kullanıcı olarak, /durum sorgusu yapmak istiyorum | 3 | 2 |
| US-014 | E04 | B2B kullanıcı olarak, LPG bildirimi almak istiyorum | 5 | 2 |
| US-021 | E03 | Data scientist olarak, otomatik haftalık retrain istiyorum | 8 | 3 |
| US-022 | E05 | Admin olarak, sistem loglarını görmek istiyorum | 3 | 3 |
| US-025 | E05 | Admin olarak, müşteri segmentleri tanımlamak istiyorum | 3 | 3 |

### Could Have (4 story — 15 SP)

| ID | Epic | User Story | SP | Faz |
|----|------|-----------|-----|-----|
| US-015 | E05 | Admin olarak, Fintech entegrasyon bölümü istiyorum | 2 | 2 |
| US-020 | E05 | Admin olarak, Crowdsource veri toplama alanı istiyorum | 5 | 3 |
| US-023 | E06 | B2B müşteri olarak, performans raporu API'si istiyorum | 3 | 3 |
| US-024 | E04 | B2C kullanıcı olarak, referral sistemi istiyorum | 5 | 3 |

### Won't Have (Bu fazda yapılmayacak)
- Mobil uygulama
- Harita üzerinde istasyon gösterme
- Ücretsiz katman

**Toplam: 25 User Story, 116 Story Point**

---

# 4. Sprint Planı ve Görev Dağılımı

## Sprint Özeti (10 Sprint, 19 Hafta)

| Sprint | Faz | Süre | Hedef | SP |
|--------|-----|------|-------|-----|
| **S0** | Faz 0 | 1 hafta | Yasal çerçeve + ticari validasyon | 8 |
| **S1** | Faz 1 | 2 hafta | Veri toplama altyapısı | 10 |
| **S2** | Faz 1 | 2 hafta | PoC model + backtesting | 13 |
| **S3** | Faz 2 | 2 hafta | Telegram bot + alarm + kullanıcı onayı | 13 |
| **S4** | Faz 2 | 2 hafta | Admin dashboard | 14 |
| **S5** | Faz 2 | 2 hafta | LPG + fintech bilgi alanı | 7 |
| **S6** | Faz 3 | 2 hafta | B2B API + anahtar yönetimi | 11 |
| **S7** | Faz 3 | 2 hafta | Ödeme + abonelik kontrolü | 13 |
| **S8** | Faz 3 | 2 hafta | Retrain + log + performans API | 14 |
| **S9** | Faz 3 | 2 hafta | Segmentasyon + crowdsource + referral | 13 |

## Görev Listesi (26 Görev)

| ID | Görev | Agent | Effort | Bağımlılık | Sprint |
|----|-------|-------|--------|------------|--------|
| T-001 | Yasal çerçeve raporu | claude-web-arastirmaci | M | - | S0 |
| T-002 | B2B müşteri görüşme raporu | gemini-urun-yoneticisi | L | - | S0 |
| T-003 | Brent + USD/TRY veri çekme | claude-kidemli-gelistirici | M | T-001 | S1 |
| T-004 | Pompa fiyat scraping | claude-kidemli-gelistirici | L | T-001 | S1 |
| T-005 | ÖTV manuel giriş arayüzü | gemini-kodlayici | S | T-003 | S1 |
| T-006 | Feature engineering + eğitim seti | claude-kidemli-gelistirici | L | T-003,T-004 | S2 |
| T-007 | XGBoost model eğitimi | claude-kidemli-gelistirici | L | T-006 | S2 |
| T-008 | Backtesting + rapor | claude-kidemli-gelistirici | M | T-007 | S2 |
| T-009 | Telegram bot kayıt + KVKK | gemini-kodlayici | M | T-001 | S3 |
| T-010 | Alarm motoru + disclaimer | claude-kidemli-gelistirici | M | T-007,T-009 | S3 |
| T-011 | Admin kullanıcı onay/red | gemini-kodlayici | M | T-009 | S3 |
| T-012 | Admin tahmin grafikleri | gemini-uiux-tasarimci | L | T-007 | S4 |
| T-013 | Kur/ÖTV izleme widget'ları | gemini-kodlayici | S | T-003,T-005 | S4 |
| T-014 | /durum komutu | gemini-kodlayici | S | T-010 | S4 |
| T-015 | LPG veri + model entegrasyonu | claude-kidemli-gelistirici | M | T-006 | S5 |
| T-016 | Fintech bilgi bölümü | gemini-uiux-tasarimci | S | T-012 | S5 |
| T-017 | B2B REST API | claude-teknik-lider | L | T-007 | S6 |
| T-018 | API anahtar yönetimi | claude-teknik-lider | M | T-017 | S6 |
| T-019 | Ödeme entegrasyonu | claude-devops | L | T-011 | S7 |
| T-020 | Abonelik bitiş kontrolü | claude-devops | M | T-019 | S7 |
| T-021 | Haftalık retrain pipeline | claude-kidemli-gelistirici | L | T-007 | S8 |
| T-022 | Dashboard log paneli | claude-qa-senaryo | S | T-017 | S8 |
| T-023 | /stats API (accuracy) | claude-teknik-lider | S | T-017 | S8 |
| T-024 | Crowdsource bildirim akışı | codex-junior-gelistirici | M | T-009,T-011 | S9 |
| T-025 | Referral akışı | gemini-kodlayici | M | T-009 | S9 |
| T-026 | Segmentasyon ve RBAC | claude-guvenlik-analisti | M | T-018 | S9 |

## Bağımlılık Grafiği

```
T-001 (Yasal) ─┬→ T-003 (Brent) ─┬→ T-006 (Features) → T-007 (Model) ─┬→ T-010 (Alarm)
                │                  │                                      ├→ T-012 (Dashboard)
                │                  │                                      ├→ T-017 (B2B API)
                │                  │                                      └→ T-021 (Retrain)
                │                  └→ T-005 (ÖTV) → T-013 (Widget)
                └→ T-004 (Pompa) → T-006
                └→ T-009 (Bot) ─┬→ T-011 (Onay) → T-019 (Ödeme) → T-020 (Kontrol)
                                ├→ T-024 (Crowdsource)
                                └→ T-025 (Referral)

T-007 → T-008 (Backtest)
T-006 → T-015 (LPG)
T-010 → T-014 (/durum)
T-012 → T-016 (Fintech bilgi)
T-017 → T-018 (API key) → T-026 (RBAC)
T-017 → T-022 (Log), T-023 (/stats)
```

**Kritik Yol:** T-001 → T-003 → T-006 → T-007 → T-010 → T-012 → MVP Go/No-Go

## Dalga Sistemi (Sprint İçi Paralel Çalışma)

| Dalga | Kategori | Görevler |
|-------|----------|----------|
| D1 | Araştırma/Compliance | T-001, T-002 |
| D2 | Data/ML | T-003, T-004, T-006, T-007, T-008, T-015, T-021 |
| D3 | Bot/Backend | T-009, T-010, T-014, T-017, T-018, T-023 |
| D4 | Dashboard/UI | T-011, T-012, T-013, T-016, T-022 |
| D5 | Ops/Monetization | T-019, T-020, T-026 |
| D6 | Growth/Community | T-024, T-025 |

## Agent Yük Dağılımı

| Agent | Görev Sayısı | Kritik Yolda mı? |
|-------|-------------|-------------------|
| claude-kidemli-gelistirici | 10 | EVET — darboğaz |
| gemini-kodlayici | 6 | Kısmen |
| claude-teknik-lider | 3 | Evet (B2B API) |
| gemini-uiux-tasarimci | 2 | Evet (Dashboard) |
| claude-web-arastirmaci | 1 | Evet (BLOCKER) |
| claude-devops | 2 | Hayır |
| claude-qa-senaryo | 1 | Hayır |
| claude-guvenlik-analisti | 1 | Hayır |
| codex-junior-gelistirici | 1 | Hayır |
| gemini-urun-yoneticisi | 1 | Hayır |

---

# 5. Risk Matrisi

| # | Risk | Skor | Azaltma |
|---|------|------|---------|
| R01 | **EPDK/yasal engel** | **15** (3×5) | Faz 0'da yasal araştırma — BLOCKER |
| R02 | CIF Med veri erişilemez | **12** (3×4) | Brent proxy modeli |
| R03 | Model doğruluğu yetersiz | **12** (3×4) | Feature iterasyonu, ensemble |
| R06 | B2B satış döngüsü uzun | **12** (4×3) | Ücretsiz pilot, ROI gösterimi |
| R09 | Tek kişi bağımlılığı | **12** (4×3) | Otomasyon + dokümantasyon |
| R11 | Gelir modeli tutmuyor | **12** (3×4) | Fiyat A/B testi |
| R05 | İtibar riski (yanlış tahmin) | **9** (3×3) | Olasılık dili, şeffaf analiz |
| R08 | Veri pipeline kesintisi | **9** (3×3) | Çoklu kaynak, monitoring |
| R04 | Ani ÖTV kararı | **8** (2×4) | Manuel flag, düşük güvenilirlik etiketi |
| R07 | Panik alım tetikleme | **8** (2×4) | Geniş zaman aralığı, disclaimer |
| R10 | LPG veri yetersizliği | **6** (3×2) | Beta etiketi |
| R12 | Rakip giriş | **6** (2×3) | Track record, B2B ilişkiler |
| R13 | Sunucu kapasite yetersizliği | **4** (2×2) | Monitoring, ölçekleme planı |

---

# 6. Başarı Metrikleri

## Kuzey Yıldızı Metriği
**"Doğru zam uyarısı alan ve buna göre aksiyon alan aktif ödeme yapan müşteri sayısı"**
12 aylık hedef: ≥500 aktif ödeme yapan müşteri

## Faz Bazlı KPI'lar

| Faz | KPI | Hedef |
|-----|-----|-------|
| **Faz 0** | Yasal çerçeve raporu | "Devam edilebilir" kararı |
| **Faz 0** | CIF veri kaynağı | ≥2 ücretsiz kaynak |
| **Faz 1** | Yön doğruluğu (benzin/motorin) | ≥%70 Accuracy |
| **Faz 1** | Yön doğruluğu (LPG) | ≥%65 Accuracy |
| **Faz 1** | Fiyat sapması | ≤±0.50 TL MAE |
| **Faz 1** | CIF proxy korelasyonu | R² ≥ 0.85 |
| **Faz 2** | Canlı doğruluk | ≥%65 (1.ay), ≥%70 (3.ay) |
| **Faz 2** | Premium B2C abone | ≥100 ödeme yapan |
| **Faz 2** | B2B pilot görüşme | ≥5 firma |
| **Faz 2** | Veri pipeline uptime | ≥%95 |
| **Faz 2** | Churn oranı | ≤%15/ay |
| **Faz 3** | MRR | ≥₺10.000/ay |
| **Faz 3** | Toplam müşteri | ≥10 (B2C+B2B) |
| **Faz 3** | API uptime | ≥%99 |
| **Faz 3** | Kümülatif doğruluk | ≥%70 |
| **Faz 3** | NPS | ≥40 |

## Kritik Kabul Kriterleri

1. Model yön doğruluğu ≥%70 (backtest)
2. Her bildirimde "Yatırım tavsiyesi değildir" disclaimer'ı
3. API yanıt süresi <500ms
4. Token/session bazlı güvenlik
5. Veri güncelliği: günde en az 1 kez
6. Admin filtresinden geçmeyen bildirim kullanıcıya gitmez

---

## Stratejik Kararlar Özeti

### Alınmış (11 karar)
K01: Ücretsiz katman YOK | K02: CIF ücretsiz scraping | K03: ÖTV manuel | K04: Yasal önce | K05: MVP'de dashboard | K06: 3 yakıt türü | K07: B2B lojistik birincil | K08: 3 faz go/no-go | K09: Mevcut sunucu | K10: "Erken uyarı" konumlandırması | K11: Crowdsource+Fintech dashboard'da

### Ertelenen (7 karar)
E01: Fintech kapsamı (Faz 3+) | E02: Crowdsource detayları (Faz 3+) | E03: Enterprise fiyatlandırma | E04: Mobil uygulama | E05: LSTM/TCN model | E06: İnsan onayı otomatik/manuel | E07: Gamification

---

**Doküman Tarihi:** 2026-02-15
**Hazırlayanlar:** Claude Opus (Stratejik) + Gemini 3 (Ürün) + Codex GPT-5.2 (Operasyonel)
**Onay Bekliyor:** Proje Sahibi
