

Tamam, bu kapsamlı bir teknik mimari ve veritabanı tasarım görevi. Önce mevcut projeyi anlayayım ve sonra detaylı çıktıları üreteyim.

# Türkiye Yakıt Maliyet Baskı Altyapısı — Blueprint v1

## Teknik Mimari Karar Dokümanı

---

## ÇIKTI 1 — TEKNİK MİMARİ DİYAGRAMI

### 1.1 — Beş Katmanlı Sistem Diyagramı (Tam Görünüm)

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    KATMAN 5 — SUNUM                                                 │
│                                                                                                     │
│   ┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────────────┐           │
│   │   ADMIN DASHBOARD    │   │    TELEGRAM BOT       │   │      B2B REST API            │           │
│   │   (React/Next.js)    │   │  (python-telegram-bot)│   │    (FastAPI + JWT)           │           │
│   │                      │   │                       │   │                              │           │
│   │ • MBE Gauge          │   │ • /durum komutu       │   │ GET /api/v1/mbe/current      │           │
│   │ • Risk Isı Haritası  │   │ • /tahmin komutu      │   │ GET /api/v1/risk/score        │           │
│   │ • Zam Takvimi        │   │ • Otomatik Alert      │   │ GET /api/v1/predictions       │           │
│   │ • SHAP Grafiği       │   │ • Günlük Özet         │   │ GET /api/v1/cost/breakdown    │           │
│   │ • Rejim Zaman Çiz.   │   │ • Abone Yönetimi     │   │ POST /api/v1/alerts/subscribe │           │
│   └──────────┬───────────┘   └──────────┬────────────┘   └──────────────┬───────────────┘           │
│              │                           │                               │                           │
│              └───────────────────────────┼───────────────────────────────┘                           │
│                                          │                                                           │
│                              ┌───────────▼────────────┐                                             │
│                              │   SUNUM GATEWAY         │                                             │
│                              │   (WebSocket + REST)    │                                             │
│                              │   Rate Limit: 100/dk   │                                             │
│                              └───────────┬────────────┘                                             │
└──────────────────────────────────────────┼──────────────────────────────────────────────────────────┘
                                           │
               ┌───────────────────────────┼────────────────────────────────┐
               │                           │                                │
               ▼                           ▼                                ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                              KATMAN 4 — ML DESTEKLEYİCİ                                             │
│                         ┌─────────────────────────────────────┐                                      │
│                         │        CIRCUIT BREAKER               │                                      │
│                         │  (ML çökerse → bypass → Katman 3)   │◄──── GRACEFUL DEGRADATION           │
│                         └────────────────┬────────────────────┘                                      │
│                                          │                                                           │
│   ┌──────────────────────┐   ┌───────────▼───────────┐   ┌──────────────────────────┐              │
│   │  FEATURE ENGINEERING │   │   MODEL ENSEMBLE       │   │    AÇIKLANABILIRLIK      │              │
│   │                      │   │                        │   │                          │              │
│   │ • MBE rolling stats  │──▶│ ┌──────────────────┐  │   │  ┌────────────────────┐  │              │
│   │ • FX momentum        │   │ │ XGBoost           │  │──▶│  │ SHAP Değerleri     │  │              │
│   │ • Brent lag(1..5)    │   │ │ (zam olasılığı)   │  │   │  │ (feature katkısı)  │  │              │
│   │ • Politik gün sayacı │   │ └──────────────────┘  │   │  └────────────────────┘  │              │
│   │ • Rejim one-hot      │   │ ┌──────────────────┐  │   │  ┌────────────────────┐  │              │
│   │ • Mevsimsellik       │   │ │ LightGBM          │  │──▶│  │ Confidence Band    │  │              │
│   │ • Tatil flag         │   │ │ (TL zam tahmini)  │  │   │  │ (güven aralığı)    │  │              │
│   └──────────────────────┘   │ └──────────────────┘  │   │  └────────────────────┘  │              │
│                              └────────────────────────┘   └──────────────────────────┘              │
│                                          │                                                           │
│                              ┌───────────▼────────────┐                                             │
│                              │  ML Prediction Cache    │                                             │
│                              │  (Redis, TTL=6h)        │                                             │
│                              └───────────┬────────────┘                                             │
└──────────────────────────────────────────┼──────────────────────────────────────────────────────────┘
                                           │
           ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
                    GRACEFUL DEGRADATION    │                                    
           │       ML bypass edildiğinde    │  Katman 3 çıktısı doğrudan       │
                   Katman 5'e iletilir  ◄──┘  sunum katmanına gider            
           └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
                                           │
┌──────────────────────────────────────────┼──────────────────────────────────────────────────────────┐
│                           KATMAN 3 — RİSK & EŞİK                                                   │
│                                          │                                                           │
│   ┌──────────────────────┐   ┌───────────▼───────────┐   ┌──────────────────────────┐              │
│   │ DİNAMİK EŞİK MOTORU │   │   RİSK SKOR MOTORU    │   │  POLİTİK GECİKME        │              │
│   │                      │   │                        │   │  METRİĞİ                │              │
│   │ • Percentile bazlı   │   │  risk = Σ(wᵢ × fᵢ)   │   │                          │              │
│   │   eşik hesaplama     │──▶│                        │◄──│ • Seçim yakınlık skoru  │              │
│   │ • Rejim-koşullu      │   │  f1: MBE seviyesi     │   │ • Bayram tatil etkisi   │              │
│   │   eşik ayarlama      │   │  f2: FX volatilite    │   │ • Son zam-gün mesafesi  │              │
│   │ • Uyarı tetikleme    │   │  f3: Politik gecikme   │   │ • Geçmiş gecikme ort.   │              │
│   │ • Hysteresis (çift   │   │  f4: Eşik aşım oranı  │   │ • Hükümet açıklama      │              │
│   │   eşik: açma/kapama) │   │  f5: Trend momentum    │   │   sentiment (opsiyonel) │              │
│   └──────────────────────┘   └───────────┬────────────┘   └──────────────────────────┘              │
│                                          │                                                           │
│                              ┌───────────▼────────────┐                                             │
│                              │  ALERT DISPATCHER       │                                             │
│                              │  Kural: risk ≥ eşik →   │                                             │
│                              │  alert üret + log       │                                             │
│                              └───────────┬────────────┘                                             │
└──────────────────────────────────────────┼──────────────────────────────────────────────────────────┘
                                           │
┌──────────────────────────────────────────┼──────────────────────────────────────────────────────────┐
│                     KATMAN 2 — HESAPLAMA (DETERMİNİSTİK ÇEKİRDEK)                                  │
│                                          │                                                           │
│   ┌──────────────────────────────────────▼──────────────────────────────────────────────┐           │
│   │                        MALİYET BİRİKİM ENDEKSİ (MBE)                                │           │
│   │                                                                                      │           │
│   │   MBE(t) = [ CIF_med(t) × USD_TRY(t) × (1 + OTV_rate) × (1 + KDV_rate)            │           │
│   │              + distribution_margin ] / pump_price(t)                                 │           │
│   │                                                                                      │           │
│   │   MBE > 1.0  →  Maliyet baskısı var (zam yönünde baskı)                            │           │
│   │   MBE < 1.0  →  Maliyet baskısı yok (indirim yönünde baskı)                        │           │
│   │   MBE ≈ 1.0  →  Denge durumu                                                        │           │
│   └──────────────────────────────────────┬──────────────────────────────────────────────┘           │
│                                          │                                                           │
│   ┌──────────────────────┐   ┌───────────▼───────────┐   ┌──────────────────────────┐              │
│   │ REVERSE-ENGINEER     │   │   SMA & TREND          │   │  FARK HESAPLAMA          │              │
│   │ MALİYET              │   │                        │   │                          │              │
│   │                      │   │ • 5-gün SMA(MBE)      │   │ • Son zam tarihinden     │              │
│   │ implied_cost =       │   │ • 10-gün SMA(MBE)     │   │   bu yana kümülatif      │              │
│   │   pump_price ÷       │──▶│ • Trend yönü flag     │──▶│   maliyet değişimi (%)   │              │
│   │   (1+OTV)(1+KDV)     │   │ • Momentum delta      │   │ • Beklenen vs gerçek     │              │
│   │   - margin           │   │                        │   │   fiyat farkı (TL/lt)    │              │
│   │   → CIF×FX implied   │   │                        │   │                          │              │
│   └──────────────────────┘   └────────────────────────┘   └──────────────────────────┘              │
│                                          │                                                           │
│                              ┌───────────▼────────────┐                                             │
│                              │ Günlük Snapshot Yazıcı  │                                             │
│                              │ (cost_base_snapshots)   │                                             │
│                              └───────────┬────────────┘                                             │
└──────────────────────────────────────────┼──────────────────────────────────────────────────────────┘
                                           │
