from __future__ import annotations

import httpx

from cas.models import Opportunity


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send_opportunity(self, opportunity: Opportunity) -> None:
        if not self.enabled:
            return

        text = (
            "🚨 Arbitrage opportunity\n"
            f"Pair: {opportunity.symbol}\n"
            f"Buy: {opportunity.buy_exchange} @ {opportunity.buy_vwap:.8f}\n"
            f"Sell: {opportunity.sell_exchange} @ {opportunity.sell_vwap:.8f}\n"
            f"Notional: {opportunity.notional_quote:.2f} quote\n"
            f"Estimated costs: {opportunity.estimated_costs_quote:.2f}\n"
            f"Net: {opportunity.net_profit_quote:.2f} "
            f"({opportunity.net_profit_pct:.3f}%)\n"
            "\nPublic market data only; re-check balances, fees, withdrawal status, and slippage before trading."
        )

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
