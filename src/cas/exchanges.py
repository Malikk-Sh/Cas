from __future__ import annotations

import asyncio
from typing import Any

import ccxt.async_support as ccxt


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