┌──────────────────────────────────────────┼──────────────────────────────────────────────────────────┐
│                           KATMAN 1 — VERİ                                                           │
│                                          │                                                           │
│   ┌──────────────────────┐   ┌───────────▼───────────┐   ┌──────────────────────────┐              │
│   │ DIŞ KAYNAKLAR        │   │   VERİ TOPLAMA        │   │  İÇ VERİ                 │              │
│   │                      │   │   ORKESTRATÖRİ        │   │                          │              │
│   │ ┌─────────────────┐  │   │   (APScheduler /      │   │ ┌──────────────────────┐ │              │
│   │ │ Argus/Platts    │──┼──▶│    Celery Beat)       │   │ │ tax_parameters       │ │              │
│   │ │ (CIF Med)       │  │   │                        │   │ │ (ÖTV, KDV oranları) │ │              │
│   │ └─────────────────┘  │   │ • Günlük 09:00 UTC    │──▶│ └──────────────────────┘ │              │
│   │ ┌─────────────────┐  │   │ • Retry: 3× exp.back  │   │ ┌──────────────────────┐ │              │
│   │ │ TCMB / XE.com   │──┼──▶│ • Validation pipeline │   │ │ regime_events        │ │              │
│   │ │ (USD/TRY kuru)  │  │   │ • Anomaly detection   │   │ │ (seçim, tatil, kriz) │ │              │
│   │ └─────────────────┘  │   │ • Gap-fill logic      │   │ └──────────────────────┘ │              │
│   │ ┌─────────────────┐  │   │ • Audit trail         │   │ ┌──────────────────────┐ │              │
│   │ │ EPDK / Dağıtıcı │──┼──▶│                        │   │ │ price_changes        │ │              │
│   │ │ (Pompa fiyatı)  │  │   │                        │   │ │ (geçmiş zam/indirim) │ │              │
│   │ └─────────────────┘  │   └────────────────────────┘   │ └──────────────────────┘ │              │
│   │ ┌─────────────────┐  │              │                 │                          │              │
│   │ │ Resmi Gazete    │──┼──────────────┘                 │                          │              │
│   │ │ (ÖTV değişiklik)│  │                                │                          │              │
│   │ └─────────────────┘  │                                │                          │              │
│   └──────────────────────┘                                └──────────────────────────┘              │
│                                          │                                                           │
│                              ┌───────────▼────────────┐                                             │
│                              │    PostgreSQL           │                                             │
│                              │    (daily_market_data)  │                                             │
│                              └───────────┬────────────┘                                             │
└──────────────────────────────────────────┼──────────────────────────────────────────────────────────┘
                                           │
                               ┌───────────▼────────────┐
                               │     ALTYAPI KATMANI     │
                               │                         │
                               │  PostgreSQL 16 (Ana DB) │
                               │  Redis 7 (Cache+Queue)  │
                               │  Celery (Task Queue)    │
                               │  Docker Compose (Dev)   │
                               │  K8s / Fly.io (Prod)    │
                               │  Prometheus + Grafana   │
                               └─────────────────────────┘
```

### 1.2 — Graceful Degradation Akış Diyagramı

```
                    ┌─────────────────────────────┐
                    │     Normal Operasyon         │
                    │  Katman 1→2→3→4→5 tam akış  │
                    └──────────────┬───────────────┘
                                   │
                          ML Katmanı sağlıklı mı?
                                   │
                    ┌──────────────┼──────────────┐
                    │              │               │
                   EVET          HAYIR         KISMEN
                    │              │               │
                    ▼              ▼               ▼
          ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐
          │  TAM MOD     │ │  SAFE MOD    │ │  PARTIAL MOD     │
          │              │ │              │ │                  │
          │ Tüm katmanlar│ │ Katman 1-3   │ │ Çalışan model    │
          │ aktif        │ │ aktif        │ │ kullanılır,      │
          │              │ │              │ │ çöken atlanır    │
          │ ML tahminleri│ │ ML tahmin =  │ │                  │
          │ gösterilir   │ │ "N/A"        │ │ Confidence flag  │
          │              │ │              │ │ = "partial"      │
          │ Confidence:  │ │ Dashboard'da │ │                  │
          │ "full"       │ │ uyarı banner │ │ Dashboard'da     │
          │              │ │ gösterilir   │ │ hangi modelin    │
          │              │ │              │ │ çalıştığı        │
          │              │ │ Alert:       │ │ gösterilir       │
          │              │ │ "Deterministik│ │                  │
          │              │ │  mod aktif"  │ │                  │
          └─────────────┘ └──────────────┘ └──────────────────┘
                    │              │               │
                    └──────────────┼───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │  HER DURUMDA GARANTİ:        │
                    │                              │
                    │  ✓ MBE hesaplanır            │
                    │  ✓ Risk skoru üretilir       │
                    │  ✓ Eşik kontrolü yapılır     │
                    │  ✓ Alert tetiklenir          │
                    │  ✓ Dashboard güncellenir     │
                    │                              │
                    │  ML OLMADAN EKSİK OLAN:      │
                    │  ✗ Zam olasılığı tahmini     │
                    │  ✗ TL zam büyüklüğü tahmini │
                    │  ✗ SHAP açıklamaları         │
                    └──────────────────────────────┘
```

### 1.3 — Dış Entegrasyon Haritası

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         DIŞ ENTEGRASYONLAR                                   │
│                                                                              │
│  VERI GİRİŞ (Inbound)                    VERİ ÇIKIŞ (Outbound)             │
│  ════════════════════                     ═════════════════════              │
│                                                                              │
│  ┌─────────────────┐                     ┌──────────────────┐               │
│  │ Argus/Platts    │ ── SFTP/API ──┐     │ Telegram API     │◄── Webhook   │
│  │ CIF Med Fiyat   │               │     │ (Bot Notify)     │               │
│  └─────────────────┘               │     └──────────────────┘               │
│  ┌─────────────────┐               │     ┌──────────────────┐               │
│  │ TCMB EVDS API   │ ── REST ─────┤     │ B2B Müşteriler   │◄── REST+JWT  │
│  │ USD/TRY Kuru    │               │     │ (Fleet, Lojistik)│               │
│  └─────────────────┘               │     └──────────────────┘               │
│  ┌─────────────────┐               │     ┌──────────────────┐               │
│  │ EPDK / Dağıtıcı │ ── Scrape ──┤     │ Prometheus       │◄── Metrics   │
│  │ Pompa Fiyatları  │   + API      │     │ (Monitoring)     │               │
│  └─────────────────┘               │     └──────────────────┘               │
│  ┌─────────────────┐               │     ┌──────────────────┐               │
│  │ Resmi Gazete    │ ── Scrape ───┤     │ Sentry           │◄── Errors    │
│  │ ÖTV Değişiklik  │               │     │ (Error Tracking) │               │
│  └─────────────────┘               │     └──────────────────┘               │
│  ┌─────────────────┐               │     ┌──────────────────┐               │
│  │ XE.com Backup   │ ── REST ─────┘     │ S3/MinIO         │◄── Backup    │
│  │ (FX Fallback)   │                     │ (DB Snapshots)   │               │
│  └─────────────────┘                     └──────────────────┘               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 — Veri Akış Pipeline Diyagramı

```
09:00 UTC                                                              09:15 UTC
   │                                                                      │
   ▼                                                                      ▼
┌──────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  ┌────────┐
│FETCH │───▶│VALIDATE  │───▶│ COMPUTE  │───▶│  RISK    │───▶│   ML     │─▶│PUBLISH │
│      │    │          │    │          │    │          │    │          │  │        │
│CIF   │    │Range chk │    │MBE calc  │    │Score gen │    │Predict   │  │Alert   │
│FX    │    │Type chk  │    │SMA calc  │    │Threshold │    │SHAP calc │  │Dash    │
│Pump  │    │Gap fill  │    │Diff calc │    │Alert chk │    │Cache     │  │API     │
│Tax   │    │Dedup     │    │Snapshot  │    │Delay met │    │          │  │Bot     │
└──────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  └────────┘
   │              │               │               │               │           │
   ▼              ▼               ▼               ▼               ▼           ▼
