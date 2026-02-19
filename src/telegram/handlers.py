"""
Telegram bot komut isleyicileri.

/rapor, /iptal, /yardim komutlari ve streak-based rapor formatlama.
predictions_v5 tablosundan ardisik gun sinyallerini (streak) hesaplayarak
kullanici dostu yakit raporu sunar.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from src.config.database import async_session_factory
from src.repositories.telegram_repository import (
    deactivate_user,
    get_user_by_telegram_id,
)

logger = logging.getLogger(__name__)

# Sabit buton klavyesi — her rapor/komut yanıtında gönderilir
RAPOR_KEYBOARD = ReplyKeyboardMarkup(
    [["📊 Rapor İste"]],
    resize_keyboard=True,
    one_time_keyboard=False,
)

# Türkçe ay adları (tekrar kullanım için modül seviyesinde)
_MONTHS_TR = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
    5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
    9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

# Yakıt tipleri ve Türkçe etiketleri
_FUEL_LABELS = {
    "benzin": "BENZİN",
    "motorin": "MOTORİN",
    "lpg": "LPG",
}


# ────────────────────────────────────────────────────────────────────────────
#  Yetki Kontrolu
# ────────────────────────────────────────────────────────────────────────────


async def _check_approved_user(update: Update) -> bool:
    """
    Kullanicinin onaylanmis ve aktif olup olmadigini kontrol eder.

    False donerse kullaniciya uygun mesaj gonderilir.
    """
    user = update.effective_user
    if user is None:
        return False

    async with async_session_factory() as session:
        try:
            db_user = await get_user_by_telegram_id(session, user.id)
            await session.commit()
        except Exception as exc:
            logger.error("Yetki kontrolu DB hatasi: %s", exc)
            await update.message.reply_text(
                "❌ Bir hata oluştu. Lütfen tekrar deneyin."
            )
            return False

    if db_user is None:
        await update.message.reply_text(
            "❌ Henüz kayıtlı değilsiniz. Kayıt için /start yazın."
        )
        return False

    if not db_user.is_active:
        await update.message.reply_text(
            "❌ Hesabınız aktif değil. Yeniden kayıt için /start yazın."
        )
        return False

    if not db_user.is_approved:
        await update.message.reply_text(
            "⏳ Hesabınız henüz onaylanmadı. "
            "Admin onayı bekleniyor."
        )
        return False

    return True


# ────────────────────────────────────────────────────────────────────────────
#  Streak Hesaplama (predictions_v5)
# ────────────────────────────────────────────────────────────────────────────


async def _calculate_streak(fuel_type: str) -> dict:
    """
    predictions_v5 tablosundan son 10 gunun verisini cekerek
    ardisik sinyal (streak) hesaplar.

    Streak kurallari:
    - first_event_direction = 0 VEYA first_event_amount = 0 → sinyal yok
    - first_event_direction = 1 ve first_event_amount > 0 → zam sinyali
    - first_event_direction = -1 → indirim sinyali
    - Bugunden geriye dogru ARDISIK ayni yonlu sinyal sayilir
    - Yon degisirse veya sinyal yoksa streak kesilir

    Returns:
        {
            "streak_count": int,
            "direction": "artis" | "dusus" | None,
            "avg_amount": float,
            "amounts": list[float],
        }
    """
    result = {
        "streak_count": 0,
        "direction": None,
        "avg_amount": 0.0,
        "amounts": [],
    }

    async with async_session_factory() as session:
        try:
            query = text("""
                SELECT run_date, first_event_direction, first_event_amount,
                       first_event_type
                FROM predictions_v5
                WHERE fuel_type = :fuel_type
                ORDER BY run_date DESC
                LIMIT 10
            """)
            rows = await session.execute(
                query, {"fuel_type": fuel_type}
            )
            records = rows.mappings().all()
            await session.commit()
        except Exception as exc:
            logger.error(
                "Streak verisi cekilemedi (%s): %s", fuel_type, exc
            )
            return result

    if not records:
        return result

    # İlk günün yönünü belirle
    streak_direction = None
    streak_count = 0
    amounts: list[float] = []

    for row in records:
        direction = int(row["first_event_direction"] or 0)
        amount = float(row["first_event_amount"] or 0)

        # Sinyal yok → streak kesilir
        if direction == 0 or amount == 0.0:
            break

        current_dir = "artis" if direction == 1 else "dusus"

        # İlk gün — streak yönünü belirle
        if streak_direction is None:
            streak_direction = current_dir
            streak_count = 1
            amounts.append(abs(amount))
            continue

        # Aynı yön → streak devam
        if current_dir == streak_direction:
            streak_count += 1
            amounts.append(abs(amount))
        else:
            # Yön değişti → streak kesilir
            break

    if streak_count > 0 and amounts:
        result["streak_count"] = streak_count
        result["direction"] = streak_direction
        result["avg_amount"] = sum(amounts) / len(amounts)
        result["amounts"] = amounts

    return result


async def _get_pump_price(fuel_type: str) -> float | None:
    """Son guncel pompa fiyatini DB'den ceker."""
    async with async_session_factory() as session:
        try:
            from src.data_collectors.market_data_repository import (
                get_latest_data,
            )

            market = await get_latest_data(session, fuel_type)
            await session.commit()

            if market and market.pump_price_tl_lt:
                return float(market.pump_price_tl_lt)
            return None
        except Exception as exc:
            logger.error(
                "Pompa fiyati cekilemedi (%s): %s", fuel_type, exc
            )
            return None


