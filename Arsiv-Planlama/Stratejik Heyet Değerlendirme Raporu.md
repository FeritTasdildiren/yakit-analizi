# Türkiye Akaryakıt Zam Öngörü Sistemi — Stratejik Heyet Değerlendirme Raporu

**Tarih:** 2026-02-15
**Heyet:** Claude Opus (Stratejik Planlayıcı) | Gemini 3 (Ürün Yöneticisi) | Codex GPT-5.2 (Operasyonel Planlayıcı)
**Yöntem:** Delphi İteratif Yakınsama (2 Tur)
**Uzlaşı Durumu:** Kısmi uzlaşı sağlandı — kalan ayrışmalar tercih seviyesinde
**Son Güncelleme:** 2026-02-15 — Proje sahibi kararları entegre edildi

> **📋 Proje Sahibi Güncelleme Özeti (8 karar):**
> 1. CIF Med verisi ücretsiz kaynaklardan scrape edilecek (lisans maliyeti kaldırıldı)
> 2. ÖTV değişimleri sisteme manuel girilebilir (düşük risk)
> 3. Yasal çerçeve araştırılıp raporlanacak (aksiyon atandı)
> 4. MVP'de admin dashboard yer alacak (heyet kararı geçersiz kılındı)
> 5. Crowdsource ve Fintech dashboard'da açıklamalı olarak yer alacak
> 6. LPG (Otogaz) sistem kapsamına dahil edildi
> 7. Ücretsiz katman kaldırıldı (doğrudan premium model)
> 8. Mevcut sunucu proxy havuzu scraping için kullanılacak

---

## Yönetici Özeti

Türkiye Akaryakıt Zam Öngörü Sistemi teknik raporu, 3 farklı LLM altyapısından (Claude, Gemini, Codex) birer temsilcinin oluşturduğu Stratejik Değerlendirme Heyeti tarafından incelendi. 2 tur iteratif değerlendirme sonucunda aşağıdaki uzlaşılmış sonuçlara ulaşıldı:

**Genel Değerlendirme: İyi bir fikir, eksik bir plan.**

Proje teknik olarak uygulanabilir. Türkiye pazarında gerçek bir ihtiyaca yanıt veriyor. Ancak geliştirmeye başlamadan önce çözülmesi gereken **3 kritik önkoşul** var:
1. Yasal çerçeve (EPDK/Rekabet Kurumu) — proje durdurucusu olabilir
2. Veri kaynağı stratejisi (CIF Med verisinin maliyeti ve sürekliliği)
3. Gelir modeli (kim, ne için, ne kadar ödeyecek)

---

## 1. Uzlaşılan Konular (3/3 Tam Uzlaşı)

### 1.1 Veri Kaynağı En Büyük Risk
**Uzlaşı:** CIF Akdeniz Rafineri fiyatları projenin temel girdisi, ancak bu verinin kaynağı, maliyeti ve sürekliliği raporda belirsiz.

| Boyut | Değerlendirme |
|-------|--------------|
| CIF Med verisi | Ücretsiz kaynaklar bulunup scrape edilecek — düşük maliyet |
| USD/TRY | TCMB'den ücretsiz erişilebilir — düşük risk |
| Pompa fiyatları | EPDK/scraping — orta risk, dağınık kaynak |
| ÖTV değişimleri | Sisteme manuel girilebilir — değişim olasılığı çok zayıf, düşük risk |

**Heyet Önerisi:** CIF Med verisi ücretsiz kaynaklardan scraping ile elde edilecek. Brent + USD/TRY + EPDK duyuruları + tarihsel CIF-Brent korelasyonu ile desteklenecek. Lisanslı veri kaynağına ihtiyaç öngörülmüyor.

**Proje Sahibi Kararı:** ÖTV değişimlikleri sisteme manuel olarak girilebilir. ÖTV değişim olasılığı çok düşük olduğundan otomatik takip gerekli değil.

