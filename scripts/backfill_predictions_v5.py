#!/usr/bin/env python3
"""
Backfill Predictions v5 — Look-Ahead Bias Free Tahmin Üretimi.

Bu script:
  1. predictions_v5 tablosundaki unique constraint'i günceller
     (run_date, fuel_type) → (run_date, fuel_type, model_version)
  2. Cutoff tarihine (2026-01-18) kadar olan verilerle backfill modelleri eğitir
  3. 2026-01-19 ~ 2026-02-18 arası için look-ahead bias olmadan tahmin üretir
  4. Tahminleri predictions_v5 tablosuna model_version="v5-backfill" ile yazar

Kullanım:
    cd /var/www/yakit_analiz
    .venv/bin/python scripts/backfill_predictions_v5.py
    .venv/bin/python scripts/backfill_predictions_v5.py --dry-run   # sadece kontrol

CRITICAL: Look-ahead bias önleme:
    - Eğitim verisi: 2022-01-01 ~ 2026-01-18 (cutoff dahil)
    - Modeller: models/backfill/ dizinine kaydedilir (models/v5/ ile karışmaz)
    - Tahminler: 2026-01-19 ~ 2026-02-18 (feature'lar sadece geçmişe bakar)

Yazar: Claude Code
Tarih: 2026-02-18
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import psycopg2
import psycopg2.extras

# ── Proje root'unu path'e ekle ──────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# .env yükleme
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass  # dotenv yoksa ortam değişkenleri zaten set edilmiş olmalı

# ── Yapılandırma ─────────────────────────────────────────────────────────────

DB_URL = os.environ.get(
    "DATABASE_URL_SYNC",
    "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi",
)

# Tarih sabitleri — CRITICAL
TRAIN_START = date(2022, 1, 1)
CUTOFF_DATE = date(2026, 1, 19)       # İlk tahmin günü
TRAIN_END = date(2026, 1, 18)         # Eğitim bitiş (cutoff - 1)
BACKFILL_START = date(2026, 1, 19)    # İlk tahmin
BACKFILL_END = date(2026, 2, 18)      # Son tahmin

FUEL_TYPES = ["benzin", "motorin", "lpg"]

MODEL_DIR = Path(PROJECT_ROOT) / "models" / "backfill"
MODEL_VERSION = "v5-backfill"

# Stage-1 eşik
STAGE1_THRESHOLD = 0.55

# Clipping limitleri
CLIP_LIMITS = {
    "benzin": {"first_event": 2.50, "net_3d": 4.00},
    "motorin": {"first_event": 2.50, "net_3d": 4.00},
    "lpg": {"first_event": 1.50, "net_3d": 2.50},
}

# LightGBM hiperparametreleri — Stage-1 (Binary Classifier)
PARAMS_STAGE1 = {
    "objective": "binary",
    "metric": "binary_logloss",
    "num_leaves": 63,
    "max_depth": 7,
    "learning_rate": 0.05,
    "n_estimators": 400,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.3,
    "reg_lambda": 0.3,
    "min_child_samples": 20,
    "scale_pos_weight": 3.0,
    "verbose": -1,
    "force_col_wise": True,
    "random_state": 42,
}

# LightGBM hiperparametreleri — Stage-2 (Regressor)
PARAMS_STAGE2 = {
    "objective": "regression",
    "metric": "mae",
    "num_leaves": 31,
    "max_depth": 6,
    "learning_rate": 0.03,
    "n_estimators": 300,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "reg_alpha": 0.3,
    "reg_lambda": 0.3,
    "min_child_samples": 10,
    "verbose": -1,
    "force_col_wise": True,
    "random_state": 42,
}

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill-v5")

# Gürültülü logger'ları sustur
logging.getLogger("lightgbm").setLevel(logging.WARNING)


# ══════════════════════════════════════════════════════════════════════════════
# YARDIMCI FONKSİYONLAR
# ══════════════════════════════════════════════════════════════════════════════


def get_db_connection() -> psycopg2.extensions.connection:
    """Sync psycopg2 DB bağlantısı döner."""
    return psycopg2.connect(DB_URL)


def import_v5_modules():
    """
    v5 predictor modüllerini import eder.

    Returns:
        (compute_labels, compute_features_bulk, FEATURE_NAMES) tuple
    """
    from src.predictor_v5.labels import compute_labels
    from src.predictor_v5.features import compute_features_bulk
    from src.predictor_v5.config import FEATURE_NAMES
    return compute_labels, compute_features_bulk, FEATURE_NAMES


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0: DB SCHEMA UPDATE
# ══════════════════════════════════════════════════════════════════════════════


def phase0_update_schema(dry_run: bool = False) -> bool:
    """
    predictions_v5 tablosundaki unique constraint'i günceller.

    Adımlar:
    1. model_version kolonuna DEFAULT 'v5' ekle, NOT NULL yap
    2. NULL model_version kayıtlarını 'v5' olarak güncelle
    3. Eski constraint'i kaldır (run_date, fuel_type)
    4. Yeni constraint ekle (run_date, fuel_type, model_version)
    """
    logger.info("=" * 70)
    logger.info("PHASE 0: DB Schema Update")
    logger.info("=" * 70)

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Mevcut constraint'leri kontrol et
            cur.execute("""
                SELECT conname, pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'predictions_v5'::regclass
                  AND contype = 'u'
            """)
            constraints = cur.fetchall()
            logger.info("Mevcut unique constraint'ler: %s", constraints)

            # Yeni constraint zaten var mı?
            new_constraint_exists = any(
                "model_version" in (c[1] or "") for c in constraints
            )

            if new_constraint_exists:
                logger.info("Yeni constraint zaten mevcut — schema update atlanıyor")
                conn.rollback()
                return True

            if dry_run:
                logger.info("[DRY-RUN] Schema güncellemesi yapılacaktı:")
                logger.info("  1. model_version DEFAULT 'v5' NOT NULL yapılacak")
                logger.info("  2. NULL model_version → 'v5' güncellenecek")
                logger.info("  3. Eski constraint kaldırılacak")
                logger.info("  4. Yeni constraint (run_date, fuel_type, model_version) eklenecek")
                conn.rollback()
                return True

            # 1. model_version kolonunu NOT NULL + DEFAULT 'v5' yap
            logger.info("model_version kolonu güncelleniyor...")
            cur.execute("""
                ALTER TABLE predictions_v5
                ALTER COLUMN model_version SET DEFAULT 'v5'
            """)

            # 2. NULL model_version kayıtlarını güncelle
            cur.execute("""
                UPDATE predictions_v5
                SET model_version = 'v5'
                WHERE model_version IS NULL
            """)
            updated = cur.rowcount
            logger.info("  %d kayıtta model_version NULL → 'v5' güncellendi", updated)

            # NOT NULL constraint ekle
            cur.execute("""
                ALTER TABLE predictions_v5
                ALTER COLUMN model_version SET NOT NULL
            """)

            # 3. Eski constraint'i kaldır
            old_constraint_name = None
            for cname, cdef in constraints:
                if "model_version" not in (cdef or ""):
                    old_constraint_name = cname
                    break

            if old_constraint_name:
                logger.info("Eski constraint kaldırılıyor: %s", old_constraint_name)
                cur.execute(
                    f"ALTER TABLE predictions_v5 DROP CONSTRAINT {old_constraint_name}"
                )
            else:
                logger.warning("Kaldırılacak eski constraint bulunamadı")

            # 4. Yeni constraint ekle
            logger.info("Yeni constraint ekleniyor: uq_predictions_v5_run_fuel_version")
            cur.execute("""
                ALTER TABLE predictions_v5
                ADD CONSTRAINT uq_predictions_v5_run_fuel_version
                UNIQUE (run_date, fuel_type, model_version)
            """)

            conn.commit()
            logger.info("Schema update tamamlandı")
            return True

    except Exception as e:
        conn.rollback()
        logger.error("Schema update hatası: %s", e)
        traceback.print_exc()
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: TRAIN BACKFILL MODELS
# ══════════════════════════════════════════════════════════════════════════════


def phase1_train_models(dry_run: bool = False) -> dict[str, dict]:
    """
    Her yakıt tipi için backfill modelleri eğitir (cutoff: 2026-01-18).

    Returns:
        {fuel_type: {"stage1": model, "stage2_first": model, "stage2_net": model,
                     "calibrator": calibrator, "feature_names": list, "metrics": dict}}
    """
    import joblib
    from lightgbm import LGBMClassifier, LGBMRegressor
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import TimeSeriesSplit

    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 1: Backfill Model Eğitimi")
    logger.info("  Eğitim aralığı: %s → %s", TRAIN_START, TRAIN_END)
    logger.info("  Cutoff (ilk tahmin): %s", CUTOFF_DATE)
    logger.info("  Model dizini: %s", MODEL_DIR)
    logger.info("=" * 70)

    compute_labels, compute_features_bulk, FEATURE_NAMES = import_v5_modules()

    # Model dizinini oluştur
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    trained_models: dict[str, dict] = {}

    for fuel_type in FUEL_TYPES:
        logger.info("")
        logger.info("━" * 50)
        logger.info("[%s] Eğitim başlıyor...", fuel_type.upper())
        logger.info("━" * 50)

        try:
            t0 = time.time()

            # ── 1. Label üretimi ──
            logger.info("[%s] Label üretimi: %s → %s", fuel_type, TRAIN_START, TRAIN_END)
            labels_df = compute_labels(fuel_type, TRAIN_START, TRAIN_END)

            if labels_df.empty:
                logger.error("[%s] Label üretilemedi — atlanıyor", fuel_type)
                continue

            logger.info(
                "[%s] Labels: %d satır, %d pozitif (%.1f%%)",
                fuel_type, len(labels_df),
                labels_df["y_binary"].sum(),
                100 * labels_df["y_binary"].mean(),
            )

            # ── 2. Feature üretimi ──
            logger.info("[%s] Feature üretimi: %s → %s", fuel_type, TRAIN_START, TRAIN_END)
            features_df = compute_features_bulk(fuel_type, TRAIN_START, TRAIN_END, dsn=DB_URL)

            if features_df is None or features_df.empty:
                logger.error("[%s] Feature üretilemedi — atlanıyor", fuel_type)
                continue

            logger.info("[%s] Features: %d satır, %d kolon", fuel_type, len(features_df), len(features_df.columns))

            # ── 3. Label ve feature'ları tarih üzerinden hizala ──
            # labels_df.run_date ve features_df.run_date (veya trade_date) üzerinden join
            # Feature DF'de kolon adı "run_date" veya "trade_date" olabilir
            feat_date_col = "run_date" if "run_date" in features_df.columns else "trade_date"

            # Her iki DF'nin tarih kolonlarını date tipine çevir
            import pandas as pd
            labels_df["_join_date"] = pd.to_datetime(labels_df["run_date"]).dt.date
            features_df["_join_date"] = pd.to_datetime(features_df[feat_date_col]).dt.date

            merged = pd.merge(
                labels_df, features_df,
                on="_join_date", how="inner", suffixes=("_label", "_feat"),
            )

            logger.info("[%s] Merge sonrası: %d satır", fuel_type, len(merged))

            if len(merged) < 50:
                logger.error(
                    "[%s] Yetersiz eğitim verisi (%d < 50) — atlanıyor",
                    fuel_type, len(merged),
                )
                continue

            # ── 4. Feature matrix ve label vektörleri ──
            # Feature kolonları: FEATURE_NAMES listesindeki kolonlar
            available_features = [f for f in FEATURE_NAMES if f in merged.columns]
            if len(available_features) < len(FEATURE_NAMES):
                missing = set(FEATURE_NAMES) - set(available_features)
                logger.warning(
                    "[%s] %d feature eksik: %s — sıfır ile doldurulacak",
                    fuel_type, len(missing), missing,
                )
                for f in missing:
                    merged[f] = 0.0
                available_features = FEATURE_NAMES

            X = merged[FEATURE_NAMES].values.astype(np.float64)
            y_binary = merged["y_binary"].values.astype(np.int32)
            y_first = merged["first_event_amount"].astype(float).values.astype(np.float64)
            y_net = merged["net_amount_3d"].astype(float).values.astype(np.float64)

            # NaN kontrolü
            nan_mask = np.isnan(X).any(axis=1)
            if nan_mask.any():
                logger.warning(
                    "[%s] %d satırda NaN var — kaldırılıyor",
                    fuel_type, nan_mask.sum(),
                )
                valid = ~nan_mask
                X = X[valid]
                y_binary = y_binary[valid]
                y_first = y_first[valid]
                y_net = y_net[valid]

            n_pos = y_binary.sum()
            n_neg = len(y_binary) - n_pos
            logger.info(
                "[%s] Final: %d satır (%d pozitif, %d negatif, oran=%.2f%%)",
                fuel_type, len(y_binary), n_pos, n_neg,
                100 * n_pos / len(y_binary) if len(y_binary) > 0 else 0,
            )

            if dry_run:
                logger.info("[DRY-RUN] [%s] Model eğitimi atlanıyor", fuel_type)
                continue

            # ── 5. Stage-1: Binary Classifier (TimeSeriesSplit + CV) ──
            logger.info("[%s] Stage-1 eğitimi başlıyor...", fuel_type)

            # Scale pos weight hesapla
            params_s1 = PARAMS_STAGE1.copy()
            if n_pos > 0 and n_neg > 0:
                params_s1["scale_pos_weight"] = max(1.0, min(10.0, n_neg / n_pos))
                logger.info(
                    "[%s] scale_pos_weight = %.2f",
                    fuel_type, params_s1["scale_pos_weight"],
                )

            # TimeSeriesSplit CV — cross-validated probability'ler kalibrasyon için
            n_splits = min(5, len(X) // 60)
            if n_splits < 2:
                n_splits = 2

            tscv = TimeSeriesSplit(n_splits=n_splits, test_size=30, gap=7)

            cv_probs = np.zeros(len(y_binary))
            cv_mask = np.zeros(len(y_binary), dtype=bool)

            for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
                X_tr, X_te = X[train_idx], X[test_idx]
                y_tr = y_binary[train_idx]

                clf_fold = LGBMClassifier(**params_s1)
                clf_fold.fit(X_tr, y_tr)

                prob_fold = clf_fold.predict_proba(X_te)[:, 1]
                cv_probs[test_idx] = prob_fold
                cv_mask[test_idx] = True

                logger.info(
                    "[%s] Stage-1 Fold %d: test=%d, mean_prob=%.3f",
                    fuel_type, fold + 1, len(test_idx), prob_fold.mean(),
                )

            # Final Stage-1 model — tüm veri üzerinde eğit
            stage1_clf = LGBMClassifier(**params_s1)
            stage1_clf.fit(X, y_binary)

            # ── 6. Stage-2: Regressors (sadece pozitif örneklerde) ──
            logger.info("[%s] Stage-2 eğitimi başlıyor...", fuel_type)

            pos_mask = y_binary == 1
            X_pos = X[pos_mask]
            y_first_pos = y_first[pos_mask]
            y_net_pos = y_net[pos_mask]

            stage2_first = None
            stage2_net = None

            if len(X_pos) >= 10:
                stage2_first = LGBMRegressor(**PARAMS_STAGE2)
                stage2_first.fit(X_pos, y_first_pos)

                stage2_net = LGBMRegressor(**PARAMS_STAGE2)
                stage2_net.fit(X_pos, y_net_pos)

                logger.info(
                    "[%s] Stage-2 eğitildi: %d pozitif örnek",
                    fuel_type, len(X_pos),
                )
            else:
                logger.warning(
                    "[%s] Yetersiz pozitif örnek (%d < 10) — Stage-2 eğitilmedi",
                    fuel_type, len(X_pos),
                )

            # ── 7. Kalibrasyon ──
            logger.info("[%s] Kalibrasyon başlıyor...", fuel_type)

            calibrator = None
            if cv_mask.any():
                cv_y = y_binary[cv_mask]
                cv_p = cv_probs[cv_mask]

                try:
                    from src.predictor_v5.calibration import auto_calibrate
                    calibrator = auto_calibrate(cv_y, cv_p)
                    logger.info("[%s] Kalibrasyon tamamlandı (v5 auto_calibrate)", fuel_type)
                except (ImportError, Exception) as e:
                    logger.warning(
                        "[%s] v5 auto_calibrate başarısız: %s — sklearn IsotonicRegression ile devam",
                        fuel_type, e,
                    )
                    try:
                        from sklearn.isotonic import IsotonicRegression
                        calibrator = IsotonicRegression(
                            y_min=0.0, y_max=1.0, out_of_bounds="clip"
                        )
                        calibrator.fit(cv_p, cv_y)
                        logger.info("[%s] Kalibrasyon tamamlandı (IsotonicRegression)", fuel_type)
                    except Exception as e2:
                        logger.warning("[%s] Kalibrasyon başarısız: %s", fuel_type, e2)

            # ── 8. Modelleri kaydet ──
            logger.info("[%s] Modeller kaydediliyor...", fuel_type)

            joblib.dump(stage1_clf, MODEL_DIR / f"{fuel_type}_stage1.joblib")
            logger.info("  %s_stage1.joblib kaydedildi", fuel_type)

            if stage2_first is not None:
                joblib.dump(stage2_first, MODEL_DIR / f"{fuel_type}_stage2_first.joblib")
                logger.info("  %s_stage2_first.joblib kaydedildi", fuel_type)

            if stage2_net is not None:
                joblib.dump(stage2_net, MODEL_DIR / f"{fuel_type}_stage2_net.joblib")
                logger.info("  %s_stage2_net.joblib kaydedildi", fuel_type)

            if calibrator is not None:
                joblib.dump(calibrator, MODEL_DIR / f"{fuel_type}_calibrator.joblib")
                logger.info("  %s_calibrator.joblib kaydedildi", fuel_type)

            elapsed = time.time() - t0
            logger.info(
                "[%s] Eğitim tamamlandı: %.1f saniye", fuel_type, elapsed,
            )

            trained_models[fuel_type] = {
                "stage1": stage1_clf,
                "stage2_first": stage2_first,
                "stage2_net": stage2_net,
                "calibrator": calibrator,
                "feature_names": FEATURE_NAMES,
                "metrics": {
                    "n_train": len(X),
                    "n_positive": int(n_pos),
                    "n_splits": n_splits,
                    "elapsed_sec": round(elapsed, 1),
                },
            }

        except Exception as e:
            logger.error("[%s] Eğitim hatası: %s", fuel_type, e)
            traceback.print_exc()
            continue

    logger.info("")
    logger.info("Phase 1 tamamlandı: %d/%d model eğitildi", len(trained_models), len(FUEL_TYPES))
    return trained_models


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: GENERATE BACKFILL PREDICTIONS
# ══════════════════════════════════════════════════════════════════════════════


def phase2_generate_predictions(
    trained_models: dict[str, dict],
    dry_run: bool = False,
) -> list[dict]:
    """
    Backfill modelleri ile 2026-01-19 ~ 2026-02-18 arası tahmin üretir.

    Returns:
        Prediction record listesi
    """
    import joblib

    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 2: Backfill Tahmin Üretimi")
    logger.info("  Tahmin aralığı: %s → %s", BACKFILL_START, BACKFILL_END)
    logger.info("=" * 70)

    _, compute_features_bulk, FEATURE_NAMES = import_v5_modules()

    # Modeller eğitilmemişse dosyadan yükle
    for fuel_type in FUEL_TYPES:
        if fuel_type not in trained_models:
            logger.info("[%s] Bellekte model yok — dosyadan yükleniyor...", fuel_type)
            stage1_path = MODEL_DIR / f"{fuel_type}_stage1.joblib"
            if stage1_path.exists():
                trained_models[fuel_type] = {
                    "stage1": joblib.load(stage1_path),
                    "stage2_first": None,
                    "stage2_net": None,
                    "calibrator": None,
                    "feature_names": FEATURE_NAMES,
                }
                s2f_path = MODEL_DIR / f"{fuel_type}_stage2_first.joblib"
                s2n_path = MODEL_DIR / f"{fuel_type}_stage2_net.joblib"
                cal_path = MODEL_DIR / f"{fuel_type}_calibrator.joblib"
                if s2f_path.exists():
                    trained_models[fuel_type]["stage2_first"] = joblib.load(s2f_path)
                if s2n_path.exists():
                    trained_models[fuel_type]["stage2_net"] = joblib.load(s2n_path)
                if cal_path.exists():
                    trained_models[fuel_type]["calibrator"] = joblib.load(cal_path)
                logger.info("[%s] Model dosyadan yüklendi", fuel_type)
            else:
                logger.error("[%s] Model dosyası bulunamadı: %s", fuel_type, stage1_path)

    predictions: list[dict] = []

    # Her yakıt tipi için feature'ları toplu hesapla (performans için)
    fuel_features: dict[str, dict] = {}

    for fuel_type in FUEL_TYPES:
        if fuel_type not in trained_models:
            logger.warning("[%s] Model mevcut değil — atlanıyor", fuel_type)
            continue

        logger.info("[%s] Feature üretimi: %s → %s", fuel_type, BACKFILL_START, BACKFILL_END)

        try:
            features_df = compute_features_bulk(
                fuel_type, BACKFILL_START, BACKFILL_END, dsn=DB_URL,
            )

            if features_df is not None and not features_df.empty:
                # Tarih bazlı index oluştur
                import pandas as pd
                feat_date_col = "run_date" if "run_date" in features_df.columns else "trade_date"
                features_df["_date"] = pd.to_datetime(features_df[feat_date_col]).dt.date
                fuel_features[fuel_type] = {
                    row["_date"]: row
                    for _, row in features_df.iterrows()
                }
                logger.info(
                    "[%s] %d gün feature üretildi",
                    fuel_type, len(fuel_features[fuel_type]),
                )
            else:
                logger.warning("[%s] Feature üretilemedi", fuel_type)
                fuel_features[fuel_type] = {}

        except Exception as e:
            logger.error("[%s] Feature üretimi hatası: %s", fuel_type, e)
            traceback.print_exc()
            fuel_features[fuel_type] = {}

    # Her gün için tahmin üret
    total_days = (BACKFILL_END - BACKFILL_START).days + 1
    logger.info("")
    logger.info("Tahmin üretimi başlıyor: %d gün x %d yakıt tipi", total_days, len(FUEL_TYPES))

    current_date = BACKFILL_START
    while current_date <= BACKFILL_END:
        for fuel_type in FUEL_TYPES:
            if fuel_type not in trained_models:
                continue

            try:
                model_info = trained_models[fuel_type]
                stage1 = model_info["stage1"]
                stage2_first = model_info.get("stage2_first")
                stage2_net = model_info.get("stage2_net")
                calibrator = model_info.get("calibrator")

                # Feature'ları al
                date_features = fuel_features.get(fuel_type, {}).get(current_date)
                if date_features is None:
                    logger.debug(
                        "[%s] %s — feature yok, atlanıyor",
                        fuel_type, current_date,
                    )
                    continue

                # Feature vektörü oluştur
                X = np.array(
                    [[float(date_features.get(f, 0.0)) for f in FEATURE_NAMES]],
                    dtype=np.float64,
                )

                # NaN kontrolü
                if np.isnan(X).any():
                    X = np.nan_to_num(X, nan=0.0)

                # Stage-1: Binary prediction
                stage1_prob_raw = float(stage1.predict_proba(X)[:, 1][0])

                # Kalibrasyon
                if calibrator is not None:
                    try:
                        # calibrator.predict() veya calibrator.transform() olabilir
                        if hasattr(calibrator, "predict"):
                            stage1_prob = float(calibrator.predict([stage1_prob_raw])[0])
                        elif hasattr(calibrator, "transform"):
                            stage1_prob = float(calibrator.transform([stage1_prob_raw])[0])
                        else:
                            stage1_prob = stage1_prob_raw
                    except Exception:
                        stage1_prob = stage1_prob_raw
                else:
                    stage1_prob = stage1_prob_raw

                # Probability sınırlama [0, 1]
                stage1_prob = max(0.0, min(1.0, stage1_prob))

                stage1_label = bool(stage1_prob >= STAGE1_THRESHOLD)

                # Stage-2: Regression (sadece pozitif tahminlerde)
                first_event_amount = 0.0
                net_amount_3d = 0.0
                first_event_direction = 0
                first_event_type = "none"

                if stage1_label == 1 and stage2_first is not None and stage2_net is not None:
                    first_event_amount = float(stage2_first.predict(X)[0])
                    net_amount_3d = float(stage2_net.predict(X)[0])

                    # Clipping
                    clip = CLIP_LIMITS[fuel_type]
                    first_event_amount = max(
                        -clip["first_event"],
                        min(clip["first_event"], first_event_amount),
                    )
                    net_amount_3d = max(
                        -clip["net_3d"],
                        min(clip["net_3d"], net_amount_3d),
                    )

                    # Direction
                    if abs(first_event_amount) >= 0.01:
                        first_event_direction = 1 if first_event_amount > 0 else -1
                        first_event_type = "predicted"

                # Alarm logic
                alarm_triggered = bool(stage1_prob >= STAGE1_THRESHOLD)
                alarm_message = None
                if alarm_triggered:
                    direction_str = "ZAM" if first_event_direction >= 0 else "INDIRIM"
                    alarm_message = (
                        f"{fuel_type.upper()} {direction_str} beklentisi: "
                        f"p={stage1_prob:.2f}, "
                        f"ilk_hareket={first_event_amount:+.2f} TL, "
                        f"net_3g={net_amount_3d:+.2f} TL"
                    )

                prediction = {
                    "run_date": current_date,
                    "fuel_type": fuel_type,
                    "stage1_probability": round(stage1_prob, 6),
                    "stage1_label": stage1_label,
                    "first_event_direction": first_event_direction,
                    "first_event_amount": round(first_event_amount, 4),
                    "first_event_type": first_event_type,
                    "net_amount_3d": round(net_amount_3d, 4),
                    "model_version": MODEL_VERSION,
                    "calibration_method": (
                        "isotonic" if calibrator is not None else "none"
                    ),
                    "alarm_triggered": alarm_triggered,
                    "alarm_suppressed": False,
                    "suppression_reason": None,
                    "alarm_message": alarm_message,
                }

                predictions.append(prediction)

            except Exception as e:
                logger.error(
                    "[%s] %s tahmin hatası: %s",
                    fuel_type, current_date, e,
                )
                traceback.print_exc()
                continue

        current_date += timedelta(days=1)

    logger.info("")
    logger.info("Phase 2 tamamlandı: %d tahmin üretildi", len(predictions))

    # İstatistikler
    for fuel_type in FUEL_TYPES:
        ft_preds = [p for p in predictions if p["fuel_type"] == fuel_type]
        if ft_preds:
            n_alarm = sum(1 for p in ft_preds if p["alarm_triggered"])
            avg_prob = sum(p["stage1_probability"] for p in ft_preds) / len(ft_preds)
            logger.info(
                "  %s: %d tahmin, %d alarm (%.1f%%), ortalama prob=%.3f",
                fuel_type, len(ft_preds), n_alarm,
                100 * n_alarm / len(ft_preds), avg_prob,
            )

    return predictions


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: WRITE TO DB
# ══════════════════════════════════════════════════════════════════════════════


UPSERT_SQL = """
    INSERT INTO predictions_v5 (
        run_date, fuel_type, stage1_probability, stage1_label,
        first_event_direction, first_event_amount, first_event_type,
        net_amount_3d, model_version, calibration_method,
        alarm_triggered, alarm_suppressed, suppression_reason, alarm_message
    ) VALUES (
        %(run_date)s, %(fuel_type)s, %(stage1_probability)s, %(stage1_label)s,
        %(first_event_direction)s, %(first_event_amount)s, %(first_event_type)s,
        %(net_amount_3d)s, %(model_version)s, %(calibration_method)s,
        %(alarm_triggered)s, %(alarm_suppressed)s, %(suppression_reason)s, %(alarm_message)s
    )
    ON CONFLICT ON CONSTRAINT uq_predictions_v5_run_fuel_version
    DO UPDATE SET
        stage1_probability = EXCLUDED.stage1_probability,
        stage1_label = EXCLUDED.stage1_label,
        first_event_direction = EXCLUDED.first_event_direction,
        first_event_amount = EXCLUDED.first_event_amount,
        first_event_type = EXCLUDED.first_event_type,
        net_amount_3d = EXCLUDED.net_amount_3d,
        calibration_method = EXCLUDED.calibration_method,
        alarm_triggered = EXCLUDED.alarm_triggered,
        alarm_suppressed = EXCLUDED.alarm_suppressed,
        suppression_reason = EXCLUDED.suppression_reason,
        alarm_message = EXCLUDED.alarm_message