┌──────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  ┌────────┐
│daily_│    │data_     │    │mbe_calc  │    │risk_     │    │ml_pred   │  │alerts  │
│market│    │quality   │    │cost_base │    │scores    │    │          │  │        │
│_data │    │_log      │    │_snapshot │    │          │    │          │  │        │
└──────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘  └────────┘
                                                                  │
                                                         ML ÇÖKERSE│bypass
                                                                  ▼
                                                        ┌──────────────┐
                                                        │ risk_scores  │
                                                        │ DOĞRUDAN →   │
                                                        │ alerts +     │
                                                        │ publish      │
                                                        └──────────────┘
```

### 1.5 — Katman Detay Açıklamaları

**KATMAN 1 — VERİ (Data Ingestion Layer)**

| Bileşen | Kaynak | Frekans | Yöntem | Fallback |
|---------|--------|---------|--------|----------|
| CIF Mediterranean | Argus/Platts | Günlük (iş günü) | SFTP veya REST API | Önceki günün değeri + flag |
| USD/TRY Kuru | TCMB EVDS API | Günlük | REST (JSON) | XE.com API backup |
| Pompa Fiyatları | EPDK / Dağıtıcı siteleri | Günlük | Web scraping + API | Manuel giriş UI |
| ÖTV/KDV Oranları | Resmi Gazete + Manuel | Event-driven | Scrape + Admin UI | Admin UI ile manuel güncelleme |
| Rejim Eventleri | Admin + Otomatik | Event-driven | Admin UI + kurallar | Tamamen admin kontrolü |

Veri kalitesi kontrol kuralları:
- Range check: CIF Med [200, 1200] USD/ton, USD/TRY [1, 100], Pompa [0.50, 100.00] TL/lt
- Günlük değişim limiti: CIF ±15%, FX ±10%, Pompa ±20%
- Missing data: İş günü eksikse → gap-fill (linear interpolation + flag)
- Duplicate detection: (trade_date, fuel_type) unique constraint

**KATMAN 2 — HESAPLAMA (Deterministic Core)**

Bu katman sistemin kalbidir. ML olmadan bile tek başına değer üretir.

Temel formüller:

```
MBE(t) = Theoretical_Cost(t) / Actual_Pump_Price(t)

Theoretical_Cost(t) = [CIF_med(t) × USD_TRY(t) × barrel_to_liter_coeff
                       × (1 + OTV_rate(t))
                       × (1 + KDV_rate)]
                      + distribution_margin(t)

Reverse_Implied_CIF(t) = [Pump_Price(t) / ((1+OTV)(1+KDV)) - margin]
                          / (USD_TRY(t) × barrel_to_liter)

SMA_5(t) = AVG(MBE(t-4)...MBE(t))

Since_Last_Change(t) = MBE(t) - MBE(last_price_change_date)
                       → Kümülatif baskı birikimi
```

**KATMAN 3 — RİSK & EŞİK (Risk & Threshold Engine)**

Risk skoru hesaplama:
```
risk_score(t) = w1 × normalize(MBE(t))              [0.30]  -- Maliyet baskısı seviyesi
              + w2 × normalize(FX_volatility(t))     [0.15]  -- Döviz oynaklığı
              + w3 × normalize(political_delay(t))   [0.20]  -- Politik gecikme
              + w4 × normalize(threshold_breach(t))  [0.20]  -- Eşik aşım oranı
              + w5 × normalize(trend_momentum(t))    [0.15]  -- Trend momentumu