### 1.2 Yasal Çerçeve MVP Öncesi Netleşmeli
**Uzlaşı:** Akaryakıt fiyat tahmini yapan bir sistemin yasal zemini net değil.

| Risk | Kaynak | Seviye |
|------|--------|--------|
| "Stokçuluğa teşvik" suçlaması | EPDK, Rekabet Kurumu | YÜKSEK |
| Fiyat manipülasyonu algısı | Kamu, medya | YÜKSEK |
| KVKK — kullanıcı verisi | Bilgi Teknolojileri Kurumu | ORTA |
| İtibar riski (yanlış tahmin) | Kullanıcılar, medya | YÜKSEK |

**Heyet Önerisi:** Geliştirmeye başlamadan ÖNCE bir hukuk danışmanından EPDK mevzuatı, 6502 sayılı kanun ve Rekabet Kurumu perspektifinde değerlendirme alınmalı. Her tahminde "Bu bir yatırım tavsiyesi değildir, istatistiki tahmindir" disclaimer'ı zorunlu olmalı.

**Proje Sahibi Kararı — Aksiyon:** İlgili kanunlar (EPDK mevzuatı, 6502 sayılı Tüketici Kanunu, Rekabet Kurumu düzenlemeleri, 5015 sayılı Petrol Piyasası Kanunu) araştırılıp detaylı bir yasal çerçeve raporu hazırlanacak. Bu rapor proje geliştirmeye başlamadan önce tamamlanmalıdır.

### 1.3 B2B Lojistik/Filo Öncelikli Segment
**Uzlaşı:** İlk hedef kitle olarak B2B lojistik ve filo kiralama şirketleri seçilmeli.

| Segment | Ödeme Potansiyeli | Öncelik | Gerekçe |
|---------|-------------------|---------|---------|
| Lojistik/Filo (B2B) | Yüksek (₺500-2000/ay) | 1. Öncelik | Doğrudan maliyet etkisi, ROI hesaplanabilir |
| Akaryakıt İstasyonları (B2B) | Orta-Yüksek | 2. Öncelik | Stok yönetimi değeri |
| Bireysel Tüketici (B2C) | Orta (₺49-99/ay premium) | Paralel | Viralite motoru + büyüme kanalı |
| Finansal Trader | Niş | İleri faz | Küçük pazar ama yüksek ARPU |

### 1.4 Gelir Modeli Tanımlanmamış — Kritik Eksiklik
**Uzlaşı:** Raporda gelir modeli yok. Bu, projenin hobi mi girişim mi olduğunu belirsiz kılıyor.

**Heyet Önerisi — Premium + API Modeli (Ücretsiz katman kaldırıldı — Proje Sahibi Kararı):**
- **Premium (B2C):** Günlük alarm, aksiyon önerisi — ₺49-99/ay
- **API (B2B):** Lojistik/istasyon entegrasyonu — ₺500-2.000/ay
- **Enterprise:** Özel dashboard, SLA, dedike destek — ₺5.000+/ay

### 1.5 MVP Tanımı — Telegram Botu + Admin Dashboard
**Proje Sahibi Kararı:** MVP'de Telegram botu ile birlikte bir admin dashboard'u da yer alacak.

**Yalın MVP — İki Bileşen:**

**A) Telegram Botu:**
- Admin onaylı kullanım — yeni kayıt olanlar dashboard'dan onay bekler
- Sadece %70+ zam olasılığı oluştuğunda mesaj atar
- Örnek: "Motorin için 3 gün içinde zam olasılığı %72. Tahmini artış: 0.90-1.20 TL. Bugün deponuzu doldurmanız tavsiye edilir."
- Kısa kanıt özeti eklenmeli (Codex önerisi): CIF trend, kur durumu, geçmiş doğruluk oranı
- Geliştirme aşamasında ücretli kullanıma geçilebilir