"""


def phase3_write_to_db(predictions: list[dict], dry_run: bool = False) -> dict:
    """
    Tahminleri predictions_v5 tablosuna yazar.

    Returns:
        {"success": N, "failed": N, "total": N}
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 3: DB Yazımı")
    logger.info("  Yazılacak tahmin sayısı: %d", len(predictions))
    logger.info("=" * 70)

    if not predictions:
        logger.warning("Yazılacak tahmin yok!")
        return {"success": 0, "failed": 0, "total": 0}

    if dry_run:
        logger.info("[DRY-RUN] %d tahmin DB'ye yazılacaktı", len(predictions))
        for p in predictions[:5]:
            logger.info(
                "  %s | %s | prob=%.3f | label=%d | first=%+.2f | net=%+.2f",
                p["run_date"], p["fuel_type"],
                p["stage1_probability"], p["stage1_label"],
                p["first_event_amount"], p["net_amount_3d"],
            )
        if len(predictions) > 5:
            logger.info("  ... ve %d tahmin daha", len(predictions) - 5)
        return {"success": 0, "failed": 0, "total": len(predictions), "dry_run": True}

    conn = get_db_connection()
    success = 0
    failed = 0

    try:
        with conn.cursor() as cur:
            for i, pred in enumerate(predictions):
                try:
                    cur.execute(UPSERT_SQL, pred)
                    success += 1
                except Exception as e:
                    logger.error(
                        "  UPSERT hatası [%s/%s]: %s",
                        pred["run_date"], pred["fuel_type"], e,
                    )
                    conn.rollback()
                    failed += 1

                # Her 50 tahminde bir commit
                if (i + 1) % 50 == 0:
                    conn.commit()
                    logger.info(
                        "  İlerleme: %d/%d (%d%%)",
                        i + 1, len(predictions),
                        int((i + 1) / len(predictions) * 100),
                    )

            # Son commit
            conn.commit()

    except Exception as e:
        conn.rollback()
        logger.error("DB yazım hatası: %s", e)
        traceback.print_exc()
    finally:
        conn.close()

    logger.info("DB yazımı tamamlandı: %d başarılı, %d başarısız", success, failed)
    return {"success": success, "failed": failed, "total": len(predictions)}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: VERIFY