# ────────────────────────────────────────────────────────────────────────────
#  Streak → Olasılık Tablosu
# ────────────────────────────────────────────────────────────────────────────


def _streak_to_probability(streak_count: int) -> int:
    """
    Ardisik gun sayisindan olasilik yuzdesi hesaplar.

    | Ardışık Gün | Olasılık |
    |-------------|----------|
    | 0           | 0 (sabit)|
    | 1           | %33      |
    | 2           | %66      |
    | 3+          | %99      |
    """
    if streak_count <= 0:
        return 0
    if streak_count == 1:
        return 33
    if streak_count == 2:
        return 66
    return 99


# ────────────────────────────────────────────────────────────────────────────
#  Rapor Formatlama (Streak-Based)
# ────────────────────────────────────────────────────────────────────────────


def _format_fuel_streak(
    label: str, pump_price: float | None, streak: dict
) -> str:
    """
    Tek bir yakit tipi icin streak-based rapor bolumunu formatlar.

    Sinyal yoksa:
        ⛽ BENZİN — 57.09 TL/L
           ✅ Durum: Sabit (değişim beklenmiyor)

    Zam sinyali:
        ⛽ BENZİN — 55.37 TL/L
           🔴 Zam Olasılığı: %33 (1 gün sinyal)
           💰 Beklenen Zam: ~1.35 TL/L

    İndirim sinyali:
        ⛽ BENZİN — 57.09 TL/L
           🟢 İndirim Olasılığı: %33 (1 gün sinyal)
           💰 Beklenen İndirim: ~0.80 TL/L
    """
    price_str = f"{pump_price:.2f} TL/L" if pump_price else "Veri yok"
    header = f"⛽ {label} — {price_str}"

    streak_count = streak.get("streak_count", 0)
    direction = streak.get("direction")
    avg_amount = streak.get("avg_amount", 0.0)

    # Sinyal yok
    if streak_count == 0 or direction is None:
        return f"{header}\n   ✅ Durum: Sabit (değişim beklenmiyor)"

    probability = _streak_to_probability(streak_count)

    # Gün açıklaması
    if streak_count >= 3:
        gun_str = f"{streak_count}+ gün ardışık sinyal"
    elif streak_count == 1:
        gun_str = "1 gün sinyal"
    else:
        gun_str = f"{streak_count} gün ardışık sinyal"

    if direction == "artis":
        emoji = "🔴"
        type_label = "Zam Olasılığı"
        change_label = "Beklenen Zam"
    else:
        emoji = "🟢"
        type_label = "İndirim Olasılığı"
        change_label = "Beklenen İndirim"

    return (
        f"{header}\n"
        f"   {emoji} {type_label}: %{probability} ({gun_str})\n"
        f"   💰 {change_label}: ~{avg_amount:.2f} TL/L"
    )


async def format_full_report() -> str:
    """
    Tam streak-based rapor mesajini olusturur.

    3 yakit tipi (benzin, motorin, lpg) icin streak hesaplar,
    pump fiyatlariyla birlikte formatlar.
    """
    today = date.today()
    date_str = f"{today.day} {_MONTHS_TR[today.month]}"

    sections = []
    for fuel_type, label in _FUEL_LABELS.items():
        pump_price = await _get_pump_price(fuel_type)
        streak = await _calculate_streak(fuel_type)
        section = _format_fuel_streak(label, pump_price, streak)
        sections.append(section)

    body = "\n\n".join(sections)

    return (
        f"📊 Yakıt Raporu — {date_str}\n\n"
        f"{body}\n\n"
        f"⚠️ Tahmin amaçlıdır, yatırım tavsiyesi değildir."
    )