**B) Admin Dashboard:**
- Veri akışının ve grafiklerin gerçek zamanlı izlenmesi
- Model tahminlerinin ve güven aralıklarının görselleştirilmesi
- Bot'a kayıt olan kullanıcıların onay/red yönetimi
- CIF, kur, pompa fiyatı trend grafikleri

### 1.6 Yol Haritası — 3 Fazlı Yaklaşım
**Uzlaşı:** Rapordaki 4 hafta + 1-2 ay yerine faz bazlı go/no-go yaklaşımı.

| Faz | Süre | Hedef | Go/No-Go Kriteri |
|-----|------|-------|-----------------|
| **Faz 1: PoC** | 4 hafta | Tarihsel veriyle offline model, Jupyter notebook sonuçları | %70 yön doğruluğu tuttu mu? |
| **Faz 2: MVP** | 4-6 hafta | Canlı veri, Telegram botu, admin dashboard, B2C lansmanı | 100+ abone, 5+ B2B pilot |
| **Faz 3: Ürün** | 4-8 hafta | Otomatik pipeline, B2B API, ödeme, monitoring | İlk ödeme yapan 10 müşteri |

### 1.7 Teknik Altyapı Yeterli ve Ekonomik
**Uzlaşı:** GPU gereksiz, tek küçük VM + PostgreSQL yeterli.

| Bileşen | Çözüm | Aylık Maliyet |
|---------|-------|---------------|
| Sunucu | Tek VPS (2-4 core, 4-8GB RAM) | $20-60 |
| Veritabanı | PostgreSQL | Dahil |
| Model | XGBoost (CPU yeterli) | $0 |
| Bildirim | Telegram Bot API | $0 |
| Admin Dashboard | Streamlit/Next.js | Dahil |
| Monitoring | Evidently/custom | $0-50 |
| Proxy (scraping) | Mevcut sunucu altyapısı | $0 |
| **Toplam** | | **$20-120/ay** |

---

## 2. Kısmi Uzlaşı (Çoğunluk Uyumu, Nüans Farkları)

### 2.1 Rekabet Avantajı ve Moat
| Agent | Görüş |
|-------|-------|
| **Claude** | Teknik moat yok, veri moat yok, ağ etkisi yok → Crowdsource pompa fiyatı (Waze modeli) ile moat oluştur |
| **Gemini** | Waze modeli TR'de çalışmaz (fiyatlar merkezi formülle belirleniyor, 1-5 kuruş fark) → Fintech/sadakat kart entegrasyonu asıl moat |
| **Codex** | Blue Ocean iddiası zayıf → Moat "veri doğruluğu ve karar kalitesi"nde |

**Uzlaşı notu:** 3 agent de "mevcut haliyle sürdürülebilir avantaj zayıf" konusunda hemfikir. Moat oluşturma yöntemi konusunda fikir ayrılığı var:
- Gemini'nin Fintech/sadakat kart entegrasyonu en pratik
- Claude'un crowdsource yaklaşımı uzun vadeli potansiyel taşıyor ama TR regüle pazarında sınırlı
- Codex'in "doğruluk = moat" yaklaşımı doğru ama başlangıçta zayıf (track record yok)

**Heyet Kararı:** İlk fazda doğruluk track record'u oluştur (Codex). Paralelde Fintech/sadakat entegrasyonu araştır (Gemini). Crowdsource ancak ileri fazda değerlendirilsin (Claude).

### 2.2 B2C'nin Rolü
| Agent | Görüş |
|-------|-------|
| **Claude** | B2C viralite motoru — B2B müşterileri B2C görünürlükle gelir. İkincil görmek stratejik hata |
| **Gemini** | B2C düşük gelir potansiyeli, B2B ana gelir kaynağı, B2C yan ürün |
| **Codex** | B2B'de viralite düşük, satış döngüsü uzun |

