from __future__ import annotations

import asyncio
from typing import Iterable

from cas.execution import validate_market_order
from cas.external_quotes import QuoteProvider
from cas.models import HybridLeg, HybridOpportunity
from cas.scanner import simulate_buy, simulate_sell


class HybridRouteScanner:
    """Scan CEX -> external swap -> CEX routes such as USDT -> BNB -> ETH -> USDT."""

    def __init__(
        self,
        pool,
        *,
        anchor_asset: str,
        start_amount: float,
        route_pairs: list[tuple[str, str]],
        providers: list[QuoteProvider],
        depth_limit: int,
        taker_fee_rate: float,
        fixed_cost_rate: float,
        max_external_premium_pct: float,
        exchange_fee_rates: dict[str, float] | None = None,
        require_network_status: bool = False,
    ) -> None:
        self.pool = pool
        self.anchor_asset = anchor_asset.upper()
        self.start_amount = start_amount
        self.route_pairs = [(a.upper(), b.upper()) for a, b in route_pairs]
        self.providers = providers
        self.depth_limit = depth_limit
        self.taker_fee_rate = taker_fee_rate
        self.fixed_cost_rate = fixed_cost_rate
        self.max_external_premium_pct = max_external_premium_pct
        self.exchange_fee_rates = exchange_fee_rates or {}
        self.require_network_status = require_network_status

    def _fee_rate(self, exchange_id: str) -> float:
        return self.exchange_fee_rates.get(exchange_id, self.taker_fee_rate)

    @staticmethod
    def _best_bid(book: dict) -> float | None:
        bids = book.get("bids") or []
        if not bids or len(bids[0]) < 2:
            return None
        price = float(bids[0][0])
        return price if price > 0 else None

    def _normalize_amount(
        self,
        exchange_id: str,
        symbol: str,
        amount: float,
    ) -> float | None:
        normalize = getattr(self.pool, "normalize_amount", None)
        if normalize is None:
            return amount if amount > 0 else None
        return normalize(exchange_id, symbol, amount)

    def _network_usable(
        self,
        exchange_id: str,
        asset: str,
        network: str,
        *,
        direction: str,
    ) -> bool:
        if not network:
            return not self.require_network_status
        getter = getattr(self.pool, "network_status", None)
        if getter is None:
            return not self.require_network_status
        status = getter(
            exchange_id,
            asset,
            network,
            direction=direction,
        )
        if status is False:
            return False
        if status is None and self.require_network_status:
            return False
        return True

    async def scan_exchange(
        self,
        exchange_id: str,
        *,
        start_amount: float | None = None,
    ) -> list[HybridOpportunity]:
        notional = self.start_amount if start_amount is None else start_amount
        if notional <= 0:
            return []

        markets = self.pool.market_map(exchange_id)
        opportunities: list[HybridOpportunity] = []
        fee_rate = self._fee_rate(exchange_id)

        for first_asset, second_asset in self.route_pairs:
            first_symbol = f"{first_asset}/{self.anchor_asset}"
            second_symbol = f"{second_asset}/{self.anchor_asset}"
            if first_symbol not in markets or second_symbol not in markets:
                continue

            first_market = markets[first_symbol]
            second_market = markets[second_symbol]
            books = await self.pool.fetch_exchange_books(
                exchange_id,
                [first_symbol, second_symbol],
                self.depth_limit,
            )
            first_book = books.get(first_symbol)
            second_book = books.get(second_symbol)
            if not first_book or not second_book:
                continue

            first_fill = simulate_buy(first_book.get("asks", []), notional)
            if first_fill is None:
                continue
            first_gross, first_vwap = first_fill
            first_exec = self._normalize_amount(
                exchange_id,
                first_symbol,
                first_gross,
            )
            if first_exec is None:
                continue
            first_check = validate_market_order(
                first_market,
                amount=first_exec,
                cost=first_exec * first_vwap,
            )
            if not first_check.ok:
                continue
            first_net = first_exec * (1.0 - fee_rate)

            quotes = await asyncio.gather(
                *(
                    provider.quote(first_asset, second_asset, first_net)
                    for provider in self.providers
                ),
                return_exceptions=True,
            )
            for provider, quote in zip(self.providers, quotes, strict=True):
                if isinstance(quote, Exception) or quote is None:
                    continue

                if not self._network_usable(
                    exchange_id,
                    first_asset,
                    quote.input_network,
                    direction="withdraw",
                ):
                    continue
                if not self._network_usable(
                    exchange_id,
                    second_asset,
                    quote.output_network,
                    direction="deposit",
                ):
                    continue

                external_output = quote.output_amount
                final_exec = self._normalize_amount(
                    exchange_id,
                    second_symbol,
                    external_output,
                )
                if final_exec is None:
                    continue

                first_bid = self._best_bid(first_book)
                second_bid = self._best_bid(second_book)
                if first_bid is None or second_bid is None:
                    continue

                final_check = validate_market_order(
                    second_market,
                    amount=final_exec,
                    cost=final_exec * second_bid,
                )
                if not final_check.ok:
                    continue

                input_value = first_net * first_bid
                output_value = external_output * second_bid
                if input_value <= 0:
                    continue
                external_premium_pct = ((output_value / input_value) - 1.0) * 100
                suspicious = external_premium_pct > self.max_external_premium_pct
                suspicious_reason = ""
                if suspicious:
                    suspicious_reason = (
                        f"external quote implies {external_premium_pct:.2f}% value creation "
                        f"vs {exchange_id} spot reference"
                    )

                final_fill = simulate_sell(
                    second_book.get("bids", []),
                    final_exec,
                )
                if final_fill is None:
                    continue
                final_gross, final_vwap = final_fill
                final_after_fee = final_gross * (1.0 - fee_rate)
                final_amount = final_after_fee - notional * self.fixed_cost_rate
                net_profit = final_amount - notional
                net_profit_pct = (net_profit / notional) * 100

                first_detail = (
                    f"BUY {first_symbol} VWAP={first_vwap:.8f}; fee={fee_rate:.6f}"
                )
                network_bits = "/".join(
                    x for x in [quote.input_network, quote.output_network] if x
                )
                swap_detail = f"quote={quote.reference}"
                if network_bits:
                    swap_detail = f"networks={network_bits}; {swap_detail}"
                final_detail = (
                    f"SELL {second_symbol} VWAP={final_vwap:.8f}; fee={fee_rate:.6f}"
                )
                if final_exec < external_output:
                    final_detail += (
                        f"; precision_dust={external_output - final_exec:.12g} {second_asset}"
                    )

                opportunities.append(
                    HybridOpportunity.now(
                        exchange=exchange_id,
                        provider=provider.name,
                        anchor_asset=self.anchor_asset,
                        path=(
                            self.anchor_asset,
                            first_asset,
                            second_asset,
                            self.anchor_asset,
                        ),
                        start_amount=notional,
                        final_amount=final_amount,
                        net_profit_quote=net_profit,
                        net_profit_pct=net_profit_pct,
                        external_premium_pct=external_premium_pct,
                        suspicious=suspicious,
                        suspicious_reason=suspicious_reason,
                        legs=(
                            HybridLeg(
                                exchange_id,
                                "cex",
                                self.anchor_asset,
                                first_asset,
                                notional,
                                first_net,
                                first_detail,
                            ),
                            HybridLeg(
                                provider.name,
                                "external_swap",
                                first_asset,
                                second_asset,
                                first_net,
                                external_output,
                                swap_detail,
                            ),
                            HybridLeg(
                                exchange_id,
                                "cex",
                                second_asset,
                                self.anchor_asset,
                                final_exec,
                                final_after_fee,
                                final_detail,
                            ),
                        ),
                    )
                )

        opportunities.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return opportunities

    async def scan(
        self,
        exchange_ids: Iterable[str],
        *,
        start_amount: float | None = None,
    ) -> list[HybridOpportunity]:
        nested = await asyncio.gather(
            *(
                self.scan_exchange(exchange_id, start_amount=start_amount)
                for exchange_id in exchange_ids
            )
        )
        found = [item for group in nested for item in group]
        found.sort(key=lambda item: item.net_profit_pct, reverse=True)
        return found
