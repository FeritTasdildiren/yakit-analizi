"""
v5 Hizli Model Egitimi — CV atlanarak direkt final model.
train_all() yerine kullanilir, 9 model dosyasi uretir.
"""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

sys.path.insert(0, '/var/www/yakit_analiz')

from src.predictor_v5.config import FUEL_TYPES, FEATURE_NAMES, MODEL_DIR
from src.predictor_v5.features import compute_features_bulk
from src.predictor_v5.labels import compute_labels

PROJECT_ROOT = Path('/var/www/yakit_analiz')
MODEL_PATH = PROJECT_ROOT / MODEL_DIR


def _compute_scale_pos_weight(y):
    n_pos = int(np.sum(y == 1))
    n_neg = int(np.sum(y == 0))
    return round(n_neg / max(n_pos, 1), 2)


def quick_train():
    end_date = date.today()
    start_date = end_date - timedelta(days=730)
    MODEL_PATH.mkdir(parents=True, exist_ok=True)

    for fuel_type in FUEL_TYPES:
        logger.info('=== %s egitimi basliyor ===', fuel_type.upper())

        # Veri cek
        features_df = compute_features_bulk(fuel_type, start_date, end_date)
        labels_df = compute_labels(fuel_type, start_date, end_date)

        if features_df.empty or labels_df.empty:
            logger.warning('%s: Veri yok, atlaniyor', fuel_type)
            continue

        # Ortak index
        common_dates = features_df.index.intersection(labels_df.index)
        X = features_df.loc[common_dates, list(FEATURE_NAMES)].values
        y_binary = labels_df.loc[common_dates, 'y_binary'].values
        y_first = labels_df.loc[common_dates, 'first_event_amount'].values
        y_net = labels_df.loc[common_dates, 'net_amount_3d'].values

        logger.info('%s: %d ornek, y=1: %d (%.1f%%)',
                    fuel_type, len(X), int(np.sum(y_binary==1)),
                    100 * np.mean(y_binary==1))

        # Stage-1: Binary classifier
        spw = _compute_scale_pos_weight(y_binary)
        logger.info('scale_pos_weight = %.2f', spw)

        stage1 = lgb.LGBMClassifier(
            objective='binary', metric='binary_logloss',
            n_estimators=100, learning_rate=0.05,
            max_depth=6, num_leaves=31, min_child_samples=20,
            scale_pos_weight=spw, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=0.1, random_state=42, verbose=-1, n_jobs=-1
        )
        stage1.fit(X, y_binary)
        s1_path = MODEL_PATH / f'{fuel_type}_stage1.joblib'
        joblib.dump(stage1, s1_path)
        logger.info('Stage-1 kaydedildi: %s', s1_path)

        # Stage-2: Sadece pozitif ornekler (y_binary == 1)
        pos_mask = y_binary == 1
        n_pos = int(np.sum(pos_mask))
        logger.info('Stage-2 pozitif ornek: %d', n_pos)

        if n_pos >= 10:
            X_pos = X[pos_mask]

            # Stage-2 first_event
            y_first_pos = y_first[pos_mask]
            stage2_first = lgb.LGBMRegressor(
                objective='regression', metric='rmse',
                n_estimators=100, learning_rate=0.05,
                max_depth=6, num_leaves=31, min_child_samples=10,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=0.1, random_state=42, verbose=-1, n_jobs=-1
            )
            stage2_first.fit(X_pos, y_first_pos)
            s2f_path = MODEL_PATH / f'{fuel_type}_stage2_first.joblib'
            joblib.dump(stage2_first, s2f_path)
            logger.info('Stage-2 first kaydedildi: %s', s2f_path)

            # Stage-2 net_amount
            y_net_pos = y_net[pos_mask]
            stage2_net = lgb.LGBMRegressor(
                objective='regression', metric='rmse',
                n_estimators=100, learning_rate=0.05,
                max_depth=6, num_leaves=31, min_child_samples=10,
                subsample=0.8, colsample_bytree=0.8,
                reg_alpha=0.1, reg_lambda=0.1, random_state=42, verbose=-1, n_jobs=-1
            )
            stage2_net.fit(X_pos, y_net_pos)
            s2n_path = MODEL_PATH / f'{fuel_type}_stage2_net.joblib'
            joblib.dump(stage2_net, s2n_path)
            logger.info('Stage-2 net kaydedildi: %s', s2n_path)
        else:
            logger.warning('%s: Yetersiz pozitif ornek (%d), Stage-2 atlaniyor', fuel_type, n_pos)

        logger.info('=== %s TAMAMLANDI ===', fuel_type.upper())

    # Sonuc kontrol
    model_files = list(MODEL_PATH.glob('*.joblib'))
    logger.info('Toplam %d model dosyasi:', len(model_files))
    for f in sorted(model_files):
        logger.info('  %s (%.1f KB)', f.name, f.stat().st_size / 1024)


if __name__ == '__main__':
    quick_train()