**Heyet Kararı:** B2C **gelir kaynağı değil ama büyüme kanalı**. Ücretsiz B2C botu → viralite → marka bilinirliği → B2B güven oluşturma. İkisi paralel yürümeli.

### 2.3 Dashboard İhtiyacı
| Agent | Görüş |
|-------|-------|
| **Claude** | MVP'de dashboard gereksiz, bot yeterli |
| **Gemini** | Dashboard gereksiz maliyet, bot yeterli |
| **Codex** | Bot + kısa kanıt özeti (açıklanabilirlik) şart. Dashboard B2B pilotta gerekli |

**Heyet Kararı (geçersiz kılındı):** ~~MVP'de bot + kanıt özeti. B2B pilot aşamasında basit dashboard.~~

**Proje Sahibi Kararı (geçerli):** MVP'de bir admin dashboard'u yer alacaktır. Bu dashboard şunları içerecek:
- Veri akışının ve grafiklerin gerçek zamanlı görüntülenmesi (CIF, kur, pompa fiyatları)
- Model tahmin sonuçlarının ve güven aralıklarının izlenmesi
- Telegram bot'una kayıt olan kullanıcıların onay/red yönetimi
- Heyet önerisinin aksine, dashboard MVP kapsamına dahil edilmiştir.

---

## 3. Ayrışma Noktaları (Tercih Seviyesi — Kritik Değil)

| Konu | Claude | Gemini | Codex | Kritiklik |
|------|--------|--------|-------|-----------|
| Crowdsource pompa fiyatı | Destekliyor (Waze modeli) | Karşı (TR regüle pazar) | Nötr | Dashboard'da yer alacak |
| Fintech/sadakat entegrasyonu | Değinmedi | Güçlü destekliyor | Nötr | Dashboard'da yer alacak |
| Gamification | Değinmedi | Destekliyor | Değinmedi | Düşük — ileri faz |
| İnsan onayı alarm sisteminde | Destekliyor | Karşı (confidence interval) | Başlangıçta evet | Düşük — konfigüre edilebilir |
| LPG yakıt takibi | Destekliyor | Nötr | Nötr | MVP'de dahil edilecek |

**Proje Sahibi Kararları:**
- **Crowdsource:** Dashboard'a "Topluluk Fiyat Bildirimi" bölümü eklenecek. Kullanıcıların bildirdiği pompa fiyatlarının nasıl toplandığı ve sistemdeki rolü açıklanacak.
- **Fintech/Sadakat Entegrasyonu:** Dashboard'da "Fintech Entegrasyon" bölümü yer alacak. Sadakat kartı ve fintech iş birlikleri ile sağlanan veri avantajı ve gelir potansiyeli açıklanacak.
- **LPG:** Sistem kapsamına dahil edilecek. LPG yakıt istasyonlarında yakıt olarak satıldığından, benzin ve motorin ile birlikte LPG (Otogaz) fiyat takibi ve tahmin modeline eklenecek.

---

## 4. Rapordaki Tutarsızlıklar (Claude Tespiti, Heyet Onaylı)

| # | Tutarsızlık | Çözüm Önerisi |
|---|------------|---------------|
| 1 | Lag 3-10 gün vs tahmin penceresi 3-7 gün | Lag dağılımını tarihsel veriyle analiz et, tahmin penceresini kalibre et |
| 2 | 4 segment hedef vs 4 hafta MVP | İlk versiyonda tek segment (B2B Lojistik) |
| 3 | "Tahmin destek aracı" vs "alarm sistemi" | "Erken uyarı sistemi" olarak netleştir |
| 4 | Sınıflandırma + Regresyon çelişki durumu | Arbitraj mekanizması: sınıflandırma kapı, regresyon detay |

---

## 5. Rapora Eklenmesi Gereken Kritik Bileşenler

### Heyet Tarafından Eklenen Yeni Başlıklar

