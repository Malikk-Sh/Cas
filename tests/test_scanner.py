from __future__ import annotations

import pytest

from cas.scanner import simulate_buy, simulate_sell


def test_simulate_buy_across_multiple_levels() -> None:
    asks = [[10.0, 5.0], [11.0, 10.0]]
    result = simulate_buy(asks, 105.0)

    assert result is not None
    base_bought, vwap = result
    assert base_bought == pytest.approx(10.0)
    assert vwap == pytest.approx(10.5)


def test_simulate_buy_returns_none_when_depth_is_insufficient() -> None:
    assert simulate_buy([[10.0, 1.0]], 100.0) is None


def test_simulate_sell_across_multiple_levels() -> None:
    bids = [[12.0, 4.0], [11.0, 6.0]]
    result = simulate_sell(bids, 10.0)

    assert result is not None
    quote_received, vwap = result
    assert quote_received == pytest.approx(114.0)
    assert vwap == pytest.approx(11.4)


def test_simulate_sell_returns_none_when_depth_is_insufficient() -> None:
    assert simulate_sell([[10.0, 1.0]], 2.0) is None
