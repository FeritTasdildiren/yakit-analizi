"""
Tests for PurgedWalkForwardCV — Predictor v5

At least 8 tests covering:
1. Fold count (~12 for 1488 days)
2. First fold date ranges
3. Last fold can be short
4. Embargo = 4 days (train_end + 4 < test_start)
5. No data leakage (train/test intersection is empty)
6. Insufficient data (< 365 days -> 0 folds)
7. get_fold_info dict format
8. get_n_splits consistency
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.predictor_v5.cv import PurgedWalkForwardCV
from src.predictor_v5.config import (
    MIN_TRAIN_DAYS,
    TEST_DAYS,
    STEP_DAYS,
    EMBARGO_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_date_range(start: date, n_days: int) -> list[date]:
    """Create a sorted list of consecutive calendar dates."""
    return [start + timedelta(days=i) for i in range(n_days)]


# Canonical dataset: ~4 years of data (1488 days)
START_DATE = date(2022, 1, 1)
CANONICAL_DAYS = 1488
CANONICAL_DATES = make_date_range(START_DATE, CANONICAL_DAYS)


# ---------------------------------------------------------------------------
# Test 1: Fold count (~12 for 1488 days)
# ---------------------------------------------------------------------------

class TestFoldCount:
    """Fold count should be ~12 for 1488 days with default params."""

    def test_fold_count_canonical(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        n_folds = len(folds)
        assert 10 <= n_folds <= 14, f"Expected ~12 folds, got {n_folds}"

    def test_fold_count_exact_calculation(self):
        """Verify exact fold count with known parameters."""
        cv = PurgedWalkForwardCV()
        n_folds = cv.get_n_splits(CANONICAL_DATES)
        expected = 0
        k = 0
        while True:
            train_end = MIN_TRAIN_DAYS - 1 + k * STEP_DAYS
            test_start = train_end + EMBARGO_DAYS + 1
            if train_end >= CANONICAL_DAYS or test_start >= CANONICAL_DAYS:
                break
            expected += 1
            k += 1
        assert n_folds == expected


# ---------------------------------------------------------------------------
# Test 2: First fold date ranges
# ---------------------------------------------------------------------------

class TestFirstFold:
    """First fold should have exactly min_train days of training."""

    def test_first_fold_train_size(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        train_idx, test_idx = folds[0]
        assert len(train_idx) == MIN_TRAIN_DAYS  # 365

    def test_first_fold_train_range(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        train_idx, _ = folds[0]
        assert train_idx[0] == 0
        assert train_idx[-1] == MIN_TRAIN_DAYS - 1  # 364

    def test_first_fold_test_start(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        train_idx, test_idx = folds[0]
        expected_test_start = MIN_TRAIN_DAYS - 1 + EMBARGO_DAYS + 1
        assert test_idx[0] == expected_test_start

    def test_first_fold_test_size(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        _, test_idx = folds[0]
        assert len(test_idx) == TEST_DAYS  # 90


# ---------------------------------------------------------------------------
# Test 3: Last fold can be short
# ---------------------------------------------------------------------------

class TestLastFold:
    """Last fold test set may be shorter than test_size."""

    def test_last_fold_can_be_short(self):
        """With data that doesn't align perfectly, last fold can be short."""
        dates = make_date_range(START_DATE, 470)
        cv = PurgedWalkForwardCV()
        folds = cv.split(dates)
        if len(folds) > 1:
            _, last_test = folds[-1]
            assert 1 <= len(last_test) <= TEST_DAYS

    def test_last_fold_short_explicit(self):
        """Create scenario where last fold is guaranteed short."""
        dates = make_date_range(START_DATE, 500)
        cv = PurgedWalkForwardCV()
        folds = cv.split(dates)
        assert len(folds) == 2
        _, last_test = folds[-1]
        assert len(last_test) < TEST_DAYS


# ---------------------------------------------------------------------------
# Test 4: Embargo = 4 days
# ---------------------------------------------------------------------------

