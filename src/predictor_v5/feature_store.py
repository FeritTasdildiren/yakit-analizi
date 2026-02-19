"""
Predictor v5 feature store.

Feature snapshot JSONB kaydetme/okuma.
Backtest ve debug icin tarih araligi DataFrame donusumu.

UPSERT: ON CONFLICT (run_date, fuel_type) DO UPDATE.
Decimal -> float donusumu JSONB yaziminda otomatik uygulanir.
"""

import json
import logging
from datetime import date
from decimal import Decimal
from typing import Any, Optional

import pandas as pd
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)

DB_DSN = "postgresql://yakit_analizi:yakit2026secure@localhost:5433/yakit_analizi"

# ---------------------------------------------------------------------------
#  Yardimci: Decimal-safe JSON encoder
# ---------------------------------------------------------------------------


class _DecimalEncoder(json.JSONEncoder):
    """Decimal degerlerini float'a cevirir (JSONB uyumu)."""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def _sanitize_features(features_dict: dict) -> dict:
    """
    Feature dict icindeki Decimal degerleri float'a cevir.
    JSONB'ye yazarken psycopg2.extras.Json ile birlikte kullanilir.
    """
    sanitized = {}
    for k, v in features_dict.items():
        if isinstance(v, Decimal):
            sanitized[k] = float(v)
        elif v is None:
            sanitized[k] = None
        else:
            sanitized[k] = v
    return sanitized


# ===========================================================================
#  UPSERT SQL
# ===========================================================================

_UPSERT_SNAPSHOT_SQL = """
INSERT INTO feature_snapshots_v5 (run_date, fuel_type, features, feature_version)
VALUES (%(run_date)s, %(fuel_type)s, %(features)s, %(feature_version)s)
ON CONFLICT (run_date, fuel_type) DO UPDATE SET
    features        = EXCLUDED.features,
    feature_version = EXCLUDED.feature_version
"""

_SELECT_SNAPSHOT_SQL = """
SELECT id, run_date, fuel_type, features, feature_version, created_at
FROM feature_snapshots_v5
WHERE fuel_type = %(fuel_type)s
  AND run_date = %(run_date)s
"""

_SELECT_RANGE_SQL = """
SELECT run_date, fuel_type, features, feature_version
FROM feature_snapshots_v5
WHERE fuel_type = %(fuel_type)s
  AND run_date >= %(start_date)s
  AND run_date <= %(end_date)s
ORDER BY run_date ASC
"""


# ===========================================================================
#  Public API
# ===========================================================================


def store_snapshot(
    fuel_type: str,
    run_date: date,
    features_dict: dict,
    feature_version: str = "v5.0",
    dsn: str = DB_DSN,
) -> None:
    """
    Feature snapshot'i JSONB olarak kaydet (UPSERT).

    Decimal degerleri otomatik float'a donusturulur.
    psycopg2.extras.Json wrapper ile JSONB'ye yazilir.
    """
    sanitized = _sanitize_features(features_dict)

    params = {
        "run_date": run_date,
        "fuel_type": fuel_type,
        "features": psycopg2.extras.Json(sanitized),
        "feature_version": feature_version,
    }

    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(_UPSERT_SNAPSHOT_SQL, params)
        conn.commit()
        logger.info(
            "Feature snapshot upsert: %s / %s (version=%s, keys=%d)",
            run_date,
            fuel_type,
            feature_version,
            len(sanitized),
        )
    finally:
        conn.close()


def load_snapshot(
    fuel_type: str,
    run_date: date,
    dsn: str = DB_DSN,
) -> Optional[dict]:
    """
    Tek gun feature snapshot yukle.

    Returns:
        dict veya None: {
            "id": int,
            "run_date": date,
            "fuel_type": str,
            "features": dict,
            "feature_version": str,
            "created_at": datetime,
        }
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                _SELECT_SNAPSHOT_SQL,
                {"fuel_type": fuel_type, "run_date": run_date},
            )
            row = cur.fetchone()
            if row is None:
                return None
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))
    finally:
        conn.close()


def load_snapshots_range(
    fuel_type: str,
    start_date: date,
    end_date: date,
    dsn: str = DB_DSN,
) -> pd.DataFrame:
    """
    Tarih araligi icin feature DataFrame'i donur.
    Backtest/debug icin kullanilir.

    Her satir bir gun, sutunlar feature isimleri.
    Ek sutunlar: run_date, fuel_type, feature_version.

    Returns:
        pd.DataFrame: Bos ise bostur (0 satir).
    """
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                _SELECT_RANGE_SQL,
                {
                    "fuel_type": fuel_type,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )
            rows = cur.fetchall()

        if not rows:
            return pd.DataFrame()

        records = []
        for run_date_val, fuel_type_val, features, version in rows:
            row_dict = {
                "run_date": run_date_val,
                "fuel_type": fuel_type_val,
                "feature_version": version,
            }
            if isinstance(features, dict):
                row_dict.update(features)
            records.append(row_dict)

        df = pd.DataFrame(records)
        df = df.set_index("run_date")
        return df
    finally:
        conn.close()
