from __future__ import annotations

import asyncio
from typing import Any, Iterable

import ccxt.async_support as ccxt

from cas.execution import canonical_network


class ExchangePool:
    def __init__(self, exchange_ids: list[str]) -> None:
        self._exchange_ids = exchange_ids
        self.exchanges: dict[str, Any] = {}

    async def start(self) -> None:
        for exchange_id in self._exchange_ids:
            exchange_cls = getattr(ccxt, exchange_id, None)
            if exchange_cls is None:
                raise ValueError(f"Unknown CCXT exchange: {exchange_id}")
            self.exchanges[exchange_id] = exchange_cls(
                {
                    "enableRateLimit": True,
                    "options": {"defaultType": "spot"},
                }
            )

        results = await asyncio.gather(
            *(exchange.load_markets() for exchange in self.exchanges.values()),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, Exception)]
        if failures:
            await self.close()
            raise RuntimeError(f"Failed to load exchange markets: {failures[0]}")

    async def close(self) -> None:
        if not self.exchanges:
            return
        await asyncio.gather(
            *(exchange.close() for exchange in self.exchanges.values()),
            return_exceptions=True,
        )

    def market_map(self, exchange_id: str) -> dict[str, dict[str, Any]]:
        exchange = self.exchanges[exchange_id]
        return exchange.markets

    def normalize_amount(
        self,
        exchange_id: str,
        symbol: str,
        amount: float,
    ) -> float | None:
        """Round an amount using the exchange's market precision rules."""
        if amount <= 0:
            return None
        exchange = self.exchanges[exchange_id]
        try:
            normalized = float(exchange.amount_to_precision(symbol, amount))
        except Exception:
            return None
        return normalized if normalized > 0 else None

    def network_status(
        self,
        exchange_id: str,
        asset: str,
        network: str,
        *,
        direction: str,
    ) -> bool | None:
        """Return deposit/withdraw status for a requested network.

        True/False means the exchange explicitly reports a status. None means
        the public CCXT metadata is insufficient to decide.
        """
        if direction not in {"deposit", "withdraw"}:
            raise ValueError("direction must be deposit or withdraw")
        requested = canonical_network(network)
        if not requested:
            return None

        exchange = self.exchanges[exchange_id]
        currencies = getattr(exchange, "currencies", {}) or {}
        currency = currencies.get(asset.upper()) or currencies.get(asset)
        if not isinstance(currency, dict):
            return None

        networks = currency.get("networks") or {}
        if isinstance(networks, dict):
            for key, metadata in networks.items():
                if not isinstance(metadata, dict):
                    continue
                aliases = [
                    str(key),
                    str(metadata.get("id") or ""),
                    str(metadata.get("network") or ""),
                    str(metadata.get("name") or ""),
                ]
                if requested not in {canonical_network(item) for item in aliases if item}:
                    continue

                value = metadata.get(direction)
                if isinstance(value, bool):
                    return value
                if metadata.get("active") is False:
                    return False
                return None

        value = currency.get(direction)
        if isinstance(value, bool):
            return value
        return None

    async def fetch_order_book(
        self,
        exchange_id: str,
        symbol: str,
        limit: int,
    ) -> dict[str, Any] | None:
        exchange = self.exchanges[exchange_id]
        if symbol not in exchange.markets:
            return None
        try:
            return await exchange.fetch_order_book(symbol, limit=limit)
        except Exception:
            return None

    async def fetch_symbol_books(
        self,
        symbol: str,
        limit: int,
    ) -> dict[str, dict[str, Any]]:
        ids = list(self.exchanges)
        books = await asyncio.gather(
            *(self.fetch_order_book(exchange_id, symbol, limit) for exchange_id in ids)
        )
        return {
            exchange_id: book
            for exchange_id, book in zip(ids, books, strict=True)
            if book is not None and book.get("asks") and book.get("bids")
        }

    async def fetch_exchange_books(
        self,
        exchange_id: str,
        symbols: Iterable[str],
        limit: int,
        *,
        concurrency: int = 8,
    ) -> dict[str, dict[str, Any]]:
        unique_symbols = list(dict.fromkeys(symbols))
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def fetch_one(symbol: str) -> tuple[str, dict[str, Any] | None]:
            async with semaphore:
                return symbol, await self.fetch_order_book(exchange_id, symbol, limit)

        results = await asyncio.gather(*(fetch_one(symbol) for symbol in unique_symbols))
        return {
            symbol: book
            for symbol, book in results
            if book is not None and book.get("asks") and book.get("bids")
        }
