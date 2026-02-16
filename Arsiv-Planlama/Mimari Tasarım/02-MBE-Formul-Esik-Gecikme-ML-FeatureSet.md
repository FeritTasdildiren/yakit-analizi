

Tamam, bu kapsamlı bir görev. Dört büyük çıktı üretmem gerekiyor. Önce projenin yapısını anlamak ve ardından her çıktıyı detaylı şekilde hazırlamak için çalışmaya başlıyorum.

# 🇹🇷 Türkiye Yakıt Maliyet Baskı Altyapısı — Blueprint v1

## Kapsamlı Teknik Dokümantasyon

---

# ÇIKTI 1 — MBE (Maliyet Birikim Endeksi) MATEMATİKSEL FORMÜL TASLAĞI

## 1.1 Değişken Tanımları

| Sembol | Tanım | Birim | Kaynak |
|--------|--------|-------|--------|
| `CIF_t` | t günündeki CIF fiyatı (Platts Med) | USD/ton | Argus/Platts |
| `FX_t` | t günündeki USD/TRY kuru | TRY/USD | TCMB |
| `OTV_t` | t günündeki ÖTV tutarı | TRY/L | GİB |
| `KDV` | KDV oranı (sabit %18) | oran | Sabit |
| `M_dist` | Dağıtıcı marjı (tahmini) | TRY/L | Tahmin |
| `M_dealer` | Bayi marjı (tahmini) | TRY/L | Tahmin |
| `P_t` | t günündeki pompa fiyatı | TRY/L | EPDK |
| `t_last` | Son zam tarihi | tarih | Hesaplanan |
| `ρ` | Ton→Litre dönüşüm katsayısı | L/ton | Sabit (~1180 benzin, ~1190 motorin) |

## 1.2 Temel Fiyat Denklemi (Türkiye Modeli)

Türkiye'de pompa fiyatı şu şekilde oluşur:

```
Pompa Fiyatı = Net Maliyet + ÖTV + (Net Maliyet + ÖTV) × KDV + M_dist + M_dealer
```

Burada **Net Maliyet**:

```
NetCost_t = (CIF_t × FX_t) / ρ
```

> **ρ (rho)** ton-litre dönüşüm katsayısı: Benzin ≈ 1180 L/ton, Motorin ≈ 1190 L/ton

## 1.3 Reverse-Engineer: Pompa Fiyatından Net Maliyet Bazı Çıkarma

Pompa fiyatından geriye doğru çözerek tutarlı bir net maliyet bazı elde ediyoruz:

```
P_t = (NetCost_t + OTV_t) × (1 + KDV) + M_dist + M_dealer

⟹ NetCost_t^(obs) = P_t / (1 + KDV) - OTV_t / (1 + KDV) - (M_dist + M_dealer) / (1 + KDV)
```

Sadeleştirilmiş:

```
NetCost_t^(obs) = [P_t - M_dist - M_dealer] / (1 + KDV) - OTV_t
```

> **Kritik Not:** `M_dist + M_dealer` kesin bilinmez. Tahmini sabit değer kullanılır (örn. toplam 1.00–1.50 TRY/L). Tutarlılık ≫ kesinlik. Biz buna `M_total` diyelim.

## 1.4 İki Kaynaklı Net Maliyet: Forward vs Observed

Sistemde iki paralel net maliyet hesabı yürür:

| Kaynak | Formül | Kullanım |
|--------|--------|----------|
| **Forward (CIF×Kur bazlı)** | `NC_t^(fwd) = (CIF_t × FX_t) / ρ` | Piyasa baskısını ölçmek |
| **Observed (Pompa bazlı)** | `NC_t^(obs) = [P_t - M_total] / (1 + KDV) - OTV_t` | Son zamın maliyet seviyesini sabitlemek |

## 1.5 MBE Ana Formülü

### Adım 1: Son Zam Anındaki Maliyet Bazını Sabitle

```
NC_base = NC_{t_last}^(obs)
```

Bu, son zam günündeki pompa fiyatından reverse-engineer edilen net maliyettir.

### Adım 2: Günlük Ham Net Maliyeti Hesapla

```
NC_t^(fwd) = (CIF_t × FX_t) / ρ
```

### Adım 3: 5 Günlük Hareketli Ortalama (Gürültü Filtresi)

```
NC_t^(sma5) = (1/5) × Σ_{i=0}^{4} NC_{t-i}^(fwd)
```

> **Neden 5 gün?** CIF günlük dalgalanması yüksek, haftalık ortalama baskıyı daha iyi temsil eder. Ayrıca dağıtıcılar genellikle haftalık ortalama ile çalışır.

### Adım 4: MBE Hesaplama

```
MBE_t = NC_t^(sma5) - NC_base
```

**Birim:** TRY/Litre

**Yorumlama:**
- `MBE_t > 0` → Maliyet baskısı birikiyor (zam yönünde)
- `MBE_t < 0` → Maliyet düşüşü (indirim yönünde)
- `MBE_t ≈ 0` → Fiyatlandırılmış seviyede denge

### Adım 5: MBE Yüzdesel Formu (Karşılaştırma İçin)

```
MBE_t^(%) = MBE_t / NC_base × 100
```

## 1.6 Rejim Bazlı Parametre Ayrımı

Türkiye'de fiyatlama davranışı siyasi rejime göre değişir:

| Rejim ID | Tanım | SMA Penceresi | Marj Tahmini (M_total) | Açıklama |
|----------|--------|---------------|------------------------|----------|
| 0 | Normal Dönem | 5 gün | 1.20 TRY/L | Standart operasyon |
| 1 | Seçim Dönemi | 7 gün | 1.00 TRY/L | Siyasi baskı, yavaş tepki |
| 2 | Kur Şoku | 3 gün | 1.50 TRY/L | Hızlı maliyet geçişi |
| 3 | Vergi Ayarlama | 5 gün | 1.20 TRY/L | ÖTV/KDV değişimi dönemi |

Rejim bağımlı MBE:

```
MBE_t^(r) = NC_t^(sma_w(r)) - NC_base^(r)

burada:
  w(r) = rejim r'nin SMA pencere genişliği
  NC_base^(r) = rejim r'nin M_total değeriyle hesaplanan baz
```

## 1.7 Benzin vs Motorin: Ayrı Hesaplama

**Karar: AYRI hesaplanacak.** Gerekçeler:

| Faktör | Benzin | Motorin |
|--------|--------|---------|
| CIF referansı | Platts Med Prem Unl 10ppm | Platts Med ULSD 10ppm |
| ÖTV | Farklı (genelde benzin > motorin) |  |
| ρ (dönüşüm) | ~1180 L/ton | ~1190 L/ton |
| Zam zamanlaması | Genelde eşzamanlı ama bazen farklı |  |
| Politik hassasiyet | Motorin daha hassas (nakliye) |  |

Her ürün için ayrı MBE serisi:

```
MBE_t^(benzin) = NC_t^(sma5, benzin) - NC_base^(benzin)
MBE_t^(motorin) = NC_t^(sma5, motorin) - NC_base^(motorin)
```

## 1.8 Sentetik Veri ile Adım Adım Örnek Hesaplama

### Senaryo: Son zam 1 Ocak'ta yapıldı. 2-8 Ocak arası MBE hesaplıyoruz.

**Ürün:** Motorin, **Rejim:** Normal (0), **ρ = 1190 L/ton**, **M_total = 1.20 TRY/L**, **KDV = 0.18**, **ÖTV = 2.50 TRY/L**

**Veri Tablosu:**

| Gün | Tarih | CIF (USD/t) | FX (TRY/USD) | Pompa (TRY/L) |
|-----|-------|-------------|---------------|----------------|
| t_last | 1 Oca | 680 | 34.20 | 40.50 |
| t+1 | 2 Oca | 685 | 34.30 | 40.50 |
| t+2 | 3 Oca | 690 | 34.35 | 40.50 |
| t+3 | 4 Oca | 688 | 34.50 | 40.50 |
| t+4 | 5 Oca | 695 | 34.60 | 40.50 |
| t+5 | 6 Oca | 700 | 34.70 | 40.50 |
| t+6 | 7 Oca | 705 | 34.80 | 40.50 |
| t+7 | 8 Oca | 710 | 34.90 | 40.50 |

### Adım 1: NC_base hesapla (1 Ocak, pompa fiyatından reverse-engineer)

```
NC_base = [P_{t_last} - M_total] / (1 + KDV) - OTV
NC_base = [40.50 - 1.20] / 1.18 - 2.50
NC_base = 39.30 / 1.18 - 2.50
NC_base = 33.305 - 2.50
NC_base = 30.805 TRY/L
```

### Adım 2: Her gün için NC_forward hesapla

```
NC_t^(fwd) = (CIF_t × FX_t) / ρ

1 Oca: (680 × 34.20) / 1190 = 23,256 / 1190 = 19.543
2 Oca: (685 × 34.30) / 1190 = 23,495.5 / 1190 = 19.744
3 Oca: (690 × 34.35) / 1190 = 23,701.5 / 1190 = 19.917
4 Oca: (688 × 34.50) / 1190 = 23,736 / 1190 = 19.946
5 Oca: (695 × 34.60) / 1190 = 24,047 / 1190 = 20.208
6 Oca: (700 × 34.70) / 1190 = 24,290 / 1190 = 20.412
7 Oca: (705 × 34.80) / 1190 = 24,534 / 1190 = 20.617
8 Oca: (710 × 34.90) / 1190 = 24,779 / 1190 = 20.823
```

### Adım 3: SMA(5) hesapla (5. günden itibaren mümkün)

