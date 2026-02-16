"""
Circuit Breaker Mekanizmasi (Katman 4).

ML tahmin servisinin saglikli olup olmadigini izler ve hata durumunda
Katman 3 (deterministik risk skoru) sistemine graceful degrade yapar.

State Machine:
    CLOSED    → ML calisiyor, normal tahmin
    OPEN      → ML cokmis, Katman 3 bypass
    HALF_OPEN → Test modunda, basarili tahminler → CLOSED'a don

Parametreler:
    failure_threshold : %10 (10 istekten 1'i basarisiz → trip)
    timeout_seconds   : 300 (5 dk sonra HALF_OPEN'a gec)
    window_size       : 100 (son 100 istek izlenir)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker durumlari."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker konfigurasyonu."""

    failure_threshold: float = 0.10      # %10 hata orani → trip
    timeout_seconds: float = 300.0       # 5 dakika → HALF_OPEN'a gec
    window_size: int = 100               # Son 100 istek izlenir
    half_open_max_calls: int = 5         # HALF_OPEN'da max test istegi


class CircuitBreaker:
    """
    ML servis circuit breaker'i.

    Thread-safe implementasyon. Hata orani esigi asildiginda
    OPEN state'e gecer ve ML tahminlerini durdurur.

    Kullanim:
        cb = CircuitBreaker()

        if cb.can_execute():
            try:
                result = ml_predict(...)
                cb.record_success()
            except Exception:
                cb.record_failure()
        else:
            # Degrade moda gec
            return degraded_response()
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._lock = Lock()

        # Istek kayitlari
        self._results: list[bool] = []  # True=basarili, False=basarisiz
        self._failure_count: int = 0
        self._success_count: int = 0

        # Zaman damgalari
        self._last_failure_time: float | None = None
        self._last_state_change_time: float = time.time()

        # HALF_OPEN sayaci
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        """Mevcut circuit durumunu dondurur (timeout kontrolu ile)."""
        with self._lock:
            self._check_timeout()
            return self._state

    @property
    def failure_rate(self) -> float:
        """Son penceredeki hata oranini dondurur."""
        with self._lock:
            if not self._results:
                return 0.0
            failures = sum(1 for r in self._results if not r)
            return failures / len(self._results)

    @property
    def failure_count(self) -> int:
        """Toplam hata sayisi."""
        return self._failure_count

    @property
    def success_count(self) -> int:
        """Toplam basari sayisi."""
        return self._success_count

    @property
    def last_failure_time(self) -> float | None:
        """Son hata zamani (Unix timestamp)."""
        return self._last_failure_time

    @property
    def last_state_change_time(self) -> float:
        """Son state degisim zamani (Unix timestamp)."""
        return self._last_state_change_time

    def can_execute(self) -> bool:
        """
        ML tahmininin calistirilip calistirilmayacagini kontrol eder.

        Returns:
            True: Tahmin yapilabilir (CLOSED veya HALF_OPEN).
            False: Tahmin yapilamaz (OPEN).
        """
        with self._lock:
            self._check_timeout()

            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self._config.half_open_max_calls:
                    return True
                return False

            # OPEN
            return False

    def record_success(self) -> None:
        """Basarili bir ML tahmini kaydeder."""
        with self._lock:
            self._add_result(success=True)
            self._success_count += 1

            if self._state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1
                # Yeterli basarili istek → CLOSED'a don
                if self._half_open_calls >= self._config.half_open_max_calls:
                    self._transition_to(CircuitState.CLOSED)
                    logger.info(
                        "Circuit breaker: HALF_OPEN → CLOSED (%d basarili test)",
                        self._half_open_calls,
                    )

    def record_failure(self) -> None:
        """Basarisiz bir ML tahmini kaydeder."""
        with self._lock:
            self._add_result(success=False)
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # HALF_OPEN'da hata → tekrar OPEN
                self._transition_to(CircuitState.OPEN)
                logger.warning("Circuit breaker: HALF_OPEN → OPEN (hata algilandi)")
                return

            if self._state == CircuitState.CLOSED:
                # Hata oranini kontrol et
                current_rate = self._current_failure_rate()
                if current_rate >= self._config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    logger.warning(
                        "Circuit breaker: CLOSED → OPEN (hata orani: %.2f%%)",
                        current_rate * 100,
                    )

    def reset(self) -> None:
        """Circuit breaker'i sifirlar (test ve admin amacli)."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._results.clear()
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._last_state_change_time = time.time()
            self._half_open_calls = 0
            logger.info("Circuit breaker sifirlandi → CLOSED")

    def get_health(self) -> dict:
        """Circuit breaker saglik bilgisini dondurur."""
        with self._lock:
            self._check_timeout()
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_rate": round(self._current_failure_rate(), 4),
                "last_failure_time": (
                    time.strftime(
                        "%Y-%m-%dT%H:%M:%S", time.localtime(self._last_failure_time)
                    )
                    if self._last_failure_time
                    else None
                ),
                "last_state_change": time.strftime(
                    "%Y-%m-%dT%H:%M:%S",
                    time.localtime(self._last_state_change_time),
                ),
                "window_size": self._config.window_size,
                "results_in_window": len(self._results),
            }

    # ── Dahili Yardimcilar ───────────────────────────────────────────────

    def _add_result(self, *, success: bool) -> None:
        """Sonuc penceresine yeni kayit ekler."""
        self._results.append(success)
        # Pencere boyutunu asarsa eski kayitlari at
        while len(self._results) > self._config.window_size:
            self._results.pop(0)

    def _current_failure_rate(self) -> float:
        """Mevcut penceredeki hata oranini hesaplar."""
        if not self._results:
            return 0.0
        failures = sum(1 for r in self._results if not r)
        return failures / len(self._results)

    def _check_timeout(self) -> None:
        """OPEN state'den timeout suresi gectiyse HALF_OPEN'a gec."""
        if self._state != CircuitState.OPEN:
            return

        elapsed = time.time() - self._last_state_change_time
        if elapsed >= self._config.timeout_seconds:
            self._transition_to(CircuitState.HALF_OPEN)
            self._half_open_calls = 0
            logger.info(
                "Circuit breaker: OPEN → HALF_OPEN (%.0f sn timeout)",
                elapsed,
            )

    def _transition_to(self, new_state: CircuitState) -> None:
        """State gecisi yapar."""
        old_state = self._state
        self._state = new_state
        self._last_state_change_time = time.time()

        if new_state == CircuitState.CLOSED:
            # CLOSED'a donuste pencereyi temizle
            self._results.clear()
            self._half_open_calls = 0

        logger.info(
            "Circuit breaker state degisimi: %s → %s",
            old_state.value,
            new_state.value,
        )


# --- Singleton Instance ---
_default_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    """Varsayilan circuit breaker instance'ini dondurur (singleton)."""
    global _default_circuit_breaker
    if _default_circuit_breaker is None:
        _default_circuit_breaker = CircuitBreaker()
    return _default_circuit_breaker


def reset_circuit_breaker() -> None:
    """Varsayilan circuit breaker'i sifirlar (test amacli)."""
    global _default_circuit_breaker
    if _default_circuit_breaker is not None:
        _default_circuit_breaker.reset()
    _default_circuit_breaker = None
