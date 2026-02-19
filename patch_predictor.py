#!/usr/bin/env python3
"""
TASK-059: predictor.py'ye Stage-2 clipping + calibration_method düzeltmesi uygula
"""
import os

FILE = "/var/www/yakit_analiz/src/predictor_v5/predictor.py"

with open(FILE, "r") as f:
    content = f.read()

original = content  # backup

# ======================================================================
# Değişiklik 1: calibration_method "platt" hardcoded → kalibratörden oku
# ======================================================================
old_cal = '''                calibrated = apply_calibration(calibrator, np.array([stage1_prob_raw]))
                stage1_prob = float(calibrated[0])
                calibration_method = "platt"
                logger.info("Kalibrasyon uygulandi: raw=%.4f -> calibrated=%.4f", stage1_prob_raw, stage1_prob)'''

new_cal = '''                calibrated = apply_calibration(calibrator, np.array([stage1_prob_raw]))
                stage1_prob = float(calibrated[0])
                calibration_method = getattr(calibrator, "method", "calibrated")
                logger.info("Kalibrasyon uygulandi (%s): raw=%.4f -> calibrated=%.4f", calibration_method, stage1_prob_raw, stage1_prob)'''

if old_cal in content:
    content = content.replace(old_cal, new_cal)
    print("✅ Değişiklik 1: calibration_method dinamik yapıldı")
else:
    print("⚠️ Değişiklik 1: Hedef string bulunamadı, atlanıyor")

# ======================================================================
# Değişiklik 2: Stage-2 output clipping ekle
# ======================================================================
# Stage-2 clipping sabitleri — imports bölümüne ekle
old_imports_end = """# Kalibrasyon modulu paralel gelistiriliyor (TASK-053)."""
new_imports_end = """# Stage-2 output clipping sinirlari (veri bazli: P95 + marj)
# Gercek degisimler: benzin/motorin max ±6 TL, p95 ~2 TL; lpg max ±2.5 TL, p95 ~1.6 TL
_CLIP_LIMITS = {
    "benzin":  {"first_event": 2.50, "net_3d": 4.00},
    "motorin": {"first_event": 2.50, "net_3d": 4.00},
    "lpg":     {"first_event": 1.50, "net_3d": 2.50},
}

# Kalibrasyon modulu paralel gelistiriliyor (TASK-053)."""

if old_imports_end in content:
    content = content.replace(old_imports_end, new_imports_end)
    print("✅ Değişiklik 2a: _CLIP_LIMITS eklendi")
else:
    print("⚠️ Değişiklik 2a: imports hedef bulunamadı")

# Stage-2 first_event clipping (predict fonksiyonu içinde)
old_first = '''                first_event_amount = float(stage2_first.predict(X)[0])
                first_event_direction = 1 if first_event_amount > 0 else -1'''

new_first = '''                first_event_amount = float(stage2_first.predict(X)[0])
                # Stage-2 output clipping
                clip_limit = _CLIP_LIMITS.get(fuel_type, _CLIP_LIMITS["benzin"])
                first_event_amount = float(np.clip(first_event_amount, -clip_limit["first_event"], clip_limit["first_event"]))
                first_event_direction = 1 if first_event_amount > 0 else -1'''

if old_first in content:
    content = content.replace(old_first, new_first)
    print("✅ Değişiklik 2b: first_event clipping eklendi")
else:
    print("⚠️ Değişiklik 2b: first_event hedef bulunamadı")

# Stage-2 net_amount clipping
old_net = '''                net_amount_3d = float(stage2_net.predict(X)[0])'''

new_net = '''                net_amount_3d_raw = float(stage2_net.predict(X)[0])
                clip_limit_net = _CLIP_LIMITS.get(fuel_type, _CLIP_LIMITS["benzin"])
                net_amount_3d = float(np.clip(net_amount_3d_raw, -clip_limit_net["net_3d"], clip_limit_net["net_3d"]))
                if abs(net_amount_3d_raw - net_amount_3d) > 0.001:
                    logger.info("Stage-2 net clipped: %.4f -> %.4f", net_amount_3d_raw, net_amount_3d)'''

# Bu sadece stage2_net bloğundaki net_amount_3d satırı
# İki yer var ama sadece stage2_net bloğundaki hedefleniyor
# Daha spesifik context ile
old_net_ctx = '''            try:
                net_amount_3d = float(stage2_net.predict(X)[0])
            except Exception as exc:
                logger.warning("Stage-2 net_amount hatasi: %s — %s", fuel_type, exc)
                net_amount_3d = 0.0'''

new_net_ctx = '''            try:
                net_amount_3d_raw = float(stage2_net.predict(X)[0])
                clip_limit_net = _CLIP_LIMITS.get(fuel_type, _CLIP_LIMITS["benzin"])
                net_amount_3d = float(np.clip(net_amount_3d_raw, -clip_limit_net["net_3d"], clip_limit_net["net_3d"]))
                if abs(net_amount_3d_raw - net_amount_3d) > 0.001:
                    logger.info("Stage-2 net clipped: %.4f -> %.4f", net_amount_3d_raw, net_amount_3d)
            except Exception as exc:
                logger.warning("Stage-2 net_amount hatasi: %s — %s", fuel_type, exc)
                net_amount_3d = 0.0'''

if old_net_ctx in content:
    content = content.replace(old_net_ctx, new_net_ctx)
    print("✅ Değişiklik 2c: net_amount_3d clipping eklendi")
else:
    print("⚠️ Değişiklik 2c: net_amount hedef bulunamadı")

# ======================================================================
# Yazma
# ======================================================================
if content != original:
    with open(FILE, "w") as f:
        f.write(content)
    print("\n✅ predictor.py güncellendi!")
else:
    print("\n⚠️ Hiçbir değişiklik yapılmadı!")
