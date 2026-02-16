"""
Circuit Breaker mekanizmasi testleri.

State gecisleri: CLOSED → OPEN → HALF_OPEN → CLOSED
Hata orani, timeout ve recovery senaryolari test edilir.
"""

import time
import pytest

from src.ml.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    get_circuit_breaker,
    reset_circuit_breaker,
)


class TestCircuitBreakerBasic:
    """Circuit breaker temel islevsellik testleri."""

    def setup_method(self):
        """Her test icin temiz bir circuit breaker olustur."""
        self.config = CircuitBreakerConfig(
            failure_threshold=0.10,
            timeout_seconds=1.0,  # Test icin kisa timeout
            window_size=10,
            half_open_max_calls=3,
        )
        self.cb = CircuitBreaker(self.config)

    def test_initial_state_is_closed(self):
        """Baslangic durumu CLOSED olmali."""
        assert self.cb.state == CircuitState.CLOSED

    def test_can_execute_when_closed(self):
        """CLOSED durumunda tahmin yapilabilmeli."""
        assert self.cb.can_execute() is True

    def test_success_stays_closed(self):
        """Basarili istekler CLOSED durumunu degistirmemeli."""
        for _ in range(10):
            self.cb.record_success()
        assert self.cb.state == CircuitState.CLOSED
        assert self.cb.success_count == 10
        assert self.cb.failure_count == 0


class TestCircuitBreakerStateTransitions:
    """Circuit breaker state gecis testleri."""

    def setup_method(self):
        self.config = CircuitBreakerConfig(
            failure_threshold=0.10,
            timeout_seconds=0.5,  # Test icin cok kisa timeout
            window_size=10,
            half_open_max_calls=3,
        )
        self.cb = CircuitBreaker(self.config)

    def test_closed_to_open_on_high_failure_rate(self):
        """Yuksek hata oraninda CLOSED → OPEN gecisi olmali."""
        # 10 istek, 1'i basarisiz → %10 = esik
        for _ in range(9):
            self.cb.record_success()
        self.cb.record_failure()  # Failure rate = 1/10 = 10% = threshold

        assert self.cb.state == CircuitState.OPEN

    def test_cannot_execute_when_open(self):
        """OPEN durumunda tahmin yapilamaz."""
        # Trip the breaker
        for _ in range(8):
            self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_failure()  # 2/10 = %20 > threshold

        assert self.cb.state == CircuitState.OPEN
        assert self.cb.can_execute() is False

    def test_open_to_half_open_after_timeout(self):
        """Timeout sonrasi OPEN → HALF_OPEN gecisi olmali."""
        # Trip the breaker
        for _ in range(8):
            self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_failure()

        assert self.cb.state == CircuitState.OPEN

        # Timeout bekle
        time.sleep(0.6)

        # State kontrolu timeout'u tetikler
        assert self.cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        """HALF_OPEN'da yeterli basari → CLOSED donusu."""
        # Trip the breaker
        for _ in range(8):
            self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_failure()

        # Timeout bekle
        time.sleep(0.6)
        assert self.cb.state == CircuitState.HALF_OPEN

        # 3 basarili istek → CLOSED
        for _ in range(3):
            self.cb.record_success()

        assert self.cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        """HALF_OPEN'da hata → tekrar OPEN."""
        # Trip the breaker
        for _ in range(8):
            self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_failure()

        # Timeout bekle
        time.sleep(0.6)
        assert self.cb.state == CircuitState.HALF_OPEN

        # HALF_OPEN'da hata → tekrar OPEN
        self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

    def test_full_recovery_cycle(self):
        """Tam bir CLOSED → OPEN → HALF_OPEN → CLOSED dongusu."""
        # 1. CLOSED → OPEN
        for _ in range(8):
            self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_failure()
        assert self.cb.state == CircuitState.OPEN

        # 2. OPEN → HALF_OPEN (timeout)
        time.sleep(0.6)
        assert self.cb.state == CircuitState.HALF_OPEN

        # 3. HALF_OPEN → CLOSED (basarili istekler)
        for _ in range(3):
            self.cb.record_success()
        assert self.cb.state == CircuitState.CLOSED


class TestCircuitBreakerFailureRate:
    """Hata orani hesaplama testleri."""

    def setup_method(self):
        self.config = CircuitBreakerConfig(
            failure_threshold=0.20,
            window_size=5,
        )
        self.cb = CircuitBreaker(self.config)

    def test_failure_rate_empty(self):
        """Bos pencerede hata orani 0 olmali."""
        assert self.cb.failure_rate == 0.0

    def test_failure_rate_all_success(self):
        """Tum basarili isteklerde hata orani 0."""
        for _ in range(5):
            self.cb.record_success()
        assert self.cb.failure_rate == 0.0

    def test_failure_rate_mixed(self):
        """Karisik isteklerde dogru hata orani."""
        self.cb.record_success()
        self.cb.record_failure()
        self.cb.record_success()
        self.cb.record_success()
        self.cb.record_success()
        assert self.cb.failure_rate == pytest.approx(0.2)

    def test_window_sliding(self):
        """Pencere dolunca eski kayitlar atilmali."""
        # 5 basari doldur
        for _ in range(5):
            self.cb.record_success()
        # 1 hata ekle — en eski basari atilir
        self.cb.record_failure()
        # Pencere: [S, S, S, S, F] → 1/5 = %20
        assert self.cb.failure_rate == pytest.approx(0.2)


class TestCircuitBreakerReset:
    """Circuit breaker sifirlama testleri."""

    def test_reset_clears_state(self):
        """Reset tum state'i temizlemeli."""
        config = CircuitBreakerConfig(
            failure_threshold=0.10,
            window_size=10,
        )
        cb = CircuitBreaker(config)

        for _ in range(10):
            cb.record_failure()

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.failure_rate == 0.0


class TestCircuitBreakerHealth:
    """Circuit breaker saglik raporu testleri."""

    def test_health_report_fields(self):
        """Saglik raporu gerekli alanlari icermeli."""
        cb = CircuitBreaker()
        health = cb.get_health()

        assert "state" in health
        assert "failure_count" in health
        assert "success_count" in health
        assert "failure_rate" in health
        assert "last_failure_time" in health
        assert "last_state_change" in health
        assert health["state"] == "CLOSED"


class TestCircuitBreakerSingleton:
    """Singleton circuit breaker testleri."""

    def setup_method(self):
        reset_circuit_breaker()

    def teardown_method(self):
        reset_circuit_breaker()

    def test_singleton_returns_same_instance(self):
        """get_circuit_breaker ayni instance'i dondurmeli."""
        cb1 = get_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is cb2

    def test_reset_creates_new_instance(self):
        """reset sonrasi yeni instance olusturulmali."""
        cb1 = get_circuit_breaker()
        reset_circuit_breaker()
        cb2 = get_circuit_breaker()
        assert cb1 is not cb2
