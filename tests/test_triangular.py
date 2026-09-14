from __future__ import annotations

import pytest

from cas.triangular import discover_triangular_cycles, evaluate_cycle


def _markets() -> dict[str, dict[str, object]]:
    return {
        "BNB/USDT": {
            "symbol": "BNB/USDT",
            "base": "BNB",
            "quote": "USDT",
            "spot": True,
            "active": True,
        },
        "ETH/BNB": {
            "symbol": "ETH/BNB",
            "base": "ETH",
            "quote": "BNB",
            "spot": True,
            "active": True,
        },
        "ETH/USDT": {
            "symbol": "ETH/USDT",
            "base": "ETH",
            "quote": "USDT",
            "spot": True,
            "active": True,
        },
    }


def test_discovers_both_directions_of_triangle() -> None:
    cycles = discover_triangular_cycles(
        _markets(),
        anchor_asset="USDT",
        allowed_assets={"BNB", "ETH"},
        max_cycles=10,
    )
    paths = {cycle.path for cycle in cycles}

    assert ("USDT", "BNB", "ETH", "USDT") in paths
    assert ("USDT", "ETH", "BNB", "USDT") in paths


def test_evaluate_profitable_usdt_bnb_eth_cycle_with_fees() -> None:
    cycle = next(
        cycle
        for cycle in discover_triangular_cycles(
            _markets(),
            anchor_asset="USDT",
            allowed_assets={"BNB", "ETH"},
            max_cycles=10,
        )
        if cycle.path == ("USDT", "BNB", "ETH", "USDT")
    )
    books = {
        "BNB/USDT": {"asks": [[100.0, 20.0]], "bids": [[99.0, 20.0]]},
        "ETH/BNB": {"asks": [[2.0, 20.0]], "bids": [[1.99, 20.0]]},
        "ETH/USDT": {"asks": [[211.0, 20.0]], "bids": [[210.0, 20.0]]},
    }

    opportunity = evaluate_cycle(
        cycle,
        books,
        exchange_id="bybit",
        start_amount=1000.0,
        fee_rate=0.001,
        fixed_cost_rate=0.0,
    )

    assert opportunity is not None
    assert opportunity.path == ("USDT", "BNB", "ETH", "USDT")
    assert opportunity.final_amount == pytest.approx(1050.0 * 0.999**3)
    assert opportunity.net_profit_pct > 4.0
    assert [leg.side for leg in opportunity.legs] == ["buy", "buy", "sell"]


def test_cycle_rejected_when_book_depth_is_insufficient() -> None:
    cycle = next(
        cycle
        for cycle in discover_triangular_cycles(
            _markets(),
            anchor_asset="USDT",
            allowed_assets={"BNB", "ETH"},
            max_cycles=10,
        )
        if cycle.path == ("USDT", "BNB", "ETH", "USDT")
    )
    books = {
        "BNB/USDT": {"asks": [[100.0, 1.0]], "bids": [[99.0, 20.0]]},
        "ETH/BNB": {"asks": [[2.0, 20.0]], "bids": [[1.99, 20.0]]},
        "ETH/USDT": {"asks": [[211.0, 20.0]], "bids": [[210.0, 20.0]]},
    }

    assert (
        evaluate_cycle(
            cycle,
            books,
            exchange_id="bybit",
            start_amount=1000.0,
            fee_rate=0.001,
            fixed_cost_rate=0.0,
        )
        is None
    )
