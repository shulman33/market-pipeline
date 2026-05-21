"""Unit tests for the rolling z-score anomaly detector.

Pure-Python: no DB, no network, no fixtures beyond stdlib. The detector is
intentionally hand-rolled to showcase O(1) rolling-window math, so these tests
exercise the invariants of that approach directly.
"""

from __future__ import annotations

import math
import random

from ingestor.anomaly import RollingZScore


def test_first_update_returns_no_zscore():
    rz = RollingZScore(window_size=60)
    result = rz.update(100.0)
    assert result.z_score is None
    assert result.is_anomaly is False


def test_no_alert_before_warmup():
    # 60 prices produce 59 returns. Window not full -> no z-score, no alert.
    rz = RollingZScore(window_size=60, threshold=2.5)
    for i in range(60):
        result = rz.update(100.0 + i * 0.01)
        assert result.is_anomaly is False
        assert result.z_score is None


def test_flat_series_handles_zero_variance():
    # All log-returns are exactly zero. variance == 0 must not raise.
    rz = RollingZScore(window_size=10, threshold=2.5)
    for _ in range(100):
        result = rz.update(50.0)
        assert result.is_anomaly is False
        assert result.z_score is None


def test_synthetic_spike_triggers_alert():
    rz = RollingZScore(window_size=60, threshold=2.5)
    rng = random.Random(42)
    price = 100.0
    # 61 updates: 1 to set last_price, 60 to fill the return window with
    # small noise (~0.1% std).
    for _ in range(61):
        price *= 1 + rng.gauss(0, 0.001)
        rz.update(price)
    # 10% jump against a 0.1% rolling std -> z well above 2.5.
    spike = rz.update(price * 1.10)
    assert spike.is_anomaly is True
    assert spike.z_score is not None
    assert abs(spike.z_score) > 2.5


def test_window_eviction_bounds_memory():
    # The deque must never exceed window_size, proving the O(1) eviction path
    # is wired (and not a growing list dressed up as a deque).
    rz = RollingZScore(window_size=10)
    for i in range(1, 101):
        rz.update(100.0 + i * 0.5)
    assert len(rz._returns) == 10


def test_running_totals_stay_consistent_with_deque():
    # Compare the O(1) running sum/sum_sq against a from-scratch recomputation
    # to catch any drift in the eviction bookkeeping over a long run.
    rz = RollingZScore(window_size=20)
    rng = random.Random(0)
    price = 100.0
    for _ in range(500):
        price *= 1 + rng.gauss(0, 0.005)
        rz.update(price)
    expected_sum = sum(rz._returns)
    expected_sum_sq = sum(r * r for r in rz._returns)
    assert math.isclose(rz._sum, expected_sum, abs_tol=1e-9)
    assert math.isclose(rz._sum_sq, expected_sum_sq, abs_tol=1e-9)
