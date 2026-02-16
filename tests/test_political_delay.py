"""
Politik Gecikme State Machine testleri.

DelayTracker state machine geçişleri, 5 gün kuralı, kısa düşüş,
z-score hesaplama ve kademeli zam senaryoları için kapsamlı testler.
"""

import pytest
from decimal import Decimal

from src.core.political_delay_tracker import (
    BELOW_THRESHOLD_RESET,
    DelayState,
    DelayTracker,
    DelayTransition,
    calculate_z_score,
    interpret_z_score,
    update_tracker,
)


# ────────────────────────────────────────────────────────────────────────────
#  IDLE → WATCHING geçişi testleri
# ────────────────────────────────────────────────────────────────────────────


class TestIdleToWatching:
    """IDLE durumundan WATCHING'e geçiş testleri."""

    def test_mbe_above_threshold_starts_watching(self):
        """MBE >= θ → WATCHING'e geçmeli."""
        tracker = DelayTracker(state=DelayState.IDLE)
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-15",
        )
        assert result.new_state == DelayState.WATCHING
        assert result.should_create_record is True
        assert tracker.threshold_cross_date == "2026-02-15"
        assert tracker.mbe_at_cross == Decimal("0.55")

    def test_mbe_below_threshold_stays_idle(self):
        """MBE < θ → IDLE kalmalı."""
        tracker = DelayTracker(state=DelayState.IDLE)
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.40"),
            threshold=Decimal("0.50"),
            current_date="2026-02-15",
        )
        assert result.new_state == DelayState.IDLE
        assert result.should_create_record is False

    def test_mbe_equal_threshold_starts_watching(self):
        """MBE == θ → WATCHING'e geçmeli (>= kontrolü)."""
        tracker = DelayTracker(state=DelayState.IDLE)
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.50"),
            threshold=Decimal("0.50"),
            current_date="2026-02-15",
        )
        assert result.new_state == DelayState.WATCHING

    def test_regime_set_on_watching_entry(self):
        """WATCHING'e girerken rejim tipi kaydedilmeli."""
        tracker = DelayTracker(state=DelayState.IDLE)
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.60"),
            threshold=Decimal("0.50"),
            current_date="2026-02-15",
            regime_type="election",
        )
        assert tracker.regime == "election"


# ────────────────────────────────────────────────────────────────────────────
#  WATCHING → CLOSED geçişi testleri
# ────────────────────────────────────────────────────────────────────────────


class TestWatchingToClosed:
    """WATCHING durumundan CLOSED'a geçiş testleri."""

    def test_price_change_closes_watching(self):
        """Tam zam → CLOSED."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=3,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
        )
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-15",
            price_changed=True,
        )
        assert result.new_state == DelayState.CLOSED
        assert result.should_close_record is True
        assert result.close_status == "closed"
        assert tracker.current_delay_days == 4  # +1 gün

    def test_partial_change_partial_close(self):
        """Kademeli zam → PARTIAL_CLOSE."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=5,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.65"),
        )
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.40"),
            threshold=Decimal("0.50"),
            current_date="2026-02-16",
            price_changed=True,
            partial_change=True,
        )
        assert result.new_state == DelayState.PARTIAL_CLOSE
        assert result.close_status == "partial_close"


# ────────────────────────────────────────────────────────────────────────────
#  5 gün kuralı testleri
# ────────────────────────────────────────────────────────────────────────────


class TestFiveDayRule:
    """Eşik altında 5 gün kuralı testleri."""

    def test_five_days_below_absorbs(self):
        """5 gün üst üste eşik altı → ABSORBED."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=10,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
            below_threshold_streak=4,  # 4. gün, bu güncelleme 5. yapacak
        )
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.40"),
            threshold=Decimal("0.50"),
            current_date="2026-02-21",
        )
        assert result.new_state == DelayState.ABSORBED
        assert result.should_close_record is True
        assert result.close_status == "absorbed"

    def test_four_days_below_continues_watching(self):
        """4 gün eşik altı → WATCHING devam (henüz absorbe değil)."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=10,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
            below_threshold_streak=3,  # 3. gün, bu 4. yapacak
        )
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.40"),
            threshold=Decimal("0.50"),
            current_date="2026-02-21",
        )
        assert result.new_state == DelayState.WATCHING
        assert tracker.below_threshold_streak == 4

    def test_short_dip_resets_streak(self):
        """Kısa düşüş sonrası eşik üstüne dönüş → streak sıfırlanmalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=5,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
            below_threshold_streak=3,
        )
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),  # Eşik üstüne döndü
            threshold=Decimal("0.50"),
            current_date="2026-02-16",
        )
        assert result.new_state == DelayState.WATCHING
        assert tracker.below_threshold_streak == 0  # Streak sıfırlandı

    def test_original_cross_date_preserved_during_dip(self):
        """Kısa düşüşte orijinal cross_date korunmalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=5,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
            below_threshold_streak=0,
        )
        # 1 gün eşik altı
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.45"),
            threshold=Decimal("0.50"),
            current_date="2026-02-16",
        )
        assert tracker.threshold_cross_date == "2026-02-10"  # Orijinal tarih korunur
        assert tracker.below_threshold_streak == 1


