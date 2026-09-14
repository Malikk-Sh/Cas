from __future__ import annotations

import asyncio
import logging
import time

from cas.config import get_settings
from cas.exchanges import ExchangePool
from cas.external_quotes import providers_from_json
from cas.hybrid import HybridRouteScanner
from cas.notifier import TelegramNotifier
from cas.p2p import BybitP2PSource
from cas.scanner import ArbitrageScanner
from cas.triangular import TriangularArbitrageScanner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("cas")


async def run() -> None:
    settings = get_settings()
    all_exchange_ids = list(
        dict.fromkeys(settings.exchange_ids + settings.hybrid_exchange_ids)
    )
    pool = ExchangePool(all_exchange_ids)
    notifier = TelegramNotifier(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
    )
    interexchange_scanner = ArbitrageScanner(
        pool,
        notional_quote=settings.notional_usdt,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        depth_limit=settings.depth_limit,
        exchange_fee_rates=settings.exchange_taker_fee_rates,
    )
    triangular_scanner = TriangularArbitrageScanner(
        pool,
        anchor_asset=settings.triangular_anchor_asset,
        start_amount=settings.notional_usdt,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        depth_limit=settings.depth_limit,
        allowed_assets=settings.triangular_asset_set,
        max_cycles=settings.triangular_max_cycles,
        exchange_fee_rates=settings.exchange_taker_fee_rates,
    )
    providers = providers_from_json(settings.external_quote_providers_json)
    hybrid_scanner = HybridRouteScanner(
        pool,
        anchor_asset=settings.hybrid_anchor_asset,
        start_amount=settings.hybrid_start_amount_usdt,
        route_pairs=settings.hybrid_route_pair_list,
        providers=providers,
        depth_limit=settings.depth_limit,
        taker_fee_rate=settings.taker_fee_rate,
        fixed_cost_rate=settings.fixed_cost_rate,
        max_external_premium_pct=settings.hybrid_max_external_premium_pct,
        exchange_fee_rates=settings.exchange_taker_fee_rates,
    )
    p2p_source = BybitP2PSource(
        api_key=settings.bybit_p2p_api_key,
        api_secret=settings.bybit_p2p_api_secret,
        fiat_currency=settings.p2p_fiat_currency,
        token=settings.p2p_token,
        testnet=settings.bybit_p2p_testnet,
        min_completion_rate=settings.p2p_min_completion_rate,
        min_recent_orders=settings.p2p_min_recent_orders,
        require_verified_advertiser=settings.p2p_require_verified_advertiser,
        page_size=settings.p2p_page_size,
    )
    last_alert_at: dict[str, float] = {}

    logger.info(
        "Starting scanner: exchanges=%s interexchange=%s triangular=%s hybrid=%s p2p=%s notional=%.2f",
        ",".join(all_exchange_ids),
        settings.interexchange_enabled,
        settings.triangular_enabled,
        settings.hybrid_enabled,
        settings.p2p_enabled,
        settings.notional_usdt,
    )
    if settings.hybrid_enabled and not providers:
        logger.warning(
            "Hybrid mode is enabled but CAS_EXTERNAL_QUOTE_PROVIDERS_JSON is empty"
        )
    if settings.p2p_enabled and not p2p_source.enabled:
        logger.warning(
            "P2P mode is enabled but CAS_BYBIT_P2P_API_KEY/SECRET are not configured"
        )
    if (
        settings.p2p_enabled
        and settings.p2p_token.upper() != settings.hybrid_anchor_asset.upper()
    ):
        logger.warning(
            "P2P token %s differs from hybrid anchor %s; P2P entry will be ignored",
            settings.p2p_token,
            settings.hybrid_anchor_asset,
        )

    await pool.start()
    try:
        while True:
            started_at = time.monotonic()

            if settings.interexchange_enabled:
                opportunities = await interexchange_scanner.scan(settings.symbol_list)
                actionable = [
                    item
                    for item in opportunities
                    if item.net_profit_pct >= settings.min_net_profit_pct
                ]
            else:
                actionable = []

            if actionable:
                best = actionable[0]
                logger.info(
                    "Interexchange best: %s | buy %s %.8f -> sell %s %.8f | net %.2f (%.3f%%)",
                    best.symbol,
                    best.buy_exchange,
                    best.buy_vwap,
                    best.sell_exchange,
                    best.sell_vwap,
                    best.net_profit_quote,
                    best.net_profit_pct,
                )
            elif settings.interexchange_enabled:
                logger.info(
                    "No interexchange opportunity above %.3f%%",
                    settings.min_net_profit_pct,
                )

            if settings.triangular_enabled:
                triangular = await triangular_scanner.scan(settings.exchange_ids)
                triangular_actionable = [
                    item
                    for item in triangular
                    if item.net_profit_pct
                    >= settings.triangular_min_net_profit_pct
                ]
            else:
                triangular_actionable = []

            if triangular_actionable:
                best_tri = triangular_actionable[0]
                logger.info(
                    "Triangular best: %s | %s | net %.4f %s (%.3f%%)",
                    best_tri.exchange,
                    " -> ".join(best_tri.path),
                    best_tri.net_profit_quote,
                    best_tri.anchor_asset,
                    best_tri.net_profit_pct,
                )
            elif settings.triangular_enabled:
                logger.info(
                    "No triangular opportunity above %.3f%%",
                    settings.triangular_min_net_profit_pct,
                )

            hybrid_start_amount = settings.hybrid_start_amount_usdt
            p2p_entry_ok = True
            if (
                settings.hybrid_enabled
                and settings.p2p_enabled
                and settings.p2p_token.upper()
                == settings.hybrid_anchor_asset.upper()
            ):
                if not p2p_source.enabled:
                    p2p_entry_ok = False
                else:
                    try:
                        p2p_quote = await p2p_source.quote(settings.p2p_fiat_amount)
                    except Exception as exc:
                        logger.warning("Bybit P2P quote failed: %s", exc)
                        p2p_quote = None
                    if p2p_quote is None:
                        p2p_entry_ok = False
                        logger.info(
                            "No eligible Bybit P2P ad for %.2f %s",
                            settings.p2p_fiat_amount,
                            settings.p2p_fiat_currency,
                        )
                    else:
                        hybrid_start_amount = p2p_quote.token_amount
                        logger.info(
                            "P2P entry: %.2f %s -> %.4f %s @ %.4f | advertiser=%s rate=%.1f%% orders=%d",
                            p2p_quote.fiat_amount,
                            p2p_quote.fiat_currency,
                            p2p_quote.token_amount,
                            p2p_quote.token,
                            p2p_quote.price,
                            p2p_quote.advertiser,
                            p2p_quote.completion_rate,
                            p2p_quote.recent_orders,
                        )

            if settings.hybrid_enabled and providers and p2p_entry_ok:
                hybrid = await hybrid_scanner.scan(
                    settings.hybrid_exchange_ids,
                    start_amount=hybrid_start_amount,
                )
                suspicious = [item for item in hybrid if item.suspicious]
                hybrid_actionable = [
                    item
                    for item in hybrid
                    if item.net_profit_pct >= settings.hybrid_min_net_profit_pct
                    and (
                        settings.hybrid_allow_suspicious
                        or not item.suspicious
                    )
                ]
            else:
                suspicious = []
                hybrid_actionable = []

            if suspicious:
                worst = max(
                    suspicious,
                    key=lambda item: item.external_premium_pct,
                )
                logger.warning(
                    "Rejected suspicious quote: %s via %s | premium %.2f%% | %s",
                    " -> ".join(worst.path),
                    worst.provider,
                    worst.external_premium_pct,
                    worst.suspicious_reason,
                )

            if hybrid_actionable:
                best_hybrid = hybrid_actionable[0]
                logger.info(
                    "Hybrid best: %s via %s | net %.4f %s (%.3f%%)",
                    " -> ".join(best_hybrid.path),
                    best_hybrid.provider,
                    best_hybrid.net_profit_quote,
                    best_hybrid.anchor_asset,
                    best_hybrid.net_profit_pct,
                )
            elif settings.hybrid_enabled and providers and p2p_entry_ok:
                logger.info(
                    "No safe hybrid opportunity above %.3f%%",
                    settings.hybrid_min_net_profit_pct,
                )

            now = time.monotonic()
            for opportunity in actionable:
                last_sent = last_alert_at.get(opportunity.key, 0.0)
                if now - last_sent < settings.alert_cooldown_seconds:
                    continue
                try:
                    await notifier.send_opportunity(opportunity)
                    if notifier.enabled:
                        last_alert_at[opportunity.key] = now
                except Exception as exc:
                    logger.warning(
                        "Telegram interexchange alert failed: %s", exc
                    )

            for opportunity in triangular_actionable:
                last_sent = last_alert_at.get(opportunity.key, 0.0)
                if now - last_sent < settings.alert_cooldown_seconds:
                    continue
                try:
                    await notifier.send_triangular_opportunity(opportunity)
                    if notifier.enabled:
                        last_alert_at[opportunity.key] = now
                except Exception as exc:
                    logger.warning(
                        "Telegram triangular alert failed: %s", exc
                    )

            for opportunity in hybrid_actionable:
                last_sent = last_alert_at.get(opportunity.key, 0.0)
                if now - last_sent < settings.alert_cooldown_seconds:
                    continue
                try:
                    await notifier.send_hybrid_opportunity(opportunity)
                    if notifier.enabled:
                        last_alert_at[opportunity.key] = now
                except Exception as exc:
                    logger.warning("Telegram hybrid alert failed: %s", exc)

            elapsed = time.monotonic() - started_at
            await asyncio.sleep(
                max(0.0, settings.poll_interval_seconds - elapsed)
            )
    finally:
        await pool.close()


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
