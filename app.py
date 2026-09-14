from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cas.config import get_settings
from cas.exchanges import ExchangePool
from cas.external_quotes import providers_from_json
from cas.hybrid import HybridRouteScanner
from cas.scanner import ArbitrageScanner
from cas.triangular import TriangularArbitrageScanner

app = FastAPI(title="CAS — Crypto Arbitrage Scanner", version="0.4.0")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    return """<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
  <title>CAS — Arbitrage Scanner</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #0b0f14; color: #e8edf2; }
    main { max-width: 980px; margin: 0 auto; padding: 28px 18px 60px; }
    h1 { margin: 0 0 8px; font-size: clamp(30px, 5vw, 54px); }
    .muted { color: #9ba8b5; }
    .card { background: #121923; border: 1px solid #253142; border-radius: 16px; padding: 18px; margin-top: 18px; }
    button { background: #e8edf2; color: #0b0f14; border: 0; border-radius: 10px; padding: 12px 18px; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .5; cursor: wait; }
    select { background:#0b0f14; color:#e8edf2; border:1px solid #34445b; border-radius:10px; padding:11px; margin-left:8px; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #080b10; padding: 14px; border-radius: 12px; min-height: 100px; }
    .ok { color:#72e7a5; } .warn { color:#ffcc66; }
  </style>
</head>
<body><main>
  <div class=\"muted\">CAS / Vercel</div>
  <h1>Crypto Arbitrage Scanner</h1>
  <p class=\"muted\">Одноразовый live-скан публичных стаканов. Vercel не запускает бесконечный 15-секундный worker: каждый запрос выполняет свежую проверку и завершает функцию.</p>
  <div class=\"card\">
    <button id=\"scan\">Запустить скан</button>
    <select id=\"mode\"><option value=\"all\">Все режимы</option><option value=\"interexchange\">Межбиржевой</option><option value=\"triangular\">Треугольный</option><option value=\"hybrid\">Гибридный</option></select>
    <span id=\"status\" class=\"muted\"></span>
    <pre id=\"out\">Нажми «Запустить скан».</pre>
  </div>
  <div class=\"card\"><b>API</b><p class=\"muted\">GET /api/health · GET /api/scan?mode=all&amp;limit=10</p></div>
<script>
const btn=document.getElementById('scan'), out=document.getElementById('out'), status=document.getElementById('status'), mode=document.getElementById('mode');
btn.onclick=async()=>{btn.disabled=true;status.textContent='  сканирую…';out.textContent='';try{const r=await fetch(`/api/scan?mode=${mode.value}&limit=10`,{cache:'no-store'});const j=await r.json();out.textContent=JSON.stringify(j,null,2);status.textContent=r.ok?'  готово':'  ошибка';status.className=r.ok?'ok':'warn';}catch(e){out.textContent=String(e);status.textContent='  ошибка';status.className='warn';}finally{btn.disabled=false;}};
</script>
</main></body></html>"""


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "ok": True,
        "service": "cas-arbitrage-scanner",
        "runtime": "vercel",
        "exchanges": settings.exchange_ids,
        "modes": {
            "interexchange": settings.interexchange_enabled,
            "triangular": settings.triangular_enabled,
            "hybrid": settings.hybrid_enabled,
            "p2p": settings.p2p_enabled,
        },
    }


@app.get("/api/scan")
async def scan_once(
    mode: Literal["all", "interexchange", "triangular", "hybrid"] = "all",
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    settings = get_settings()
    all_exchange_ids = list(dict.fromkeys(settings.exchange_ids + settings.hybrid_exchange_ids))
    pool = ExchangePool(all_exchange_ids)
    started = time.monotonic()
    result: dict[str, Any] = {
        "mode": mode,
        "exchanges": all_exchange_ids,
        "interexchange": [],
        "triangular": [],
        "hybrid": [],
        "warnings": [],
    }

    try:
        await asyncio.wait_for(pool.start(), timeout=20.0)

        if mode in {"all", "interexchange"} and settings.interexchange_enabled:
            scanner = ArbitrageScanner(
                pool,
                notional_quote=settings.notional_usdt,
                taker_fee_rate=settings.taker_fee_rate,
                fixed_cost_rate=settings.fixed_cost_rate,
                depth_limit=settings.depth_limit,
                exchange_fee_rates=settings.exchange_taker_fee_rates,
            )
            items = await scanner.scan(settings.symbol_list)
            result["interexchange"] = [
                _jsonable(item)
                for item in items
                if item.net_profit_pct >= settings.min_net_profit_pct
            ][:limit]

        if mode in {"all", "triangular"} and settings.triangular_enabled:
            scanner = TriangularArbitrageScanner(
                pool,
                anchor_asset=settings.triangular_anchor_asset,
                start_amount=settings.notional_usdt,
                taker_fee_rate=settings.taker_fee_rate,
                fixed_cost_rate=settings.fixed_cost_rate,
                depth_limit=settings.depth_limit,
                allowed_assets=settings.triangular_asset_set,
                max_cycles=min(settings.triangular_max_cycles, 80),
                exchange_fee_rates=settings.exchange_taker_fee_rates,
            )
            items = await scanner.scan(settings.exchange_ids)
            result["triangular"] = [
                _jsonable(item)
                for item in items
                if item.net_profit_pct >= settings.triangular_min_net_profit_pct
            ][:limit]

        if mode in {"all", "hybrid"} and settings.hybrid_enabled:
            providers = providers_from_json(settings.external_quote_providers_json)
            if not providers:
                result["warnings"].append(
                    "Hybrid mode has no live external quote provider configured on Vercel."
                )
            else:
                scanner = HybridRouteScanner(
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
                    require_network_status=settings.hybrid_require_network_status,
                )
                items = await scanner.scan(settings.hybrid_exchange_ids)
                result["hybrid"] = [
                    _jsonable(item)
                    for item in items
                    if item.net_profit_pct >= settings.hybrid_min_net_profit_pct
                    and (settings.hybrid_allow_suspicious or not item.suspicious)
                ][:limit]

    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Exchange initialization timed out") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"scan failed: {type(exc).__name__}: {exc}") from exc
    finally:
        await pool.close()

    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result["counts"] = {
        key: len(result[key]) for key in ("interexchange", "triangular", "hybrid")
    }
    return json.loads(json.dumps(result, default=str))