```

Eşik stratejisi (Hysteresis / Çift Eşik):
- Uyarı AÇ eşiği: risk ≥ 0.70 (yüksek baskı)
- Uyarı KAPA eşiği: risk ≤ 0.55 (baskı azaldı)
- Bu çift eşik sistemi, eşik etrafında salınım durumlarında gereksiz alert spam'ini önler.

**KATMAN 4 — ML DESTEKLEYİCİ (ML Enhancement Layer)**

| Model | Görev | Input | Output | Eğitim Frekansı |
|-------|-------|-------|--------|-----------------|
| XGBoost Classifier | Zam olasılığı (7 gün içinde zam var mı?) | MBE, FX trend, politik delay, rejim flags, mevsim | probability [0,1] | Haftalık retrain |
| LightGBM Regressor | Zam büyüklüğü tahmini (TL/lt) | Aynı feature set + historik zam büyüklükleri | TL değeri + confidence interval | Haftalık retrain |

Circuit Breaker kuralları:
- Model inference > 5 saniye → timeout, bypass
- Model accuracy son 30 günde < %60 → otomatik devre dışı + alert
- Feature pipeline hata → bypass + alert
- Manuel override: Admin UI'dan ML katmanı açma/kapama

**KATMAN 5 — SUNUM (Presentation Layer)**

| Kanal | Hedef Kitle | Güncelleme | Özellikler |
|-------|-------------|------------|------------|
| Admin Dashboard | İç ekip, analistler | Real-time (WebSocket) | MBE gauge, risk ısı haritası, SHAP grafiği, rejim timeline |
| Telegram Bot | Filo yöneticileri, bireysel | Push notification | /durum, /tahmin, /abone, günlük özet |
| B2B REST API | Kurumsal müşteriler | On-demand + webhook | JWT auth, rate limit, versiyonlu endpoint'ler |

---

## ÇIKTI 2 — VERİTABANI SCHEMA TASARIMI

### 2.1 — Genel Tasarım İlkeleri

| İlke | Uygulama |
|------|----------|
| Deterministik çekirdek merkezde | `daily_market_data` → `mbe_calculations` → `risk_scores` zinciri bağımsız çalışır |
| High Precision | Tüm parasal ve oran kolonları `NUMERIC(18,8)` — floating point hatası yok |
| fuel_type ENUM | `CREATE TYPE fuel_type_enum AS ENUM ('benzin', 'motorin', 'lpg')` |
| Rejim = Event Flag | `regime_events` tablosu, zaman aralığı değil tekil event olarak modellenir |
| Audit Trail | Her tabloda `created_at`, `updated_at`; kritik tablolarda `source` ve `data_quality_flag` |
| Soft Delete | Kritik tablolarda `is_active` veya `deleted_at` ile soft delete |
| Partitioning | `daily_market_data` ve `mbe_calculations` tabloları `trade_date` üzerinden range partition |

### 2.2 — ENUM Tanımları

```
fuel_type_enum    : 'benzin', 'motorin', 'lpg'
regime_type_enum  : 'election', 'holiday', 'economic_crisis', 'tax_change', 'geopolitical', 'other'
alert_level_enum  : 'info', 'warning', 'critical'
alert_channel_enum: 'telegram', 'email', 'webhook', 'dashboard'
direction_enum    : 'increase', 'decrease', 'no_change'
model_type_enum   : 'xgboost_classifier', 'lightgbm_regressor'
data_quality_enum : 'verified', 'interpolated', 'manual', 'estimated', 'stale'
```

---

### TABLO 1: `daily_market_data`

**Amaç:** Tüm dış kaynaklardan gelen günlük ham piyasa verilerinin tek noktadan depolanması. Sistemin temel veri katmanı. Her satır bir gün + yakıt tipi kombinasyonu.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar, otomatik artan | NO | nextval |
| trade_date | DATE | İşlem tarihi (veri hangi güne ait) | NO | — |
| fuel_type | fuel_type_enum | Yakıt tipi (benzin/motorin/lpg) | NO | — |
| cif_med_usd_ton | NUMERIC(18,8) | CIF Akdeniz fiyatı (USD/ton) | YES | NULL |
| usd_try_rate | NUMERIC(18,8) | USD/TRY döviz kuru (TCMB kapanış) | YES | NULL |
| pump_price_tl_lt | NUMERIC(18,8) | Pompa satış fiyatı (TL/litre, KDV dahil) | YES | NULL |
| brent_usd_bbl | NUMERIC(18,8) | Brent petrol fiyatı (USD/varil) — referans | YES | NULL |
| distribution_margin_tl | NUMERIC(18,8) | Dağıtıcı + bayi marjı (TL/litre) | YES | NULL |
| data_quality_flag | data_quality_enum | Verinin kalite durumu | NO | 'verified' |
| source | VARCHAR(100) | Veri kaynağı (örn: 'argus_api', 'tcmb_evds', 'manual') | NO | — |
| raw_payload | JSONB | Ham API yanıtı (audit ve debug için) | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_daily_market_date_fuel | (trade_date, fuel_type) | UNIQUE | Aynı gün+yakıt için mükerrer kayıt önleme |
| idx_daily_market_date | (trade_date DESC) | B-Tree | Tarih bazlı sorgular (son N gün) |
| idx_daily_market_fuel_date | (fuel_type, trade_date DESC) | B-Tree | Yakıt tipine göre zaman serisi sorguları |
| idx_daily_market_quality | (data_quality_flag) WHERE data_quality_flag != 'verified' | Partial B-Tree | Kalite kontrolü gerektiren kayıtları hızlı bulma |

**Partition:** `trade_date` üzerinden aylık RANGE partition. Eski aylar read-only tablespace'e taşınır.

**FK İlişkileri:** Yok (root tablo, dış veri kaynağı). Diğer tablolar bu tabloya referans verir.

---

### TABLO 2: `tax_parameters`

**Amaç:** ÖTV ve KDV oranlarının zamansal takibi. Vergi oranları değiştiğinde yeni satır eklenir, eski satır `valid_to` ile kapatılır. Böylece geçmişe dönük hesaplamalar doğru vergi oranıyla yapılabilir.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| otv_rate | NUMERIC(18,8) | ÖTV oranı (örn: 0.25 = %25) — sabit TL/lt ise otv_fixed_tl kullanılır | YES | NULL |
| otv_fixed_tl | NUMERIC(18,8) | ÖTV sabit tutar (TL/litre) — Türkiye'de ÖTV genelde sabit tutardır | YES | NULL |
| kdv_rate | NUMERIC(18,8) | KDV oranı (örn: 0.20 = %20) | NO | — |
| valid_from | DATE | Bu oranların geçerlilik başlangıcı | NO | — |
| valid_to | DATE | Bu oranların geçerlilik bitişi (NULL = hâlâ geçerli) | YES | NULL |
| gazette_reference | VARCHAR(255) | Resmi Gazete sayı/tarih referansı | YES | NULL |
| notes | TEXT | Değişiklik açıklaması | YES | NULL |
| created_by | VARCHAR(100) | Kaydı oluşturan kullanıcı/sistem | NO | 'system' |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| idx_tax_fuel_valid | (fuel_type, valid_from DESC) | B-Tree | Belirli bir tarihte geçerli vergi oranını bulma |
| idx_tax_active | (fuel_type) WHERE valid_to IS NULL | Partial B-Tree | Güncel aktif oranları hızlı sorgulama |

**FK İlişkileri:** Yok (referans tablosu). `mbe_calculations` ve `cost_base_snapshots` tarafından tarih aralığı bazlı JOIN ile kullanılır.

---

### TABLO 3: `regime_events`

**Amaç:** Fiyatlamayı etkileyen politik, ekonomik ve takvimsel olayların event flag olarak kaydedilmesi. Her olay ayrı bir satır. Zam gecikmesini açıklayan kontekst sağlar.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| event_type | regime_type_enum | Olay tipi (election, holiday, economic_crisis, vb.) | NO | — |
| event_name | VARCHAR(255) | Olay adı (örn: '2024 Yerel Seçim', 'Kurban Bayramı') | NO | — |
| start_date | DATE | Olayın başlangıç tarihi | NO | — |
| end_date | DATE | Olayın bitiş tarihi (NULL = tek günlük veya devam ediyor) | YES | NULL |
| impact_score | NUMERIC(5,2) | Olayın tahmini etki skoru [0-10] (admin tarafından girilir) | YES | NULL |
| description | TEXT | Olayın detaylı açıklaması | YES | NULL |
| is_active | BOOLEAN | Olay hâlâ aktif mi? | NO | TRUE |
| source | VARCHAR(100) | Olay kaynağı (admin_manual, auto_detected, calendar) | NO | 'admin_manual' |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| idx_regime_dates | (start_date, end_date) | B-Tree | Tarih aralığı sorguları (belirli bir günde aktif eventler) |
| idx_regime_type_date | (event_type, start_date DESC) | B-Tree | Tip bazlı kronolojik sorgular |
| idx_regime_active | (is_active) WHERE is_active = TRUE | Partial B-Tree | Aktif eventleri hızlı listeleme |

**FK İlişkileri:** `political_delay_history.regime_event_id → regime_events.id`

---

### TABLO 4: `price_changes`

**Amaç:** Gerçekleşen tüm fiyat değişikliklerinin (zam ve indirim) kaydedilmesi. Bu tablo, MBE hesaplamasında "son zamdan bu yana fark" metriği ve ML eğitim verisi için kritik.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| change_date | DATE | Fiyat değişikliğinin yürürlük tarihi | NO | — |
| direction | direction_enum | Değişiklik yönü (increase/decrease/no_change) | NO | — |
| old_price_tl_lt | NUMERIC(18,8) | Değişiklik öncesi pompa fiyatı (TL/lt) | NO | — |
| new_price_tl_lt | NUMERIC(18,8) | Değişiklik sonrası pompa fiyatı (TL/lt) | NO | — |
| change_amount_tl | NUMERIC(18,8) | Fark tutarı (TL/lt) — new - old | NO | — |
| change_pct | NUMERIC(10,4) | Yüzde değişim ((new-old)/old × 100) | NO | — |
| mbe_at_change | NUMERIC(18,8) | Değişiklik anındaki MBE değeri | YES | NULL |
| risk_score_at_change | NUMERIC(10,4) | Değişiklik anındaki risk skoru | YES | NULL |
| days_since_last_change | INTEGER | Önceki değişiklikten bu yana geçen gün sayısı | YES | NULL |
| announced_by | VARCHAR(255) | Açıklayan kurum (EPDK, dağıtıcı adı) | YES | NULL |
| source_url | TEXT | Haber/duyuru kaynağı URL'i | YES | NULL |
| notes | TEXT | Ek açıklamalar | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_price_change_fuel_date | (fuel_type, change_date) | UNIQUE | Aynı gün+yakıt mükerrer zam kaydı önleme |
| idx_price_change_date | (change_date DESC) | B-Tree | Kronolojik sorgular |
| idx_price_change_fuel_dir | (fuel_type, direction, change_date DESC) | B-Tree | Yakıt + yön bazlı geçmiş analizi |
| idx_price_change_last | (fuel_type, change_date DESC) INCLUDE (new_price_tl_lt) | Covering B-Tree | Son fiyatı hızlı bulma (index-only scan) |

**FK İlişkileri:** `political_delay_history.price_change_id → price_changes.id`

---

### TABLO 5: `cost_base_snapshots`

**Amaç:** Her gün için hesaplanan teorik maliyet bileşenlerinin snapshot'ı. Reverse-engineer edilmiş maliyet ve bileşenlerin ayrıştırılması. Audit trail ve geçmişe dönük analiz için.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| trade_date | DATE | Snapshot tarihi | NO | — |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| cif_component_tl | NUMERIC(18,8) | CIF bileşeni TL karşılığı (CIF × FX × dönüşüm katsayısı) | NO | — |
| otv_component_tl | NUMERIC(18,8) | ÖTV bileşeni (TL/lt) | NO | — |
| kdv_component_tl | NUMERIC(18,8) | KDV bileşeni (TL/lt) | NO | — |
| margin_component_tl | NUMERIC(18,8) | Dağıtıcı+bayi marj bileşeni (TL/lt) | NO | — |
| theoretical_cost_tl | NUMERIC(18,8) | Toplam teorik maliyet (TL/lt) — tüm bileşenlerin toplamı | NO | — |
| actual_pump_price_tl | NUMERIC(18,8) | Gerçek pompa fiyatı (TL/lt) | NO | — |
| implied_cif_usd_ton | NUMERIC(18,8) | Reverse-engineer: Pompa fiyatından türetilen zımni CIF | NO | — |
| cost_gap_tl | NUMERIC(18,8) | Fark: theoretical_cost - actual_pump_price | NO | — |
| cost_gap_pct | NUMERIC(10,4) | Fark yüzdesi: (theoretical - actual) / actual × 100 | NO | — |
| market_data_id | BIGINT | İlgili daily_market_data kaydı referansı | NO | — |
| tax_param_id | BIGINT | Kullanılan vergi parametresi referansı | NO | — |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_snapshot_date_fuel | (trade_date, fuel_type) | UNIQUE | Günlük teklik garantisi |
| idx_snapshot_date | (trade_date DESC) | B-Tree | Tarih bazlı sorgular |
| idx_snapshot_gap | (fuel_type, cost_gap_pct DESC) | B-Tree | En büyük maliyet farklarını sıralama |
| idx_snapshot_market | (market_data_id) | B-Tree | FK lookup hızlandırma |

**FK İlişkileri:**
- `cost_base_snapshots.market_data_id → daily_market_data.id`
- `cost_base_snapshots.tax_param_id → tax_parameters.id`

---

### TABLO 6: `mbe_calculations`

**Amaç:** Maliyet Birikim Endeksi (MBE) ve türev metriklerin günlük hesaplama sonuçlarının saklanması. Deterministic core'un birincil çıktı tablosu.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| trade_date | DATE | Hesaplama tarihi | NO | — |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| mbe_value | NUMERIC(18,8) | MBE değeri (>1 = baskı var, <1 = baskı yok) | NO | — |
| sma_5 | NUMERIC(18,8) | 5 günlük basit hareketli ortalama (MBE) | YES | NULL |
| sma_10 | NUMERIC(18,8) | 10 günlük basit hareketli ortalama (MBE) | YES | NULL |
| trend_direction | direction_enum | SMA trend yönü (increase = yukarı, decrease = aşağı) | YES | NULL |
| momentum_delta | NUMERIC(18,8) | SMA_5 - SMA_10 (pozitif = hızlanan baskı) | YES | NULL |
| since_last_change_mbe | NUMERIC(18,8) | Son fiyat değişikliğinden bu yana MBE birikimi | YES | NULL |
| since_last_change_days | INTEGER | Son fiyat değişikliğinden bu yana geçen gün | YES | NULL |
| cumulative_cost_drift_pct | NUMERIC(10,4) | Son zamdan bu yana kümülatif maliyet kayması (%) | YES | NULL |
| snapshot_id | BIGINT | İlgili cost_base_snapshot kaydı referansı | NO | — |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_mbe_date_fuel | (trade_date, fuel_type) | UNIQUE | Günlük teklik |
| idx_mbe_date | (trade_date DESC) | B-Tree | Tarih bazlı sorgular |
| idx_mbe_fuel_date | (fuel_type, trade_date DESC) INCLUDE (mbe_value, sma_5) | Covering B-Tree | Yakıt bazlı zaman serisi (index-only scan) |
| idx_mbe_high_pressure | (fuel_type, trade_date DESC) WHERE mbe_value > 1.05 | Partial B-Tree | Yüksek baskı dönemlerini hızlı filtreleme |
| idx_mbe_snapshot | (snapshot_id) | B-Tree | FK lookup |

**Partition:** `trade_date` üzerinden aylık RANGE partition (`daily_market_data` ile aynı strateji).

**FK İlişkileri:** `mbe_calculations.snapshot_id → cost_base_snapshots.id`

---

### TABLO 7: `threshold_config`

**Amaç:** Dinamik eşik parametrelerinin konfigürasyonu. Hangi koşulda hangi seviyede alert tetikleneceğinin yönetimi. Admin tarafından ayarlanabilir, versiyon takibi yapılır.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| fuel_type | fuel_type_enum | Yakıt tipi (NULL = tüm yakıtlar için geçerli) | YES | NULL |
| metric_name | VARCHAR(100) | Eşik uygulanan metrik adı (örn: 'risk_score', 'mbe_value', 'cost_gap_pct') | NO | — |
| alert_level | alert_level_enum | Alert seviyesi (info/warning/critical) | NO | — |
| threshold_open | NUMERIC(18,8) | Alert AÇMA eşiği (metrik bu değeri aşarsa alert tetiklenir) | NO | — |
| threshold_close | NUMERIC(18,8) | Alert KAPAMA eşiği (metrik bu değerin altına düşerse alert kapanır) — Hysteresis | NO | — |
| cooldown_hours | INTEGER | Aynı alert tekrar tetiklenmeden önce bekleme süresi (saat) | NO | 24 |
| is_active | BOOLEAN | Bu eşik kuralı aktif mi? | NO | TRUE |
| regime_modifier | JSONB | Rejim durumlarına göre eşik çarpanları (örn: {"election": 1.2, "holiday": 0.8}) | YES | NULL |
| version | INTEGER | Konfigürasyon versiyon numarası | NO | 1 |
| notes | TEXT | Eşik değişiklik gerekçesi | YES | NULL |
| created_by | VARCHAR(100) | Oluşturan kullanıcı | NO | 'system' |
| valid_from | TIMESTAMPTZ | Bu konfigürasyonun geçerlilik başlangıcı | NO | NOW() |
| valid_to | TIMESTAMPTZ | Geçerlilik bitişi (NULL = hâlâ geçerli) | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| idx_threshold_active | (metric_name, alert_level) WHERE is_active = TRUE AND valid_to IS NULL | Partial B-Tree | Aktif eşikleri hızlı sorgulama |
| idx_threshold_fuel | (fuel_type, metric_name) WHERE is_active = TRUE | Partial B-Tree | Yakıt bazlı eşik sorguları |

**FK İlişkileri:** Yok (bağımsız konfigürasyon tablosu). `alerts` tablosu tarafından `threshold_config_id` ile referans edilir.

---

### TABLO 8: `political_delay_history`

**Amaç:** Politik nedenlerle geciken/ertelenen fiyat değişikliklerinin kaydedilmesi. Seçim, bayram, kriz gibi olayların fiyat değişikliği üzerindeki geciktirici etkisini ölçer. ML modeli için değerli feature.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| expected_change_date | DATE | Eşik aşımına göre beklenen fiyat değişikliği tarihi | NO | — |
| actual_change_date | DATE | Gerçekleşen fiyat değişikliği tarihi (NULL = henüz gerçekleşmedi) | YES | NULL |
| delay_days | INTEGER | Gecikme gün sayısı (actual - expected, NULL = devam ediyor) | YES | NULL |
| mbe_at_expected | NUMERIC(18,8) | Beklenen tarihte MBE değeri | NO | — |
| mbe_at_actual | NUMERIC(18,8) | Gerçekleşen tarihte MBE değeri (NULL = henüz gerçekleşmedi) | YES | NULL |
| accumulated_pressure_pct | NUMERIC(10,4) | Gecikme süresince biriken maliyet baskısı (%) | YES | NULL |
| regime_event_id | BIGINT | İlişkili rejim olayı (gecikmenin nedeni) | YES | NULL |
| price_change_id | BIGINT | İlişkili fiyat değişikliği kaydı | YES | NULL |
| attribution_notes | TEXT | Gecikmenin sebebine dair açıklama | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| idx_delay_fuel_date | (fuel_type, expected_change_date DESC) | B-Tree | Yakıt bazlı gecikme geçmişi |
| idx_delay_pending | (fuel_type) WHERE actual_change_date IS NULL | Partial B-Tree | Henüz çözülmemiş gecikmeleri listeleme |
| idx_delay_regime | (regime_event_id) | B-Tree | Rejim olayına göre gecikmeleri bulma |
| idx_delay_price | (price_change_id) | B-Tree | Fiyat değişikliğine bağlı gecikmeyi bulma |

**FK İlişkileri:**
- `political_delay_history.regime_event_id → regime_events.id`
- `political_delay_history.price_change_id → price_changes.id`

---

### TABLO 9: `risk_scores`

**Amaç:** Günlük hesaplanan bileşik risk skorunun ve alt bileşenlerinin saklanması. Katman 3'ün birincil çıktısı. ML olmadan da üretilir.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| trade_date | DATE | Hesaplama tarihi | NO | — |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| composite_score | NUMERIC(10,4) | Bileşik risk skoru [0.00 - 1.00] | NO | — |
| mbe_component | NUMERIC(10,4) | MBE bileşen skoru (normalize edilmiş) | NO | — |
| fx_volatility_component | NUMERIC(10,4) | FX volatilite bileşen skoru | NO | — |
| political_delay_component | NUMERIC(10,4) | Politik gecikme bileşen skoru | NO | — |
| threshold_breach_component | NUMERIC(10,4) | Eşik aşım bileşen skoru | NO | — |
| trend_momentum_component | NUMERIC(10,4) | Trend momentum bileşen skoru | NO | — |
| weight_vector | JSONB | Kullanılan ağırlık vektörü (örn: {"mbe":0.30, "fx":0.15, ...}) | NO | — |
| triggered_alerts | BOOLEAN | Bu skor alert tetikledi mi? | NO | FALSE |
| system_mode | VARCHAR(20) | Hesaplama modu ('full', 'safe', 'partial') — graceful degradation durumu | NO | 'full' |
| mbe_calculation_id | BIGINT | İlgili MBE hesaplama kaydı referansı | NO | — |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_risk_date_fuel | (trade_date, fuel_type) | UNIQUE | Günlük teklik |
| idx_risk_date | (trade_date DESC) | B-Tree | Tarih bazlı sorgular |
| idx_risk_high | (fuel_type, trade_date DESC) WHERE composite_score >= 0.70 | Partial B-Tree | Yüksek riskli günleri hızlı listeleme |
| idx_risk_alerts | (triggered_alerts, trade_date DESC) WHERE triggered_alerts = TRUE | Partial B-Tree | Alert tetikleyen skorları listeleme |
| idx_risk_mbe | (mbe_calculation_id) | B-Tree | FK lookup |

**FK İlişkileri:** `risk_scores.mbe_calculation_id → mbe_calculations.id`

---

### TABLO 10: `ml_predictions`

**Amaç:** ML modellerinin ürettiği tahminlerin saklanması. XGBoost zam olasılığı ve LightGBM TL tahmini. Geriye dönük model performans değerlendirmesi için kritik.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| prediction_date | DATE | Tahminin yapıldığı tarih | NO | — |
| fuel_type | fuel_type_enum | Yakıt tipi | NO | — |
| model_type | model_type_enum | Model tipi (xgboost_classifier / lightgbm_regressor) | NO | — |
| model_version | VARCHAR(50) | Model versiyonu (örn: 'v2.3.1-20260215') | NO | — |
| target_horizon_days | INTEGER | Tahmin ufku (kaç gün sonrası için tahmin) | NO | 7 |
| probability_increase | NUMERIC(10,6) | Zam olasılığı [0-1] (XGBoost çıktısı) | YES | NULL |
| predicted_change_tl | NUMERIC(18,8) | Tahmini zam büyüklüğü TL/lt (LightGBM çıktısı) | YES | NULL |
| confidence_lower | NUMERIC(18,8) | Güven aralığı alt sınırı (TL/lt) | YES | NULL |
| confidence_upper | NUMERIC(18,8) | Güven aralığı üst sınırı (TL/lt) | YES | NULL |
| confidence_level | NUMERIC(5,2) | Güven aralığı seviyesi (örn: 0.90 = %90) | YES | 0.90 |
| shap_values | JSONB | SHAP feature importance değerleri (JSON) | YES | NULL |
| top_features | JSONB | En etkili 5 feature ve katkıları (özet) | YES | NULL |
| feature_snapshot | JSONB | Tahmin anında kullanılan feature değerleri (reproducibility) | YES | NULL |
| actual_outcome | direction_enum | Gerçekleşen sonuç (backfill: tahmin doğru mu?) | YES | NULL |
| actual_change_tl | NUMERIC(18,8) | Gerçekleşen değişiklik tutarı (backfill) | YES | NULL |
| is_accurate | BOOLEAN | Tahmin doğru çıktı mı? (backfill, post-hoc) | YES | NULL |
| risk_score_id | BIGINT | İlgili risk skoru referansı | YES | NULL |
| inference_time_ms | INTEGER | Model inference süresi (milisaniye) | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_pred_date_fuel_model | (prediction_date, fuel_type, model_type) | UNIQUE | Aynı gün+yakıt+model teklik |
| idx_pred_date | (prediction_date DESC) | B-Tree | Tarih bazlı sorgular |
| idx_pred_fuel_model | (fuel_type, model_type, prediction_date DESC) | B-Tree | Model bazlı zaman serisi |
| idx_pred_accuracy | (model_type, is_accurate) WHERE is_accurate IS NOT NULL | Partial B-Tree | Model performans analizi |
| idx_pred_high_prob | (fuel_type, prediction_date DESC) WHERE probability_increase > 0.70 | Partial B-Tree | Yüksek olasılıklı tahminleri hızlı listeleme |
| idx_pred_risk | (risk_score_id) | B-Tree | FK lookup |

**FK İlişkileri:** `ml_predictions.risk_score_id → risk_scores.id`

---

### TABLO 11: `alerts`

**Amaç:** Sistem tarafından üretilen tüm alert'lerin kaydedilmesi. Eşik aşımı, risk seviyesi değişikliği, anomali tespiti gibi durumlardan tetiklenir. Hangi kanala gönderildiği ve okunup okunmadığı takip edilir.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| alert_date | TIMESTAMPTZ | Alert oluşturma zamanı | NO | NOW() |
| fuel_type | fuel_type_enum | İlgili yakıt tipi | NO | — |
| alert_level | alert_level_enum | Alert seviyesi (info/warning/critical) | NO | — |
| alert_type | VARCHAR(100) | Alert tipi (örn: 'mbe_threshold', 'risk_high', 'ml_prediction', 'data_anomaly', 'system_degradation') | NO | — |
| title | VARCHAR(500) | Alert başlığı (kısa, okunabilir) | NO | — |
| message | TEXT | Alert detay mesajı (Markdown destekli) | NO | — |
| metric_name | VARCHAR(100) | Tetikleyen metrik adı | YES | NULL |
| metric_value | NUMERIC(18,8) | Tetikleme anındaki metrik değeri | YES | NULL |
| threshold_value | NUMERIC(18,8) | Aşılan eşik değeri | YES | NULL |
| threshold_config_id | BIGINT | İlgili eşik konfigürasyonu | YES | NULL |
| risk_score_id | BIGINT | İlgili risk skoru | YES | NULL |
| channels_sent | alert_channel_enum[] | Gönderildiği kanallar (PostgreSQL array) | YES | NULL |
| is_read | BOOLEAN | Dashboard'da okundu mu? | NO | FALSE |
| is_resolved | BOOLEAN | Alert durumu çözüldü mü? (risk düştü, zam geldi vb.) | NO | FALSE |
| resolved_at | TIMESTAMPTZ | Çözülme zamanı | YES | NULL |
| resolved_reason | VARCHAR(500) | Çözülme sebebi | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| idx_alert_date | (alert_date DESC) | B-Tree | Kronolojik listeleme |
| idx_alert_unread | (fuel_type, alert_level) WHERE is_read = FALSE | Partial B-Tree | Okunmamış alert'leri hızlı listeleme |
| idx_alert_unresolved | (fuel_type, alert_level, alert_date DESC) WHERE is_resolved = FALSE | Partial B-Tree | Çözülmemiş alert'leri listeleme |
| idx_alert_type_date | (alert_type, alert_date DESC) | B-Tree | Tip bazlı analiz |
| idx_alert_threshold | (threshold_config_id) | B-Tree | FK lookup |
| idx_alert_risk | (risk_score_id) | B-Tree | FK lookup |

**FK İlişkileri:**
- `alerts.threshold_config_id → threshold_config.id`
- `alerts.risk_score_id → risk_scores.id`

---

### TABLO 12: `api_keys`

**Amaç:** B2B REST API erişimi için API key yönetimi. Müşteri bazlı rate limiting, erişim kontrolü ve kullanım takibi.

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| client_name | VARCHAR(255) | Müşteri/firma adı | NO | — |
| client_email | VARCHAR(255) | Müşteri iletişim e-postası | NO | — |
| api_key_hash | VARCHAR(128) | API key'in SHA-256 hash'i (asla plain text saklanmaz) | NO | — |
| api_key_prefix | VARCHAR(12) | API key'in ilk 8 karakteri (tanımlama için, örn: 'yk_live_8f3a') | NO | — |
| scopes | TEXT[] | Erişim kapsamları (örn: {'mbe:read', 'risk:read', 'predictions:read'}) | NO | '{"mbe:read"}' |
| rate_limit_per_minute | INTEGER | Dakika başı istek limiti | NO | 60 |
| rate_limit_per_day | INTEGER | Günlük istek limiti | NO | 10000 |
| is_active | BOOLEAN | API key aktif mi? | NO | TRUE |
| expires_at | TIMESTAMPTZ | Son kullanma tarihi (NULL = süresiz) | YES | NULL |
| last_used_at | TIMESTAMPTZ | Son kullanım zamanı | YES | NULL |
| total_requests | BIGINT | Toplam istek sayısı (counter) | NO | 0 |
| ip_whitelist | INET[] | İzin verilen IP adresleri (NULL = sınırsız) | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_api_key_hash | (api_key_hash) | UNIQUE | Hash teklik garantisi |
| idx_api_key_prefix | (api_key_prefix) | B-Tree | Prefix ile hızlı tanımlama |
| idx_api_key_active | (is_active) WHERE is_active = TRUE | Partial B-Tree | Aktif key'leri listeleme |
| idx_api_key_client | (client_name) | B-Tree | Müşteri bazlı sorgular |

**FK İlişkileri:** `alert_subscriptions.api_key_id → api_keys.id`

---

### TABLO 13: `alert_subscriptions`

**Amaç:** Telegram bot ve B2B API kullanıcılarının alert abonelik tercihlerinin yönetimi. Hangi kullanıcı hangi yakıt tipi, hangi seviye alert'leri, hangi kanaldan almak istiyor?

| Kolon Adı | PostgreSQL Tip | Açıklama | Nullable | Default |
|-----------|---------------|----------|----------|---------|
| id | BIGSERIAL | Birincil anahtar | NO | nextval |
| subscriber_type | VARCHAR(50) | Abone tipi ('telegram_user', 'telegram_group', 'api_client', 'email') | NO | — |
| subscriber_id | VARCHAR(255) | Abone tanımlayıcı (Telegram chat_id, e-posta adresi, vb.) | NO | — |
| subscriber_name | VARCHAR(255) | Abone görünen adı | YES | NULL |
| fuel_types | fuel_type_enum[] | Abone olunan yakıt tipleri (PostgreSQL array) | NO | '{benzin,motorin,lpg}' |
| alert_levels | alert_level_enum[] | Abone olunan alert seviyeleri | NO | '{warning,critical}' |
| channels | alert_channel_enum[] | Tercih edilen bildirim kanalları | NO | — |
| daily_summary | BOOLEAN | Günlük özet rapor gönderilsin mi? | NO | TRUE |
| daily_summary_time | TIME | Günlük özet gönderim saati (UTC) | NO | '07:00' |
| language | VARCHAR(5) | Tercih edilen dil (tr/en) | NO | 'tr' |
| is_active | BOOLEAN | Abonelik aktif mi? | NO | TRUE |
| api_key_id | BIGINT | İlişkili API key (B2B müşteriler için) | YES | NULL |
| mute_until | TIMESTAMPTZ | Bu tarihe kadar bildirim gönderme (geçici sessizlik) | YES | NULL |
| created_at | TIMESTAMPTZ | Kayıt oluşturma zamanı | NO | NOW() |
| updated_at | TIMESTAMPTZ | Son güncelleme zamanı | NO | NOW() |

**İndeks Stratejisi:**
| İndeks Adı | Kolonlar | Tip | Gerekçe |
|------------|---------|-----|---------|
| uq_subscription | (subscriber_type, subscriber_id) | UNIQUE | Abone teklik garantisi |
| idx_sub_active | (is_active) WHERE is_active = TRUE | Partial B-Tree | Aktif aboneleri hızlı listeleme |
| idx_sub_type | (subscriber_type, is_active) | B-Tree | Tip bazlı abone sorguları |
| idx_sub_summary | (daily_summary, daily_summary_time) WHERE daily_summary = TRUE AND is_active = TRUE | Partial B-Tree | Günlük özet gönderim kuyruğu |
| idx_sub_api_key | (api_key_id) WHERE api_key_id IS NOT NULL | Partial B-Tree | FK lookup |

**FK İlişkileri:** `alert_subscriptions.api_key_id → api_keys.id`

---

### 2.3 — ER İlişki Özet Diyagramı

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              ENTITY-RELATIONSHIP DİYAGRAMI                               │
│                                                                                          │
│                                                                                          │
│  ┌──────────────────┐         ┌──────────────────────┐         ┌──────────────────┐     │
│  │ daily_market_data │────1:1──▶│ cost_base_snapshots   │◀──1:1───│ tax_parameters   │     │
│  │ (ROOT)            │         │                       │         │ (REF)            │     │
│  └──────────────────┘         └───────────┬───────────┘         └──────────────────┘     │
│                                            │                                              │
│                                          1:1                                              │
│                                            │                                              │
│                                            ▼                                              │
│                                ┌──────────────────────┐                                  │
│                                │ mbe_calculations      │                                  │
│                                │ (CORE OUTPUT)         │                                  │
│                                └───────────┬───────────┘                                  │
│                                            │                                              │
│                                          1:1                                              │
│                                            │                                              │
│                                            ▼                                              │
│  ┌──────────────────┐         ┌──────────────────────┐                                   │
│  │ threshold_config  │────1:N──▶│ risk_scores           │                                   │
│  │ (CONFIG)          │         │ (LAYER 3 OUTPUT)      │                                   │
│  └──────────────────┘         └───────────┬───────────┘                                   │
│                                            │                                              │
│                                     ┌──────┴──────┐                                       │
│                                     │             │                                       │
│                                   1:N           1:1                                       │
│                                     │             │                                       │
│                                     ▼             ▼                                       │
│                          ┌──────────────┐  ┌──────────────────┐                           │
│                          │ alerts        │  │ ml_predictions    │                           │
│                          │               │  │ (LAYER 4 OUTPUT)  │                           │
│                          └──────┬───────┘  └──────────────────┘                           │
│                                 │                                                         │
│                               N:1                                                         │
│                                 │                                                         │
│                                 ▼                                                         │
│                    ┌────────────────────────┐                                             │
│                    │ alert_subscriptions     │──── N:1 ───▶ ┌──────────────┐              │
│                    │                         │               │ api_keys     │              │
│                    └────────────────────────┘               └──────────────┘              │
│                                                                                          │
│                                                                                          │
│  ┌──────────────────┐                      ┌──────────────────────┐                      │
│  │ regime_events     │─────────1:N─────────▶│ political_delay_     │                      │
│  │ (EVENT FLAG)      │                      │ history              │                      │
│  └──────────────────┘                      └──────────┬───────────┘                      │
│                                                        │                                  │
│  ┌──────────────────┐                                N:1                                  │
│  │ price_changes     │─────────1:N──────────────────────┘                                 │
│  │ (HISTORICAL)      │                                                                    │
│  └──────────────────┘                                                                    │
│                                                                                          │
│                                                                                          │
│  ═══════════════════════════════════════════════════════════════════════                  │
│  VERİ AKIŞ YÖNÜ (Soldan Sağa / Yukarıdan Aşağıya):                                     │
│                                                                                          │
│  daily_market_data → cost_base_snapshots → mbe_calculations → risk_scores                │
│       ↓                                                          ↓      ↘               │
│  tax_parameters                                              alerts   ml_predictions     │
│                                                                 ↓                        │
│  regime_events → political_delay_history ← price_changes  alert_subscriptions            │
│                                                                 ↓                        │
│                                                              api_keys                    │
│  ═══════════════════════════════════════════════════════════════════════                  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.4 — FK İlişki Özet Tablosu

| Kaynak Tablo | Kaynak Kolon | Hedef Tablo | Hedef Kolon | İlişki | ON DELETE |
|-------------|-------------|------------|------------|--------|----------|
| cost_base_snapshots | market_data_id | daily_market_data | id | N:1 | RESTRICT |
| cost_base_snapshots | tax_param_id | tax_parameters | id | N:1 | RESTRICT |
| mbe_calculations | snapshot_id | cost_base_snapshots | id | 1:1 | RESTRICT |
| risk_scores | mbe_calculation_id | mbe_calculations | id | 1:1 | RESTRICT |
| ml_predictions | risk_score_id | risk_scores | id | N:1 | SET NULL |
| alerts | threshold_config_id | threshold_config | id | N:1 | SET NULL |
| alerts | risk_score_id | risk_scores | id | N:1 | SET NULL |
| political_delay_history | regime_event_id | regime_events | id | N:1 | SET NULL |
| political_delay_history | price_change_id | price_changes | id | N:1 | SET NULL |
| alert_subscriptions | api_key_id | api_keys | id | N:1 | CASCADE |

**ON DELETE Stratejisi Gerekçesi:**
- `RESTRICT`: Veri zinciri bütünlüğü kritik olan ilişkilerde (hesaplama zinciri). Bağımlı veri varken silme engellenir.
- `SET NULL`: Opsiyonel referanslarda. Kaynak silinse bile alert/tahmin kaydı korunur, sadece referans NULL olur.
- `CASCADE`: Bağımlı kaydın ana kayıtsız anlamsız olduğu durumlarda (API key silinirse abonelik de silinir).

### 2.5 — Partition ve Arşivleme Stratejisi

```
┌──────────────────────────────────────────────────────────────┐
│                    PARTITION STRATEJİSİ                       │
│                                                              │
│  Partitioned Tablolar (Aylık RANGE, trade_date bazlı):       │
│  ├── daily_market_data                                       │
│  ├── cost_base_snapshots                                     │
│  ├── mbe_calculations                                        │
│  ├── risk_scores                                             │
│  └── ml_predictions                                          │
│                                                              │
│  Partition Naming: {tablo_adı}_y{YYYY}_m{MM}                │
│  Örnek: daily_market_data_y2026_m02                          │
│                                                              │
│  Arşivleme Politikası:                                       │
│  ├── Son 12 ay  → SSD (hot storage, tam indeks)             │
│  ├── 12-36 ay   → HDD (warm storage, azaltılmış indeks)     │
│  └── 36+ ay     → S3/MinIO (cold storage, sadece backup)    │
│                                                              │
│  Partition oluşturma: pg_partman extension ile otomatik      │
│  Aylık cron job: yeni ay partition'ı önceden oluştur         │
└──────────────────────────────────────────────────────────────┘
```

### 2.6 — Tahmini Veri Hacmi (3 Yıllık Projeksiyon)

| Tablo | Günlük Kayıt | Yıllık Kayıt | 3 Yıl Toplam | Tahmini Boyut |
|-------|-------------|-------------|-------------|--------------|
| daily_market_data | ~3 (3 yakıt × 1 gün) | ~780 | ~2,340 | ~5 MB |
| cost_base_snapshots | ~3 | ~780 | ~2,340 | ~8 MB |
| mbe_calculations | ~3 | ~780 | ~2,340 | ~6 MB |
| risk_scores | ~3 | ~780 | ~2,340 | ~7 MB |
| ml_predictions | ~6 (3 yakıt × 2 model) | ~1,560 | ~4,680 | ~25 MB (JSONB SHAP) |
| alerts | ~0-5 (event-driven) | ~500 | ~1,500 | ~3 MB |
| price_changes | ~0-2 (event-driven) | ~100 | ~300 | ~1 MB |
| political_delay_history | rare | ~20 | ~60 | <1 MB |
| **TOPLAM** | | | | **~56 MB** |

> **Not:** Veri hacmi küçüktür. PostgreSQL bu ölçekte sorunsuz çalışır. Partitioning, query performance'tan çok veri yönetimi (arşivleme, backup) için tercih edilmiştir.

---

## TEKNOLOJİ STACK KARARI

| Katman | Teknoloji | Alternatif | Tercih Gerekçesi |
|--------|-----------|------------|-------------------|
| Backend Framework | **FastAPI (Python)** | Django REST, Flask | Async desteği, otomatik OpenAPI docs, tip güvenliği (Pydantic) |
| Veritabanı | **PostgreSQL 16** | TimescaleDB, ClickHouse | Standart SQL, JSONB desteği, partitioning, NUMERIC precision, ekosistem olgunluğu |
| Cache | **Redis 7** | Memcached | Pub/sub (alert dispatch), sorted sets (rate limiting), ML cache |
| Task Queue | **Celery + Redis** | APScheduler, Dramatiq | Retry mekanizması, cron scheduling (beat), monitoring (Flower) |
| ML Framework | **XGBoost + LightGBM** | CatBoost, sklearn | Tabular data'da SOTA performans, SHAP native desteği, hafif deployment |
| Frontend | **Next.js (React)** | Vue, Svelte | SSR/SSG, büyük ekosistem, Vercel deployment kolaylığı |
| Monitoring | **Prometheus + Grafana** | Datadog, New Relic | Açık kaynak, maliyet-etkin, custom metric esnekliği |
| Containerization | **Docker Compose (dev) / K8s (prod)** | Fly.io, Railway | Tam kontrol, horizontal scaling, production-grade orchestration |

---

## AKSİYON MADDELERİ

| # | Aksiyon | Öncelik | Tahmini Süre | Bağımlılık |
|---|---------|---------|-------------|------------|
| 1 | PostgreSQL schema migration dosyalarını oluştur (Alembic) | P0 - Kritik | 2 gün | — |
| 2 | ENUM type'ları ve seed data scriptlerini hazırla | P0 - Kritik | 1 gün | #1 |
| 3 | Veri toplama pipeline'ını (Katman 1) geliştir — TCMB, EPDK scraper | P0 - Kritik | 5 gün | #1 |
| 4 | Deterministik çekirdek hesaplama modülünü (Katman 2) geliştir | P0 - Kritik | 4 gün | #1, #3 |
| 5 | Risk & eşik motorunu (Katman 3) geliştir | P1 - Yüksek | 3 gün | #4 |
| 6 | Alert dispatch mekanizmasını kur (Redis Pub/Sub) | P1 - Yüksek | 2 gün | #5 |
| 7 | Telegram Bot MVP'sini geliştir (/durum, /abone) | P1 - Yüksek | 3 gün | #6 |
| 8 | Admin Dashboard MVP'sini geliştir (MBE gauge, risk haritası) | P1 - Yüksek | 5 gün | #5 |
| 9 | B2B REST API'yi geliştir (JWT auth, rate limiting) | P2 - Orta | 4 gün | #5 |
| 10 | ML pipeline'ını kur — feature engineering + XGBoost + LightGBM | P2 - Orta | 7 gün | #4 |
| 11 | Circuit breaker ve graceful degradation'ı implemente et | P2 - Orta | 2 gün | #10 |
| 12 | SHAP integration ve açıklanabilirlik modülünü ekle | P3 - Düşük | 3 gün | #10 |
| 13 | End-to-end integration test suite'i yaz | P1 - Yüksek | 4 gün | #1-#8 |
| 14 | Monitoring ve alerting altyapısını kur (Prometheus + Grafana) | P2 - Orta | 2 gün | — |
| 15 | Production deployment pipeline'ı (CI/CD, Docker, K8s) | P2 - Orta | 3 gün | — |

**Toplam Tahmini Süre:** ~50 iş günü (1 geliştirici), ~25 iş günü (2 geliştirici paralel çalışma)

---

---TECRÜBE BAŞLANGIÇ---
## Türkiye Yakıt Maliyet Baskı Altyapısı - 2026-02-15

### Görev: 5 katmanlı teknik mimari diyagramı ve 13 tabloluk PostgreSQL veritabanı schema tasarımı

- [KARAR] Deterministik çekirdeği (Katman 1-3) ML'den bağımsız tasarla → ML katmanı opsiyonel hale gelir, Circuit Breaker ile graceful degradation doğal olarak sağlanır. Bu sayede MVP daha erken çıkar ve ML eklenirken mevcut sistem bozulmaz.

- [KARAR] NUMERIC(18,8) kullanımı tüm parasal/oran kolonlarında → Float kullanmak yakıt fiyatı gibi yüksek hassasiyet gereken domainlerde kümülatif yuvarlama hatalarına yol açar. 8 ondalık basamak, barrel-to-liter dönüşümlerinde bile yeterli precision sağlar.

- [KARAR] Hysteresis (çift eşik) alert sistemi → Tek eşik kullanmak, metrik eşik etrafında salındığında dakikada onlarca alert üretir (alert storm). Açma/kapama eşiği ayrımı bu problemi tamamen ortadan kaldırır.

- [KARAR] tax_parameters tablosunda temporal (valid_from/valid_to) tasarım → Türkiye'de ÖTV oranları sık değişir. Eski oranları silmek yerine zamansal kayıt tutmak, geçmişe dönük MBE hesaplamalarının doğruluğunu garanti eder.

- [PATTERN] Aylık RANGE partitioning + 3 katmanlı arşivleme (SSD/HDD/S3) → Veri hacmi küçük olsa da, partition yapısı maintenance window'suz arşivleme ve backup operasyonlarını mümkün kılar. Performans değil, operasyonel kolaylık hedeflenmiştir.

- [PATTERN] ML prediction tablosunda feature_snapshot JSONB kolonu → Model reproducibility için kritik. 6 ay sonra "bu tahmin neden böyle çıktı?" sorusuna cevap verebilmek, hem debugging hem regulatör uyum açısından değerli.

- [PATTERN] Partial index kullanımı (WHERE koşullu indeksler) → Tablonun %95'i "normal" veriyken sadece anomali/yüksek risk/okunmamış kayıtlarda sorgu yapılıyorsa, partial index hem disk tasarrufu sağlar hem de o küçük subset'te çok hızlı arama yapar.

- [UYARI] CIF Med verisi hafta sonları yayınlanmaz → Gap-fill stratejisi (Cuma değerini Pazartesi'ye kadar taşıma + data_quality_flag='interpolated') mutlaka implemente edilmeli. Aksi halde hafta sonu MBE hesaplanamaz ve downstream tüm katmanlar durur.

- [UYARI] Türkiye'de ÖTV hem oran (%) hem sabit tutar (TL/lt) olabilir → Schema'da hem otv_rate hem otv_fixed_tl kolonu var. Hesaplama motorunda hangi kolonun dolu olduğuna göre branching logic gerekir. Bu edge case'i atlamak tüm MBE hesaplamalarını yanlış yapar.

- [UYARI] API key'i plain text saklamak güvenlik açığıdır → Schema'da api_key_hash (SHA-256) saklanır, prefix ile tanımlama yapılır. Key üretildiğinde kullanıcıya bir kez gösterilir, sonra hash'lenir. Asla geri dönüştürülemez. Bu pattern JWT secret yönetimi ile aynı mantıktır.
---TECRÜBE BİTİŞ---
