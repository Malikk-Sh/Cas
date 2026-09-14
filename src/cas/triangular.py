from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable

from cas.exchanges import ExchangePool
from cas.models import TriangularLeg, TriangularOpportunity
from cas.scanner import simulate_buy, simulate_sell


@dataclass(slots=True, frozen=True)
class CycleLegSpec:
    from_asset: str
    to_asset: str
    symbol: str
    market_base: str
    market_quote: str


@dataclass(slots=True, frozen=True)
class CycleSpec:
    path: tuple[str, str, str, str]
    legs: tuple[CycleLegSpec, CycleLegSpec, CycleLegSpec]


def discover_triangular_cycles(
    markets: dict[str, dict[str, Any]],
    *,
    anchor_asset: str,
    allowed_assets: set[str] | None = None,
    max_cycles: int = 200,
) -> list[CycleSpec]:
    """Discover directed 3-trade cycles that start and end in anchor_asset."""
    anchor = anchor_asset.upper()
    allowed = {asset.upper() for asset in allowed_assets} if allowed_assets else None
    adjacency: dict[str, dict[str, CycleLegSpec]] = {}

    for market in markets.values():
        if market.get("spot") is False or market.get("active") is False:
            continue
        base = str(market.get("base") or "").upper()
        quote = str(market.get("quote") or "").upper()
        symbol = str(market.get("symbol") or "")
        if not base or not quote or not symbol or base == quote:
            continue

        if allowed is not None and base != anchor and base not in allowed:
            continue
        if allowed is not None and quote != anchor and quote not in allowed:
            continue

        adjacency.setdefault(base, {})[quote] = CycleLegSpec(
            from_asset=base,
            to_asset=quote,
            symbol=symbol,
            market_base=base,
            market_quote=quote,
        )
        adjacency.setdefault(quote, {})[base] = CycleLegSpec(
            from_asset=quote,
            to_asset=base,
            symbol=symbol,
            market_base=base,
            market_quote=quote,
        )

    cycles: list[CycleSpec] = []
    seen: set[tuple[str, str, str, str]] = set()
    for first in sorted(adjacency.get(anchor, {})):
        if first == anchor:
            continue
        for second in sorted(adjacency.get(first, {})):
            if second in {anchor, first}:
                continue
            if anchor not in adjacency.get(second, {}):
                continue
            path = (anchor, first, second, anchor)
            if path in seen:
                continue
            seen.add(path)
            cycles.append(
                CycleSpec(
                    path=path,
                    legs=(
                        adjacency[anchor][first],
                        adjacency[first][second],
                        adjacency[second][anchor],
                    ),
                )
            )
            if len(cycles) >= max_cycles:
                return cycles

    return cycles


def _execute_cycle(
    cycle: CycleSpec,
    books: dict[str, dict[str, Any]],
    *,
    start_amount: float,
    fee_rate: float,
) -> tuple[float, tuple[TriangularLeg, TriangularLeg, TriangularLeg]] | None:
    amount = start_amount
    executed: list[TriangularLeg] = []

    for leg in cycle.legs:
        book = books.get(leg.symbol)
        if not book:
            return None

        if leg.from_asset == leg.market_quote and leg.to_asset == leg.market_base:
            fill = simulate_buy(book.get("asks", []), amount)
            if fill is None:
                return None
            gross_output, vwap = fill
            side = "buy"
        elif leg.from_asset == leg.market_base and leg.to_asset == leg.market_quote:
            fill = simulate_sell(book.get("bids", []), amount)
            if fill is None:
                return None
            gross_output, vwap = fill
            side = "sell"
        else:
            return None

        net_output = gross_output * (1.0 - fee_rate)
        executed.append(
            TriangularLeg(
                from_asset=leg.from_asset,
                to_asset=leg.to_asset,
                symbol=leg.symbol,
                side=side,
                input_amount=amount,
                output_amount=net_output,
                vwap=vwap,
                fee_rate=fee_rate,
            )
        )
        amount = net_output

    if len(executed) != 3:
        return None
    return amount, (executed[0], executed[1], executed[2])


