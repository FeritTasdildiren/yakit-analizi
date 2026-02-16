"""
Telegram bot komut isleyicileri.

/rapor, /iptal, /yardim komutlari ve rapor formatlama yardimcilari.
DB'den veri cekerek kullaniciya anlik durum raporu sunar.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from telegram import ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes

from src.config.database import async_session_factory
from src.repositories.telegram_repository import (
    deactivate_user,
    get_user_by_telegram_id,
)

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────────
#  Yetki Kontrolu
# ────────────────────────────────────────────────────────────────────────────


async def _check_approved_user(
    update: Update,
) -> bool:
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
#  Rapor Veri Toplama
# ────────────────────────────────────────────────────────────────────────────


async def _fetch_report_data(fuel_type: str) -> dict | None:
    """
    Belirtilen yakit tipi icin rapor verisini DB'den ceker.

    MBE, Risk, ML tahmini ve piyasa verilerini toplar.
    Fallback mekanizmasi: DB verisi cekilemezse None doner.

    Args:
        fuel_type: "benzin" veya "motorin"

    Returns:
        Rapor verisi dict'i veya None.
    """
    async with async_session_factory() as session:
        try:
            # Piyasa verisi (guncel fiyat)
            from src.data_collectors.market_data_repository import get_latest_data

            market = await get_latest_data(session, fuel_type)

            # MBE degeri
            from src.core.mbe_repository import get_latest_mbe

            mbe = await get_latest_mbe(session, fuel_type)

            # Risk skoru
            from src.core.risk_repository import get_latest_risk

            risk = await get_latest_risk(session, fuel_type)

            # ML tahmini
            from src.repositories.ml_repository import get_latest_prediction

            prediction = await get_latest_prediction(session, fuel_type)

            await session.commit()

            return {
                "fuel_type": fuel_type,
                "pump_price": (
                    float(market.pump_price_tl_lt)
                    if market and market.pump_price_tl_lt
                    else None
                ),
                "mbe_value": (
                    float(mbe.mbe_value) if mbe and mbe.mbe_value else None
                ),
                "risk_score": (
                    float(risk.composite_score) * 100
                    if risk and risk.composite_score
                    else None
                ),
                "ml_direction": (
                    prediction.predicted_direction
                    if prediction
                    else None
                ),
                "ml_probability": _get_direction_probability(prediction),
                "expected_change": (
                    float(prediction.expected_change_tl)
                    if prediction and prediction.expected_change_tl
                    else None
                ),
                "model_version": (
                    prediction.model_version
                    if prediction
                    else None
                ),
            }
        except Exception as exc:
            logger.error(
                "Rapor verisi cekilemedi (%s): %s",
                fuel_type,
                exc,
            )
            return None


def _get_direction_probability(prediction) -> float | None:
    """ML tahmininden en yuksek olasilik degerini hesaplar."""
    if prediction is None:
        return None

    direction = prediction.predicted_direction
    if direction == "hike" and prediction.probability_hike:
        return float(prediction.probability_hike) * 100
    elif direction == "stable" and prediction.probability_stable:
        return float(prediction.probability_stable) * 100
    elif direction == "cut" and prediction.probability_cut:
        return float(prediction.probability_cut) * 100
    return None


# ────────────────────────────────────────────────────────────────────────────
#  Rapor Formatlama
# ────────────────────────────────────────────────────────────────────────────

_DIRECTION_MAP = {
    "hike": "ZAM",
    "stable": "SABİT",
    "cut": "İNDİRİM",
}

_RISK_EMOJI = {
    "low": "✅ Normal",
    "medium": "⚠️ Yüksek risk",
    "high": "🔴 Çok yüksek risk",
}


def _risk_level(score: float | None) -> str:
    """Risk seviyesini emoji ile dondurur."""
    if score is None:
        return "❓ Veri yok"
    if score >= 70:
        return "🔴 Çok yüksek risk"
    if score >= 50:
        return "⚠️ Yüksek risk"
    return "✅ Normal"


def _format_fuel_section(data: dict | None, label: str) -> str:
    """Tek bir yakit tipi icin rapor bolumunu formatlar."""
    if data is None:
        return f"⛽ {label}\n└ Veri alınamadı\n"

    pump = f"{data['pump_price']:.2f} TL/L" if data["pump_price"] else "Veri yok"
    mbe = f"{data['mbe_value']:+.2f} TL/L" if data["mbe_value"] is not None else "Veri yok"

    risk_val = data["risk_score"]
    risk_str = f"{risk_val:.0f}/100" if risk_val is not None else "Veri yok"

    direction = _DIRECTION_MAP.get(data["ml_direction"], "Veri yok")
    prob = f"%{data['ml_probability']:.0f} olasılık" if data["ml_probability"] else ""
    ml_str = f"{direction} ({prob})" if prob else direction

    expected = (
        f"{data['expected_change']:+.2f} TL/L"
        if data["expected_change"]
        else "-"
    )

    status = _risk_level(risk_val)

    return (
        f"⛽ {label}\n"
        f"├ Güncel Fiyat: {pump}\n"
        f"├ MBE Değeri: {mbe}\n"
        f"├ Risk Skoru: {risk_str}\n"
        f"├ ML Tahmini: {ml_str}\n"
        f"├ Beklenen Değişim: {expected}\n"
        f"└ Durum: {status}\n"
    )


def format_full_report(
    benzin_data: dict | None,
    motorin_data: dict | None,
) -> str:
    """Tam rapor mesajini formatlar."""
    today = date.today()
    months_tr = {
        1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
        5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
        9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
    }
    date_str = f"{today.day} {months_tr[today.month]} {today.year}"
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%d.%m.%Y %H:%M")

    model_ver = "v1.0"
    if benzin_data and benzin_data.get("model_version"):
        model_ver = benzin_data["model_version"]
    elif motorin_data and motorin_data.get("model_version"):
        model_ver = motorin_data["model_version"]

    benzin_section = _format_fuel_section(benzin_data, "BENZİN")
    motorin_section = _format_fuel_section(motorin_data, "MOTORİN")

    return (
        f"📊 Yakıt Analizi Raporu\n"
        f"📅 {date_str}\n\n"
        f"{benzin_section}\n"
        f"{motorin_section}\n"
        f"🤖 Model: {model_ver} | Güncelleme: {time_str}\n"
        f"⚠️ Bu bilgiler yatırım tavsiyesi değildir."
    )


def format_daily_notification(
    benzin_data: dict | None,
    motorin_data: dict | None,
) -> str:
    """Gunluk bildirim mesajini formatlar (kisa versiyon)."""
    today = date.today()
    months_tr = {
        1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan",
        5: "Mayıs", 6: "Haziran", 7: "Temmuz", 8: "Ağustos",
        9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
    }
    date_str = f"{today.day} {months_tr[today.month]}"

    lines = [f"🔔 Günlük Yakıt Raporu — {date_str}\n"]

    for data, label in [(benzin_data, "Benzin"), (motorin_data, "Motorin")]:
        if data is None:
            lines.append(f"⛽ {label}: Veri alınamadı")
            continue

        direction = _DIRECTION_MAP.get(data["ml_direction"], "?")
        prob = f"%{data['ml_probability']:.0f}" if data["ml_probability"] else "?"

        risk_emoji = "⚠️" if data["risk_score"] and data["risk_score"] >= 50 else "✅"
        expected = (
            f" ({data['expected_change']:+.2f} TL/L bekleniyor)"
            if data["expected_change"]
            else ""
        )

        if data["ml_direction"] == "hike":
            lines.append(
                f"⛽ {label}: {direction} riski {prob} {risk_emoji}{expected}"
            )
        else:
            lines.append(
                f"⛽ {label}: {direction} {prob} {risk_emoji}"
            )

    lines.append("\nDetay için /rapor yazın.")
    lines.append("⚠️ Yatırım tavsiyesi değildir.")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────────────
#  /rapor Komutu
# ────────────────────────────────────────────────────────────────────────────


async def rapor_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    /rapor komut isleyicisi.

    Sadece onaylanmis kullanicilar kullanabilir.
    Benzin ve motorin icin anlik durum raporu gonderir.
    """
    if not await _check_approved_user(update):
        return

    # Veri topla
    benzin_data = await _fetch_report_data("benzin")
    motorin_data = await _fetch_report_data("motorin")

    # Rapor formatla ve gonder
    report = format_full_report(benzin_data, motorin_data)
    await update.message.reply_text(report)


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
    "📊 /rapor komutu benzin ve motorin için:\n"
    "• Güncel pompa fiyatı\n"
    "• MBE (Maliyet Baz Etkisi) değeri\n"
    "• Risk skoru (0-100)\n"
    "• ML tahmin yönü ve olasılığı\n"
    "• Beklenen değişim miktarı\n\n"
    "gösterir.\n\n"
    "🔔 Onaylı kullanıcılar her gün sabah 10:00'da\n"
    "otomatik bildirim alır.\n\n"
    "⚠️ Bu bot yatırım tavsiyesi vermez."
)


async def yardim_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """/yardim komut isleyicisi."""
    await update.message.reply_text(HELP_MESSAGE)
