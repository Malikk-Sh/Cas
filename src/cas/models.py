from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(slots=True, frozen=True)
class Opportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    notional_quote: float
    base_amount: float
    buy_vwap: float
    sell_vwap: float
    gross_profit_quote: float
    estimated_costs_quote: float
    net_profit_quote: float
    net_profit_pct: float
    detected_at: datetime

    @classmethod
    def now(cls, **kwargs: object) -> "Opportunity":
        return cls(detected_at=datetime.now(timezone.utc), **kwargs)  # type: ignore[arg-type]

    @property
    def key(self) -> str:
        return f"{self.symbol}:{self.buy_exchange}:{self.sell_exchange}"
