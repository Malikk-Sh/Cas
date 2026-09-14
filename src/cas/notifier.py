from __future__ import annotations

import httpx

from cas.models import Opportunity, TriangularOpportunity


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def _send_text(self, text: str) -> None:
        if not self.enabled:
            return
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

    async def send_opportunity(self, opportunity: Opportunity) -> None:
        text = (
            "🚨 Межбиржевая связка\n"
            f"Пара: {opportunity.symbol}\n"
            f"Купить: {opportunity.buy_exchange} @ {opportunity.buy_vwap:.8f}\n"
            f"Продать: {opportunity.sell_exchange} @ {opportunity.sell_vwap:.8f}\n"
            f"Объём: {opportunity.notional_quote:.2f} quote\n"
            f"Расчётные издержки: {opportunity.estimated_costs_quote:.2f}\n"
            f"Net: {opportunity.net_profit_quote:.2f} "
            f"({opportunity.net_profit_pct:.3f}%)\n\n"
            "Публичные данные: перед сделкой перепроверь стакан, комиссии, ввод/вывод и проскальзывание."
        )
        await self._send_text(text)

    async def send_triangular_opportunity(self, opportunity: TriangularOpportunity) -> None:
        leg_lines = []
        for index, leg in enumerate(opportunity.legs, start=1):
            leg_lines.append(
                f"{index}. {leg.side.upper()} {leg.symbol}: "
                f"{leg.input_amount:.8f} {leg.from_asset} → "
                f"{leg.output_amount:.8f} {leg.to_asset} @ {leg.vwap:.8f}"
            )

        text = (
            "🔺 Треугольная связка\n"
            f"Биржа: {opportunity.exchange}\n"
            f"Маршрут: {' → '.join(opportunity.path)}\n"
            f"Старт: {opportunity.start_amount:.2f} {opportunity.anchor_asset}\n"
            + "\n".join(leg_lines)
            + "\n"
            f"Расчётные издержки: {opportunity.estimated_costs_quote:.4f} {opportunity.anchor_asset}\n"
            f"Финиш: {opportunity.final_amount:.4f} {opportunity.anchor_asset}\n"
            f"Net: {opportunity.net_profit_quote:.4f} {opportunity.anchor_asset} "
            f"({opportunity.net_profit_pct:.3f}%)\n\n"
            "Это оценка по публичным стаканам; комиссии и исполнение могут отличаться."
        )
        await self._send_text(text)
