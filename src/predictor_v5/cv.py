"""
Purged Walk-Forward Cross-Validation — Predictor v5

Expanding window CV with embargo gap to prevent data leakage.
Calendar-day based (not trading-day), ~12 folds for 1488 days of data.

Leakage protection:
  - train_end + embargo_days < test_start  (STRICT)
  - Label window D+3: train_end + 3 < test_start → embargo=4 guarantees this
  - Zero train/test overlap
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.predictor_v5.config import (
    EMBARGO_DAYS,
    MIN_TRAIN_DAYS,
    STEP_DAYS,
    TEST_DAYS,
)


class PurgedWalkForwardCV:
    """Purged walk-forward cross-validation with expanding training window.

    Parameters
    ----------
    min_train : int
        Minimum training period in calendar days (default 365).
    test_size : int
        Test period length in calendar days (default 90).
    step_size : int
        Step between consecutive folds in calendar days (default 90).
    embargo : int
        Embargo gap between train end and test start in calendar days (default 4).
        Must be >= LABEL_WINDOW (3) to prevent label leakage.
    """

    def __init__(
        self,
        min_train: int = MIN_TRAIN_DAYS,
        test_size: int = TEST_DAYS,
        step_size: int = STEP_DAYS,
        embargo: int = EMBARGO_DAYS,
    ) -> None:
        if min_train < 1:
            raise ValueError(f"min_train must be >= 1, got {min_train}")
        if test_size < 1:
            raise ValueError(f"test_size must be >= 1, got {test_size}")
        if step_size < 1:
            raise ValueError(f"step_size must be >= 1, got {step_size}")
        if embargo < 0:
            raise ValueError(f"embargo must be >= 0, got {embargo}")

        self.min_train = min_train
        self.test_size = test_size
        self.step_size = step_size
        self.embargo = embargo

    def split(
        self, dates: list[date]
    ) -> list[tuple[list[int], list[int]]]:
        """Generate train/test index splits from a sorted date list.

        Parameters
        ----------
        dates : list[date]
            Sorted list of unique calendar dates (ascending).

        Returns
        -------
        list[tuple[list[int], list[int]]]
            Each tuple contains (train_indices, test_indices).
            Indices are integer positions into the *dates* list.

        Raises
        ------
        ValueError
            If dates is empty or not sorted ascending.
        """
        if not dates:
            return []

        n = len(dates)
        folds: list[tuple[list[int], list[int]]] = []

        # Fold generation with expanding window
        # Fold k:
        #   train_start = 0
        #   train_end   = min_train - 1 + k * step_size
        #   embargo zone = [train_end + 1, train_end + embargo]
        #   test_start  = train_end + embargo + 1
        #   test_end    = test_start + test_size - 1  (capped at n-1)
        fold_idx = 0
        while True:
            train_end = self.min_train - 1 + fold_idx * self.step_size

            # Train must fit in data
            if train_end >= n:
                break

            test_start = train_end + self.embargo + 1

            # Test must start within data
            if test_start >= n:
                break

            test_end = min(test_start + self.test_size - 1, n - 1)

            train_indices = list(range(0, train_end + 1))
            test_indices = list(range(test_start, test_end + 1))

            folds.append((train_indices, test_indices))
            fold_idx += 1

        return folds

    def get_fold_info(
        self, dates: list[date]
    ) -> list[dict]:
        """Return human-readable fold information.

        Parameters
        ----------
        dates : list[date]
            Sorted list of unique calendar dates.

        Returns
        -------
        list[dict]
            Each dict has keys:
            - fold: int (1-based fold number)
            - train_start: date
            - train_end: date
            - train_size: int
            - embargo_start: date
            - embargo_end: date
            - test_start: date
            - test_end: date
            - test_size: int
        """
        if not dates:
            return []

        folds = self.split(dates)
        info: list[dict] = []

        for i, (train_idx, test_idx) in enumerate(folds):
            train_start_date = dates[train_idx[0]]
            train_end_date = dates[train_idx[-1]]
            test_start_date = dates[test_idx[0]]
            test_end_date = dates[test_idx[-1]]

            # Embargo zone: from train_end+1 to test_start-1
            embargo_start_idx = train_idx[-1] + 1
            embargo_end_idx = test_idx[0] - 1

            embargo_start_date = dates[embargo_start_idx] if embargo_start_idx < len(dates) else None
            embargo_end_date = dates[embargo_end_idx] if embargo_end_idx < len(dates) else None

            info.append({
                "fold": i + 1,
                "train_start": train_start_date,
                "train_end": train_end_date,
                "train_size": len(train_idx),
                "embargo_start": embargo_start_date,
                "embargo_end": embargo_end_date,
                "test_start": test_start_date,
                "test_end": test_end_date,
                "test_size": len(test_idx),
            })

        return info

    def get_n_splits(self, dates: list[date]) -> int:
        """Return the number of folds for the given date list.

        Parameters
        ----------
        dates : list[date]
            Sorted list of unique calendar dates.

        Returns
        -------
        int
            Number of CV folds.
        """
        return len(self.split(dates))

    def __repr__(self) -> str:
        return (
            f"PurgedWalkForwardCV("
            f"min_train={self.min_train}, "
            f"test_size={self.test_size}, "
            f"step_size={self.step_size}, "
            f"embargo={self.embargo})"
        )
