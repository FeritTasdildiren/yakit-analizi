"""
Predictor v5/v6 — Alarm ve Post-Processing modülü.

ML tahmin sonuçlarını alarm kararına çevirir.
v6: Gevşetilmiş koşullar + deterministik fallback alarm.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from src.predictor_v5.config import ALARM_THRESHOLD, COOLDOWN_HOURS


# ---------------------------------------------------------------------------
# 1) compute_risk_trend
# ---------------------------------------------------------------------------

def compute_risk_trend(risk_scores_recent: List[float]) -> str:
    """
    Son 6 günlük risk skorlarından trend hesapla.

    Son 3 günün ortalaması vs önceki 3 günün ortalaması:
    - Fark > 0.02  → "up"
    - Fark < -0.02 → "down"
    - Aksi halde   → "stable"

    En az 6 skor gerekir, yetersizse "stable" döner.
    """
    if len(risk_scores_recent) < 6:
        return "stable"

    recent_3 = risk_scores_recent[-3:]
    prev_3 = risk_scores_recent[-6:-3]

    avg_recent = sum(recent_3) / len(recent_3)
    avg_prev = sum(prev_3) / len(prev_3)

    diff = avg_recent - avg_prev

    if diff > 0.02:
        return "up"
    elif diff < -0.02:
        return "down"
    else:
        return "stable"


# ---------------------------------------------------------------------------
# 2) determine_alarm_type
# ---------------------------------------------------------------------------

def determine_alarm_type(prediction: Dict, risk_trend: str) -> str:
    """
    ML tahmin sonuçlarına ve risk trendine göre alarm tipi belirle.

    Tipler:
    - "consistent": Yön tutarlı ve büyük değişim (|net_amount| >= 0.30)
    - "volatile":   Yönler farklı (first_event vs net_amount_3d)
    - "gradual":    Yön tutarlı ama küçük değişim (|net_amount| < 0.30)
    - "no_change":  Varsayılan — direction=0 veya net_amount yok
    """
    direction = prediction.get("first_event_direction", 0)
    first_amount = prediction.get("first_event_amount")
    net_amount = prediction.get("net_amount_3d")

    if direction == 0 or net_amount is None:
        return "no_change"

    # Decimal'i float'a çevir
    if isinstance(net_amount, Decimal):
        net_amount = float(net_amount)
    if isinstance(first_amount, Decimal):
        first_amount = float(first_amount)

    # Yön tutarlılığı kontrolü
    net_direction = 1 if net_amount > 0 else (-1 if net_amount < 0 else 0)

    if direction != net_direction:
        return "volatile"

    if abs(net_amount) >= 0.30:
        return "consistent"
    else:
        return "gradual"


# ---------------------------------------------------------------------------
# 3) generate_alarm_message
# ---------------------------------------------------------------------------

def generate_alarm_message(alarm_type: str, prediction: Dict, fuel_type: str) -> str:
    """
    Alarm tipine göre Türkçe bildirim mesajı üret.
    """
    fuel_names = {
        "benzin": "Benzin",
        "motorin": "Motorin",
        "lpg": "LPG",
    }
    fuel_label = fuel_names.get(fuel_type, fuel_type.capitalize())

    prob = prediction.get("stage1_probability", Decimal("0"))
    if isinstance(prob, Decimal):
        prob = float(prob)
    prob_pct = f"{prob * 100:.0f}"

    net_amount = prediction.get("net_amount_3d")
    if net_amount is not None:
        if isinstance(net_amount, Decimal):
            net_amount_f = float(net_amount)
        else:
            net_amount_f = net_amount
        net_str = f"{abs(net_amount_f):.2f}"
        direction_word = "artış" if net_amount_f > 0 else "düşüş"
    else:
        net_str = "?"
        direction_word = "değişim"

    templates = {
        "consistent": (
            f"⚠️ {fuel_label} Fiyat Alarmı — "
            f"Önümüzdeki 3 gün içinde ~{net_str} TL/lt {direction_word} bekleniyor. "
            f"Model güveni: %{prob_pct}. "
            f"Yön ve büyüklük tutarlı, güçlü sinyal."
        ),
        "volatile": (
            f"⚡ {fuel_label} Fiyat Uyarısı — "
            f"Karışık sinyaller tespit edildi. "
            f"İlk hareket ve 3 günlük net etki farklı yönlerde. "
            f"Model güveni: %{prob_pct}. Dikkatli takip önerilir."
        ),
        "gradual": (
            f"📊 {fuel_label} Fiyat Bildirimi — "
            f"Küçük ama tutarlı bir {direction_word} bekleniyor (~{net_str} TL/lt). "
            f"Model güveni: %{prob_pct}. "
            f"Kademeli değişim sinyali."
        ),
        "no_change": (
            f"✅ {fuel_label} — "
            f"Önümüzdeki 3 gün için belirgin bir fiyat değişimi beklenmiyor. "
            f"Model güveni: %{prob_pct}."
        ),
        "already_happened": (
            f"ℹ️ {fuel_label} — "
            f"Bugün zaten bir fiyat değişikliği gerçekleşti. "
            f"Yeni alarm değerlendirmesi yarın yapılacak."
        ),
        "deterministic": (
            f"🔴 {fuel_label} Deterministik Alarm — "
            f"ML modelden bağımsız, maliyet göstergeleri fiyat değişimi sinyali veriyor. "
            f"Piyasa koşulları değişim eşiğini aştı."
        ),
    }

    return templates.get(alarm_type, templates["no_change"])


# ---------------------------------------------------------------------------
# 4) evaluate_deterministic_alarm — v6 YENİ
# ---------------------------------------------------------------------------

def evaluate_deterministic_alarm(
    features: Optional[Dict] = None,
    mbe_value: float = 0.0,
    days_since_last_change: float = 0.0,
    cost_gap_pct: float = 0.0,
    delta_mbe_3d: float = 0.0,
    risk_composite: float = 0.0,
) -> Dict:
    """
    ML'den bağımsız deterministik alarm kuralları.
    
    Kurallar:
    1. MBE < -1.0 AND days_since_last_change >= 7 → alarm
    2. cost_gap_pct > 3.0% → alarm
    3. delta_mbe_3d < -1.5 → alarm (hızlı bozulma)
    4. risk_composite >= 0.70 AND days_since_last_change >= 5 → alarm
    
    Args:
        features: Feature dict (varsa buradan çeker). Yoksa ayrı parametreler.
    
    Returns:
        dict: {"triggered": bool, "rules": [str], "confidence": float}
    """
    if features is not None:
        mbe_value = features.get("mbe_value", 0.0)
        days_since_last_change = features.get("days_since_last_change", 0.0)
        cost_gap_pct = features.get("cost_gap_pct", 0.0)
        delta_mbe_3d = features.get("delta_mbe_3d", 0.0)
        risk_composite = features.get("risk_composite", 0.0)

    triggered_rules = []
    
    # Kural 1: Yüksek MBE açığı + uzun süre değişmemiş
    if mbe_value < -1.0 and days_since_last_change >= 7:
        triggered_rules.append("mbe_gap_stale")
    
    # Kural 2: Maliyet farkı çok yüksek
    if cost_gap_pct > 3.0:
        triggered_rules.append("cost_gap_high")
    
    # Kural 3: Hızlı MBE bozulması
    if delta_mbe_3d < -1.5:
        triggered_rules.append("mbe_rapid_decline")
    
    # Kural 4: Yüksek risk + uzun bekleyiş
    if risk_composite >= 0.70 and days_since_last_change >= 5:
        triggered_rules.append("high_risk_stale")
    
    triggered = len(triggered_rules) > 0
    # Her kural 0.25 güven ekler, max 1.0
    confidence = min(len(triggered_rules) * 0.25, 1.0) if triggered else 0.0
    
    return {
        "triggered": triggered,
        "rules": triggered_rules,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# 5) evaluate_alarm  (ana akış — v6 güncelleme)
# ---------------------------------------------------------------------------

def evaluate_alarm(
    prediction: Dict,
    risk_trend: str,
    last_alarm_time: Optional[datetime],
    last_price_change_time: Optional[datetime],
    price_changed_today: bool,
    features: Optional[Dict] = None,
) -> Dict:
    """
    ML tahmin sonucunu alarm kararına çevirir.

    v6 Akış:
    1. price_changed_today → alarm_type="already_happened", should_alarm=True
    2. Cooldown aktif → should_alarm=False
    3. ML prob >= ALARM_THRESHOLD → alarm (risk_trend koşulu KALDIRILDI)
       VEYA (risk_composite >= 0.65 AND prob >= 0.15) → alarm
    4. Deterministik alarm kontrol (ML'den bağımsız)
    5. Hiçbiri sağlanmıyor → should_alarm=False
    """
    now = datetime.utcnow()
    fuel_type = prediction.get("fuel_type", "benzin")

    # Probability
    prob = prediction.get("stage1_probability", Decimal("0"))
    if isinstance(prob, Decimal):
        prob_decimal = prob
        prob_float = float(prob)
    else:
        prob_decimal = Decimal(str(prob))
        prob_float = float(prob)

    # Cooldown hesaplama
    cooldown_active = False
    cooldown_remaining_hours = 0.0

    if last_alarm_time is not None:
        if last_alarm_time.tzinfo is not None:
            last_alarm_time = last_alarm_time.replace(tzinfo=None)
        elapsed = now - last_alarm_time
        cooldown_td = timedelta(hours=int(COOLDOWN_HOURS))
        if elapsed < cooldown_td:
            cooldown_active = True
            remaining = cooldown_td - elapsed
            cooldown_remaining_hours = round(remaining.total_seconds() / 3600, 1)

    # 1) Bugün fiyat değişti mi?
    if price_changed_today:
        msg = generate_alarm_message("already_happened", prediction, fuel_type)
        return {
            "should_alarm": True,
            "alarm_type": "already_happened",
            "message": msg,
            "confidence": prob_float,
            "cooldown_active": cooldown_active,
            "cooldown_remaining_hours": cooldown_remaining_hours,
        }

    # 2) Cooldown aktif mi?
    if cooldown_active:
        return {
            "should_alarm": False,
            "alarm_type": None,
            "message": None,
            "confidence": prob_float,
            "cooldown_active": True,
            "cooldown_remaining_hours": cooldown_remaining_hours,
        }

    # 3) v6 ML alarm — GEVŞETİLMİŞ KOŞUL
    #    Eski: prob >= 0.55 AND risk_trend == "up"
    #    Yeni: prob >= 0.25 OR (risk_composite >= 0.65 AND prob >= 0.15)
    risk_composite = 0.0
    if features is not None:
        risk_composite = features.get("risk_composite", 0.0)
    
    ml_alarm = False
    if prob_decimal >= ALARM_THRESHOLD:
        ml_alarm = True
    elif risk_composite >= 0.65 and prob_float >= 0.15:
        ml_alarm = True

    if ml_alarm:
        alarm_type = determine_alarm_type(prediction, risk_trend)
        msg = generate_alarm_message(alarm_type, prediction, fuel_type)
        return {
            "should_alarm": True,
            "alarm_type": alarm_type,
            "message": msg,
            "confidence": prob_float,
            "cooldown_active": False,
            "cooldown_remaining_hours": 0.0,
        }

    # 4) v6 Deterministik alarm — ML'den bağımsız
    det_result = evaluate_deterministic_alarm(features=features)
    if det_result["triggered"]:
        msg = generate_alarm_message("deterministic", prediction, fuel_type)
        return {
            "should_alarm": True,
            "alarm_type": "deterministic",
            "message": msg,
            "confidence": det_result["confidence"],
            "cooldown_active": False,
            "cooldown_remaining_hours": 0.0,
            "deterministic_rules": det_result["rules"],
        }

    # 5) Koşullar sağlanmıyor
    return {
        "should_alarm": False,
        "alarm_type": None,
        "message": None,
        "confidence": prob_float,
        "cooldown_active": False,
        "cooldown_remaining_hours": 0.0,
    }
