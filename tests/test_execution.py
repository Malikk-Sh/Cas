from __future__ import annotations

from cas.execution import canonical_network, validate_market_order


def test_market_min_amount_and_cost_limits() -> None:
    market = {
        "limits": {
            "amount": {"min": 0.01, "max": 10.0},
            "cost": {"min": 5.0, "max": 10000.0},
        }
    }
    assert validate_market_order(market, amount=0.02, cost=10.0).ok
    low_amount = validate_market_order(market, amount=0.001, cost=10.0)
    assert not low_amount.ok
    assert "below min" in low_amount.reason
    low_cost = validate_market_order(market, amount=0.02, cost=1.0)
    assert not low_cost.ok
    assert "below min" in low_cost.reason


def test_missing_market_limits_are_not_rejected() -> None:
    assert validate_market_order({}, amount=1.0, cost=100.0).ok


def test_common_network_aliases_normalize() -> None:
    assert canonical_network("BEP20") == "BSC"
    assert canonical_network("BNB Smart Chain") == "BSC"
    assert canonical_network("ERC20") == "ETH"
    assert canonical_network("Ethereum") == "ETH"
