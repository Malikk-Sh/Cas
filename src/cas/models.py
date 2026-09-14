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
        return f"inter:{self.symbol}:{self.buy_exchange}:{self.sell_exchange}"


@dataclass(slots=True, frozen=True)
class TriangularLeg:
    from_asset: str
    to_asset: str
    symbol: str
    side: str
    input_amount: float
    output_amount: float
    vwap: float
    fee_rate: float


@dataclass(slots=True, frozen=True)
class TriangularOpportunity:
    exchange: str
    anchor_asset: str
    path: tuple[str, str, str, str]
    start_amount: float
    final_amount: float
    gross_profit_quote: float
    estimated_costs_quote: float
    net_profit_quote: float
    net_profit_pct: float
    legs: tuple[TriangularLeg, TriangularLeg, TriangularLeg]
    detected_at: datetime

    @classmethod
    def now(cls, **kwargs: object) -> "TriangularOpportunity":
        return cls(detected_at=datetime.now(timezone.utc), **kwargs)  # type: ignore[arg-type]

    @property
    def key(self) -> str:
        return f"tri:{self.exchange}:{'->'.join(self.path)}"


@dataclass(slots=True, frozen=True)
class HybridLeg:
    venue: str
    kind: str
    from_asset: str
    to_asset: str
    input_amount: float
    output_amount: float
    detail: str = ""


@dataclass(slots=True, frozen=True)
class HybridOpportunity:
    exchange: str
    provider: str
    anchor_asset: str
    path: tuple[str, str, str, str]
    start_amount: float
    final_amount: float
    net_profit_quote: float
    net_profit_pct: float
    external_premium_pct: float
    suspicious: bool
    suspicious_reason: str
    legs: tuple[HybridLeg, HybridLeg, HybridLeg]
    detected_at: datetime

    @classmethod
    def now(cls, **kwargs: object) -> "HybridOpportunity":
        return cls(detected_at=datetime.now(timezone.utc), **kwargs)  # type: ignore[arg-type]

    @property
    def key(self) -> str:
        return f"hybrid:{self.exchange}:{self.provider}:{'->'.join(self.path)}"