# ══════════════════════════════════════════════════════════════════════════════


def phase4_verify():
    """
    Yazılan tahminleri doğrular ve özet rapor yazdırır.
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info("PHASE 4: Doğrulama")
    logger.info("=" * 70)

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            # 1. model_version bazında dağılım
            cur.execute("""
                SELECT model_version, count(*) AS cnt,
                       MIN(run_date) AS min_date, MAX(run_date) AS max_date,
                       AVG(stage1_probability) AS avg_prob,
                       SUM(CASE WHEN alarm_triggered THEN 1 ELSE 0 END) AS alarm_count
                FROM predictions_v5
                GROUP BY model_version
                ORDER BY model_version
            """)
            rows = cur.fetchall()

            logger.info("")
            logger.info("Model version bazında dağılım:")
            for row in rows:
                logger.info(
                    "  %s: %d tahmin [%s ~ %s] avg_prob=%.3f alarms=%d",
                    row["model_version"], row["cnt"],
                    row["min_date"], row["max_date"],
                    float(row["avg_prob"] or 0),
                    row["alarm_count"],
                )

            # 2. Yakıt tipi bazında (backfill)
            cur.execute("""
                SELECT fuel_type, count(*) AS cnt,
                       AVG(stage1_probability) AS avg_prob,
                       SUM(CASE WHEN alarm_triggered THEN 1 ELSE 0 END) AS alarm_count,
                       AVG(CASE WHEN alarm_triggered THEN first_event_amount ELSE NULL END) AS avg_first,
                       AVG(CASE WHEN alarm_triggered THEN net_amount_3d ELSE NULL END) AS avg_net
                FROM predictions_v5
                WHERE model_version = %s
                GROUP BY fuel_type
                ORDER BY fuel_type
            """, (MODEL_VERSION,))
            ft_rows = cur.fetchall()

            if ft_rows:
                logger.info("")
                logger.info("Backfill tahminleri (model=%s):", MODEL_VERSION)
                for row in ft_rows:
                    logger.info(
                        "  %s: %d tahmin, avg_prob=%.3f, %d alarm, "
                        "avg_first=%s, avg_net=%s",
                        row["fuel_type"], row["cnt"],
                        float(row["avg_prob"] or 0),
                        row["alarm_count"],
                        f"{float(row['avg_first']):+.3f}" if row["avg_first"] else "N/A",
                        f"{float(row['avg_net']):+.3f}" if row["avg_net"] else "N/A",
                    )

            # 3. Örnek tahminler
            cur.execute("""
                SELECT run_date, fuel_type, stage1_probability, stage1_label,
                       first_event_amount, net_amount_3d, alarm_triggered
                FROM predictions_v5
                WHERE model_version = %s
                ORDER BY run_date, fuel_type
                LIMIT 15
            """, (MODEL_VERSION,))
            sample_rows = cur.fetchall()

            if sample_rows:
                logger.info("")
                logger.info("Örnek tahminler (ilk 15):")
                for row in sample_rows:
                    logger.info(
                        "  %s | %s | prob=%.3f | label=%d | first=%+.2f | net=%+.2f | alarm=%s",
                        row["run_date"], row["fuel_type"],
                        float(row["stage1_probability"]),
                        row["stage1_label"],
                        float(row["first_event_amount"] or 0),
                        float(row["net_amount_3d"] or 0),
                        "YES" if row["alarm_triggered"] else "no",
                    )

            # 4. Toplam kayıt
            cur.execute("SELECT count(*) FROM predictions_v5")
            total = cur.fetchone()[0]
            logger.info("")
            logger.info("Toplam predictions_v5 kayıt sayısı: %d", total)

    except Exception as e:
        logger.error("Doğrulama hatası: %s", e)
        traceback.print_exc()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════


def main():
    """Ana fonksiyon — 4 fazı sırayla çalıştırır."""
    parser = argparse.ArgumentParser(
        description="Backfill Predictions v5 — Look-Ahead Bias Free Tahmin Üretimi",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sadece kontrol et, DB'ye yazma",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Eğitimi atla, mevcut modelleri kullan (models/backfill/)",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help="Schema update atla",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Sadece doğrulama yap (Phase 4)",
    )
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("BACKFILL PREDICTIONS v5 BAŞLADI")
    logger.info("  Proje kökü: %s", PROJECT_ROOT)
    logger.info("  DB: %s", DB_URL.split("@")[1] if "@" in DB_URL else "***")
    logger.info("  Eğitim aralığı: %s → %s", TRAIN_START, TRAIN_END)
    logger.info("  Tahmin aralığı: %s → %s", BACKFILL_START, BACKFILL_END)
    logger.info("  Model dizini: %s", MODEL_DIR)
    logger.info("  Model versiyonu: %s", MODEL_VERSION)
    logger.info("  Dry-run: %s", args.dry_run)
    logger.info("=" * 70)

    t_total = time.time()

    if args.verify_only:
        phase4_verify()
        return

    # Phase 0: Schema Update
    if not args.skip_schema:
        if not phase0_update_schema(dry_run=args.dry_run):
            logger.error("Phase 0 başarısız — script durduruluyor")
            sys.exit(1)

    # Phase 1: Train Models
    trained_models: dict[str, dict] = {}
    if not args.skip_train:
        trained_models = phase1_train_models(dry_run=args.dry_run)
        if not trained_models and not args.dry_run:
            logger.error("Phase 1 başarısız — hiçbir model eğitilemedi")
            sys.exit(1)
    else:
        logger.info("Phase 1 atlandı (--skip-train)")

    # Phase 2: Generate Predictions
    predictions = phase2_generate_predictions(trained_models, dry_run=args.dry_run)
    if not predictions and not args.dry_run:
        logger.error("Phase 2 başarısız — hiçbir tahmin üretilemedi")
        sys.exit(1)

    # Phase 3: Write to DB
    result = phase3_write_to_db(predictions, dry_run=args.dry_run)

    # Phase 4: Verify
    if not args.dry_run:
        phase4_verify()

    elapsed_total = time.time() - t_total
    logger.info("")
    logger.info("=" * 70)
    logger.info("BACKFILL PREDICTIONS v5 TAMAMLANDI")
    logger.info("  Toplam süre: %.1f saniye (%.1f dakika)", elapsed_total, elapsed_total / 60)
    logger.info("  Yazım sonucu: %s", result)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