class TestEmbargo:
    """Embargo gap must be exactly EMBARGO_DAYS between train end and test start."""

    def test_embargo_gap_all_folds(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, test_idx) in enumerate(folds):
            gap = test_idx[0] - train_idx[-1]
            assert gap == EMBARGO_DAYS + 1, (
                f"Fold {i}: gap between train_end and test_start "
                f"should be {EMBARGO_DAYS + 1}, got {gap}"
            )

    def test_embargo_dates_no_overlap(self):
        """Embargo zone dates should not appear in train or test."""
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, test_idx) in enumerate(folds):
            embargo_indices = set(range(train_idx[-1] + 1, test_idx[0]))
            assert len(embargo_indices) == EMBARGO_DAYS, (
                f"Fold {i}: embargo zone should have {EMBARGO_DAYS} days"
            )
            assert embargo_indices.isdisjoint(set(train_idx))
            assert embargo_indices.isdisjoint(set(test_idx))

    def test_embargo_custom_value(self):
        """Custom embargo value should work correctly."""
        cv = PurgedWalkForwardCV(embargo=10)
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, test_idx) in enumerate(folds):
            gap = test_idx[0] - train_idx[-1]
            assert gap == 11  # embargo + 1


# ---------------------------------------------------------------------------
# Test 5: No data leakage
# ---------------------------------------------------------------------------

class TestNoLeakage:
    """Train and test sets must never overlap."""

    def test_no_index_overlap(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, test_idx) in enumerate(folds):
            train_set = set(train_idx)
            test_set = set(test_idx)
            overlap = train_set & test_set
            assert len(overlap) == 0, (
                f"Fold {i}: train/test overlap at indices {overlap}"
            )

    def test_label_window_safety(self):
        """
        Label uses D+1..D+3 (LABEL_WINDOW=3).
        train_end + 3 < test_start must hold.
        With embargo=4: test_start = train_end + 5, so train_end + 3 < train_end + 5 OK.
        """
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        label_window = 3
        for i, (train_idx, test_idx) in enumerate(folds):
            train_end = train_idx[-1]
            test_start = test_idx[0]
            assert train_end + label_window < test_start, (
                f"Fold {i}: label leakage! "
                f"train_end={train_end}, label reaches {train_end + label_window}, "
                f"test_start={test_start}"
            )

    def test_expanding_window_no_future_leak(self):
        """Each fold's train set must only contain past data relative to test."""
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, test_idx) in enumerate(folds):
            assert max(train_idx) < min(test_idx), (
                f"Fold {i}: train contains future data relative to test"
            )


# ---------------------------------------------------------------------------
# Test 6: Insufficient data
# ---------------------------------------------------------------------------

class TestInsufficientData:
    """With fewer days than min_train + embargo + 1, should return 0 folds."""

    def test_empty_dates(self):
        cv = PurgedWalkForwardCV()
        assert cv.split([]) == []

    def test_too_few_days(self):
        dates = make_date_range(START_DATE, 369)  # just 1 short
        cv = PurgedWalkForwardCV()
        folds = cv.split(dates)
        assert len(folds) == 0

    def test_exact_minimum_one_fold(self):
        min_for_one = MIN_TRAIN_DAYS + EMBARGO_DAYS + 1  # 370
        dates = make_date_range(START_DATE, min_for_one)
        cv = PurgedWalkForwardCV()
        folds = cv.split(dates)
        assert len(folds) == 1
        _, test_idx = folds[0]
        assert len(test_idx) == 1  # only 1 test day

    def test_fewer_than_min_train(self):
        dates = make_date_range(START_DATE, 100)
        cv = PurgedWalkForwardCV()
        assert cv.get_n_splits(dates) == 0


# ---------------------------------------------------------------------------
# Test 7: get_fold_info dict format
# ---------------------------------------------------------------------------

