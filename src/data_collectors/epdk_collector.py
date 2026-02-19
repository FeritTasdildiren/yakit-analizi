"""
EPDK Pompa Fiyatı Veri Çekme Servisi

Üç veri kaynağı desteklenir (fallback zinciri):

1. **PETROL OFİSİ WEB SCRAPING** (birincil — en güvenilir):
   URL: https://www.petrolofisi.com.tr/akaryakit-fiyatlari
   Method: GET + HTML table parse
   Avantaj: Sunucu IP'sinden erişilebilir, basit HTML tablo yapısı,
            tüm iller tek sayfada, benzin + motorin + LPG hepsi mevcut

2. **BİLDİRİM PORTALI** (ikincil — WAF bypass):
   URL: https://bildirim.epdk.gov.tr/bildirim-portal/faces/pages/tarife/petrol/
        illereGorePetrolAkaryakitFiyatSorgula.xhtml
   Method: JSF AJAX POST (ViewState + form parametreleri)
   Not: JSF form field ID'leri değişebilir, kırılgan

3. **EPDK XML Web Servisi** (son çare):
   URL: https://www.epdk.gov.tr/Detay/DownloadXMLData
   Method: GET
   Params: sorguNo=72, parametre={il_trafik_kodu}
   Not: Sunucu IP'si WAF tarafından 418 ile engelleniyor, yerel ortamda çalışır

Tüm fiyatlar Decimal tipinde tutulur (float KULLANILMAZ).
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────────────

EPDK_BASE_URL: Final[str] = "https://www.epdk.gov.tr/Detay/DownloadXMLData"
EPDK_SORGU_NO: Final[str] = "72"
EPDK_TIMEOUT_SECONDS: Final[int] = 60
EPDK_MAX_RETRIES: Final[int] = 3
EPDK_BACKOFF_BASE: Final[float] = 2.0

# Bildirim portal sabitleri
BILDIRIM_BASE_URL: Final[str] = (
    "https://bildirim.epdk.gov.tr/bildirim-portal/faces/pages/"
    "tarife/petrol/illereGorePetrolAkaryakitFiyatSorgula.xhtml"
)
BILDIRIM_LPG_URL: Final[str] = (
    "https://bildirim.epdk.gov.tr/bildirim-portal/faces/pages/"
    "tarife/lpg/illereGoreLPGFiyatSorgula.xhtml"
)

# Türkiye ortalaması hesaplamak için büyük 5 il
BUYUK_5_IL: Final[dict[str, str]] = {
    "34": "İSTANBUL",
    "06": "ANKARA",
    "35": "İZMİR",
    "16": "BURSA",
    "07": "ANTALYA",
}

# İl trafik kodu → Bildirim portal il adı eşleştirmesi
# Bildirim portalda İstanbul ikiye ayrılmış: ANADOLU ve AVRUPA
IL_KODU_TO_BILDIRIM: Final[dict[str, list[str]]] = {
    "34": ["İSTANBUL (ANADOLU)", "İSTANBUL (AVRUPA)"],
    "06": ["ANKARA"],
    "35": ["İZMİR"],
    "16": ["BURSA"],
    "07": ["ANTALYA"],
}

# Bildirim portal ürün adı → bizim yakıt tipi eşleştirmesi
BILDIRIM_PRODUCT_MAP: Final[dict[str, str]] = {
    "Kurşunsuz Benzin 95 Oktan": "benzin",
    "Motorin": "motorin",
}

YAKIT_TIPLERI: Final[list[str]] = ["benzin", "motorin", "lpg"]

# ── Petrol Ofisi Sabitleri ─────────────────────────────────────────────────
PETROL_OFISI_URL: Final[str] = "https://www.petrolofisi.com.tr/akaryakit-fiyatlari"

# PO şehir adı → il trafik kodu eşleştirmesi
# İstanbul Avrupa + Anadolu olarak ikiye ayrılmış, ortalaması alınır
PO_NAME_TO_IL: Final[dict[str, str]] = {
    "ISTANBUL (AVRUPA)": "34",
    "ISTANBUL (ANADOLU)": "34",
    "ANKARA": "06",
    "IZMIR": "35",
    "BURSA": "16",
    "ANTALYA": "07",
}

# Tarayıcı benzeri HTTP başlıkları
BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ── Pydantic Modeller ────────────────────────────────────────────────────────


class EPDKRecord(BaseModel):
    """Tek bir dağıtıcı kaydını temsil eder (XML'deki <Table> elemanı)."""

    il_kodu: str
    il_adi: str
    dagitici: str
    benzin_fiyat: Decimal | None = None
    motorin_fiyat: Decimal | None = None
    lpg_fiyat: Decimal | None = None
    tarih: date


class BildirimRecord(BaseModel):
    """Bildirim portalından alınan tek bir fiyat kaydı."""

    tarih: date
    il_adi: str
    dagitici: str
    urun: str
    fiyat: Decimal


class PumpPriceData(BaseModel):
    """İl bazlı ortalama pompa fiyatı verisi."""

    trade_date: date
    fuel_type: str = Field(description="benzin | motorin | lpg")
    pump_price_tl_lt: Decimal
    source: str = "petrol_ofisi"
    il_kodu: str | None = None
    dagitici_sayisi: int


# ── Yardımcı Fonksiyonlar ───────────────────────────────────────────────────


def _parse_decimal(raw: str | None) -> Decimal | None:
    """
    Türkçe formatlı sayıyı Decimal'e dönüştürür.
    Virgüllü sayı dönüşümü: '43,72' → Decimal('43.72')
    Noktalı sayı: '43.72' → Decimal('43.72')
    Boş veya geçersiz değerler için None döner.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw or raw == "-":
        return None
    try:
        # Virgüllü sayı dönüşümü
        normalized = raw.replace(",", ".")
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        logger.warning("Geçersiz sayı değeri: '%s'", raw)
        return None


def _parse_date(raw: str | None) -> date:
    """
    EPDK tarih formatını parse eder.
    Beklenen format: '15.02.2026' (dd.MM.yyyy)
    """
    if raw is None:
        return date.today()
    raw = raw.strip()
    if not raw:
        return date.today()
    try:
        return datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        logger.warning("Geçersiz tarih formatı: '%s', bugünün tarihi kullanılıyor.", raw)
        return date.today()


def _calculate_average(values: list[Decimal]) -> Decimal:
    """Decimal listesinin ortalamasını hesaplar (2 ondalık hane)."""
    if not values:
        return Decimal("0.00")
    total = sum(values)
    avg = total / len(values)
    return avg.quantize(Decimal("0.01"))


# ── Petrol Ofisi Web Scraping (Birincil Kaynak) ──────────────────────────────


async def _fetch_petrol_ofisi_all_cities() -> dict[str, dict[str, Decimal | None]]:
    """
    Petrol Ofisi'nin akaryakıt fiyatları sayfasından tüm illerin fiyatlarını çeker.

    Petrol Ofisi, tek bir HTML sayfasında tüm illerin fiyatlarını tablo olarak sunar.
    Her satırda: Şehir | Benzin 95 | Diesel | Gazyağı | Kalorifer | Fuel Oil | LPG

    Fiyatlar <span class="with-tax">XX.XX</span> formatında (KDV dahil pompa fiyatı).

    Returns:
        il_kodu → {benzin: Decimal, motorin: Decimal, lpg: Decimal} sözlüğü.
        İstanbul için Avrupa+Anadolu ortalaması alınır.
    """
    logger.info("Petrol Ofisi fiyat sayfası çekiliyor: %s", PETROL_OFISI_URL)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30),
        follow_redirects=True,
        headers=BROWSER_HEADERS,
    ) as client:
        response = await client.get(PETROL_OFISI_URL)
        response.raise_for_status()

    content = response.text
    logger.info(
        "Petrol Ofisi yanıt alındı: status=%d, boyut=%d byte",
        response.status_code,
        len(content),
    )

    # HTML tablo satırlarını parse et
    # <tr ... data-disctrict-name="CITYNAME"> ... <td>...<span class="with-tax">PRICE</span>...</td> ...
    row_pattern = re.compile(
        r'<tr[^>]*data-disctrict-name="([^"]*)"[^>]*>(.*?)</tr>',
        re.DOTALL | re.IGNORECASE,
    )
    td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
    tax_pattern = re.compile(r'<span\s+class="with-tax">([^<]+)</span>', re.IGNORECASE)

    results: dict[str, dict[str, Decimal | None]] = {}

    for row_match in row_pattern.finditer(content):
        city_name = row_match.group(1).strip()
        row_html = row_match.group(2)

        # Sadece hedef illeri al
        il_kodu = PO_NAME_TO_IL.get(city_name)
        if il_kodu is None:
            continue

        # Her <td> hücresinden with-tax fiyatını çıkar
        cells = td_pattern.findall(row_html)
        prices: list[Decimal | None] = []
        for cell in cells:
            tax_match = tax_pattern.search(cell)
            if tax_match:
                prices.append(_parse_decimal(tax_match.group(1)))
            else:
                prices.append(None)

        # Tablo yapısı: [0]=Şehir, [1]=Benzin95, [2]=Diesel, [3]=Gazyağı,
        #               [4]=Kalorifer, [5]=FuelOil, [6]=LPG
        if len(prices) < 7:
            logger.warning(
                "PO satırında yetersiz hücre: city=%s, cells=%d", city_name, len(prices)
            )
            continue

        record = {
            "benzin": prices[1],
            "motorin": prices[2],
            "lpg": prices[6],
        }

        if il_kodu in results:
            # İstanbul: Avrupa + Anadolu ortalaması
            existing = results[il_kodu]
            for fuel in ("benzin", "motorin", "lpg"):
                if existing[fuel] is not None and record[fuel] is not None:
                    existing[fuel] = (
                        (existing[fuel] + record[fuel]) / 2
                    ).quantize(Decimal("0.01"))
                elif record[fuel] is not None:
                    existing[fuel] = record[fuel]
        else:
            results[il_kodu] = record

    logger.info("Petrol Ofisi parse tamamlandı: %d il verisi alındı.", len(results))
    return results


async def _fetch_petrol_ofisi_turkey_average() -> dict[str, Decimal]:
    """
    Petrol Ofisi üzerinden Türkiye ortalaması pompa fiyatlarını hesaplar.

    Büyük 5 il (İstanbul, Ankara, İzmir, Bursa, Antalya) fiyatlarından
    basit ortalama ile Türkiye ortalaması döndürülür.

    Returns:
        Yakıt tipi → ortalama fiyat sözlüğü.
        Örnek: {'benzin': Decimal('58.07'), 'motorin': Decimal('58.93'), 'lpg': Decimal('30.06')}
    """
    city_prices = await _fetch_petrol_ofisi_all_cities()

    if not city_prices:
        logger.warning("Petrol Ofisi'nden hiç il verisi alınamadı.")
        return {}

    averages: dict[str, Decimal] = {}
    for fuel_type in YAKIT_TIPLERI:
        prices = [
            city_prices[il_kodu][fuel_type]
            for il_kodu in BUYUK_5_IL
            if il_kodu in city_prices and city_prices[il_kodu].get(fuel_type) is not None
        ]
        if prices:
            averages[fuel_type] = _calculate_average(prices)
            logger.info(
                "PO Türkiye ortalaması [%s]: %s TL/lt (%d il)",
                fuel_type,
                averages[fuel_type],
                len(prices),
            )

    return averages


async def _fetch_petrol_ofisi_il(
    il_kodu: str,
    tarih: date | None = None,
) -> list[PumpPriceData]:
    """
    Petrol Ofisi üzerinden belirtilen il için pompa fiyatlarını çeker.

    Not: Petrol Ofisi sadece güncel fiyatları sunar, tarih filtresi yok.
    Geçmiş tarih istendiğinde boş dönüşür.

    Args:
        il_kodu: İl trafik kodu.
        tarih: İstenen tarih. Bugünden farklıysa boş dönüşür.

    Returns:
        PumpPriceData listesi.
    """
    # Petrol Ofisi sadece güncel fiyat sunar
    if tarih is not None and tarih != date.today():
        logger.info(
            "PO geçmiş tarih desteklemiyor: tarih=%s, bugün=%s", tarih, date.today()
        )
        return []

    target_date = tarih or date.today()

    try:
        city_prices = await _fetch_petrol_ofisi_all_cities()
    except Exception:
        logger.warning("Petrol Ofisi erişilemedi.", exc_info=True)
        return []

    if il_kodu not in city_prices:
        logger.warning("PO'da il %s verisi bulunamadı.", il_kodu)
        return []

    prices = city_prices[il_kodu]
    results: list[PumpPriceData] = []

    for fuel_type in YAKIT_TIPLERI:
        price = prices.get(fuel_type)
        if price is not None:
            results.append(
                PumpPriceData(
                    trade_date=target_date,
                    fuel_type=fuel_type,
                    pump_price_tl_lt=price,
                    source="petrol_ofisi",
                    il_kodu=il_kodu,
                    dagitici_sayisi=1,  # Tek dağıtıcı: Petrol Ofisi
                )
            )

    return results


# ── Bildirim Portal (İkincil Kaynak) ────────────────────────────────────────


def _extract_viewstate(html: str) -> str | None:
    """JSF ViewState token'ını HTML'den çıkarır."""
    pattern = r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"'
    match = re.search(pattern, html)
    if match:
        return match.group(1)

    # Alternatif pattern
    pattern2 = r'id="j_id1:javax\.faces\.ViewState:\d+"\s+value="([^"]+)"'
    match2 = re.search(pattern2, html)
    if match2:
        return match2.group(1)

    return None


def _parse_bildirim_response(response_text: str) -> list[BildirimRecord]:
    """
    Bildirim portal AJAX yanıtından fiyat kayıtlarını çıkarır.

    JSF partial response CDATA bloklarından <td> hücrelerini parse eder.
    Her kayıt: tarih, il, dağıtıcı, ürün, fiyat (5 hücre).
    """
    records: list[BildirimRecord] = []

    # CDATA bloklarını çıkar
    cdata_blocks = re.findall(r"<!\[CDATA\[(.*?)\]\]>", response_text, re.DOTALL)

    for cdata in cdata_blocks:
        # <td> hücrelerini çıkar
        tds = re.findall(r"<td[^>]*>(.*?)</td>", cdata, re.DOTALL)
        clean_cells: list[str] = []
        for td in tds:
            clean = re.sub(r"<[^>]+>", "", td).strip()
            # Form elemanlarını ve PrimeFaces widget'larını filtrele
            if (
                clean
                and not clean.startswith("PrimeFaces")
                and not clean.startswith("Tümü")
                and "Başlangıç" not in clean
                and "Bitiş" not in clean
                and "Marka:" not in clean
                and "Bölge:" not in clean
                and "Yakıt Tipi:" not in clean
                and len(clean) < 200
            ):
                clean_cells.append(clean)

        # Kayıtları parse et: tarih, il, dağıtıcı, ürün, fiyat
        date_pattern = re.compile(r"\d{2}\.\d{2}\.\d{4}")
        i = 0
        while i < len(clean_cells):
            if date_pattern.match(clean_cells[i]) and i + 4 < len(clean_cells):
                try:
                    fiyat = _parse_decimal(clean_cells[i + 4])
                    if fiyat is not None:
                        records.append(
                            BildirimRecord(
                                tarih=_parse_date(clean_cells[i]),
                                il_adi=clean_cells[i + 1].strip(),
                                dagitici=clean_cells[i + 2].strip().upper(),
                                urun=clean_cells[i + 3].strip(),
                                fiyat=fiyat,
                            )
                        )
                    i += 5
                    continue
                except Exception:
                    logger.debug("Bildirim kayıt parse hatası, indeks %d", i)
            i += 1

    return records


async def _fetch_bildirim_page(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[str, str | None]:
    """
    Bildirim portal sayfasını yükler ve ViewState token'ı çıkarır.

    Returns:
        (html_content, viewstate) tuple'ı.
    """
    response = await client.get(url)
    response.raise_for_status()
    viewstate = _extract_viewstate(response.text)
    return response.text, viewstate


async def _query_bildirim_petrol(
    client: httpx.AsyncClient,
    viewstate: str,
    il_adi: str,
    urun: str,
    tarih_str: str,
) -> list[BildirimRecord]:
    """
    Bildirim portal petrol akaryakıt fiyat sorgusunu çalıştırır.

    Args:
        client: HTTP client (cookie'leri paylaşır).
        viewstate: JSF ViewState token.
        il_adi: İl adı (Bildirim portal formatında, ör: "İSTANBUL (AVRUPA)").
        urun: Ürün adı (ör: "Kurşunsuz Benzin 95 Oktan", "Motorin").
        tarih_str: Tarih string (dd.MM.yyyy formatında).

    Returns:
        BildirimRecord listesi.
    """
    form_data = {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": "akarYakitFiyatlariKriterleriForm:j_idt49",
        "javax.faces.partial.execute": "@all",
        "javax.faces.partial.render": (
            "akaryakitSorguSonucu messages akarYakitFiyatlariKriterleriForm"
        ),
        "akarYakitFiyatlariKriterleriForm:j_idt49": (
            "akarYakitFiyatlariKriterleriForm:j_idt49"
        ),
        "akarYakitFiyatlariKriterleriForm": "akarYakitFiyatlariKriterleriForm",
        "akarYakitFiyatlariKriterleriForm:j_idt29_input": tarih_str,
        "akarYakitFiyatlariKriterleriForm:j_idt32_focus": "",
        "akarYakitFiyatlariKriterleriForm:j_idt32_input": "Tümü",
        "akarYakitFiyatlariKriterleriForm:j_idt36_input": tarih_str,
        "akarYakitFiyatlariKriterleriForm:j_idt39_focus": "",
        "akarYakitFiyatlariKriterleriForm:j_idt39_input": il_adi,
        "akarYakitFiyatlariKriterleriForm:j_idt46_focus": "",
        "akarYakitFiyatlariKriterleriForm:j_idt46_input": urun,
        "javax.faces.ViewState": viewstate,
    }

    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BILDIRIM_BASE_URL,
        "Origin": "https://bildirim.epdk.gov.tr",
    }

    response = await client.post(BILDIRIM_BASE_URL, data=form_data, headers=post_headers)
    response.raise_for_status()

    records = _parse_bildirim_response(response.text)
    logger.info(
        "Bildirim portal sorgusu: il=%s, urun=%s, tarih=%s → %d kayıt",
        il_adi,
        urun,
        tarih_str,
        len(records),
    )
    return records


async def _fetch_bildirim_petrol_prices(
    il_kodu: str,
    tarih: date | None = None,
) -> list[PumpPriceData]:
    """
    Bildirim portal üzerinden belirtilen il için benzin ve motorin fiyatlarını çeker.

    Args:
        il_kodu: İl trafik kodu (ör: '34', '06').
        tarih: İstenen tarih. None ise bugün kullanılır.

    Returns:
        PumpPriceData listesi (benzin + motorin).
    """
    target_date = tarih or date.today()
    tarih_str = target_date.strftime("%d.%m.%Y")
    il_names = IL_KODU_TO_BILDIRIM.get(il_kodu, [])

    if not il_names:
        logger.warning("İl kodu %s için bildirim portal eşleştirmesi yok.", il_kodu)
        return []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(EPDK_TIMEOUT_SECONDS),
        follow_redirects=True,
        headers=BROWSER_HEADERS,
    ) as client:
        # ViewState al
        _, viewstate = await _fetch_bildirim_page(client, BILDIRIM_BASE_URL)
        if not viewstate:
            logger.error("Bildirim portal ViewState alınamadı.")
            return []

        # Her il adı ve her ürün için sorgu yap
        all_records: list[BildirimRecord] = []

        for il_adi in il_names:
            for urun in BILDIRIM_PRODUCT_MAP:
                try:
                    records = await _query_bildirim_petrol(
                        client, viewstate, il_adi, urun, tarih_str
                    )
                    all_records.extend(records)

                    # Yeni ViewState al (JSF her yanıtta günceller)
                    # Sayfayı yeniden yükle
                    _, viewstate = await _fetch_bildirim_page(client, BILDIRIM_BASE_URL)
                    if not viewstate:
                        logger.warning("ViewState yenilemesi başarısız, mevcut devam.")
                except Exception:
                    logger.exception(
                        "Bildirim sorgusu başarısız: il=%s, urun=%s",
                        il_adi,
                        urun,
                    )

    # Kayıtları PumpPriceData'ya dönüştür
    fuel_prices: dict[str, list[Decimal]] = {"benzin": [], "motorin": []}

    for rec in all_records:
        fuel_type = BILDIRIM_PRODUCT_MAP.get(rec.urun)
        if fuel_type and fuel_type in fuel_prices:
            fuel_prices[fuel_type].append(rec.fiyat)

    results: list[PumpPriceData] = []
    for fuel_type, prices in fuel_prices.items():
        if prices:
            avg_price = _calculate_average(prices)
            results.append(
                PumpPriceData(
                    trade_date=target_date,
                    fuel_type=fuel_type,
                    pump_price_tl_lt=avg_price,
                    source="epdk_bildirim",
                    il_kodu=il_kodu,
                    dagitici_sayisi=len(prices),
                )
            )

    logger.info(
        "Bildirim portal il %s: %d yakıt tipi, %d toplam kayıt",
        il_kodu,
        len(results),
        len(all_records),
    )
    return results


# ── LPG Bildirim Portal ─────────────────────────────────────────────────────

# LPG form sabitleri (petrolden farklı form yapısı)
LPG_FORM_ID: Final[str] = "lpgFiyatlariKriterleriForm"
LPG_BUTTON_ID: Final[str] = "lpgFiyatlariKriterleriForm:j_idt46"
LPG_RENDER_TARGET: Final[str] = (
    "akaryakitSorguSonucu messages lpgFiyatlariKriterleriForm"
)


def _parse_lpg_response(response_text: str) -> list[BildirimRecord]:
    """
    LPG bildirim portal AJAX yanıtından fiyat kayıtlarını çıkarır.

    LPG tablosu kolon sırası (petrolden farklı):
        İl Adı, Firma Adı, Yakıt Tipi, Fiyat, Geçerlilik Tarihi
    """
    records: list[BildirimRecord] = []
    cdata_blocks = re.findall(r"<!\[CDATA\[(.*?)\]\]>", response_text, re.DOTALL)

    for cdata in cdata_blocks:
        if "data-ri" not in cdata:
            continue

        tds = re.findall(r"<td[^>]*>(.*?)</td>", cdata, re.DOTALL)
        clean_cells: list[str] = []
        for td in tds:
            clean = re.sub(r"<[^>]+>", "", td).strip()
            if clean and not clean.startswith("PrimeFaces") and len(clean) < 200:
                clean_cells.append(clean)

        # LPG: her 5 hücre = il, dagitici, urun, fiyat, tarih
        date_pattern = re.compile(r"\d{2}\.\d{2}\.\d{4}")
        i = 0
        while i + 4 < len(clean_cells):
            if date_pattern.match(clean_cells[i + 4]):
                try:
                    fiyat = _parse_decimal(clean_cells[i + 3])
                    if fiyat is not None:
                        records.append(
                            BildirimRecord(
                                tarih=_parse_date(clean_cells[i + 4]),
                                il_adi=clean_cells[i].strip(),
                                dagitici=clean_cells[i + 1].strip().upper(),
                                urun=clean_cells[i + 2].strip(),
                                fiyat=fiyat,
                            )
                        )
                    i += 5
                    continue
                except Exception:
                    logger.debug("LPG kayıt parse hatası, indeks %d", i)
            i += 1

    return records


async def _query_bildirim_lpg(
    client: httpx.AsyncClient,
    viewstate: str,
    il_adi: str,
    tarih_str: str,
) -> list[BildirimRecord]:
    """LPG bildirim portal sorgusunu çalıştırır."""
    form_data = {
        "javax.faces.partial.ajax": "true",
        "javax.faces.source": LPG_BUTTON_ID,
        "javax.faces.partial.execute": "@all",
        "javax.faces.partial.render": LPG_RENDER_TARGET,
        LPG_BUTTON_ID: LPG_BUTTON_ID,
        LPG_FORM_ID: LPG_FORM_ID,
        f"{LPG_FORM_ID}:j_idt29_input": tarih_str,
        f"{LPG_FORM_ID}:j_idt31_input": tarih_str,
        f"{LPG_FORM_ID}:j_idt34_focus": "",
        f"{LPG_FORM_ID}:j_idt34_input": "Tümü",
        f"{LPG_FORM_ID}:j_idt38_focus": "",
        f"{LPG_FORM_ID}:j_idt38_input": il_adi,
        f"{LPG_FORM_ID}:j_idt43_focus": "",
        f"{LPG_FORM_ID}:j_idt43_input": "Otogaz",
        "javax.faces.ViewState": viewstate,
    }

    post_headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Faces-Request": "partial/ajax",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BILDIRIM_LPG_URL,
        "Origin": "https://bildirim.epdk.gov.tr",
    }

    response = await client.post(BILDIRIM_LPG_URL, data=form_data, headers=post_headers)
    response.raise_for_status()

    records = _parse_lpg_response(response.text)
    logger.info(
        "LPG bildirim sorgusu: il=%s, tarih=%s → %d kayıt",
        il_adi,
        tarih_str,
        len(records),
    )
    return records


async def _fetch_bildirim_lpg_prices(
    il_kodu: str,
    tarih: date | None = None,
) -> list[PumpPriceData]:
    """
    Bildirim portal üzerinden LPG (Otogaz) fiyatlarını çeker.

    LPG verileri bazen 1 gün gecikmeli olabilir. Eğer istenen tarihte
    veri yoksa bir önceki gün denenir.
    """
    from datetime import timedelta

    target_date = tarih or date.today()
    il_names = IL_KODU_TO_BILDIRIM.get(il_kodu, [])

    if not il_names:
        return []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(EPDK_TIMEOUT_SECONDS),
        follow_redirects=True,
        headers=BROWSER_HEADERS,
    ) as client:
        try:
            page_resp = await client.get(BILDIRIM_LPG_URL)
            page_resp.raise_for_status()
        except Exception:
            logger.exception("LPG bildirim sayfası yüklenemedi.")
            return []

        viewstate = _extract_viewstate(page_resp.text)
        if not viewstate:
            logger.error("LPG bildirim portal ViewState alınamadı.")
            return []

        all_records: list[BildirimRecord] = []
        dates_to_try = [target_date, target_date - timedelta(days=1)]

        for try_date in dates_to_try:
            tarih_str = try_date.strftime("%d.%m.%Y")

            for il_adi in il_names:
                try:
                    records = await _query_bildirim_lpg(
                        client, viewstate, il_adi, tarih_str
                    )
                    all_records.extend(records)

                    page_resp = await client.get(BILDIRIM_LPG_URL)
                    viewstate = _extract_viewstate(page_resp.text) or viewstate
                except Exception:
                    logger.exception(
                        "LPG bildirim sorgusu başarısız: il=%s, tarih=%s",
                        il_adi,
                        tarih_str,
                    )

            if all_records:
                logger.info(
                    "LPG bildirim il %s: %d kayıt (tarih: %s)",
                    il_kodu,
                    len(all_records),
                    tarih_str,
                )
                break

    lpg_prices: list[Decimal] = [rec.fiyat for rec in all_records if rec.fiyat]

    if lpg_prices:
        avg = _calculate_average(lpg_prices)
        return [
            PumpPriceData(
                trade_date=target_date,
                fuel_type="lpg",
                pump_price_tl_lt=avg,
                source="epdk_bildirim_lpg",
                il_kodu=il_kodu,
                dagitici_sayisi=len(lpg_prices),
            )
        ]

    return []


# ── XML Parse (Yedek Kaynak) ────────────────────────────────────────────────


def parse_epdk_xml(xml_content: str) -> list[EPDKRecord]:
    """
    EPDK XML yanıtını parse ederek EPDKRecord listesine dönüştürür.

    Beklenen XML yapısı:
        <NewDataSet>
          <Table>
            <IL_KODU>34</IL_KODU>
            <IL_ADI>İSTANBUL</IL_ADI>
            <DAGITICI>SHELL</DAGITICI>
            <BENZIN>43,72</BENZIN>
            <MOTORIN>41,85</MOTORIN>
            <LPG>18,50</LPG>
            <TARIH>15.02.2026</TARIH>
          </Table>
          ...
        </NewDataSet>

    Args:
        xml_content: EPDK'dan dönen ham XML string.

    Returns:
        Parse edilmiş EPDKRecord listesi.
    """
    records: list[EPDKRecord] = []

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        logger.error("XML parse hatası: %s", exc)
        return records

    for table_elem in root.findall(".//Table"):
        try:
            il_kodu_elem = table_elem.find("IL_KODU")
            il_adi_elem = table_elem.find("IL_ADI")
            dagitici_elem = table_elem.find("DAGITICI")
            tarih_elem = table_elem.find("TARIH")
            benzin_elem = table_elem.find("BENZIN")
            motorin_elem = table_elem.find("MOTORIN")
            lpg_elem = table_elem.find("LPG")

            il_kodu = (
                il_kodu_elem.text.strip()
                if il_kodu_elem is not None and il_kodu_elem.text
                else ""
            )
            il_adi = (
                il_adi_elem.text.strip()
                if il_adi_elem is not None and il_adi_elem.text
                else ""
            )
            dagitici_raw = (
                dagitici_elem.text.strip()
                if dagitici_elem is not None and dagitici_elem.text
                else ""
            )
            tarih_raw = tarih_elem.text if tarih_elem is not None else None

            if not il_kodu or not dagitici_raw:
                logger.warning(
                    "Eksik alan: il_kodu='%s', dagitici='%s' — kayıt atlanıyor.",
                    il_kodu,
                    dagitici_raw,
                )
                continue

            # Dağıtıcı adını normalize et (UPPER + STRIP)
            dagitici = dagitici_raw.upper().strip()

            record = EPDKRecord(
                il_kodu=il_kodu,
                il_adi=il_adi.upper().strip(),
                dagitici=dagitici,
                benzin_fiyat=_parse_decimal(
                    benzin_elem.text if benzin_elem is not None else None
                ),
                motorin_fiyat=_parse_decimal(
                    motorin_elem.text if motorin_elem is not None else None
                ),
                lpg_fiyat=_parse_decimal(
                    lpg_elem.text if lpg_elem is not None else None
                ),
                tarih=_parse_date(tarih_raw),
            )
            records.append(record)

        except Exception:
            logger.exception("Kayıt parse edilirken beklenmeyen hata, kayıt atlanıyor.")
            continue

    logger.info("EPDK XML parse tamamlandı: %d kayıt okundu.", len(records))
    return records


# ── Ortalama Hesaplama Yardımcıları ──────────────────────────────────────────


def _records_to_pump_prices(
    records: list[EPDKRecord],
    il_kodu: str | None = None,
) -> list[PumpPriceData]:
    """
    EPDKRecord listesinden yakıt tipi bazlı ortalama PumpPriceData listesi üretir.

    Dağıtıcı bazlı fiyatları toplayıp il ortalaması hesaplar.
    Her yakıt tipi (benzin, motorin, lpg) için ayrı PumpPriceData döndürür.
    """
    if not records:
        return []

    # Tarih: İlk kaydın tarihini referans al
    reference_date = records[0].tarih
    effective_il_kodu = il_kodu or records[0].il_kodu

    results: list[PumpPriceData] = []

    # Yakıt tipi → fiyat listesi
    fuel_map: dict[str, list[Decimal]] = {
        "benzin": [],
        "motorin": [],
        "lpg": [],
    }

    for rec in records:
        if rec.benzin_fiyat is not None:
            fuel_map["benzin"].append(rec.benzin_fiyat)
        if rec.motorin_fiyat is not None:
            fuel_map["motorin"].append(rec.motorin_fiyat)
        if rec.lpg_fiyat is not None:
            fuel_map["lpg"].append(rec.lpg_fiyat)

    for fuel_type, prices in fuel_map.items():
        if not prices:
            logger.debug(
                "İl %s için %s fiyatı bulunamadı, atlanıyor.",
                effective_il_kodu,
                fuel_type,
            )
            continue

        avg_price = _calculate_average(prices)

        results.append(
            PumpPriceData(
                trade_date=reference_date,
                fuel_type=fuel_type,
                pump_price_tl_lt=avg_price,
                source="epdk_xml",
                il_kodu=effective_il_kodu,
                dagitici_sayisi=len(prices),
            )
        )

    return results


# ── HTTP İstekleri (Retry + Exponential Backoff) ─────────────────────────────


async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, str],
) -> str:
    """
    Verilen URL'e GET isteği atar. Başarısız olursa exponential backoff ile 3 kez dener.

    Args:
        client: httpx.AsyncClient örneği.
        url: Hedef URL.
        params: Query parametreleri.

    Returns:
        Yanıt body'si (string).

    Raises:
        httpx.HTTPStatusError: 3 denemeden sonra hala başarısız.
        httpx.RequestError: Bağlantı hatası.
    """
    last_exc: Exception | None = None

    for attempt in range(1, EPDK_MAX_RETRIES + 1):
        try:
            logger.info(
                "EPDK XML isteği gönderiliyor (deneme %d/%d): params=%s",
                attempt,
                EPDK_MAX_RETRIES,
                params,
            )
            response = await client.get(url, params=params)
            response.raise_for_status()
            logger.info(
                "EPDK XML yanıt alındı: status=%d, boyut=%d byte",
                response.status_code,
                len(response.content),
            )
            return response.text

        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < EPDK_MAX_RETRIES:
                wait_time = EPDK_BACKOFF_BASE ** attempt
                logger.warning(
                    "EPDK XML isteği başarısız (deneme %d/%d): %s — %.1f sn bekleniyor.",
                    attempt,
                    EPDK_MAX_RETRIES,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "EPDK XML isteği %d denemeden sonra başarısız: %s",
                    EPDK_MAX_RETRIES,
                    exc,
                )

    raise last_exc  # type: ignore[misc]


# ── Ana Fonksiyonlar ─────────────────────────────────────────────────────────


async def fetch_pump_prices(
    il_kodu: str,
    tarih: date | None = None,
) -> list[PumpPriceData]:
    """
    Belirtilen il için pompa fiyatlarını çeker.

    Fallback zinciri:
    1. Petrol Ofisi web scraping — güvenilir, WAF engeli yok
    2. Bildirim portal (JSF AJAX) — WAF engeli yok ama kırılgan
    3. EPDK XML Web Servisi — WAF engeli olabilir

    Args:
        il_kodu: İl trafik kodu (ör: '34' İstanbul, '06' Ankara).
        tarih: İstenen tarih. None ise güncel fiyatlar çekilir.

    Returns:
        Her yakıt tipi için ortalama PumpPriceData listesi.
    """
    logger.info("Pompa fiyatları çekiliyor: il_kodu=%s, tarih=%s", il_kodu, tarih)

    # ── Kaynak 1: Petrol Ofisi (benzin + motorin + lpg) ──
    try:
        po_results = await _fetch_petrol_ofisi_il(il_kodu, tarih)
        if po_results:
            logger.info(
                "Petrol Ofisi başarılı: il=%s, %d yakıt tipi",
                il_kodu,
                len(po_results),
            )
            return po_results
    except Exception:
        logger.warning(
            "Petrol Ofisi erişilemedi, bildirim portal deneniyor...",
            exc_info=True,
        )

    # ── Kaynak 2: Bildirim Portal (benzin + motorin) ──
    try:
        bildirim_results = await _fetch_bildirim_petrol_prices(il_kodu, tarih)
        if bildirim_results:
            logger.info(
                "Bildirim portal başarılı: il=%s, %d yakıt tipi",
                il_kodu,
                len(bildirim_results),
            )

            # LPG'yi de çekmeye çalış
            try:
                lpg_results = await _fetch_bildirim_lpg_prices(il_kodu, tarih)
                bildirim_results.extend(lpg_results)
            except Exception:
                logger.warning("LPG bildirim verisi alınamadı, devam ediliyor.")

            return bildirim_results
    except Exception:
        logger.warning(
            "Bildirim portal erişilemedi, XML fallback deneniyor...",
            exc_info=True,
        )

    # ── Kaynak 3: EPDK XML (Son Çare) ──
    logger.info("EPDK XML fallback: il_kodu=%s", il_kodu)

    params: dict[str, str] = {
        "sorguNo": EPDK_SORGU_NO,
        "parametre": il_kodu,
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(EPDK_TIMEOUT_SECONDS),
            follow_redirects=True,
            headers={
                "Accept": "application/xml",
                "Accept-Encoding": "gzip, deflate",
                "User-Agent": "YakitAnalizi/1.0",
            },
        ) as client:
            xml_content = await _fetch_with_retry(client, EPDK_BASE_URL, params)

        records = parse_epdk_xml(xml_content)

        if not records:
            logger.warning("EPDK XML'den il %s için kayıt gelmedi.", il_kodu)
            return []

        # Tarih filtresi (belirtilmişse)
        if tarih is not None:
            records = [r for r in records if r.tarih == tarih]
            if not records:
                logger.warning(
                    "EPDK XML'den il %s, tarih %s için kayıt bulunamadı.",
                    il_kodu,
                    tarih,
                )
                return []

        pump_prices = _records_to_pump_prices(records, il_kodu=il_kodu)

        logger.info(
            "EPDK XML başarılı: il %s, %d yakıt tipi.",
            il_kodu,
            len(pump_prices),
        )
        return pump_prices

    except Exception:
        logger.error(
            "Tüm kaynaklar başarısız (PO + Bildirim + XML): il=%s",
            il_kodu,
            exc_info=True,
        )
        return []




async def fetch_istanbul_avrupa(
    tarih: date | None = None,
) -> dict[str, Decimal]:
    """
    Petrol Ofisi uzerinden Istanbul (Avrupa) pompa fiyatlarini ceker.

    Avcilar ilcesi Avrupa yakasinda oldugu icin ISTANBUL (AVRUPA)
    satirindaki fiyatlar kullanilir. Boylece tarihsel po_istanbul_avcilar
    verileriyle tutarlilik saglanir.

    Args:
        tarih: Istenen tarih. None veya bugun degilse bos doner.

    Returns:
        Yakit tipi -> fiyat sozlugu.
        Ornek: {'benzin': Decimal('57.09'), 'motorin': Decimal('57.84'), 'lpg': Decimal('30.29')}
    """
    if tarih is not None and tarih != date.today():
        logger.info(
            "PO gecmis tarih desteklemiyor: tarih=%s, bugun=%s", tarih, date.today()
        )
        return {}

    try:
        city_prices = await _fetch_petrol_ofisi_all_cities()
    except Exception:
        logger.warning("Petrol Ofisi erisilemedi.", exc_info=True)
        return {}

    # _fetch_petrol_ofisi_all_cities Istanbul icin Avrupa+Anadolu
    # ortalamasi aliyor. Biz sadece Avrupa istiyoruz.
    # Dogrudan HTML'den ISTANBUL (AVRUPA) satirini cek
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30),
            follow_redirects=True,
            headers=BROWSER_HEADERS,
        ) as client:
            response = await client.get(PETROL_OFISI_URL)
            response.raise_for_status()

        html_content = response.text

        row_pattern = re.compile(
            r'<tr[^>]*data-disctrict-name="ISTANBUL \(AVRUPA\)"[^>]*>(.*?)</tr>',
            re.DOTALL | re.IGNORECASE,
        )
        match = row_pattern.search(html_content)
        if not match:
            logger.warning("PO HTML'de ISTANBUL (AVRUPA) satiri bulunamadi.")
            # Fallback: ortalama fiyatlari kullan
            if "34" in city_prices:
                logger.info("Fallback: Istanbul ortalamasi kullaniliyor.")
                return {k: v for k, v in city_prices["34"].items() if v is not None}
            return {}

        row_html = match.group(1)
        tax_pattern = re.compile(
            r'<span\s+class="with-tax">([^<]+)</span>', re.IGNORECASE
        )
        prices = tax_pattern.findall(row_html)

        # Tablo: [0]=Benzin95, [1]=Diesel, [2]=Gazyagi, [3]=Kalorifer, [4]=FuelOil, [5]=LPG
        result: dict[str, Decimal] = {}
        if len(prices) >= 6:
            benzin = _parse_decimal(prices[0])
            motorin = _parse_decimal(prices[1])
            lpg = _parse_decimal(prices[5])

            if benzin is not None:
                result["benzin"] = benzin
            if motorin is not None:
                result["motorin"] = motorin
            if lpg is not None:
                result["lpg"] = lpg

            logger.info(
                "PO Istanbul Avrupa fiyatlari: benzin=%s, motorin=%s, lpg=%s",
                result.get("benzin"),
                result.get("motorin"),
                result.get("lpg"),
            )
        else:
            logger.warning(
                "PO Istanbul Avrupa satirinda yetersiz fiyat: %d", len(prices)
            )

        return result

    except Exception:
        logger.warning("Istanbul Avrupa fiyat cekme hatasi.", exc_info=True)
        # Fallback: ortalama
        if "34" in city_prices:
            return {k: v for k, v in city_prices["34"].items() if v is not None}
        return {}


async def fetch_turkey_average(
    tarih: date | None = None,
) -> dict[str, Decimal]:
    """
    Türkiye ortalaması pompa fiyatlarını hesaplar.

    Fallback zinciri:
    1. Petrol Ofisi — tek HTTP isteğiyle tüm iller (hızlı + güvenilir)
    2. Il bazlı fallback zinciri (Bildirim Portal → EPDK XML)

    Args:
        tarih: İstenen tarih. None ise güncel fiyatlar kullanılır.

    Returns:
        Yakıt tipi → ortalama fiyat sözlüğü.
        Örnek: {'benzin': Decimal('58.07'), 'motorin': Decimal('58.93'), 'lpg': Decimal('30.06')}
    """
    logger.info("Türkiye ortalaması hesaplanıyor: %d il çekilecek.", len(BUYUK_5_IL))

    # ── Hızlı yol: Petrol Ofisi (tek istek, tüm iller) ──
    if tarih is None or tarih == date.today():
        try:
            po_averages = await _fetch_petrol_ofisi_turkey_average()
            if po_averages:
                logger.info(
                    "Türkiye ortalaması Petrol Ofisi'nden alındı: %s",
                    {k: str(v) for k, v in po_averages.items()},
                )
                return po_averages
        except Exception:
            logger.warning(
                "Petrol Ofisi Türkiye ortalaması başarısız, il bazlı fallback deneniyor...",
                exc_info=True,
            )

    # ── Yavaş yol: İl bazlı fallback zinciri ──
    fuel_prices: dict[str, list[Decimal]] = {ft: [] for ft in YAKIT_TIPLERI}

    for il_kodu, il_adi in BUYUK_5_IL.items():
        try:
            result = await fetch_pump_prices(il_kodu=il_kodu, tarih=tarih)
            for price_data in result:
                if price_data.fuel_type in fuel_prices:
                    fuel_prices[price_data.fuel_type].append(price_data.pump_price_tl_lt)
        except Exception:
            logger.error("İl %s (%s) çekilemedi.", il_kodu, il_adi, exc_info=True)

    # Ortalama hesapla
    averages: dict[str, Decimal] = {}
    for fuel_type, prices in fuel_prices.items():
        if prices:
            averages[fuel_type] = _calculate_average(prices)
            logger.info(
                "Türkiye ortalaması [%s]: %s TL/lt (%d il verisi)",
                fuel_type,
                averages[fuel_type],
                len(prices),
            )
        else:
            logger.warning("Türkiye ortalaması [%s]: Veri bulunamadı.", fuel_type)

    return averages
