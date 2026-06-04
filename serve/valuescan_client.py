"""Valuescan Open API client for visualization-only AI tracking."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ValuescanConfigError(RuntimeError):
    """Raised when required Valuescan configuration is missing."""


class ValuescanAPIError(RuntimeError):
    """Raised when Valuescan returns an invalid or failed response."""


Transport = Callable[[str, dict[str, str], bytes, int], dict[str, Any]]


class ValuescanClient:
    """Small server-side client that keeps Valuescan credentials off the frontend."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        stream_base_url: str | None = None,
        timeout: int = 10,
        transport: Transport | None = None,
    ):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = (base_url or os.getenv("VS_OPEN_API_BASE_URL") or "https://api.valuescan.io/api").rstrip("/")
        self.stream_base_url = (stream_base_url or os.getenv("VS_OPEN_STREAM_BASE_URL") or "https://stream.valuescan.ai").rstrip("/")
        self.timeout = timeout
        self.transport = transport or self._urllib_transport

    def _api_key(self) -> str:
        value = self.api_key or os.getenv("VS_OPEN_API_KEY")
        if not value:
            raise ValuescanConfigError("Missing VS_OPEN_API_KEY")
        return value

    def _secret_key(self) -> str:
        value = self.secret_key or os.getenv("VS_OPEN_SECRET_KEY")
        if not value:
            raise ValuescanConfigError("Missing VS_OPEN_SECRET_KEY")
        return value

    @staticmethod
    def json_body(payload: dict[str, Any] | None) -> str:
        return json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":"))

    def build_post_headers(self, raw_body: str, timestamp: str | None = None) -> dict[str, str]:
        ts = timestamp or str(int(time.time() * 1000))
        api_key = self._api_key()
        secret_key = self._secret_key()
        sign_content = ts + raw_body
        sign = hmac.new(
            secret_key.encode("utf-8"),
            sign_content.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-KEY": api_key,
            "X-TIMESTAMP": ts,
            "X-SIGN": sign,
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "*/*",
        }

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raw_body = self.json_body(payload)
        headers = self.build_post_headers(raw_body)
        url = self.base_url + "/" + path.lstrip("/")
        return self.transport(url, headers, raw_body.encode("utf-8"), self.timeout)

    def build_stream_url(
        self,
        channel: str,
        timestamp: str | None = None,
        nonce: str | None = None,
        tokens: str | list[int | str] | None = None,
    ) -> str:
        if channel not in {"market", "signal"}:
            raise ValueError("channel must be 'market' or 'signal'")
        ts = timestamp or str(int(time.time() * 1000))
        nonce_value = nonce or uuid.uuid4().hex
        sign = hmac.new(
            self._secret_key().encode("utf-8"),
            (ts + nonce_value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params: dict[str, str] = {
            "apiKey": self._api_key(),
            "sign": sign,
            "timestamp": ts,
            "nonce": nonce_value,
        }
        if channel == "signal":
            if isinstance(tokens, list):
                params["tokens"] = ",".join(str(t) for t in tokens)
            else:
                params["tokens"] = tokens or ""
        return f"{self.stream_base_url}/stream/{channel}/subscribe?{urlencode(params)}"

    def token_list(self, search: str) -> dict[str, Any]:
        return self.post("/open/v1/vs-token/list", {"search": search})

    def resolve_token(self, search: str = "BTC") -> dict[str, Any]:
        known = {
            "BTC": {"id": 1, "symbol": "BTC", "name": "Bitcoin"},
            "ETH": {"id": 1027, "symbol": "ETH", "name": "Ethereum"},
        }
        search_upper = search.upper()
        if search_upper in known:
            return known[search_upper]
        data = self.token_list(search).get("data") or []
        if not data:
            raise ValuescanAPIError(f"No Valuescan token matched {search!r}")
        for item in data:
            if str(item.get("symbol", "")).upper() == search_upper:
                return item
        return data[0]

    def support_resistance(self, vs_token_id: int | str, date_ms: int) -> dict[str, Any]:
        return self.post("/open/v1/indicator/getDenseAreaList", {"vsTokenId": int(vs_token_id), "date": date_ms})

    def price_market(self, vs_token_id: int | str, start_ms: int, end_ms: int) -> dict[str, Any]:
        return self.post(
            "/open/v1/indicator/getPriceMarketList",
            {"vsTokenId": int(vs_token_id), "startTime": start_ms, "endTime": end_ms},
        )

    def social_sentiment(self, vs_token_id: int | str) -> dict[str, Any]:
        return self.post("/open/v1/social-sentiment/getCoinSocialSentiment", {"vsTokenId": int(vs_token_id)})

    def market_analysis_history(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return self.post("/open/v1/ai/getAiTokenAnalyseResultList", {"page": page, "pageSize": page_size})

    def chance_coin_list(self) -> dict[str, Any]:
        return self.post("/open/v1/ai/getChanceCoinList", {})

    def risk_coin_list(self) -> dict[str, Any]:
        return self.post("/open/v1/ai/getRiskCoinList", {})

    def funds_coin_list(self) -> dict[str, Any]:
        return self.post("/open/v1/ai/getFundsCoinList", {})

    def chance_coin_messages(self, vs_token_id: int | str) -> dict[str, Any]:
        return self.post("/open/v1/ai/getChanceCoinMessageList", {"vsTokenId": int(vs_token_id)})

    def risk_coin_messages(self, vs_token_id: int | str) -> dict[str, Any]:
        return self.post("/open/v1/ai/getRiskCoinMessageList", {"vsTokenId": int(vs_token_id)})

    def funds_coin_messages(self, vs_token_id: int | str, trade_type: int | str = 1) -> dict[str, Any]:
        return self.post(
            "/open/v1/ai/getFundsCoinMessageList",
            {"vsTokenId": int(vs_token_id), "tradeType": int(trade_type)},
        )

    def stream_events(self, channel: str, tokens: str | list[int | str] | None = None):
        url = self.build_stream_url(channel, tokens=tokens)
        req = Request(url, headers={"Accept": "text/event-stream"})
        with urlopen(req, timeout=300) as resp:
            for raw_line in resp:
                yield raw_line.decode("utf-8")

    @staticmethod
    def _urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: int) -> dict[str, Any]:
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            text = resp.read().decode("utf-8")
        if status < 200 or status >= 300:
            raise ValuescanAPIError(f"Valuescan HTTP {status}: {text[:200]}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValuescanAPIError("Valuescan returned invalid JSON") from exc
        if payload.get("code") not in (None, 200):
            raise ValuescanAPIError(f"Valuescan error {payload.get('code')}: {payload.get('message')}")
        return payload