**5.1 Karar Motoru — Geliştirilmiş Versiyon (Codex + Claude)**
```
Dual-Model Mimarisi:
├── Kısa Vade Nowcast (1-3 gün): Acil alarm
│   └── Tetikleyici: Zam olasılığı > %65 + CIF 5g artış > %4 + kur pozitif
├── Orta Vade Trend (1-4 hafta): Planlama sinyali
│   └── Tetikleyici: CIF 14g trend + kur 7g trend + mevsimsel patern
└── ÖTV Policy-Change Detector: Manuel flag
    └── ÖTV değişikliğinden sonra 1-2 hafta "düşük güvenilirlik" etiketi
```

**5.2 Doğruluk ve Güven Politikası (Claude önerisi, heyet onaylı)**
- Tahmin güven aralığı %70'in altındaysa yayınlama
- "Zam kesin" yerine "zam olasılığı yüksek" dili kullan
- Her tahmine geçmiş doğruluk oranı ekle ("Son 30 günde %78 doğruluk")
- Yanlış tahmin sonrası şeffaf analiz yayınla

**5.3 Monetizasyon Stratejisi (Gemini + Claude)**

| Katman | Kitle | Fiyat | Özellikler |
|--------|-------|-------|-----------|
| Premium | B2C | ₺49-99/ay | Günlük alarm, aksiyon önerisi |
| API Standart | B2B | ₺500-2.000/ay | REST API, günlük sinyal |
| Enterprise | B2B | ₺5.000+/ay | Özel dashboard, SLA, dedike destek |
| Veri Analitik | B2B | Proje bazlı | Özel rapor, danışmanlık |

**5.4 Proxy Veri Stratejisi (Gemini önerisi, heyet onaylı)**

CIF Med lisans maliyetini ertelemek için başlangıç proxy modeli:
1. **Brent petrol fiyatı** (ücretsiz, günlük)
2. **USD/TRY kuru** (TCMB, ücretsiz)
3. **Tarihsel Brent↔CIF Med korelasyonu** (tek seferlik hesaplanır)
4. **EPDK duyuru scraping** (pompa fiyat güncellemeleri)
5. **Resmi Gazete scraping** (ÖTV değişiklikleri) 

Gölge modda (shadow mode) 2-4 hafta çalıştırılarak proxy doğruluğu test edilir. Kabul edilebilir seviyedeyse lisans maliyeti ertelenebilir.

**Proje Sahibi Notu — Mevcut Altyapı:** Sunucuda halihazırda çalışır durumda bir proxy havuzu bulunmaktadır. Scraping operasyonları bu mevcut proxy altyapısı üzerinden yürütülecektir. Ek proxy maliyeti öngörülmemektedir.

**5.5 Konumlandırma (Heyet Uzlaşısı)**

| Yanlış | Doğru |
|--------|-------|
| "Akaryakıt fiyat tahmini" | "Akaryakıt Erken Uyarı ve Maliyet Optimizasyon Sistemi" |
| "Tahmin destek aracı" | "B2B: Risk yönetim platformu / B2C: Tasarruf asistanı" |
| Dashboard son kullanıcıya açık | Bot (B2C) + Admin Dashboard (yönetim) + API (B2B) odaklı |
| Kesin fiyat tahmini algısı | Olasılık + aksiyon önerisi |

**5.6 Go-to-Market Stratejisi (Gemini + Claude)**
1. **Faz 1 (Ay 1-2):** Gölge modda model doğruluk testi + hukuki danışmanlık
2. **Faz 2 (Ay 2-3):** Telegram botu + admin dashboard lansmanı (B2C premium), 1000 abone hedefi
3. **Faz 3 (Ay 3-4):** 5-10 lojistik firma ile ücretsiz B2B pilot, ROI ölçümü
4. **Faz 4 (Ay 4-6):** Ödeme sistemi aktif, B2B API satışı başlat