def evaluate_cycle(
    cycle: CycleSpec,
    books: dict[str, dict[str, Any]],
    *,
    exchange_id: str,
    start_amount: float,
    fee_rate: float,
    fixed_cost_rate: float,
) -> TriangularOpportunity | None:
    with_fees = _execute_cycle(
        cycle,
        books,
        start_amount=start_amount,
        fee_rate=fee_rate,
    )
    if with_fees is None:
        return None
    final_after_fees, legs = with_fees

    without_fees = _execute_cycle(
        cycle,
        books,
        start_amount=start_amount,
        fee_rate=0.0,
    )
    if without_fees is None:
        return None
    final_without_fees, _ = without_fees

    fee_impact = max(0.0, final_without_fees - final_after_fees)
    fixed_cost = start_amount * fixed_cost_rate
    net_final = final_after_fees - fixed_cost
    gross_profit = final_without_fees - start_amount
    estimated_costs = fee_impact + fixed_cost
    net_profit = net_final - start_amount
    net_profit_pct = (net_profit / start_amount) * 100

    return TriangularOpportunity.now(
        exchange=exchange_id,
        anchor_asset=cycle.path[0],
        path=cycle.path,
        start_amount=start_amount,
        final_amount=net_final,
        gross_profit_quote=gross_profit,
        estimated_costs_quote=estimated_costs,
        net_profit_quote=net_profit,
        net_profit_pct=net_profit_pct,
        legs=legs,
    )


class TriangularArbitrageScanner:
    def __init__(
        self,
        pool: ExchangePool,
        *,
        anchor_asset: str,
        start_amount: float,
        taker_fee_rate: float,
        fixed_cost_rate: float,
        depth_limit: int,
        allowed_assets: set[str] | None = None,
        max_cycles: int = 200,
        exchange_fee_rates: dict[str, float] | None = None,
    ) -> None:
        self.pool = pool
        self.anchor_asset = anchor_asset.upper()
        self.start_amount = start_amount
        self.taker_fee_rate = taker_fee_rate
        self.fixed_cost_rate = fixed_cost_rate
        self.depth_limit = depth_limit
        self.allowed_assets = allowed_assets
        self.max_cycles = max_cycles
        self.exchange_fee_rates = exchange_fee_rates or {}

    def _fee_rate(self, exchange_id: str) -> float:
        return self.exchange_fee_rates.get(exchange_id, self.taker_fee_rate)

    async def scan_exchange(self, exchange_id: str) -> list[TriangularOpportunity]:
        markets = self.pool.market_map(exchange_id)
        cycles = discover_triangular_cycles(
            markets,
            anchor_asset=self.anchor_asset,
            allowed_assets=self.allowed_assets,
            max_cycles=self.max_cycles,
        )
        if not cycles:
            return []

        symbols = sorted({leg.symbol for cycle in cycles for leg in cycle.legs})
        books = await self.pool.fetch_exchange_books(
            exchange_id,
            symbols,
            self.depth_limit,
        )
        fee_rate = self._fee_rate(exchange_id)
        opportunities = [
            opportunity
            for cycle in cycles
            if (
                opportunity := evaluate_cycle(
                    cycle,
                    books,
                    exchange_id=exchange_id,
                    start_amount=self.start_amount,
                    fee_rate=fee_rate,
                    fixed_cost_rate=self.fixed_cost_rate,
                )
            )
            is not None
        ]
        opportunities.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return opportunities

    async def scan(self, exchange_ids: Iterable[str]) -> list[TriangularOpportunity]:
        batches = await asyncio.gather(
            *(self.scan_exchange(exchange_id) for exchange_id in exchange_ids)
        )
        found = [item for batch in batches for item in batch]
        found.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return found
