"""Per-symbol rolling z-score detector on log-returns.

The DS&A piece of the project: O(1) per-update mean and stddev via running
`sum` and `sum_of_squares` over a fixed-size deque. The deque only ever holds
`window_size` values; updates evict the oldest and append the new return,
adjusting the two running totals by two scalar operations each.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    z_score: float | None
    is_anomaly: bool


class RollingZScore:
    def __init__(self, window_size: int = 60, threshold: float = 2.5):
        if window_size < 2:
            raise ValueError("window_size must be at least 2")
        self.window_size = window_size
        self.threshold = threshold
        self._returns: deque[float] = deque(maxlen=window_size)
        self._sum: float = 0.0
        self._sum_sq: float = 0.0
        self._last_price: float | None = None

    def update(self, price: float) -> AnomalyResult:
        if price <= 0:
            raise ValueError("price must be positive")

        if self._last_price is None:
            self._last_price = price
            return AnomalyResult(z_score=None, is_anomaly=False)

        r = math.log(price / self._last_price)
        self._last_price = price

        # If the deque is full, the upcoming append will evict self._returns[0];
        # subtract that value from the running totals BEFORE the append so the
        # totals stay in sync with the deque contents in O(1).
        if len(self._returns) == self.window_size:
            evicted = self._returns[0]
            self._sum -= evicted
            self._sum_sq -= evicted * evicted

        self._returns.append(r)
        self._sum += r
        self._sum_sq += r * r

        if len(self._returns) < self.window_size:
            return AnomalyResult(z_score=None, is_anomaly=False)

        n = self.window_size
        mean = self._sum / n
        # Floating-point can drive variance slightly negative on a flat series
        # (all returns identical), so guard before sqrt.
        variance = self._sum_sq / n - mean * mean
        if variance <= 0:
            return AnomalyResult(z_score=None, is_anomaly=False)

        z = (r - mean) / math.sqrt(variance)
        return AnomalyResult(z_score=z, is_anomaly=abs(z) > self.threshold)
