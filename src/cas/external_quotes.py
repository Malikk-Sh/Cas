from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

import httpx


@dataclass(slots=True, frozen=True)
class ExternalQuote:
    provider: str
    from_asset: str
    to_asset: str
    input_amount: float
    output_amount: float
    input_network: str = ""
    output_network: str = ""
    reference: str = ""


class QuoteProvider(Protocol):
    name: str

    async def quote(
        self, from_asset: str, to_asset: str, amount: float
    ) -> ExternalQuote | None: ...


def _substitute(value: Any, variables: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for key, replacement in variables.items():
            value = value.replace("{" + key + "}", replacement)
        return value
    if isinstance(value, dict):
        return {str(k): _substitute(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, variables) for v in value]
    return value


def _json_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not part:
            continue
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def _number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"No numeric value in {value!r}")
    return float(match.group(0))


@dataclass(slots=True)
class HttpQuoteProvider:
    name: str
    url: str
    method: str = "GET"
    response_mode: str = "json"
    output_path: str = ""
    output_regex: str = ""
    input_network: str = ""
    output_network: str = ""
    headers: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    async def quote(
        self, from_asset: str, to_asset: str, amount: float
    ) -> ExternalQuote | None:
        variables = {
            "from_asset": from_asset,
            "to_asset": to_asset,
            "amount": f"{amount:.12g}",
            "input_network": self.input_network,
            "output_network": self.output_network,
        }
        url = str(_substitute(self.url, variables))
        if not url.startswith("https://") and not (
            self.allow_insecure_http and url.startswith("http://")
        ):
            raise ValueError(f"Provider {self.name}: only HTTPS URLs are allowed")
        headers = _substitute(self.headers, variables)
        params = _substitute(self.params, variables)
        body = _substitute(self.body, variables)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds, follow_redirects=True
        ) as client:
            method = self.method.upper()
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(
                    url, headers=headers, params=params, json=body
                )
            else:
                raise ValueError(
                    f"Provider {self.name}: unsupported method {self.method}"
                )
            response.raise_for_status()
            if self.response_mode.lower() == "json":
                raw = _json_path(response.json(), self.output_path)
            else:
                if not self.output_regex:
                    raise ValueError(
                        f"Provider {self.name}: output_regex is required for text mode"
                    )
                match = re.search(
                    self.output_regex,
                    response.text,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if not match:
                    return None
                raw = match.groupdict().get("amount") or match.group(1)
            output = _number(raw)
            if output <= 0:
                return None
            return ExternalQuote(
                provider=self.name,
                from_asset=from_asset,
                to_asset=to_asset,
                input_amount=amount,
                output_amount=output,
                input_network=self.input_network,
                output_network=self.output_network,
                reference=str(response.url),
            )


@dataclass(slots=True)
class StaticRateQuoteProvider:
    """Deterministic provider for tests/manual diagnostics; not live data."""

    name: str
    rates: dict[tuple[str, str], float]
    input_network: str = ""
    output_network: str = ""

    async def quote(
        self, from_asset: str, to_asset: str, amount: float
    ) -> ExternalQuote | None:
        rate = self.rates.get((from_asset.upper(), to_asset.upper()))
        if rate is None:
            return None
        return ExternalQuote(
            provider=self.name,
            from_asset=from_asset,
            to_asset=to_asset,
            input_amount=amount,
            output_amount=amount * rate,
            input_network=self.input_network,
            output_network=self.output_network,
            reference="static-config",
        )


def providers_from_json(raw: str) -> list[QuoteProvider]:
    if not raw.strip():
        return []
    items = json.loads(raw)
    if not isinstance(items, list):
        raise ValueError(
            "CAS_EXTERNAL_QUOTE_PROVIDERS_JSON must contain a JSON array"
        )
    providers: list[QuoteProvider] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "http")).lower()
        name = str(item.get("name", "")).strip()
        if not name:
            raise ValueError("External quote provider requires name")
        if kind == "http":
            providers.append(
                HttpQuoteProvider(
                    name=name,
                    url=str(item["url"]),
                    method=str(item.get("method", "GET")),
                    response_mode=str(item.get("response_mode", "json")),
                    output_path=str(item.get("output_path", "")),
                    output_regex=str(item.get("output_regex", "")),
                    input_network=str(item.get("input_network", "")),
                    output_network=str(item.get("output_network", "")),
                    headers=dict(item.get("headers") or {}),
                    params=dict(item.get("params") or {}),
                    body=dict(item.get("body") or {}),
                    timeout_seconds=float(item.get("timeout_seconds", 10.0)),
                    allow_insecure_http=bool(
                        item.get("allow_insecure_http", False)
                    ),
                )
            )
        elif kind == "static_rate":
            rates: dict[tuple[str, str], float] = {}
            for pair, rate in dict(item.get("rates") or {}).items():
                if ":" not in pair:
                    continue
                first, second = pair.split(":", 1)
                rates[(first.upper(), second.upper())] = float(rate)
            providers.append(
                StaticRateQuoteProvider(
                    name=name,
                    rates=rates,
                    input_network=str(item.get("input_network", "")),
                    output_network=str(item.get("output_network", "")),
                )
            )
        else:
            raise ValueError(f"Unknown quote provider kind: {kind}")
    return providers