```
SMA5(5 Oca) = (19.543 + 19.744 + 19.917 + 19.946 + 20.208) / 5 = 19.872
SMA5(6 Oca) = (19.744 + 19.917 + 19.946 + 20.208 + 20.412) / 5 = 20.045
SMA5(7 Oca) = (19.917 + 19.946 + 20.208 + 20.412 + 20.617) / 5 = 20.220
SMA5(8 Oca) = (19.946 + 20.208 + 20.412 + 20.617 + 20.823) / 5 = 20.401
```

> **İlk 4 gün için:** Yeterli veri yok → geriye doğru padding veya NC_forward doğrudan kullanılabilir. Önerilen: `t_last` günü dahil edilerek SMA hesaplanır.

### Adım 4: MBE hesapla

**BURADA KRİTİK BİR GÖZLEM:**

NC_base (pompa'dan reverse-engineer) = **30.805 TRY/L** iken NC_forward (CIF×Kur) = **~19.5 TRY/L**. Bu fark normaldir çünkü NC_forward sadece ham CIF×Kur/ρ'dir, vergi öncesi rafineri maliyeti. NC_base ise pompa fiyatı içindeki "vergisiz + marjsız" kısmın tamamıdır (rafineri maliyeti + iç nakliye + diğer).

**Bu yüzden MBE'de iki yaklaşım var:**

#### Yaklaşım A — Delta Bazlı (ÖNERİLEN)

MBE sadece **değişimi** ölçer, mutlak seviye farkını değil:

```
MBE_t = NC_t^(sma5) - NC_{t_last}^(fwd_sma5)

Burada NC_{t_last}^(fwd_sma5) = son zam tarihindeki forward SMA5 değeri
```

Bu durumda her iki taraf da aynı metodoloji (CIF×Kur/ρ) ile hesaplanır ve fark anlamlı olur.

```
NC_{t_last}^(fwd_sma5) ≈ 19.543 (son zam günündeki forward değer, veya
                          önceki 5 günün ortalaması)

MBE(5 Oca) = 19.872 - 19.543 = +0.329 TRY/L
MBE(6 Oca) = 20.045 - 19.543 = +0.502 TRY/L
MBE(7 Oca) = 20.220 - 19.543 = +0.677 TRY/L
MBE(8 Oca) = 20.401 - 19.543 = +0.858 TRY/L
```

#### Yaklaşım B — Pompa Bazlı Baskı Yüzdesi

```
MBE_%_t = (NC_t^(sma5) - NC_{t_last}^(fwd)) / NC_{t_last}^(fwd) × 100

MBE_%(8 Oca) = (20.401 - 19.543) / 19.543 × 100 = +4.39%
```

### Nihai MBE Formülü (Yaklaşım A — Referans)

```
┌─────────────────────────────────────────────────────────┐
│                                                          │
│   MBE_t = SMA_w(r) [ (CIF_i × FX_i) / ρ ]             │
│                     i ∈ {t-w+1, ..., t}                  │
│                                                          │
│         − SMA_w(r) [ (CIF_j × FX_j) / ρ ]              │
│                     j ∈ {t_last-w+1, ..., t_last}        │
│                                                          │
│   Birim: TRY/Litre                                       │
│   w(r): Rejim bağımlı SMA pencere genişliği             │
│   ρ: Ürüne özgü ton-litre dönüşüm katsayısı            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### MBE Değişim Hızı (Türev Feature)

```
ΔMBE_t = MBE_t - MBE_{t-1}       (günlük değişim)
ΔMBE_t^(3) = MBE_t - MBE_{t-3}   (3 günlük momentum)
```

### Pseudocode

```python
def calculate_mbe(
    cif_series: pd.Series,      # Günlük CIF fiyatları (USD/ton)
    fx_series: pd.Series,       # Günlük USD/TRY kuru
    rho: float,                 # Ton-litre dönüşüm katsayısı
    last_hike_date: pd.Timestamp,
    regime: int = 0,
    pump_price_at_hike: float = None,  # Opsiyonel: pompa bazlı kontrol
    m_total: float = 1.20,
    kdv: float = 0.18,
    otv: float = None
) -> pd.DataFrame:
    """
    MBE (Maliyet Birikim Endeksi) hesaplayıcı.
    
    Returns: DataFrame with columns [date, nc_forward, sma, mbe, mbe_pct, delta_mbe]
    """
    # Rejim bazlı SMA penceresi
    WINDOW_MAP = {0: 5, 1: 7, 2: 3, 3: 5}
    w = WINDOW_MAP.get(regime, 5)
    
    # Adım 1: Forward net maliyet serisi
    nc_forward = (cif_series * fx_series) / rho
    
    # Adım 2: SMA hesapla
    nc_sma = nc_forward.rolling(window=w, min_periods=1).mean()
    
    # Adım 3: Baz değer (son zam tarihindeki SMA)
    # Son zam tarihinden geriye w gün alarak SMA hesapla
    hike_idx = nc_forward.index.get_loc(last_hike_date)
    if hike_idx >= w - 1:
        nc_base = nc_forward.iloc[hike_idx - w + 1 : hike_idx + 1].mean()
    else:
        nc_base = nc_forward.iloc[:hike_idx + 1].mean()
    
    # Adım 4: MBE hesapla
    mbe = nc_sma - nc_base
    
    # Adım 5: Yüzdesel MBE
    mbe_pct = (mbe / nc_base) * 100
    
    # Adım 6: MBE değişim hızı
    delta_mbe = mbe.diff(1)
    
    # Sadece son zamdan sonraki günleri döndür
    result = pd.DataFrame({
        'date': nc_forward.index,
        'nc_forward': nc_forward,
        'nc_sma': nc_sma,
        'mbe': mbe,
        'mbe_pct': mbe_pct,
        'delta_mbe': delta_mbe
    })
    
    return result[result['date'] > last_hike_date]


def reverse_engineer_nc_base(
    pump_price: float,
    otv: float,
    kdv: float = 0.18,
    m_total: float = 1.20
) -> float:
    """
    Pompa fiyatından net maliyet bazını çıkar.
    Tutarlılık > Kesinlik
    """
    return (pump_price - m_total) / (1 + kdv) - otv
```

---

# ÇIKTI 2 — EŞİK HESAPLAMA METODOLOJİSİ

## 2.1 Temel Felsefe

Eşik sabit bir değer değil, **veriden öğrenilen, rejime bağlı, periyodik olarak güncellenen** bir parametredir.

**Temel soru:** "Geçmişte zamlar genellikle MBE hangi seviyeye ulaştığında gerçekleşti?"

## 2.2 Eşik Belirleme İstatistiksel Yöntemi

### Adım 1: Tarihsel Veri Toplama

Her geçmiş zam olayı `k` için:

```
Zam_k = {
    tarih: zam tarihi,
    mbe_at_hike: zam anındaki MBE değeri,
    regime: o dönemdeki rejim,
    direction: zam / indirim,
    magnitude: TRY/L değişim
}
```

### Adım 2: Zam Öncesi MBE Dağılımı

```
D_hike = {MBE_{t_k} : k ∈ tüm geçmiş zam olayları, yön = "zam"}
D_cut  = {MBE_{t_k} : k ∈ tüm geçmiş zam olayları, yön = "indirim"}
```

### Adım 3: Percentil Bazlı Eşik

```
θ_zam = Percentile(D_hike, p)     p ∈ [0.25, 0.35]  — alt çeyreklik
θ_indirim = Percentile(D_cut, q)   q ∈ [0.25, 0.35]  — (negatif tarafta)
```

> **Neden %25-35 percentil?** Eşik = "bu seviyeye geldiğinde %65-75 ihtimalle zam gelir" anlamına gelir. %70-80 yoğunlaşma aralığı bu mantıkla uyumlu: zamların %70-80'i bu eşiğin üzerinde gerçekleşmiş.

### Alternatif: Kernel Density Estimation (KDE)

```
f̂(x) = (1/nh) × Σ_{k=1}^{n} K((x - MBE_k) / h)

K = Gaussian kernel
h = bandwidth (Silverman's rule)
```

KDE ile en yoğun bölge (mode) ve %70-80 yoğunlaşma aralığı:

```
θ_lower, θ_upper = en küçük [a,b] aralığı öyle ki:
    ∫_a^b f̂(x) dx ≥ 0.75
```

## 2.3 Rejim Bazlı Eşikler

| Rejim | Eşik Hesaplama Seti | Beklenti |
|-------|---------------------|----------|
| Normal (0) | Sadece normal dönem zamları | Orta eşik (~0.60-0.80 TRY/L) |
| Seçim (1) | Seçim dönemi zamları | Yüksek eşik (~1.00-1.50 TRY/L) |
| Kur Şoku (2) | Kur şoku dönemi zamları | Düşük eşik (~0.30-0.50 TRY/L) |
| Vergi Ayarlama (3) | Vergi değişimi zamları | Özel hesaplama |

```
θ_zam^(r) = Percentile(D_hike^(r), p_r)

burada:
  D_hike^(r) = rejim r'deki zamların MBE dağılımı
  p_r = rejim bazlı percentil (rejim 1 için daha yüksek p)
```

**Rejim bazlı percentil kalibrasyonu:**

```
p_r = {
    0: 0.30,   # Normal: zamların %70'i bu eşiğin üstünde
    1: 0.20,   # Seçim: daha az veri, daha muhafazakar
    2: 0.35,   # Kur şoku: hızlı tepki, daha sıkı eşik
    3: 0.30    # Vergi: normal gibi
}
```

## 2.4 ±0.25 TRY/L Sabit Sınıfı Tanımı

```
Sınıf(MBE_t) = {
    "ZAM_BASKISI"      eğer MBE_t > +0.25
    "SABİT"            eğer -0.25 ≤ MBE_t ≤ +0.25
    "İNDİRİM_BASKISI"  eğer MBE_t < -0.25
}
```

> **0.25 TRY/L mantığı:** Bu eşik altındaki maliyet değişimlerini dağıtıcılar marjdan absorbe edebilir. Pompa fiyatı değişmez. Bu "gürültü filtresi" görevi görür.

## 2.5 Eşik Güncelleme (Kalibrasyon) Prosedürü

```
Kalibrasyon Tetikleyicileri:
┌────────────────────────────────────────────────┐
│ 1. Periyodik: Her 6 ayda bir (Ocak, Temmuz)   │
│ 2. Olay bazlı: Rejim değişimi gerçekleştiğinde │  
│ 3. Performans: Son 10 zamın >30%'u eşik altında│
│    gerçekleştiyse (eşik çok yüksek)            │
│ 4. Manuel: Analist tetiklemesi                  │
└────────────────────────────────────────────────┘
```

```
Kalibrasyon Adımları:
1. Son 18 aydaki tüm zam olaylarını topla
2. Rejim bazlı filtrele
3. Percentil hesapla
4. Yeni eşik = α × θ_yeni + (1-α) × θ_eski    (α = 0.7, smooth geçiş)
5. Validasyonu çalıştır
6. Onay sonrası canlıya al
```

## 2.6 Eşik Validasyon Yöntemi

### Metrik 1: Capture Rate (Yakalama Oranı)

```
CaptureRate(θ) = |{k : MBE_{t_k} ≥ θ, yön_k = "zam"}| / |{k : yön_k = "zam"}|

Hedef: CaptureRate ≥ 0.70 (eşik, zamların en az %70'ini yakalamalı)
```

### Metrik 2: False Alarm Oranı

```
FalseAlarmRate(θ) = |{t : MBE_t ≥ θ, sonraki 7 günde zam yok}| / |{t : MBE_t ≥ θ}|

Hedef: FalseAlarmRate ≤ 0.40
```

### Metrik 3: Ortalama Erken Uyarı Süresi

```
EarlyWarning(θ) = mean({t_k - t_cross_k : k ∈ zamlar})

burada t_cross_k = MBE'nin θ'yı ilk aştığı gün (zam k öncesinde)

Hedef: 1 ≤ EarlyWarning ≤ 7 gün
```

### Validasyon Pseudocode

```python
def validate_threshold(
    threshold: float,
    hike_events: List[HikeEvent],
    mbe_series: pd.Series,
    regime: int
) -> dict:
    """
    Eşik validasyonu — Capture Rate, False Alarm, Early Warning
    """
    # Rejim filtrele
    events = [e for e in hike_events if e.regime == regime and e.direction == 'zam']
    
    # Capture Rate
    captured = sum(1 for e in events if mbe_series[e.date] >= threshold)
    capture_rate = captured / len(events) if events else 0
    
    # False Alarm Rate
    threshold_crossings = mbe_series[mbe_series >= threshold].index
    false_alarms = 0
    total_crossings = 0
    
    for cross_date in threshold_crossings:
        total_crossings += 1
        # Sonraki 7 günde zam var mı?
        window_end = cross_date + pd.Timedelta(days=7)
        hike_in_window = any(
            cross_date <= e.date <= window_end for e in events
        )
        if not hike_in_window:
            false_alarms += 1
    
    false_alarm_rate = false_alarms / total_crossings if total_crossings else 0
    
    # Early Warning
    early_warnings = []
    for e in events:
        # MBE'nin eşiği ilk aştığı günü bul (zamdan geriye doğru)
        pre_hike = mbe_series[:e.date]
        crossings = pre_hike[pre_hike >= threshold]
        if len(crossings) > 0:
            first_cross = crossings.index[0]
            early_warnings.append((e.date - first_cross).days)
    
    avg_early_warning = np.mean(early_warnings) if early_warnings else None
    
    return {
        'threshold': threshold,
        'regime': regime,
        'capture_rate': capture_rate,           # Hedef ≥ 0.70
        'false_alarm_rate': false_alarm_rate,   # Hedef ≤ 0.40
        'avg_early_warning_days': avg_early_warning,  # Hedef 1-7
        'n_events': len(events),
        'VALID': capture_rate >= 0.70 and false_alarm_rate <= 0.40
    }
```

## 2.7 Sentetik Örnekle Eşik Belirleme

### Senaryo: 20 tarihsel zam olayı, normal rejim

```
Geçmiş zamların MBE değerleri (TRY/L):
D_hike = [0.42, 0.55, 0.61, 0.65, 0.68, 0.70, 0.72, 0.75, 0.78, 0.80,
          0.82, 0.85, 0.88, 0.90, 0.95, 1.02, 1.10, 1.25, 1.40, 1.80]

Sıralı (zaten sıralı). n = 20
```

**Percentil hesaplama (p=0.30):**

```
Pozisyon = p × (n + 1) = 0.30 × 21 = 6.3
θ_zam = D_hike[6] + 0.3 × (D_hike[7] - D_hike[6])
θ_zam = 0.70 + 0.3 × (0.72 - 0.70)
θ_zam = 0.70 + 0.006 = 0.706 TRY/L
```

**Yuvarlama:** θ_zam ≈ **0.70 TRY/L**

**Validasyon:**
```
Capture Rate = |{MBE ≥ 0.70}| / 20 = 15/20 = 0.75 ✓ (≥ 0.70)
```

**KDE yaklaşımı (aynı veri):**

```
KDE peak (mode) ≈ 0.78 TRY/L
%75 yoğunlaşma aralığı: [0.62, 1.12] TRY/L
Alt sınır = 0.62 → Eşik adayı

Sonuç: Percentil ve KDE benzer sonuç veriyor. θ ∈ [0.65, 0.75] makul.
```

### Eşik Seçim Grid Search

```python
def find_optimal_threshold(
    mbe_at_hikes: np.array,
    mbe_series: pd.Series,
    hike_events: list,
    regime: int,
    theta_range: tuple = (0.30, 1.50),
    step: float = 0.05
) -> float:
    """
    Grid search ile optimal eşik bul.
    Kriter: Capture Rate ≥ 0.70'i sağlayan en düşük False Alarm Rate
    """
    best_theta = None
    best_score = -1
    
    for theta in np.arange(theta_range[0], theta_range[1], step):
        result = validate_threshold(theta, hike_events, mbe_series, regime)
        
        if result['capture_rate'] >= 0.70:
            # Score: yüksek capture, düşük false alarm
            score = result['capture_rate'] - 0.5 * result['false_alarm_rate']
            if score > best_score:
                best_score = score
                best_theta = theta
    
    return best_theta
```

---

# ÇIKTI 3 — POLİTİK GECİKME METRİĞİ İMPLEMENTASYON PLANI

## 3.1 Konsept Tanımı

**Politik Gecikme (PG):** Maliyet baskısının (MBE) eşiği aştığı gün ile fiili zam arasındaki gün sayısı.

```
PG_k = t_hike_k - t_cross_k

burada:
  t_cross_k = zam k öncesinde MBE'nin θ'yı ilk aştığı gün
  t_hike_k  = fiili zam tarihi
```

**Türkiye kontekstinde anlam:** PG > tarihsel ortalama → siyasi baskı/erteleme muhtemel.

## 3.2 Geriye Dönük Hesaplama Yöntemi (Backfill)

### Adım 1: Tarihsel Zam Listesi Oluşturma

```
hike_events = [
    {date: "2024-03-15", product: "motorin", direction: "zam", 
     magnitude: +1.50, regime: 0},
    {date: "2024-04-02", product: "motorin", direction: "zam", 
     magnitude: +0.80, regime: 1},
    ...
]
```

### Adım 2: Her Zam İçin MBE Serisini Geriye Doğru Hesapla

```python
def backfill_political_delay(
    hike_events: List[dict],
    cif_series: pd.Series,
    fx_series: pd.Series,
    pump_series: pd.Series,
    product: str,
    rho: float,
    thresholds: Dict[int, float]  # rejim -> eşik
) -> List[dict]:
    """
    Tüm geçmiş zamlar için politik gecikmeyi geriye dönük hesapla.
    """
    results = []
    
    # Zamları kronolojik sırala
    events = sorted(
        [e for e in hike_events if e['product'] == product],
        key=lambda x: x['date']
    )
    
    for i, event in enumerate(events):
        # Bu zamın "önceki zamı" bul → MBE baz tarihini belirle
        if i == 0:
            # İlk zam: bilinen en eski tarihi baz al
            base_date = cif_series.index[0]
        else:
            base_date = events[i-1]['date']
        
        # MBE serisini hesapla (base_date → event.date arası)
        mbe = calculate_mbe(
            cif_series=cif_series[base_date:event['date']],
            fx_series=fx_series[base_date:event['date']],
            rho=rho,
            last_hike_date=base_date,
            regime=event['regime']
        )
        
        # Eşiği al
        theta = thresholds[event['regime']]
        
        # Eşiğin ilk aşıldığı günü bul
        crossings = mbe[mbe['mbe'] >= theta]
        
        if len(crossings) > 0:
            first_cross_date = crossings.iloc[0]['date']
            delay_days = (event['date'] - first_cross_date).days
        else:
            first_cross_date = None
            delay_days = None  # Eşik hiç aşılmadı (edge case)
        
        results.append({
            'hike_date': event['date'],
            'product': product,
            'regime': event['regime'],
            'magnitude': event['magnitude'],
            'mbe_at_hike': mbe.iloc[-1]['mbe'] if len(mbe) > 0 else None,
            'threshold': theta,
            'first_cross_date': first_cross_date,
            'political_delay_days': delay_days,
            'mbe_max_before_hike': mbe['mbe'].max() if len(mbe) > 0 else None
        })
    
    return results
```

## 3.3 Politik Gecikme Metrikleri

### Temel Metrikler

```
# Tüm zamlar için
PG_mean = mean({PG_k : k ∈ zamlar, PG_k ≠ None})
PG_std  = std({PG_k : k ∈ zamlar, PG_k ≠ None})
PG_median = median({PG_k : k ∈ zamlar, PG_k ≠ None})

# Rejim bazlı
PG_mean^(r) = mean({PG_k : k ∈ zamlar, rejim_k = r})
PG_std^(r)  = std({PG_k : k ∈ zamlar, rejim_k = r})
```

### Anomali Skoru (Canlı Sistem)

```
PG_zscore_t = (PG_current_t - PG_mean^(r)) / PG_std^(r)

burada PG_current_t = bugünden itibaren eşiğin aşıldığı günden beri geçen gün

Yorumlama:
  z < 1.0  → Normal gecikme aralığında
  1.0 ≤ z < 2.0 → Dikkat, ortalamanın üstünde gecikme
  z ≥ 2.0 → Anormal gecikme, politik müdahale olası
```

## 3.4 Canlı Sistem: Gecikme Takip Mekanizması

### State Machine

```
┌─────────────┐     MBE ≥ θ      ┌──────────────┐     Zam geldi     ┌───────────┐
│  BEKLEME    │ ──────────────→   │  EŞİK_AŞILDI │ ──────────────→   │ KAPANDI   │
│  (IDLE)     │                   │  (WATCHING)   │                   │ (CLOSED)  │
└─────────────┘                   └──────────────┘                   └───────────┘
       ↑                                │                                  │
       │         MBE < θ (sürekli       │                                  │
       │          5 gün boyunca)        │                                  │
       └────────────────────────────────┘                                  │
       ↑                                                                   │
       └───────────────────────────────────────────────────────────────────┘
                              Yeni dönem başladı
```

### Canlı Tracking Veri Yapısı

```python
@dataclass
class DelayTracker:
    product: str                    # "benzin" | "motorin"
    state: str                      # "IDLE" | "WATCHING" | "CLOSED"
    threshold_cross_date: Optional[date]  # Eşiğin ilk aşıldığı tarih
    current_delay_days: int         # Bugüne kadar geçen gün
    mbe_at_cross: float            # Eşik aşılma anındaki MBE
    mbe_current: float             # Bugünkü MBE
    mbe_max: float                 # Dönem içi maksimum MBE
    regime: int                    # Aktif rejim
    historical_avg_delay: float    # Bu rejimin tarihsel ort. gecikmesi
    historical_std_delay: float    # Bu rejimin tarihsel std. gecikmesi
    z_score: float                 # Anomali skoru
    
    # Eşik altına düşme takibi
    below_threshold_streak: int    # Kaç gündür eşik altında
    BELOW_THRESHOLD_RESET: int = 5 # Bu kadar gün altında kalırsa reset
```

## 3.5 Dashboard Gösterim Formatı

```
┌─────────────────────────────────────────────────────────────────┐
│  🔴 MOTORİN — Maliyet Baskısı Aktif                            │
│                                                                  │
│  MBE: +0.92 TRY/L  │  Eşik: 0.70 TRY/L  │  Aşım: +0.22 TRY/L│
│                                                                  │
│  ⏱️ Eşik aşıldı: 8 gün  │  Tarihsel ort: 4.2 gün (±1.8)      │
│                                                                  │
│  ⚠️ Z-Score: 2.11 — Anormal gecikme, politik erteleme olası     │
│                                                                  │
│  ████████████████████░░░░░  Gecikme: ████████ (8/4.2 gün)       │
│  [================>----]     Baskı yoğunluğu: %131               │
│                                                                  │
│  Rejim: Normal (0)  │  Son zam: 15 Oca 2026  │  Bu dönem max    │
│                        MBE: +1.05 TRY/L (3 gün önce)            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  🟢 BENZİN — Denge                                              │
│                                                                  │
│  MBE: +0.18 TRY/L  │  Eşik: 0.75 TRY/L  │  Aşım: yok         │
│                                                                  │
│  Durum: SABİT (|MBE| < 0.25)                                    │
│  Son zam: 20 Oca 2026  │  Rejim: Normal (0)                     │
└─────────────────────────────────────────────────────────────────┘
```

## 3.6 Edge Case'ler

### Edge Case 1: Eşik Aşıldı Ama Zam Gelmeden Eşik Altına Düştü

```
Kural: Eşik altına düşüp 5 gün boyunca altında kalırsa → "Absorbe Edildi" olarak kapat

Zaman çizelgesi:
  Gün 1: MBE = 0.75 > θ(0.70) → WATCHING başlat
  Gün 5: MBE = 0.82
  Gün 8: MBE = 0.65 < θ → below_streak = 1
  Gün 9: MBE = 0.68 < θ → below_streak = 2
  Gün 10: MBE = 0.71 > θ → below_streak = 0 (reset)
  Gün 12: MBE = 0.60 < θ → below_streak = 1
  ...
  Gün 16: MBE = 0.55 < θ → below_streak = 5 → ABSORBE_EDİLDİ → IDLE

Kayıt:
  {type: "ABSORBED", cross_date: gün_1, absorb_date: gün_16, 
   max_mbe: 0.82, delay_at_absorb: 16}
```

```python
def handle_below_threshold(tracker: DelayTracker, mbe_today: float, 
                           threshold: float) -> DelayTracker:
    if tracker.state != "WATCHING":
        return tracker
    
    if mbe_today < threshold:
        tracker.below_threshold_streak += 1
        if tracker.below_threshold_streak >= tracker.BELOW_THRESHOLD_RESET:
            # Absorbe edildi — log & reset
            log_absorbed_event(tracker)
            tracker.state = "IDLE"
            tracker.threshold_cross_date = None
            tracker.current_delay_days = 0
            tracker.below_threshold_streak = 0
    else:
        tracker.below_threshold_streak = 0  # Streak kırıldı
    
    return tracker
```

### Edge Case 2: Birden Fazla Eşik Aşılması (Arada Düşüp Tekrar Çıkma)

```
Zaman çizelgesi:
  Gün 1-7:   MBE > θ (ilk aşım)
  Gün 8-10:  MBE < θ (3 gün, < 5 gün reset)
  Gün 11-15: MBE > θ (tekrar aşım)
  Gün 16:    ZAM!

Kural: below_streak < RESET_THRESHOLD → aynı watching döneminin devamı
       İlk cross_date korunur (Gün 1)
       Politik gecikme = 16 - 1 = 15 gün

Kayıt:
  {cross_date: gün_1, hike_date: gün_16, delay: 15,
   dip_events: [{start: gün_8, end: gün_10, min_mbe: ...}]}
```

### Edge Case 3: Kademeli Zam

```
Zaman çizelgesi:
  Gün 1: MBE > θ → WATCHING başlat
  Gün 5: Kısmi zam (+0.50 TRY/L, ama MBE 0.90 idi)
  Gün 5 sonrası: Yeni MBE bazı → NC_base güncellenir
  Gün 6: Yeni MBE = 0.40 (< θ) → ama hâlâ baskı var
  Gün 10: İkinci zam (+0.40 TRY/L)

Kural: Kısmi zam → "PARTIAL_CLOSE" durumu
  - Eski watching dönemi kapatılır (delay = 5 gün)
  - NC_base güncellenir
  - Yeni MBE hesaplanır
  - Eğer yeni MBE hâlâ > θ → hemen yeni WATCHING başlat
  - Eğer yeni MBE < θ → IDLE'a dön

Kayıt:
  [{type: "PARTIAL", cross_date: gün_1, hike_date: gün_5, 
    delay: 5, magnitude: 0.50, remaining_mbe: 0.40},
   {type: "FULL", cross_date: gün_6_veya_yeni_cross, hike_date: gün_10,
    delay: 4_veya_5, magnitude: 0.40}]
```

```python
def handle_hike_event(
    tracker: DelayTracker,
    hike_magnitude: float,
    mbe_at_hike: float,
    new_nc_base: float,  # Zam sonrası yeni baz
    threshold: float
) -> DelayTracker:
    """Zam geldiğinde tracker'ı güncelle."""
    
    if tracker.state == "WATCHING":
        # Zam büyüklüğü vs MBE karşılaştır
        remaining_pressure = mbe_at_hike - hike_magnitude
        # (Basitleştirilmiş — gerçekte yeni MBE hesaplanmalı)
        
        if abs(remaining_pressure) <= 0.25:
            # Tam kapatma
            log_close_event(tracker, "FULL", hike_magnitude)
            tracker.state = "IDLE"
        else:
            # Kısmi kapatma
            log_close_event(tracker, "PARTIAL", hike_magnitude)
            tracker.state = "IDLE"
            
            # Yeni MBE ile yeniden değerlendir
            # (NC_base güncellenecek, sonraki MBE hesabında etki edecek)
    
    # NC_base'i güncelle (MBE modülünde)
    tracker.current_delay_days = 0
    tracker.threshold_cross_date = None
    tracker.below_threshold_streak = 0
    
    return tracker
```

### Edge Case 4: Rejim Geçişi Sırasında Eşik Aşık

```
Gün 1-5: Rejim 0, θ = 0.70, MBE > 0.70 → WATCHING
Gün 6: Rejim 1'e geçiş (seçim dönemi), θ = 1.20

Karar: Rejim değiştiğinde:
  1. Eski rejimin eşiği ile mevcut delay'i logla
  2. Yeni rejimin eşiğini uygula
  3. MBE yeni eşiğin altında mı kontrol et
     - Altında → IDLE'a dön (yeni rejimde henüz baskı yok)
     - Üstünde → WATCHING devam, ama yeni cross_date = rejim geçiş tarihi
```

## 3.7 Sentetik Örnek: Tam Yaşam Döngüsü

```
=== MOTORİN — 30 Günlük Senaryo ===

Son zam: 1 Ocak, NC_base(fwd) = 19.50 TRY/L, Rejim: Normal(0), θ = 0.70

Gün  │ MBE    │ Durum     │ Gecikme │ Olay
─────┼────────┼───────────┼─────────┼──────────────────────
  1  │ +0.05  │ IDLE      │   -     │ 
  3  │ +0.18  │ IDLE      │   -     │ SABİT sınıfı
  5  │ +0.35  │ IDLE      │   -     │ ZAM_BASKISI sınıfı
  7  │ +0.55  │ IDLE      │   -     │ 
  9  │ +0.72  │ WATCHING  │   0     │ ⚡ Eşik aşıldı!
 10  │ +0.80  │ WATCHING  │   1     │
 11  │ +0.65  │ WATCHING  │   2     │ Eşik altı (streak=1)
 12  │ +0.75  │ WATCHING  │   3     │ Eşik üstü (streak=0)
 13  │ +0.88  │ WATCHING  │   4     │ z=0.0 (tam ortalamada)
 14  │ +0.92  │ WATCHING  │   5     │ z=0.44
 15  │ +0.85  │ WATCHING  │   6     │ z=1.0 — DİKKAT
 16  │ +0.78  │ WATCHING  │   7     │ z=1.56
 17  │ +0.90  │ WATCHING  │   8     │ z=2.11 — ANORMAL ⚠️
 18  │ +0.95  │ WATCHING  │   9     │ z=2.67 — KRİTİK 🔴
 19  │  -     │ CLOSED    │   -     │ 🎯 ZAM! +1.00 TRY/L
 19  │ +0.05  │ IDLE      │   -     │ Yeni dönem başladı

Dashboard çıktısı (Gün 18):
"Eşik aşıldı: 9 gün | Tarihsel ort: 4.2 gün (±1.8) | Z: 2.67 🔴"

Kayıt:
{hike_date: "19 Oca", cross_date: "9 Oca", delay: 10 gün,
 regime: 0, mbe_at_hike: 0.95, mbe_max: 0.95, magnitude: 1.00,
 z_score: 2.67, type: "FULL"}
```

## 3.8 Tam Pseudocode: Daily Orchestrator

```python
def daily_delay_update(
    tracker: DelayTracker,
    mbe_today: float,
    today: date,
    threshold: float,
    historical_stats: dict  # {mean, std} for current regime
) -> DelayTracker:
    """
    Her gün çalışan politik gecikme güncelleyici.
    """
    
    if tracker.state == "IDLE":
        if mbe_today >= threshold:
            # Eşik ilk kez aşıldı → WATCHING başlat
            tracker.state = "WATCHING"
            tracker.threshold_cross_date = today
            tracker.current_delay_days = 0
            tracker.mbe_at_cross = mbe_today
            tracker.mbe_max = mbe_today
            tracker.below_threshold_streak = 0
            
            emit_alert("THRESHOLD_CROSSED", tracker)
    
    elif tracker.state == "WATCHING":
        tracker.current_delay_days = (today - tracker.threshold_cross_date).days
        tracker.mbe_current = mbe_today
        tracker.mbe_max = max(tracker.mbe_max, mbe_today)
        
        # Z-score güncelle
        if historical_stats['std'] > 0:
            tracker.z_score = (
                (tracker.current_delay_days - historical_stats['mean']) 
                / historical_stats['std']
            )
        else:
            tracker.z_score = 0
        
        # Eşik altına düşme kontrolü
        if mbe_today < threshold:
            tracker.below_threshold_streak += 1
            if tracker.below_threshold_streak >= tracker.BELOW_THRESHOLD_RESET:
                log_absorbed_event(tracker)
                tracker.state = "IDLE"
                tracker.threshold_cross_date = None
                tracker.current_delay_days = 0
                emit_alert("ABSORBED", tracker)
        else:
            tracker.below_threshold_streak = 0
        
        # Anomali alert
        if tracker.z_score >= 2.0:
            emit_alert("ANOMALY_HIGH", tracker)
        elif tracker.z_score >= 1.0:
            emit_alert("ANOMALY_MEDIUM", tracker)
    
    return tracker


def handle_price_change(
    tracker: DelayTracker,
    change_amount: float,  # TRY/L (pozitif=zam, negatif=indirim)
    new_nc_base: float,
    change_date: date,
    threshold: float
) -> DelayTracker:
    """
    Fiyat değişimi (zam/indirim) geldiğinde çağrılır.
    """
    if abs(change_amount) < 0.25:
        return tracker  # Önemsiz değişim, yoksay
    
    if tracker.state == "WATCHING":
        # Gecikme kaydını logla
        event_type = "FULL"  # Varsayılan
        
        # Kalan baskıyı hesapla (basitleştirilmiş)
        remaining = tracker.mbe_current - abs(change_amount)
        if remaining > threshold:
            event_type = "PARTIAL"
        
        log_delay_event({
            'type': event_type,
            'cross_date': tracker.threshold_cross_date,
            'hike_date': change_date,
            'delay_days': tracker.current_delay_days,
            'regime': tracker.regime,
            'magnitude': change_amount,
            'mbe_at_cross': tracker.mbe_at_cross,
            'mbe_at_hike': tracker.mbe_current,
            'mbe_max': tracker.mbe_max,
            'z_score': tracker.z_score
        })
    
    # Reset tracker
    tracker.state = "IDLE"
    tracker.threshold_cross_date = None
    tracker.current_delay_days = 0
    tracker.below_threshold_streak = 0
    tracker.z_score = 0
    
    # NC_base güncellenir (MBE modülünde yapılır)
    
    return tracker
```

---

# ÇIKTI 4 — ML KATMANI (KATMAN 2) FEATURE SET ÖNERİSİ

## 4.1 Mimari Pozisyon

```
┌─────────────────────────────────────────────────┐
│              KARAR MİMARİSİ                      │
│                                                  │
│  KATMAN 1: Deterministik Kural Motoru            │
│  ├── MBE Hesaplama                               │
│  ├── Eşik Karşılaştırma                         │
│  ├── Politik Gecikme Takibi                      │
│  └── Rejim Tanıma                                │
│         │                                        │
│         ▼ (feature üretir)                       │
│                                                  │
│  KATMAN 2: ML Destekleyici (BU BÖLÜM)           │
│  ├── Zam olasılığı tahmini                       │
│  ├── Zam büyüklüğü tahmini                      │
│  └── Güven skoru                                 │
│         │                                        │
│         ▼                                        │
│                                                  │
│  ÇIKTI: Katman 1 + Katman 2 birleşik sinyal     │
│  "Katman 1 eşik aşıldı dedi + Katman 2 %85     │
│   olasılık diyor → YÜKSEK güvenle zam sinyali"  │
└─────────────────────────────────────────────────┘
```

**ML katmanı asla tek başına sinyal üretmez.** Katman 1'in sinyalini güçlendirir veya filtreye alır.

## 4.2 Tam Feature Seti

### Grup A: Katman 1 Türevli Feature'lar (Çekirdek)

| # | Feature | Tanım | Birim | Hesaplama |
|---|---------|--------|-------|-----------|
| A1 | `mbe_value` | Güncel MBE değeri | TRY/L | Çıktı 1'den |
| A2 | `mbe_pct` | MBE yüzdesel | % | MBE / NC_base × 100 |
| A3 | `mbe_to_threshold` | MBE / Eşik oranı | oran | MBE / θ |
| A4 | `mbe_above_threshold` | Eşik aşılmış mı | binary | 1 if MBE > θ else 0 |
| A5 | `days_above_threshold` | Eşik aşıldıktan sonra gün | gün | Çıktı 3'ten |
| A6 | `delay_z_score` | Gecikme anomali skoru | z | Çıktı 3'ten |
| A7 | `delta_mbe_1d` | MBE günlük değişim | TRY/L | MBE_t - MBE_{t-1} |
| A8 | `delta_mbe_3d` | MBE 3 günlük momentum | TRY/L | MBE_t - MBE_{t-3} |
| A9 | `delta_mbe_5d` | MBE 5 günlük momentum | TRY/L | MBE_t - MBE_{t-5} |
| A10 | `mbe_acceleration` | MBE ivmesi | TRY/L/gün² | ΔMBE_t - ΔMBE_{t-1} |
| A11 | `mbe_max_since_hike` | Son zamdan beri max MBE | TRY/L | max(MBE_{t_last:t}) |
| A12 | `mbe_volatility_5d` | MBE 5 günlük volatilite | TRY/L | std(MBE_{t-4:t}) |
| A13 | `days_since_last_hike` | Son zamdan beri gün | gün | t - t_last |
| A14 | `absorbed_count_90d` | Son 90 günde absorbe sayısı | adet | Çıktı 3'ten |

### Grup B: Dış Veri Feature'ları (Piyasa Dinamikleri)

| # | Feature | Tanım | Birim | Hesaplama |
|---|---------|--------|-------|-----------|
| B1 | `cif_change_1d` | CIF günlük değişim | USD/ton | CIF_t - CIF_{t-1} |
| B2 | `cif_change_5d` | CIF haftalık değişim | USD/ton | CIF_t - CIF_{t-5} |
| B3 | `cif_change_pct_5d` | CIF haftalık % değişim | % | (CIF_t/CIF_{t-5} - 1)×100 |
| B4 | `fx_change_1d` | Kur günlük değişim | TRY | FX_t - FX_{t-1} |
| B5 | `fx_change_5d` | Kur haftalık değişim | TRY | FX_t - FX_{t-5} |
| B6 | `fx_volatility_10d` | Kur 10 günlük volatilite | TRY | std(FX_{t-9:t}) |
| B7 | `fx_volatility_30d` | Kur 30 günlük volatilite | TRY | std(FX_{t-29:t}) |
| B8 | `cif_fx_corr_20d` | CIF-Kur 20 gün korelasyonu | [-1,1] | corr(CIF, FX, 20d) |
| B9 | `brent_change_5d` | Brent haftalık değişim | USD/bbl | Brent_t - Brent_{t-5} |
| B10 | `crack_spread` | Rafineri marjı (Brent→CIF) | USD/ton | CIF - (Brent × ~7.45) |
| B11 | `cost_driver` | Maliyet sürücüsü | {CIF, FX, BOTH} | Hangisi daha çok etki ediyor |

**B11 hesaplama detayı:**

```
Δ_cif_contrib = (ΔCIF × FX_{t-1}) / ρ
Δ_fx_contrib  = (CIF_{t-1} × ΔFX) / ρ

cost_driver = {
    "CIF"   if |Δ_cif_contrib| > 2 × |Δ_fx_contrib|
    "FX"    if |Δ_fx_contrib| > 2 × |Δ_cif_contrib|
    "BOTH"  otherwise
}
# ML'de one-hot encode edilir
```

### Grup C: Rejim Feature'ları

| # | Feature | Tanım | Birim | Hesaplama |
|---|---------|--------|-------|-----------|
| C1 | `regime_id` | Aktif rejim | {0,1,2,3} | Rejim tanıma modülünden |
| C2 | `regime_duration_days` | Rejimde geçen gün | gün | Rejim başlangıcından beri |
| C3 | `regime_0_flag` | Normal dönem mi | binary | 1 if regime=0 |
| C4 | `regime_1_flag` | Seçim dönemi mi | binary | 1 if regime=1 |
| C5 | `regime_2_flag` | Kur şoku mu | binary | 1 if regime=2 |
| C6 | `regime_3_flag` | Vergi ayarlama mı | binary | 1 if regime=3 |
| C7 | `regime_transition_recent` | Son 30 günde rejim değişti mi | binary | |

### Grup D: Zaman Feature'ları

| # | Feature | Tanım | Birim | Hesaplama |
|---|---------|--------|-------|-----------|
| D1 | `day_of_week` | Haftanın günü | 0-6 | Pazartesi=0, Pazar=6 |
| D2 | `is_monday` | Pazartesi mi | binary | Zamlar genelde Pazartesi/Salı |
| D3 | `is_tuesday` | Salı mı | binary | |
| D4 | `month` | Ay | 1-12 | |
| D5 | `is_pre_holiday` | Tatil öncesi mi | binary | Resmi tatilden 1-3 gün önce |
| D6 | `is_post_holiday` | Tatil sonrası mı | binary | Resmi tatilden 1-2 gün sonra |
| D7 | `days_to_election` | Seçime kaç gün | gün | Bilinen seçim takviminden |
| D8 | `election_proximity` | Seçim yakınlığı kategorisi | {FAR, NEAR, IMMINENT} | >180d, 30-180d, <30d |
| D9 | `is_ramadan` | Ramazan ayı mı | binary | |
| D10 | `is_summer` | Yaz dönemi mi (talep yüksek) | binary | Haziran-Eylül |
| D11 | `quarter` | Çeyrek | 1-4 | |
| D12 | `is_year_end` | Yıl sonu mu (Aralık) | binary | ÖTV ayarlama dönemi |

### Grup E: Tarihsel Pattern Feature'ları

| # | Feature | Tanım | Birim | Hesaplama |
|---|---------|--------|-------|-----------|
| E1 | `avg_hike_interval_90d` | Son 90 gündeki ort. zam aralığı | gün | |
| E2 | `hike_count_30d` | Son 30 günde zam sayısı | adet | |
| E3 | `hike_count_90d` | Son 90 günde zam sayısı | adet | |
| E4 | `last_hike_magnitude` | Son zamın büyüklüğü | TRY/L | |
| E5 | `avg_hike_magnitude_90d` | Son 90 gündeki ort. zam büyüklüğü | TRY/L | |
| E6 | `consecutive_hike_days` | Ardışık zam günü sayısı | gün | |

**Toplam: 47 feature** (A:14 + B:11 + C:7 + D:12 + E:6)

## 4.3 Feature Önem Sıralaması Önerisi (Beklenen SHAP Sırası)

```
SHAP Önem Sıralaması (Hipotez — gerçek veriden kalibre edilecek):

Tier 1 — Ana Sürücüler (toplam SHAP ~60%):
  1. mbe_value (A1)              — ~15%  En temel sinyal
  2. mbe_above_threshold (A4)    — ~12%  Eşik durumu
  3. days_above_threshold (A5)   — ~10%  Gecikme süresi
  4. delta_mbe_3d (A8)           — ~8%   Momentum
  5. mbe_to_threshold (A3)       — ~8%   Eşiğe göre pozisyon
  6. days_since_last_hike (A13)  — ~7%   Son zamdan beri geçen süre

Tier 2 — Güçlendiriciler (toplam SHAP ~25%):
  7. cif_change_5d (B2)          — ~5%
  8. fx_volatility_10d (B6)      — ~4%
  9. regime_id (C1)              — ~4%
 10. delay_z_score (A6)          — ~3%
 11. mbe_acceleration (A10)      — ~3%
 12. cost_driver (B11)           — ~3%
 13. fx_change_5d (B5)           — ~3%

Tier 3 — Bağlam (toplam SHAP ~15%):
 14. day_of_week (D1)            — ~3%
 15. election_proximity (D8)     — ~3%
 16. hike_count_30d (E2)         — ~2%
 17. is_ramadan (D9)             — ~2%
 18. mbe_volatility_5d (A12)     — ~2%
 19. regime_duration_days (C2)   — ~1.5%
 20. Diğerleri                   — ~1.5%
```

## 4.4 Hedef Değişken Tanımı

### Sınıflandırma (Birincil Görev)

```
y_class = {
    "ZAM"     if gerçek_fiyat_değişimi > +0.25 TRY/L    (sonraki 1-3 gün içinde)
    "SABİT"   if |gerçek_fiyat_değişimi| ≤ 0.25 TRY/L
    "İNDİRİM" if gerçek_fiyat_değişimi < -0.25 TRY/L
}

Zaman penceresi: t+1, t+2, t+3 (1-3 gün ilerisi)
Tercih: t+1 (yarın) — en actionable
```

**Sınıf dağılımı tahmini (Türkiye bağlamı):**

```
SABİT:   ~85-90%  (çoğu gün fiyat değişmez)
ZAM:     ~7-10%   
İNDİRİM: ~3-5%    

→ Yüksek sınıf dengesizliği!
```

### Regresyon (İkincil Görev)

```
y_reg = gerçek_fiyat_değişimi (TRY/L)

Sadece y_class ∈ {ZAM, İNDİRİM} olan günlerde eğitilir.
Amaç: Zam olacaksa ne kadar?
```

## 4.5 Model Spesifikasyonu

### XGBoost / LightGBM Konfigürasyonu

```python
# === SINIFLANDIRMA MODELİ ===
clf_params = {
    # LightGBM
    'objective': 'multiclass',
    'num_class': 3,
    'metric': 'multi_logloss',
    
    # Tree yapısı
    'num_leaves': 31,
    'max_depth': 6,
    'min_child_samples': 20,
    'learning_rate': 0.05,
    'n_estimators': 300,
    
    # Regularizasyon
    'reg_alpha': 0.1,        # L1
    'reg_lambda': 1.0,       # L2
    'min_split_gain': 0.01,
    
    # Sınıf dengesizliği (AŞAĞIDA DETAYLI)
    'class_weight': {0: 1.0, 1: 10.0, 2: 15.0},  # SABİT, ZAM, İNDİRİM
    
    # Diğer
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'random_state': 42,
    'verbose': -1
}

# === REGRESYON MODELİ ===
reg_params = {
    'objective': 'regression',
    'metric': 'mae',
    'num_leaves': 15,       # Daha basit — daha az veri
    'max_depth': 4,
    'learning_rate': 0.03,
    'n_estimators': 200,
    'reg_alpha': 0.5,
    'reg_lambda': 2.0,
    'min_child_samples': 10,
    'subsample': 0.7,
    'colsample_bytree': 0.7
}
```

### Önerilen Feature Set (Optimized)

```python
# Sınıflandırma için (tam set yerine pruned set — daha az overfitting)
CLASSIFICATION_FEATURES = [
    # Tier 1 (zorunlu)
    'mbe_value', 'mbe_above_threshold', 'days_above_threshold',
    'delta_mbe_3d', 'mbe_to_threshold', 'days_since_last_hike',
    
    # Tier 2 (güçlendirici)
    'cif_change_5d', 'fx_volatility_10d', 'regime_id',
    'delay_z_score', 'mbe_acceleration', 'fx_change_5d',
    
    # Tier 3 (bağlam — seçici)
    'day_of_week', 'election_proximity_NEAR', 'election_proximity_IMMINENT',
    'hike_count_30d', 'mbe_volatility_5d',
]
# Toplam: 17 feature (47'den → overfitting riski düşük)

# Regresyon için
REGRESSION_FEATURES = [
    'mbe_value', 'mbe_pct', 'delta_mbe_5d', 'mbe_max_since_hike',
    'cif_change_5d', 'fx_change_5d', 'days_above_threshold',
    'regime_id', 'last_hike_magnitude', 'avg_hike_magnitude_90d'
]
# Toplam: 10 feature
```

## 4.6 High Precision Stratejisi

### Strateji 1: Class Weight Ayarlama

```python
# Sınıf dengesizliği: SABİT ~87%, ZAM ~9%, İNDİRİM ~4%
# Hedef: ZAM precision > 0.85, recall > 0.50

# Yaklaşım: Cost-sensitive learning
# ZAM'ı kaçırmanın maliyeti < ZAM'ı yanlış söylemenin maliyeti (precision > recall)

class_weights = {
    0: 1.0,     # SABİT — baseline
    1: 8.0,     # ZAM — recall için yükselt ama aşırıya kaçma
    2: 12.0     # İNDİRİM — en az veri, en yüksek weight
}

# UYARI: Çok yüksek weight → recall ↑ ama precision ↓
# İteratif ayarlama gerekir
```

### Strateji 2: Probability Threshold Ayarlama

```python
def high_precision_predict(
    model,
    X: pd.DataFrame,
    precision_threshold: float = 0.75  # Minimum olasılık
) -> np.array:
    """
    Yüksek precision tahmin: düşük güvenli tahminleri SABİT'e çek.
    """
    probas = model.predict_proba(X)  # shape: (n, 3)
    
    predictions = []
    for i in range(len(X)):
        p_sabit = probas[i, 0]
        p_zam = probas[i, 1]
        p_indirim = probas[i, 2]
        
        # ZAM veya İNDİRİM demek için yüksek güven gerekir
        if p_zam >= precision_threshold:
            predictions.append("ZAM")
        elif p_indirim >= precision_threshold:
            predictions.append("İNDİRİM")
        else:
            predictions.append("SABİT")  # Default: SABİT
    
    return np.array(predictions)


def find_optimal_threshold(
    model,
    X_val: pd.DataFrame,
    y_val: np.array,
    target_precision: float = 0.85
) -> float:
    """
    Grid search ile minimum precision sağlayan en düşük threshold'u bul.
    Böylece recall maximize edilir.
    """
    probas = model.predict_proba(X_val)
    
    best_threshold = 1.0
    best_recall = 0
    
    for threshold in np.arange(0.50, 0.99, 0.01):
        preds = ['ZAM' if p[1] >= threshold else 'SABİT' for p in probas]
        
        # ZAM için precision
        zam_preds = [i for i, p in enumerate(preds) if p == 'ZAM']
        if len(zam_preds) == 0:
            continue
            
        true_zams = sum(1 for i in zam_preds if y_val[i] == 'ZAM')
        precision = true_zams / len(zam_preds)
        
        if precision >= target_precision:
            # Recall hesapla
            total_true_zams = sum(1 for y in y_val if y == 'ZAM')
            recall = true_zams / total_true_zams if total_true_zams > 0 else 0
            
            if recall > best_recall:
                best_recall = recall
                best_threshold = threshold
    
    return best_threshold
```

### Strateji 3: Two-Stage Prediction (Katman 1 + Katman 2 Entegrasyonu)

```python
def combined_prediction(
    mbe_value: float,
    threshold: float,
    ml_proba_zam: float,
    delay_days: int,
    delay_z_score: float,
    ml_precision_threshold: float = 0.75
) -> dict:
    """
    Katman 1 (deterministik) + Katman 2 (ML) birleşik sinyal.
    
    Returns: {signal, confidence, reasoning}
    """
    
    # Katman 1 sinyali
    layer1_signal = "ZAM_BASKISI" if mbe_value >= threshold else "SABİT"
    
    # Katman 2 sinyali
    layer2_signal = "ZAM" if ml_proba_zam >= ml_precision_threshold else "SABİT"
    
    # Birleşik karar matrisi
    if layer1_signal == "ZAM_BASKISI" and layer2_signal == "ZAM":
        # İki katman da zam diyor → YÜKSEK GÜVEN
        confidence = "HIGH"
        signal = "ZAM_BEKLENİYOR"
        reasoning = (
            f"MBE ({mbe_value:.2f}) eşiği ({threshold:.2f}) aştı. "
            f"ML modeli %{ml_proba_zam*100:.0f} olasılık veriyor. "
            f"Gecikme: {delay_days} gün (z={delay_z_score:.1f})"
        )
    
    elif layer1_signal == "ZAM_BASKISI" and layer2_signal == "SABİT":
        # Katman 1 baskı görüyor ama ML ikna değil → ORTA GÜVEN
        confidence = "MEDIUM"
        signal = "BASKI_VAR_ZAMANLAMA_BELİRSİZ"
        reasoning = (
            f"MBE ({mbe_value:.2f}) eşiği aştı ama ML modeli "
            f"henüz %{ml_proba_zam*100:.0f} olasılık veriyor (eşik: "
            f"%{ml_precision_threshold*100:.0f}). Gecikme devam edebilir."
        )
    
    elif layer1_signal == "SABİT" and layer2_signal == "ZAM":
        # ML zam diyor ama eşik aşılmadı → DİKKAT (nadir)
        confidence = "LOW"
        signal = "ERKENCİ_SİNYAL"
        reasoning = (
            f"MBE ({mbe_value:.2f}) henüz eşik altında ama ML "
            f"erken sinyal veriyor. İzlemeye devam."
        )
    
    else:
        # İkisi de sabit
        confidence = "NONE"
        signal = "SABİT"
        reasoning = "Baskı yok."
    
    return {
        'signal': signal,
        'confidence': confidence,
        'reasoning': reasoning,
        'layer1': layer1_signal,
        'layer2': layer2_signal,
        'ml_proba_zam': ml_proba_zam,
        'mbe_value': mbe_value,
        'delay_days': delay_days
    }
```

### Strateji 4: Cost-Sensitive Loss Function

```python
# Custom cost matrix
# cost[true][predicted]
COST_MATRIX = {
    #                 Pred:SABİT  Pred:ZAM  Pred:İNDİRİM
    'SABİT':    {    'SABİT': 0,  'ZAM': 5,  'İNDİRİM': 5    },  # False alarm
    'ZAM':      {    'SABİT': 2,  'ZAM': 0,  'İNDİRİM': 10   },  # Miss = 2 (tolerable)
    'İNDİRİM':  {    'SABİT': 2,  'ZAM': 10, 'İNDİRİM': 0    },  # Cross-miss = 10
}

# Neden ZAM'ı kaçırmak (2) < yanlış ZAM demek (5)?
# High precision felsefesi: "ZAM dediğimizde doğru olmalı"
# Kaçırdığımız zamlar olabilir ama söylediğimiz zamlar güvenilir olmalı

def custom_eval_metric(y_pred, dtrain):
    """LightGBM custom evaluation metric: cost-sensitive accuracy"""
    y_true = dtrain.get_label()
    labels = ['SABİT', 'ZAM', 'İNDİRİM']
    
    total_cost = 0
    n = len(y_true)
    
    for i in range(n):
        true_label = labels[int(y_true[i])]
        pred_label = labels[int(y_pred[i])]
        total_cost += COST_MATRIX[true_label][pred_label]
    
    avg_cost = total_cost / n
    
    # LightGBM format: (name, value, is_higher_better)
    return 'custom_cost', avg_cost, False
```

## 4.7 Model Değerlendirme Metrikleri

```
Birincil Metrikler:
  - ZAM Precision ≥ 0.85        (söylediğimizde doğru olmalı)
  - ZAM Recall ≥ 0.50           (yarısını yakalasak yeter)
  - İNDİRİM Precision ≥ 0.80
  - Macro F1 (bilgi amaçlı)

İkincil Metrikler:
  - Regresyon MAE (TL bazlı)
  - Early Warning doğruluğu (1-3 gün önceden sinyal)
  - False Positive Rate < 0.05 (günlük yanlış alarm)

Operasyonel Metrikler:
  - Katman 1 + 2 birleşik HIGH confidence precision ≥ 0.90
  - Ortalama erken uyarı süresi ≥ 1 gün
```

## 4.8 Sentetik Feature Set Örneği

```
Gün: 15 Şubat 2026 — Motorin

Feature Set:
┌──────────────────────────────┬──────────┐
│ Feature                       │ Değer    │
├──────────────────────────────┼──────────┤
│ mbe_value                     │ +0.85    │
│ mbe_pct                       │ +4.2%    │
│ mbe_to_threshold              │ 1.21     │
│ mbe_above_threshold           │ 1        │
│ days_above_threshold          │ 6        │
│ delay_z_score                 │ 1.44     │
│ delta_mbe_1d                  │ +0.05    │
│ delta_mbe_3d                  │ +0.18    │
│ delta_mbe_5d                  │ +0.30    │
│ mbe_acceleration              │ -0.02    │
│ mbe_max_since_hike            │ +0.90    │
│ mbe_volatility_5d             │ 0.08     │
│ days_since_last_hike          │ 22       │
│ absorbed_count_90d            │ 1        │
│ cif_change_5d                 │ +12.5    │
│ fx_volatility_10d             │ 0.35     │
│ regime_id                     │ 0        │
│ delay_z_score                 │ 1.44     │
│ fx_change_5d                  │ +0.50    │
│ day_of_week                   │ 0 (Pzt)  │
│ election_proximity_NEAR       │ 0        │
│ election_proximity_IMMINENT   │ 0        │
│ hike_count_30d                │ 2        │
│ mbe_volatility_5d             │ 0.08     │
├──────────────────────────────┼──────────┤
│ Model output:                 │          │
│   P(SABİT)                    │ 0.20     │
│   P(ZAM)                      │ 0.78     │
│   P(İNDİRİM)                  │ 0.02     │
├──────────────────────────────┼──────────┤
│ Precision threshold           │ 0.75     │
│ ML Prediction                 │ ZAM ✓    │
│ Katman 1 Signal               │ EŞİK_AŞILDI │
│ Combined                      │ HIGH CONFIDENCE │
└──────────────────────────────┴──────────┘

Çıktı:
"🔴 ZAM BEKLENİYOR (Yüksek Güven)
 MBE +0.85 TRY/L, eşiği %21 aştı, 6 gündür sürdürüyor.
 ML: %78 olasılık. Tarihsel ort. gecikme: 4.2 gün, şu an 6. gün."
```

## 4.9 Training Pipeline Pseudocode

```python
def train_fuel_hike_model(
    feature_df: pd.DataFrame,      # Tarihsel feature matrix
    labels: pd.Series,             # ZAM/SABİT/İNDİRİM
    magnitudes: pd.Series,         # TL bazlı değişim (regresyon için)
    test_size: float = 0.2
) -> dict:
    """
    Tam training pipeline.
    Time-series split kullanır (shuffle yok!).
    """
    import lightgbm as lgb
    from sklearn.model_selection import TimeSeriesSplit
    
    # === 1. Time-based split (ASLA random shuffle yapma!) ===
    split_idx = int(len(feature_df) * (1 - test_size))
    X_train = feature_df.iloc[:split_idx]
    X_test = feature_df.iloc[split_idx:]
    y_train = labels.iloc[:split_idx]
    y_test = labels.iloc[split_idx:]
    
    # === 2. Sınıflandırma modeli ===
    label_map = {'SABİT': 0, 'ZAM': 1, 'İNDİRİM': 2}
    y_train_enc = y_train.map(label_map)
    y_test_enc = y_test.map(label_map)
    
    # Class weight hesapla
    counts = y_train_enc.value_counts()
    total = len(y_train_enc)
    sample_weights = y_train_enc.map({
        0: total / (3 * counts[0]),    # SABİT
        1: total / (3 * counts[1]) * 2.0,  # ZAM — ekstra boost
        2: total / (3 * counts[2]) * 2.0   # İNDİRİM — ekstra boost
    })
    
    clf = lgb.LGBMClassifier(**clf_params)
    clf.fit(
        X_train[CLASSIFICATION_FEATURES],
        y_train_enc,
        sample_weight=sample_weights,
        eval_set=[(X_test[CLASSIFICATION_FEATURES], y_test_enc)],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)]
    )
    
    # === 3. Optimal threshold bul ===
    opt_threshold = find_optimal_threshold(
        clf, X_test[CLASSIFICATION_FEATURES], y_test,
        target_precision=0.85
    )
    
    # === 4. Regresyon modeli (sadece zam/indirim günlerinde) ===
    zam_mask_train = y_train != 'SABİT'
    zam_mask_test = y_test != 'SABİT'
    
    reg = lgb.LGBMRegressor(**reg_params)
    if zam_mask_train.sum() > 30:  # Yeterli veri varsa
        reg.fit(
            X_train[zam_mask_train][REGRESSION_FEATURES],
            magnitudes.iloc[:split_idx][zam_mask_train],
            eval_set=[(
                X_test[zam_mask_test][REGRESSION_FEATURES],
                magnitudes.iloc[split_idx:][zam_mask_test]
            )],
            callbacks=[lgb.early_stopping(30)]
        )
    
    # === 5. SHAP analizi ===
    import shap
    explainer = shap.TreeExplainer(clf)
    shap_values = explainer.shap_values(X_test[CLASSIFICATION_FEATURES])
    
    # === 6. Cross-validation (TimeSeriesSplit) ===
    tscv = TimeSeriesSplit(n_splits=5)
    cv_scores = []
    for train_idx, val_idx in tscv.split(X_train):
        fold_clf = lgb.LGBMClassifier(**clf_params)
        fold_clf.fit(
            X_train.iloc[train_idx][CLASSIFICATION_FEATURES],
            y_train_enc.iloc[train_idx],
            sample_weight=sample_weights.iloc[train_idx]
        )
        fold_preds = fold_clf.predict(
            X_train.iloc[val_idx][CLASSIFICATION_FEATURES]
        )
        fold_prec = precision_score(
            y_train_enc.iloc[val_idx], fold_preds, 
            labels=[1], average='binary'
        )
        cv_scores.append(fold_prec)
    
    return {
        'classifier': clf,
        'regressor': reg,
        'optimal_threshold': opt_threshold,
        'shap_values': shap_values,
        'cv_precision_scores': cv_scores,
        'cv_precision_mean': np.mean(cv_scores),
        'feature_importance': dict(zip(
            CLASSIFICATION_FEATURES,
            clf.feature_importances_
        ))
    }
```

---

# ÖZET MİMARİ DİYAGRAM

```
                    VERİ KAYNAKLARI
    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │  CIF     │  │  USD/TRY │  │  Pompa   │  │  Rejim   │
    │  (Platts)│  │  (TCMB)  │  │  (EPDK)  │  │  (Manuel)│
    └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │              │
         └──────┬──────┘             │              │
                │                    │              │
    ┌───────────▼────────────────────▼──────────────▼───────┐
    │                  KATMAN 1 — Deterministik              │
    │                                                        │
    │  ┌──────────┐    ┌──────────┐    ┌──────────────┐     │
    │  │   MBE    │───▶│  Eşik    │───▶│   Politik     │     │
    │  │  Hesap   │    │ Kontrol  │    │   Gecikme     │     │
    │  │ (Çıktı1) │    │ (Çıktı2) │    │  (Çıktı 3)   │     │
    │  └──────────┘    └──────────┘    └──────────────┘     │
    │       │               │                │               │
    │       └───────────────┼────────────────┘               │
    │                       │                                │
    │              Feature Üretimi (47 feature)              │
    └───────────────────────┼────────────────────────────────┘
                            │
    ┌───────────────────────▼────────────────────────────────┐
    │                  KATMAN 2 — ML Destekleyici             │
    │                                                        │
    │  ┌───────────────┐        ┌───────────────┐           │
    │  │ Sınıflandırma │        │   Regresyon   │           │
    │  │ (ZAM/SABİT/   │        │ (TL büyüklük) │           │
    │  │  İNDİRİM)     │        │               │           │
    │  └───────┬───────┘        └───────┬───────┘           │
    │          │                        │                    │
    │          └────────┬───────────────┘                    │
    │                   │                                    │
    │          High Precision Filter                         │
    │          (threshold = 0.75-0.85)                       │
    └───────────────────┼────────────────────────────────────┘
                        │
    ┌───────────────────▼────────────────────────────────────┐
    │              BİRLEŞİK SİNYAL                           │
    │                                                        │
    │  Katman 1 (Eşik aşıldı mı?) × Katman 2 (ML olasılık) │
    │                                                        │
    │  → HIGH / MEDIUM / LOW / NONE güven seviyesi           │
    │  → Dashboard + Alert sistemi                           │
    └────────────────────────────────────────────────────────┘
```

---

---TECRÜBE BAŞLANGIÇ---
## Türkiye Yakıt Maliyet Baskı Altyapısı (Blueprint v1) - 2026-02-15

### Görev: 4 çıktılı (MBE formülü, eşik metodolojisi, politik gecikme metriği, ML feature set) yakıt fiyat analiz altyapısı tasarımı

- [KARAR] NC_forward vs NC_observed (pompa bazlı) iki ayrı net maliyet serisi tanımlandı → Delta bazlı MBE (Yaklaşım A) seçildi, çünkü aynı metodoloji (CIF×Kur/ρ) üzerinden değişimi ölçmek tutarlılık sağlıyor. Mutlak seviye farkı (forward ~19.5 vs observed ~30.8 TRY/L) yanıltıcı olurdu.

- [KARAR] Benzin ve motorin için AYRI MBE hesaplamasına karar verildi → Farklı CIF referansları, farklı ÖTV oranları, farklı ρ katsayıları ve farklı politik hassasiyet seviyeleri nedeniyle birleşik hesaplama bilgi kaybına yol açardı.

- [KARAR] ML'yi destekleyici katman (Katman 2) olarak konumlandırdık, çekirdek değil → High precision stratejisi bu mimariyle doğal uyum sağlıyor: Katman 1 (deterministik kural motoru) zaten temel sinyali üretiyor, ML sadece güveni artırıyor veya filtre uyguluyor.

- [PATTERN] Edge case'leri state machine ile modellemek işe yaradı → IDLE → WATCHING → CLOSED geçişleri tüm senaryoları (absorbe, kısmi zam, rejim geçişi) temiz şekilde kapsıyor. State machine'siz bu karmaşıklık yönetilemezdi.

- [PATTERN] Eşik belirlemede grid search + validation metrics (capture rate, false alarm, early warning) üçlüsü işe yaradı → Tek metriğe optimize etmek yerine çoklu kısıt (capture ≥ 0.70 VE false alarm ≤ 0.40) daha sağlam eşik üretiyor.

- [HATA] İlk MBE hesabında NC_base'i pompa fiyatından, NC_current'ı CIF×Kur'dan alınca seviye uyumsuzluğu oluştu → Çözüm: Her iki tarafı da aynı metodoloji (forward SMA) ile hesaplayıp delta almak. Reverse-engineer sadece cross-validation ve kalibrasyon için kullanılıyor.

- [UYARI] SMA pencere genişliği rejim bazlı değişiyor (3-5-7) → Bu, rejim geçişlerinde MBE'de yapay sıçramalar yaratabilir. Geçiş anında smooth blending (α × eski_sma + (1-α) × yeni_sma, α 5 günde 1→0) uygulanmalı.

- [UYARI] ML modeli TimeSeriesSplit kullanılmalı, asla random shuffle → Akaryakıt fiyatlama zaman serisinde güçlü otokorelasyon var, random split data leakage yaratır ve metrikler yapay olarak şişer.

- [UYARI] Class weight'leri aşırı yükseltmek (ZAM: 20× gibi) precision'ı düşürür → Optimum 8-12× aralığında, ama her kalibrasyon döngüsünde threshold tuning ile birlikte ayarlanmalı. Cost matrix ile custom loss function daha kontrollü bir alternatif.

- [UYARI] ±0.25 TRY/L sabit sınıfı eşiği de zamanla kalibre edilmeli → Enflasyon ve kur seviyesi yükseldikçe 0.25 TRY/L'nin "gürültü" olarak absorbe edilebilirliği değişir. Yılda bir kez gözden geçirilmeli.
---TECRÜBE BİTİŞ---