# ────────────────────────────────────────────────────────────────────────────
#  WATCHING devam testleri
# ────────────────────────────────────────────────────────────────────────────


class TestWatchingContinue:
    """WATCHING durumu devam senaryoları."""

    def test_delay_days_increments(self):
        """Her güncelleme delay_days'i 1 artırmalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=5,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
        )
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-16",
        )
        assert tracker.current_delay_days == 6

    def test_mbe_max_updates(self):
        """Yeni MBE max'ı aşarsa güncellenmeli."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=2,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
        )
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.70"),
            threshold=Decimal("0.50"),
            current_date="2026-02-13",
        )
        assert tracker.mbe_max == Decimal("0.70")

    def test_mbe_max_not_decreasing(self):
        """MBE düşse bile mbe_max azalmamalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=2,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.70"),
        )
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-13",
        )
        assert tracker.mbe_max == Decimal("0.70")


# ────────────────────────────────────────────────────────────────────────────
#  Terminal durumdan IDLE'a dönüş
# ────────────────────────────────────────────────────────────────────────────


class TestTerminalToIdle:
    """Terminal durumlardan IDLE'a dönüş testleri."""

    def test_closed_returns_to_idle(self):
        """CLOSED durumundayken update → IDLE'a dönmeli."""
        tracker = DelayTracker(state=DelayState.CLOSED)
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-20",
        )
        assert result.new_state == DelayState.IDLE

    def test_absorbed_returns_to_idle(self):
        """ABSORBED durumundayken update → IDLE'a dönmeli."""
        tracker = DelayTracker(state=DelayState.ABSORBED)
        result = update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-20",
        )
        assert result.new_state == DelayState.IDLE


# ────────────────────────────────────────────────────────────────────────────
#  Z-Score testleri
# ────────────────────────────────────────────────────────────────────────────


class TestZScore:
    """Z-score hesaplama ve yorumlama testleri."""

    def test_normal_z_score(self):
        """Ortalamada → z ≈ 0."""
        z = calculate_z_score(Decimal("10"), Decimal("10"), Decimal("5"))
        assert z == Decimal("0")

    def test_high_z_score(self):
        """Ortalamadan 2 std sapma → z = 2."""
        z = calculate_z_score(Decimal("20"), Decimal("10"), Decimal("5"))
        assert z == Decimal("2.00")

    def test_zero_std_above_mean(self):
        """Std=0, mean üstünde → z=3 (anormal)."""
        z = calculate_z_score(Decimal("15"), Decimal("10"), Decimal("0"))
        assert z == Decimal("3")

    def test_zero_std_at_mean(self):
        """Std=0, mean'de → z=0."""
        z = calculate_z_score(Decimal("10"), Decimal("10"), Decimal("0"))
        assert z == Decimal("0")

    def test_interpret_normal(self):
        """z < 1.0 → normal."""
        assert interpret_z_score(Decimal("0.5")) == "normal"

    def test_interpret_dikkat(self):
        """1.0 <= z < 2.0 → dikkat."""
        assert interpret_z_score(Decimal("1.5")) == "dikkat"

    def test_interpret_anormal(self):
        """z >= 2.0 → anormal."""
        assert interpret_z_score(Decimal("2.5")) == "anormal"

    def test_z_score_computed_during_watching(self):
        """WATCHING sırasında z-score hesaplanmalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=15,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.60"),
        )
        update_tracker(
            tracker=tracker,
            current_mbe=Decimal("0.55"),
            threshold=Decimal("0.50"),
            current_date="2026-02-26",
            historical_mean_delay=Decimal("10"),
            historical_std_delay=Decimal("3"),
        )
        # delay_days = 16 (15+1), z = (16-10)/3 = 2.0
        assert tracker.z_score == Decimal("2.00")


# ────────────────────────────────────────────────────────────────────────────
#  Serialization testleri
# ────────────────────────────────────────────────────────────────────────────


class TestTrackerSerialization:
    """DelayTracker serialization testleri."""

    def test_to_dict_and_back(self):
        """to_dict → from_dict round-trip korunmalı."""
        tracker = DelayTracker(
            state=DelayState.WATCHING,
            threshold_cross_date="2026-02-10",
            current_delay_days=7,
            mbe_at_cross=Decimal("0.55"),
            mbe_max=Decimal("0.65"),
            regime="election",
            z_score=Decimal("1.23"),
            below_threshold_streak=2,
        )
        data = tracker.to_dict()
        restored = DelayTracker.from_dict(data)

        assert restored.state == tracker.state
        assert restored.threshold_cross_date == tracker.threshold_cross_date
        assert restored.current_delay_days == tracker.current_delay_days
        assert restored.mbe_at_cross == tracker.mbe_at_cross
        assert restored.mbe_max == tracker.mbe_max
        assert restored.regime == tracker.regime
        assert restored.z_score == tracker.z_score
        assert restored.below_threshold_streak == tracker.below_threshold_streak