**5.7 Etik ve Toplumsal Etki Değerlendirmesi (Claude)**
- Zam öngörüsü panik alıma yol açabilir → "Zam kesin" dili yasaklı
- İstasyonlarda kuyruk riski → Tahmini geniş zaman aralığında paylaş (spesifik gün belirtme)
- Yanlış tahminlerin ekonomik zarar potansiyeli → Sorumluluk sınırları ve disclaimer zorunlu

---

## 6. Operasyonel Fizibilite Özeti (Codex, heyet onaylı)

| Başlık | Fizibilite | Effort | Risk |
|--------|-----------|--------|------|
| Teknik mimari (Python+XGBoost) | Uygulanabilir | M | Düşük |
| Veri pipeline | Koşullu | M-L | Orta |
| Altyapı | Uygulanabilir | S-M | Düşük |
| Veri kaynağı | Riskli | L | Yüksek |
| Monitoring/drift | Koşullu | M | Orta |
| Otomasyon | Koşullu | M | Orta |

**Minimum ekip:** 1 Veri/ML mühendisi + 1 Full-stack + hukuk danışmanı (dış kaynak)
**Aylık işletme:** $20-120 (veri lisansı hariç) — proxy veri ile başlanırsa $20-50

---

## 7. Nihai Skor ve Tavsiye

### Heyet Skoru

| Boyut | Claude | Gemini | Codex | Uzlaşı |
|-------|--------|--------|-------|--------|
| Vizyon netliği | 7/10 | 7/10 | 7/10 | **7/10** |
| Teknik fizibilite | 8/10 | 8/10 | 8/10 | **8/10** |
| Pazar potansiyeli | 7/10 | 8/10 | 7/10 | **7.5/10** |
| Rekabet durumu | 4/10 | 5/10 | 4/10 | **4.3/10** |
| İş modeli olgunluğu | 2/10 | 3/10 | 3/10 | **2.7/10** |
| Risk yönetimi | 3/10 | 4/10 | 4/10 | **3.7/10** |
| Yol haritası gerçekçiliği | 6/10 | 6/10 | 6/10 | **6/10** |
| **GENEL** | **5.4** | **5.9** | **5.6** | **5.6/10** |

### Nihai Tavsiye

**PROJE İLERLEMELİ — ancak 3 önkoşul tamamlanmadan geliştirmeye başlanmamalı:**

1. **[BLOCKER] Yasal danışmanlık** — EPDK mevzuatı ve Rekabet Kurumu perspektifinden hukuki görüş. Bu bir proje durdurucusu olabilir.

2. **[BLOCKER] Veri stratejisi doğrulaması** — Proxy veri modeli (Brent + kur + korelasyon) ile gölge modda 2-4 hafta test. CIF Med lisansı gerekiyorsa maliyet-gelir analizi.

3. **[BLOCKER] Gelir modeli doğrulaması** — 10 potansiyel B2B müşterisi (lojistik firma) ile görüşme. "Bu hizmete ₺X/ay öder misiniz?" sorusuna cevap aranmalı.

**Bu 3 önkoşul tamamlandıktan sonra:** Faz 1 (PoC) → gölge modda model testi → Faz 2 (MVP) → Telegram botu lansmanı

---

## Heyet İmzaları

| Üye | Model | Rol | Onay |
|-----|-------|-----|------|
| Claude Stratejik Planlayıcı | Claude Opus | Derin muhakeme, risk analizi | ✅ Onaylı |
| Gemini Ürün Yöneticisi | Gemini 3 | Pazar analizi, ürün stratejisi | ✅ Onaylı |
| Codex Operasyonel Planlayıcı | Codex GPT-5.2 | Operasyonel fizibilite | ✅ Onaylı |

**Rapor Tarihi:** 2026-02-15
**Yöntem:** Delphi İteratif Yakınsama — 2 Tur
**Uzlaşı:** Kısmi (kalan ayrışmalar tercih seviyesinde, kritik değil)
