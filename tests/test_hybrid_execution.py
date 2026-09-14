from __future__ import annotations

import pytest

from cas.external_quotes import StaticRateQuoteProvider
from cas.hybrid import HybridRouteScanner


class NetworkPool:
    def __init__(self, *, withdraw_ok: bool | None, deposit_ok: bool | None) -> None:
        self.withdraw_ok = withdraw_ok
        self.deposit_ok = deposit_ok

    def market_map(self, exchange_id: str) -> dict:
        return {
            "BNB/USDT": {"limits": {"cost": {"min": 5.0}}},
            "ETH/USDT": {"limits": {"cost": {"min": 5.0}}},
        }

    async def fetch_exchange_books(self, exchange_id: str, symbols: list[str], limit: int) -> dict:
        return {
            "BNB/USDT": {"asks": [[500.0, 10.0]], "bids": [[499.0, 10.0]]},
            "ETH/USDT": {"asks": [[2500.0, 10.0]], "bids": [[2490.0, 10.0]]},
        }

    def normalize_amount(self, exchange_id: str, symbol: str, amount: float) -> float:
        return float(f"{amount:.6f}")

    def network_status(self, exchange_id: str, asset: str, network: str, *, direction: str) -> bool | None:
        if asset == "BNB" and direction == "withdraw":
            return self.withdraw_ok
        if asset == "ETH" and direction == "deposit":
            return self.deposit_ok
        return None


def make_scanner(pool: NetworkPool, *, strict: bool) -> HybridRouteScanner:
    return HybridRouteScanner(
        pool,
        anchor_asset="USDT",
        start_amount=1000.0,
        route_pairs=[("BNB", "ETH")],
        providers=[
            StaticRateQuoteProvider(
                "swap",
                {("BNB", "ETH"): 0.205},
                input_network="BEP20",
                output_network="ERC20",
            )
        ],
        depth_limit=10,
        taker_fee_rate=0.0,
        fixed_cost_rate=0.0,
        max_external_premium_pct=5.0,
        require_network_status=strict,
    )


@pytest.mark.asyncio
async def test_strict_mode_rejects_closed_withdraw_network() -> None:
    items = await make_scanner(
        NetworkPool(withdraw_ok=False, deposit_ok=True),
        strict=True,
    ).scan(["bybit"])
    assert items == []


@pytest.mark.asyncio
async def test_strict_mode_rejects_unknown_network_status() -> None:
    items = await make_scanner(
        NetworkPool(withdraw_ok=None, deposit_ok=True),
        strict=True,
    ).scan(["bybit"])
    assert items == []


@pytest.mark.asyncio
async def test_strict_mode_accepts_open_networks() -> None:
    items = await make_scanner(
        NetworkPool(withdraw_ok=True, deposit_ok=True),
        strict=True,
    ).scan(["bybit"])
    assert len(items) == 1
    assert items[0].net_profit_pct == pytest.approx(2.09, abs=0.02)
