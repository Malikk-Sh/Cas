from __future__ import annotations

from itertools import permutations
from typing import Iterable, Sequence

from cas.exchanges import ExchangePool
from cas.models import Opportunity

OrderLevels = Sequence[Sequence[float]]


def simulate_buy(asks: OrderLevels, quote_budget: float) -> tuple[float, float] | None:
    """Return (base_bought, vwap) for spending quote_budget against asks."""
    remaining_quote = quote_budget
    base_bought = 0.0

    for level in asks:
        if len(level) < 2:
            continue
        price = float(level[0])
        base_available = float(level[1])
        if price <= 0 or base_available <= 0:
            continue

        level_quote_value = price * base_available
        quote_fill = min(remaining_quote, level_quote_value)
        base_bought += quote_fill / price
        remaining_quote -= quote_fill

        if remaining_quote <= max(1e-9, quote_budget * 1e-9):
            break

    if remaining_quote > max(1e-8, quote_budget * 1e-6) or base_bought <= 0:
        return None

    return base_bought, quote_budget / base_bought


def simulate_sell(bids: OrderLevels, base_amount: float) -> tuple[float, float] | None:
    """Return (quote_received, vwap) for selling base_amount against bids."""
    remaining_base = base_amount
    quote_received = 0.0

    for level in bids:
        if len(level) < 2:
            continue
        price = float(level[0])
        base_available = float(level[1])
        if price <= 0 or base_available <= 0:
            continue

        base_fill = min(remaining_base, base_available)
        quote_received += base_fill * price
        remaining_base -= base_fill

        if remaining_base <= max(1e-12, base_amount * 1e-9):
            break

    if remaining_base > max(1e-10, base_amount * 1e-6) or quote_received <= 0:
        return None

    return quote_received, quote_received / base_amount


class ArbitrageScanner:
    def __init__(
        self,
        pool: ExchangePool,
        *,
        notional_quote: float,
        taker_fee_rate: float,
        fixed_cost_rate: float,
        depth_limit: int,
    ) -> None:
        self.pool = pool
        self.notional_quote = notional_quote
        self.taker_fee_rate = taker_fee_rate
        self.fixed_cost_rate = fixed_cost_rate
        self.depth_limit = depth_limit

    async def scan_symbol(self, symbol: str) -> list[Opportunity]:
        books = await self.pool.fetch_symbol_books(symbol, self.depth_limit)
        opportunities: list[Opportunity] = []

        for buy_exchange, sell_exchange in permutations(books.keys(), 2):
            buy_book = books[buy_exchange]
            sell_book = books[sell_exchange]

            buy_fill = simulate_buy(buy_book["asks"], self.notional_quote)
            if buy_fill is None:
                continue
            base_amount, buy_vwap = buy_fill

            sell_fill = simulate_sell(sell_book["bids"], base_amount)
            if sell_fill is None:
                continue
            quote_received, sell_vwap = sell_fill

            gross_profit = quote_received - self.notional_quote
            trading_costs = (
                self.notional_quote * self.taker_fee_rate
                + quote_received * self.taker_fee_rate
            )
            fixed_costs = self.notional_quote * self.fixed_cost_rate
            total_costs = trading_costs + fixed_costs
            net_profit = gross_profit - total_costs
            net_profit_pct = (net_profit / self.notional_quote) * 100

            opportunities.append(
                Opportunity.now(
                    symbol=symbol,
                    buy_exchange=buy_exchange,
                    sell_exchange=sell_exchange,
                    notional_quote=self.notional_quote,
                    base_amount=base_amount,
                    buy_vwap=buy_vwap,
                    sell_vwap=sell_vwap,
                    gross_profit_quote=gross_profit,
                    estimated_costs_quote=total_costs,
                    net_profit_quote=net_profit,
                    net_profit_pct=net_profit_pct,
                )
            )

        opportunities.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return opportunities

    async def scan(self, symbols: Iterable[str]) -> list[Opportunity]:
        found: list[Opportunity] = []
        for symbol in symbols:
            found.extend(await self.scan_symbol(symbol))
        found.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return found
