from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class ExecutionCheck:
    ok: bool
    reason: str = ""


def validate_market_order(
    market: dict[str, Any],
    *,
    amount: float,
    cost: float,
) -> ExecutionCheck:
    """Validate an estimated market order against CCXT min/max limits.

    Missing limits are treated as unknown rather than as a failure. Precision is
    handled separately by the exchange adapter before this check.
    """
    if amount <= 0 or cost <= 0:
        return ExecutionCheck(False, "non-positive order amount/cost")

    limits = market.get("limits") or {}
    amount_limits = limits.get("amount") or {}
    cost_limits = limits.get("cost") or {}

    min_amount = amount_limits.get("min")
    max_amount = amount_limits.get("max")
    min_cost = cost_limits.get("min")
    max_cost = cost_limits.get("max")

    if min_amount is not None and amount + 1e-15 < float(min_amount):
        return ExecutionCheck(
            False,
            f"amount {amount:.12g} below min {float(min_amount):.12g}",
        )
    if max_amount is not None and amount - 1e-15 > float(max_amount):
        return ExecutionCheck(
            False,
            f"amount {amount:.12g} above max {float(max_amount):.12g}",
        )
    if min_cost is not None and cost + 1e-12 < float(min_cost):
        return ExecutionCheck(
            False,
            f"cost {cost:.12g} below min {float(min_cost):.12g}",
        )
    if max_cost is not None and cost - 1e-12 > float(max_cost):
        return ExecutionCheck(
            False,
            f"cost {cost:.12g} above max {float(max_cost):.12g}",
        )

    return ExecutionCheck(True)


def canonical_network(value: str) -> str:
    """Normalize common exchange/network aliases for compatibility checks."""
    raw = "".join(ch for ch in value.upper() if ch.isalnum())
    if not raw:
        return ""
    if "BEP20" in raw or raw in {"BSC", "BNBSMARTCHAIN", "BSCBNB"}:
        return "BSC"
    if "ERC20" in raw or raw in {"ETH", "ETHEREUM", "ETHMAINNET"}:
        return "ETH"
    if "TRC20" in raw or raw in {"TRX", "TRON"}:
        return "TRX"
    if "ARBITRUM" in raw or raw in {"ARB", "ARBEVM"}:
        return "ARBITRUM"
    if "OPTIMISM" in raw or raw in {"OP", "OPMAINNET"}:
        return "OPTIMISM"
    if raw in {"MATIC", "POL", "POLYGON", "POLYGONPOS"}:
        return "POLYGON"
    if raw in {"SOL", "SOLANA"}:
        return "SOL"
    if raw in {"BASE", "BASEMAINNET"}:
        return "BASE"
    if raw in {"AVAXC", "AVALANCHEC", "AVALANCHECCHAIN"}:
        return "AVAXC"
    return raw
