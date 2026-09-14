from __future__ import annotations

import pytest

from cas.external_quotes import StaticRateQuoteProvider
from cas.hybrid import HybridRouteScanner


class Pool:
    def market_map(self, exchange_id: str) -> dict:
        return {"BNB/USDT": {}, "ETH/USDT": {}}

    async def fetch_exchange_books(
        self,
        exchange_id: str,
        symbols: list[str],
        limit: int,
    ) -> dict:
        return {
            "BNB/USDT": {
                "asks": [[500.0, 10.0]],
                "bids": [[499.0, 10.0]],
            },
            "ETH/USDT": {
                "asks": [[2500.0, 10.0]],
                "bids": [[2490.0, 10.0]],
            },
        }


@pytest.mark.asyncio
async def test_hybrid_profitable_route() -> None:
    scanner = HybridRouteScanner(
        Pool(),
        anchor_asset="USDT",
        start_amount=1000.0,
        route_pairs=[("BNB", "ETH")],
        providers=[
            StaticRateQuoteProvider(
                "swap",
                {("BNB", "ETH"): 0.205},
            )
        ],
        depth_limit=10,
        taker_fee_rate=0.0,
        fixed_cost_rate=0.0,
        max_external_premium_pct=5.0,
    )
    items = await scanner.scan(["bybit"])
    assert len(items) == 1
    assert items[0].net_profit_pct == pytest.approx(2.09, abs=0.01)
    assert not items[0].suspicious


@pytest.mark.asyncio
async def test_screenshot_like_impossible_quote_is_not_executable_without_depth() -> None:
    huge_rate = 2676.03 / 1.1535
    scanner = HybridRouteScanner(
        Pool(),
        anchor_asset="USDT",
        start_amount=576.75,
        route_pairs=[("BNB", "ETH")],
        providers=[
            StaticRateQuoteProvider(
                "claimed-site",
                {("BNB", "ETH"): huge_rate},
            )
        ],
        depth_limit=10,
        taker_fee_rate=0.0,
        fixed_cost_rate=0.0,
        max_external_premium_pct=5.0,
    )
    items = await scanner.scan(["bybit"])
    assert items == []


class DeepPool(Pool):
    async def fetch_exchange_books(
        self,
        exchange_id: str,
        symbols: list[str],
        limit: int,
    ) -> dict:
        return {
            "BNB/USDT": {
                "asks": [[500.0, 10000.0]],
                "bids": [[499.0, 10000.0]],
            },
            "ETH/USDT": {
                "asks": [[2500.0, 10000.0]],
                "bids": [[2490.0, 10000.0]],
            },
        }


@pytest.mark.asyncio
async def test_impossible_quote_is_flagged_when_depth_exists() -> None:
    huge_rate = 2676.03 / 1.1535
    scanner = HybridRouteScanner(
        DeepPool(),
        anchor_asset="USDT",
        start_amount=576.75,
        route_pairs=[("BNB", "ETH")],
        providers=[
            StaticRateQuoteProvider(
                "claimed-site",
                {("BNB", "ETH"): huge_rate},
            )
        ],
        depth_limit=10,
        taker_fee_rate=0.0,
        fixed_cost_rate=0.0,
        max_external_premium_pct=5.0,
    )
    items = await scanner.scan(["bybit"])
    assert len(items) == 1
    assert items[0].suspicious
    assert items[0].external_premium_pct > 100000.0
