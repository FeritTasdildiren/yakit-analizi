"""
EPDK Pompa Fiyatı Veri Çekme Servisi

EPDK'nın kamuya açık XML Web Servisi üzerinden akaryakıt pompa fiyatlarını çeker.
URL: https://www.epdk.gov.tr/Detay/DownloadXMLData
Method: GET
Params: sorguNo=72, parametre={il_trafik_kodu}

Tüm fiyatlar Decimal tipinde tutulur (float KULLANILMAZ).
"""

from __future__ import annotations

import asyncio
import logging
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

# Türkiye ortalaması hesaplamak için büyük 5 il
BUYUK_5_IL: Final[dict[str, str]] = {
    "34": "İSTANBUL",
    "06": "ANKARA",
    "35": "İZMİR",
    "16": "BURSA",
    "07": "ANTALYA",
}

YAKIT_TIPLERI: Final[list[str]] = ["benzin", "motorin", "lpg"]


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


class PumpPriceData(BaseModel):
    """İl bazlı ortalama pompa fiyatı verisi."""

    trade_date: date
    fuel_type: str = Field(description="benzin | motorin | lpg")
    pump_price_tl_lt: Decimal
    source: str = "epdk_xml"
    il_kodu: str | None = None
    dagitici_sayisi: int


# ── XML Parse ─────────────────────────────────────────────────────────────────


def _parse_decimal(raw: str | None) -> Decimal | None:
    """
    Türkçe formatlı sayıyı Decimal'e dönüştürür.
    Virgüllü sayı dönüşümü: '43,72' → Decimal('43.72')
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

            il_kodu = il_kodu_elem.text.strip() if il_kodu_elem is not None and il_kodu_elem.text else ""
            il_adi = il_adi_elem.text.strip() if il_adi_elem is not None and il_adi_elem.text else ""
            dagitici_raw = dagitici_elem.text.strip() if dagitici_elem is not None and dagitici_elem.text else ""
            tarih_raw = tarih_elem.text if tarih_elem is not None else None

            if not il_kodu or not dagitici_raw:
                logger.warning("Eksik alan: il_kodu='%s', dagitici='%s' — kayıt atlanıyor.", il_kodu, dagitici_raw)
                continue

            # Dağıtıcı adını normalize et (UPPER + STRIP)
            dagitici = dagitici_raw.upper().strip()

            record = EPDKRecord(
                il_kodu=il_kodu,
                il_adi=il_adi.upper().strip(),
                dagitici=dagitici,
                benzin_fiyat=_parse_decimal(benzin_elem.text if benzin_elem is not None else None),
                motorin_fiyat=_parse_decimal(motorin_elem.text if motorin_elem is not None else None),
                lpg_fiyat=_parse_decimal(lpg_elem.text if lpg_elem is not None else None),
                tarih=_parse_date(tarih_raw),
            )
            records.append(record)

        except Exception:
            logger.exception("Kayıt parse edilirken beklenmeyen hata, kayıt atlanıyor.")
            continue

    logger.info("EPDK XML parse tamamlandı: %d kayıt okundu.", len(records))
    return records


# ── Ortalama Hesaplama Yardımcıları ──────────────────────────────────────────


def _calculate_average(values: list[Decimal]) -> Decimal:
    """Decimal listesinin ortalamasını hesaplar (2 ondalık hane)."""
    if not values:
        return Decimal("0.00")
    total = sum(values)
    avg = total / len(values)
    return avg.quantize(Decimal("0.01"))


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

    # Yakıt tipi → (alan adı, fiyat listesi)
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
            logger.debug("İl %s için %s fiyatı bulunamadı, atlanıyor.", effective_il_kodu, fuel_type)
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
                "EPDK isteği gönderiliyor (deneme %d/%d): params=%s",
                attempt,
                EPDK_MAX_RETRIES,
                params,
            )
            response = await client.get(url, params=params)
            response.raise_for_status()
            logger.info("EPDK yanıt alındı: status=%d, boyut=%d byte", response.status_code, len(response.content))
            return response.text

        except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
            last_exc = exc
            if attempt < EPDK_MAX_RETRIES:
                wait_time = EPDK_BACKOFF_BASE ** attempt
                logger.warning(
                    "EPDK isteği başarısız (deneme %d/%d): %s — %.1f saniye bekleniyor.",
                    attempt,
                    EPDK_MAX_RETRIES,
                    exc,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(
                    "EPDK isteği %d denemeden sonra başarısız: %s",
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
    Belirtilen il için EPDK'dan pompa fiyatlarını çeker.

    Args:
        il_kodu: İl trafik kodu (ör: '34' İstanbul, '06' Ankara).
        tarih: İstenen tarih. None ise güncel fiyatlar çekilir.

    Returns:
        Her yakıt tipi için ortalama PumpPriceData listesi.
    """
    logger.info("EPDK pompa fiyatları çekiliyor: il_kodu=%s, tarih=%s", il_kodu, tarih)

    params: dict[str, str] = {
        "sorguNo": EPDK_SORGU_NO,
        "parametre": il_kodu,
    }

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
        logger.warning("EPDK'dan il %s için kayıt gelmedi.", il_kodu)
        return []

    # Tarih filtresi (belirtilmişse)
    if tarih is not None:
        records = [r for r in records if r.tarih == tarih]
        if not records:
            logger.warning(
                "EPDK'dan il %s, tarih %s için kayıt bulunamadı.",
                il_kodu,
                tarih,
            )
            return []

    pump_prices = _records_to_pump_prices(records, il_kodu=il_kodu)

    logger.info(
        "İl %s için %d yakıt tipi fiyatı hesaplandı.",
        il_kodu,
        len(pump_prices),
    )

    return pump_prices


async def fetch_turkey_average(
    tarih: date | None = None,
) -> dict[str, Decimal]:
    """
    Türkiye ortalaması pompa fiyatlarını hesaplar.

    Büyük 5 il (İstanbul, Ankara, İzmir, Bursa, Antalya) çekilip
    basit ortalama ile Türkiye ortalaması döndürülür.

    Args:
        tarih: İstenen tarih. None ise güncel fiyatlar kullanılır.

    Returns:
        Yakıt tipi → ortalama fiyat sözlüğü.
        Örnek: {'benzin': Decimal('43.50'), 'motorin': Decimal('41.20'), 'lpg': Decimal('18.30')}
    """
    logger.info("Türkiye ortalaması hesaplanıyor: %d il çekilecek.", len(BUYUK_5_IL))

    # Tüm illeri paralel çek
    tasks = [
        fetch_pump_prices(il_kodu=il_kodu, tarih=tarih)
        for il_kodu in BUYUK_5_IL
    ]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Yakıt tipi bazlı fiyatları topla
    fuel_prices: dict[str, list[Decimal]] = {ft: [] for ft in YAKIT_TIPLERI}

    for il_kodu, result in zip(BUYUK_5_IL, all_results):
        if isinstance(result, Exception):
            logger.error("İl %s (%s) çekilemedi: %s", il_kodu, BUYUK_5_IL[il_kodu], result)
            continue

        for price_data in result:
            if price_data.fuel_type in fuel_prices:
                fuel_prices[price_data.fuel_type].append(price_data.pump_price_tl_lt)

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
