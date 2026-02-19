from decimal import Decimal

# Label
THRESHOLD_TL = Decimal("0.15")  # v6: 0.25 -> 0.15 (daha hassas yakalama)
LABEL_WINDOW = 3  # D+1..D+3 takvim günü

# CV
MIN_TRAIN_DAYS = 365  # takvim günü
TEST_DAYS = 90
STEP_DAYS = 90
EMBARGO_DAYS = 4

# Feature
FF_MAX_LOOKBACK = 15  # takvim günü forward-fill max
FUEL_TYPES = ["benzin", "motorin", "lpg"]

# Pipeline
PIPELINE_HOUR = "18:30"  # TSİ

# Alarm — v6 dual threshold sistemi
ALARM_THRESHOLD = Decimal("0.25")       # Kalibre olasılık eşiği (0.55 -> 0.25)
ALARM_THRESHOLD_RAW = Decimal("0.45")   # Raw probability eşiği (yedek)
COOLDOWN_HOURS = 12                       # 24h -> 12h

# Kalibrasyon bypass
USE_CALIBRATION = False  # v6: Kalibrasyon devre dışı, raw probability kullan

# Model paths
MODEL_DIR = "models/v5"
# Her yakıt tipi için: {fuel}_stage1.joblib, {fuel}_stage2_first.joblib, {fuel}_stage2_net.joblib, {fuel}_calibrator.joblib

# Feature listesi (MERKEZİ — features.py ve trainer.py bunu kullanır)
FEATURE_NAMES = [
    # Brent
    "brent_close", "brent_return_1d", "brent_sma_5", "brent_sma_10", "brent_vol_5d",
    # FX
    "fx_close", "fx_return_1d", "fx_sma_5", "fx_sma_10", "fx_vol_5d",
    # CIF proxy
    "cif_proxy", "cif_proxy_return_1d",
    # MBE
    "mbe_value", "mbe_pct", "mbe_sma_5", "mbe_sma_10", "delta_mbe", "delta_mbe_3d",
    # NC
    "nc_forward", "nc_sma_3", "nc_sma_5",
    # Risk
    "risk_composite", "risk_mbe_comp", "risk_fx_comp", "risk_trend_comp",
    # Cost
    "cost_gap_tl", "cost_gap_pct", "otv_component_tl",
    # Temporal
    "days_since_last_change", "day_of_week", "is_weekend",
    # Staleness
    "mbe_stale", "nc_stale", "brent_stale", "fx_stale", "cif_stale",
    # === v6 YENİ FEATURE'LAR (13 adet) ===
    # Kümülatif MBE
    "mbe_cumulative_5d", "mbe_cumulative_10d",
    # Maliyet farkı genişleme
    "cost_gap_expanding_days",
    # Fiyat değişim aralığı ve büyüklüğü
    "avg_change_interval", "last_change_amount", "last_change_direction",
    # Son pompadan beri değişimler
    "brent_change_since_last_pump", "fx_change_since_last_pump", "cost_base_change_since_last_pump",
    # Momentum/ROC
    "mbe_roc_3d", "cost_gap_roc_3d",
    # Etkileşim
    "brent_fx_interaction",
    # Z-score
    "fx_rate_zscore_20d",
]