async def format_daily_notification() -> str:
    """
    Gunluk bildirim mesajini streak-based kisa formatta olusturur.

    Tum sabit:
        🔔 Günlük Rapor — 20 Şubat
        ⛽ Benzin: Sabit ✅
        ⛽ Motorin: Sabit ✅
        ⛽ LPG: Sabit ✅
        Detay → /rapor

    Sinyal varsa:
        🔔 Günlük Rapor — 20 Şubat
        ⛽ Benzin: 🔴 %66 Zam Olasılığı (~1.47 TL)
        ⛽ Motorin: Sabit ✅
        ⛽ LPG: 🟢 %33 İndirim Olasılığı (~0.80 TL)
        Detay → /rapor
    """
    today = date.today()
    date_str = f"{today.day} {_MONTHS_TR[today.month]}"

    lines = [f"🔔 Günlük Rapor — {date_str}\n"]

    # Kısa etiketler (bildirimde küçük harf)
    short_labels = {"benzin": "Benzin", "motorin": "Motorin", "lpg": "LPG"}

    for fuel_type, label in short_labels.items():
        streak = await _calculate_streak(fuel_type)
        streak_count = streak.get("streak_count", 0)
        direction = streak.get("direction")
        avg_amount = streak.get("avg_amount", 0.0)

        if streak_count == 0 or direction is None:
            lines.append(f"⛽ {label}: Sabit ✅")
        else:
            probability = _streak_to_probability(streak_count)
            if direction == "artis":
                lines.append(
                    f"⛽ {label}: 🔴 %{probability} Zam Olasılığı "
                    f"(~{avg_amount:.2f} TL)"
                )
            else:
                lines.append(
                    f"⛽ {label}: 🟢 %{probability} İndirim Olasılığı "
                    f"(~{avg_amount:.2f} TL)"
                )

    lines.append("\nDetay → /rapor")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  /rapor Komutu
# ────────────────────────────────────────────────────────────────────────────


async def rapor_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /rapor komut isleyicisi ve "📊 Rapor İste" buton isleyicisi.

    Sadece onaylanmis kullanicilar kullanabilir.
    Benzin, motorin ve LPG icin streak-based durum raporu gonderir.
    """
    if not await _check_approved_user(update):
        return

    report = await format_full_report()
    await update.message.reply_text(
        report,
        reply_markup=RAPOR_KEYBOARD,
    )


# ────────────────────────────────────────────────────────────────────────────
#  /iptal Komutu
# ────────────────────────────────────────────────────────────────────────────


async def iptal_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /iptal komut isleyicisi.

    Kullanicinin aboneligini iptal eder (is_active=False).
    """
    user = update.effective_user
    if user is None:
        return

    async with async_session_factory() as session:
        try:
            db_user = await get_user_by_telegram_id(session, user.id)

            if db_user is None:
                await update.message.reply_text(
                    "❌ Henüz kayıtlı değilsiniz. Kayıt için /start yazın."
                )
                await session.commit()
                return

            if not db_user.is_active:
                await update.message.reply_text(
                    "ℹ️ Aboneliğiniz zaten iptal edilmiş. "
                    "Tekrar kayıt için /start yazın."
                )
                await session.commit()
                return

            await deactivate_user(session, user.id)
            await session.commit()

        except Exception as exc:
            logger.error("Iptal islem hatasi: %s", exc)
            await update.message.reply_text(
                "❌ İptal sırasında bir hata oluştu. Lütfen tekrar deneyin."
            )
            return

    await update.message.reply_text(
        "✅ Aboneliğiniz iptal edildi. Tekrar kayıt için /start yazın.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ────────────────────────────────────────────────────────────────────────────
#  /yardim Komutu
# ────────────────────────────────────────────────────────────────────────────


HELP_MESSAGE = (
    "📖 Yakıt Haber Bot — Yardım\n\n"
    "Kullanılabilir komutlar:\n\n"
    "/start — Kayıt ol veya durumunu kontrol et\n"
    "/rapor — Anlık yakıt analizi raporu al\n"
    "/iptal — Aboneliğini iptal et\n"
    "/yardim — Bu yardım mesajını göster\n\n"
    "📊 Rapor komutu benzin, motorin ve LPG için:\n"
    "• Güncel pompa fiyatı\n"
    "• Fiyat değişim sinyali (ardışık gün analizi)\n"
    "• Beklenen değişim miktarı\n\n"
    "gösterir.\n\n"
    "💡 Alttaki '📊 Rapor İste' butonuna basarak da\n"
    "rapor alabilirsiniz.\n\n"
    "🔔 Onaylı kullanıcılar her gün otomatik bildirim alır.\n\n"
    "⚠️ Bu bot yatırım tavsiyesi vermez."
)


async def yardim_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/yardim komut isleyicisi."""
    await update.message.reply_text(
        HELP_MESSAGE,
        reply_markup=RAPOR_KEYBOARD,
    )