class TestGetFoldInfo:
    """get_fold_info should return well-formed dicts."""

    def test_fold_info_keys(self):
        cv = PurgedWalkForwardCV()
        info = cv.get_fold_info(CANONICAL_DATES)
        expected_keys = {
            "fold", "train_start", "train_end", "train_size",
            "embargo_start", "embargo_end",
            "test_start", "test_end", "test_size",
        }
        for fold_dict in info:
            assert set(fold_dict.keys()) == expected_keys

    def test_fold_info_types(self):
        cv = PurgedWalkForwardCV()
        info = cv.get_fold_info(CANONICAL_DATES)
        for fold_dict in info:
            assert isinstance(fold_dict["fold"], int)
            assert isinstance(fold_dict["train_start"], date)
            assert isinstance(fold_dict["train_end"], date)
            assert isinstance(fold_dict["train_size"], int)
            assert isinstance(fold_dict["test_start"], date)
            assert isinstance(fold_dict["test_end"], date)
            assert isinstance(fold_dict["test_size"], int)

    def test_fold_info_fold_numbers(self):
        """Fold numbers should be 1-based and sequential."""
        cv = PurgedWalkForwardCV()
        info = cv.get_fold_info(CANONICAL_DATES)
        fold_numbers = [d["fold"] for d in info]
        assert fold_numbers == list(range(1, len(info) + 1))

    def test_fold_info_first_fold_dates(self):
        cv = PurgedWalkForwardCV()
        info = cv.get_fold_info(CANONICAL_DATES)
        first = info[0]
        assert first["train_start"] == START_DATE
        assert first["train_end"] == START_DATE + timedelta(days=MIN_TRAIN_DAYS - 1)
        assert first["test_start"] == START_DATE + timedelta(
            days=MIN_TRAIN_DAYS + EMBARGO_DAYS
        )

    def test_fold_info_empty_dates(self):
        cv = PurgedWalkForwardCV()
        assert cv.get_fold_info([]) == []

    def test_fold_info_train_expanding(self):
        """Train size should increase with each fold (expanding window)."""
        cv = PurgedWalkForwardCV()
        info = cv.get_fold_info(CANONICAL_DATES)
        train_sizes = [d["train_size"] for d in info]
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] > train_sizes[i - 1], (
                f"Train size not expanding: fold {i} ({train_sizes[i]}) "
                f"<= fold {i-1} ({train_sizes[i-1]})"
            )


# ---------------------------------------------------------------------------
# Test 8: get_n_splits consistency
# ---------------------------------------------------------------------------

class TestGetNSplits:
    """get_n_splits must be consistent with split()."""

    def test_n_splits_equals_split_length(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        n = cv.get_n_splits(CANONICAL_DATES)
        assert n == len(folds)

    def test_n_splits_empty(self):
        cv = PurgedWalkForwardCV()
        assert cv.get_n_splits([]) == 0

    def test_n_splits_various_lengths(self):
        """Test consistency for multiple data lengths."""
        cv = PurgedWalkForwardCV()
        for n_days in [100, 370, 500, 1000, 1488, 2000]:
            dates = make_date_range(START_DATE, n_days)
            assert cv.get_n_splits(dates) == len(cv.split(dates))


# ---------------------------------------------------------------------------
# Bonus: Parameter validation
# ---------------------------------------------------------------------------

class TestParameterValidation:
    """Constructor should reject invalid parameters."""

    def test_invalid_min_train(self):
        with pytest.raises(ValueError):
            PurgedWalkForwardCV(min_train=0)

    def test_invalid_test_size(self):
        with pytest.raises(ValueError):
            PurgedWalkForwardCV(test_size=0)

    def test_invalid_step_size(self):
        with pytest.raises(ValueError):
            PurgedWalkForwardCV(step_size=0)

    def test_invalid_embargo(self):
        with pytest.raises(ValueError):
            PurgedWalkForwardCV(embargo=-1)

    def test_repr(self):
        cv = PurgedWalkForwardCV()
        r = repr(cv)
        assert "PurgedWalkForwardCV" in r
        assert "min_train=365" in r
        assert "embargo=4" in r


# ---------------------------------------------------------------------------
# Bonus: Expanding window property
# ---------------------------------------------------------------------------

class TestExpandingWindow:
    """Verify the expanding window property across all folds."""

    def test_train_grows_by_step_size(self):
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i in range(1, len(folds)):
            prev_train = folds[i - 1][0]
            curr_train = folds[i][0]
            growth = len(curr_train) - len(prev_train)
            assert growth == STEP_DAYS, (
                f"Fold {i}: train growth should be {STEP_DAYS}, got {growth}"
            )

    def test_all_folds_start_at_zero(self):
        """Expanding window: every fold starts training from index 0."""
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i, (train_idx, _) in enumerate(folds):
            assert train_idx[0] == 0, (
                f"Fold {i}: train should start at 0, got {train_idx[0]}"
            )

    def test_test_windows_dont_overlap(self):
        """Consecutive test windows should not overlap (step >= test in our config)."""
        cv = PurgedWalkForwardCV()
        folds = cv.split(CANONICAL_DATES)
        for i in range(1, len(folds)):
            prev_test_end = folds[i - 1][1][-1]
            curr_test_start = folds[i][1][0]
            assert curr_test_start > prev_test_end, (
                f"Fold {i}: test windows overlap! "
                f"prev_end={prev_test_end}, curr_start={curr_test_start}"
            )
