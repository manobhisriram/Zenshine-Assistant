"""Minimal async-safe circuit breaker (closed -> open -> half-open)."""

from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self._threshold = failure_threshold
        self._reset = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        # once the reset window passes the breaker is half-open: one attempt is let through
        return time.monotonic() - self._opened_at < self._reset

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = time.monotonic()
