"""Fail-closed OKX Demo Trading REST client.

There is intentionally no production/live mode or configurable REST host here.
All private requests are signed and hard-pinned to OKX Demo Trading with
x-simulated-trading: 1. This module never submits an order during import.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

BASE_URL = "https://www.okx.com"


class OKXDemoError(RuntimeError):
    pass


class OKXDemoClient:
    def __init__(self, api_key: str, api_secret: str, passphrase: str,
                 timeout: float = 10.0, opener=None):
        self.api_key = str(api_key).strip()
        self.api_secret = str(api_secret).strip()
        self.passphrase = str(passphrase).strip()
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen
        if not (self.api_key and self.api_secret and self.passphrase):
            raise OKXDemoError("Demo API credentials are incomplete.")

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        if str(env.get("OKX_DEMO_TRADING", "")).strip() != "1":
            return None
        keys = [
            env.get("OKX_DEMO_API_KEY", ""),
            env.get("OKX_DEMO_API_SECRET", ""),
            env.get("OKX_DEMO_PASSPHRASE", ""),
        ]
        if not all(str(x).strip() for x in keys):
            return None
        return cls(*keys)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def request(self, method: str, path: str, params: dict[str, Any] | None = None,
                payload: dict[str, Any] | None = None) -> dict[str, Any]:
        method = method.upper()
        if not path.startswith("/") or not path.startswith("/api/v5/"):
            raise OKXDemoError("Refusing non-OKX-V5 API path.")
        query = urllib.parse.urlencode(params or {})
        request_path = path + ("?" + query if query else "")
        body = "" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        timestamp = self._timestamp()
        prehash = timestamp + method + request_path + body
        signature = base64.b64encode(
            hmac.new(self.api_secret.encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "x-simulated-trading": "1",
            "User-Agent": "OKX-Demo-Only-Scalper/1.0",
        }
        data = body.encode("utf-8") if body else None
        req = urllib.request.Request(BASE_URL + request_path, data=data, headers=headers, method=method)
        try:
            with self._opener(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise OKXDemoError(f"OKX demo request failed ({type(exc).__name__}).") from None
        if not isinstance(result, dict) or result.get("code") != "0":
            code = result.get("code", "unknown") if isinstance(result, dict) else "invalid-response"
            message = result.get("msg", "") if isinstance(result, dict) else ""
            raise OKXDemoError(f"OKX demo API rejected request (code {code}): {message}")
        return result

    def instrument(self, inst_id: str = "BTC-USDT-SWAP") -> dict[str, Any]:
        result = self.request(
            "GET", "/api/v5/public/instruments",
            params={"instType": "SWAP", "instId": inst_id},
        )
        data = result.get("data", [])
        if len(data) != 1 or data[0].get("state") != "live":
            raise OKXDemoError("Instrument is missing or not live-tradable on OKX.")
        return data[0]

    def account_config(self) -> dict[str, Any]:
        result = self.request("GET", "/api/v5/account/config")
        data = result.get("data", [])
        if len(data) != 1:
            raise OKXDemoError("Could not confirm demo account configuration.")
        return data[0]

    def usdt_equity(self) -> float:
        result = self.request("GET", "/api/v5/account/balance", params={"ccy": "USDT"})
        data = result.get("data", [])
        if not data:
            raise OKXDemoError("Demo account returned no USDT balance.")
        details = data[0].get("details", [])
        usdt = next((x for x in details if x.get("ccy") == "USDT"), None)
        if usdt and usdt.get("eq") not in (None, ""):
            return float(usdt["eq"])
        if data[0].get("totalEq") not in (None, ""):
            return float(data[0]["totalEq"])
        raise OKXDemoError("Could not read demo account equity.")

    def set_leverage(self, inst_id: str, leverage: int = 10) -> dict[str, Any]:
        if inst_id != "BTC-USDT-SWAP" or not 1 <= int(leverage) <= 10:
            raise OKXDemoError("Only 1x–10x BTC-USDT-SWAP demo leverage is allowed.")
        result = self.request("POST", "/api/v5/account/set-leverage", payload={
            "instId": inst_id, "lever": str(int(leverage)), "mgnMode": "isolated", "posSide": "net"
        })
        data = result.get("data", [])
        return data[0] if data else {}

    def positions(self, inst_id: str = "BTC-USDT-SWAP") -> list[dict[str, Any]]:
        result = self.request(
            "GET", "/api/v5/account/positions", params={"instType": "SWAP", "instId": inst_id}
        )
        return [p for p in result.get("data", []) if abs(float(p.get("pos", 0.0))) > 0.0]

    def account_bills(self, inst_id: str = "BTC-USDT-SWAP", begin_ms: int | None = None,
                      end_ms: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"instType": "SWAP", "instId": inst_id, "limit": "100"}
        if begin_ms is not None:
            params["begin"] = str(int(begin_ms))
        if end_ms is not None:
            params["end"] = str(int(end_ms))
        result = self.request("GET", "/api/v5/account/bills", params=params)
        return result.get("data", [])

    def account_bills_archive(self, inst_id: str = "BTC-USDT-SWAP", begin_ms: int | None = None,
                              end_ms: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"instType": "SWAP", "instId": inst_id, "limit": "100"}
        if begin_ms is not None:
            params["begin"] = str(int(begin_ms))
        if end_ms is not None:
            params["end"] = str(int(end_ms))
        result = self.request("GET", "/api/v5/account/bills-archive", params=params)
        return result.get("data", [])

    def place_market_order(self, inst_id: str, side: str, contracts: str,
                           client_order_id: str, reduce_only: bool = False,
                           stop_px: str | None = None) -> dict[str, Any]:
        if inst_id != "BTC-USDT-SWAP" or side not in {"buy", "sell"}:
            raise OKXDemoError("Only BTC-USDT-SWAP buy/sell orders are allowed in this build.")
        if not contracts or float(contracts) <= 0:
            raise OKXDemoError("Order size must be positive.")
        body: dict[str, Any] = {
            "instId": inst_id,
            "tdMode": "isolated",
            "clOrdId": client_order_id[:32],
            "side": side,
            "ordType": "market",
            "sz": str(contracts),
            "posSide": "net",
        }
        if reduce_only:
            body["reduceOnly"] = True
        if stop_px is not None:
            # Exchange-side stop is attached to the entry so the position is protected
            # if the local scanner disconnects after the entry fills.
            body["attachAlgoOrds"] = [{
                "attachAlgoClOrdId": (client_order_id + "S")[:32],
                "slTriggerPx": str(stop_px),
                "slTriggerPxType": "mark",
                "slOrdPx": "-1",
            }]
        result = self.request("POST", "/api/v5/trade/order", payload=body)
        rows = result.get("data", [])
        if len(rows) != 1 or rows[0].get("sCode", "0") != "0":
            raise OKXDemoError("OKX demo did not accept the order.")
        return rows[0]

    def order(self, inst_id: str, order_id: str) -> dict[str, Any]:
        result = self.request(
            "GET", "/api/v5/trade/order", params={"instId": inst_id, "ordId": order_id}
        )
        data = result.get("data", [])
        if len(data) != 1:
            raise OKXDemoError("Order detail unavailable.")
        return data[0]

    def order_by_client_id(self, inst_id: str, client_order_id: str) -> dict[str, Any] | None:
        result = self.request(
            "GET", "/api/v5/trade/order", params={"instId": inst_id, "clOrdId": client_order_id}
        )
        data = result.get("data", [])
        return data[0] if len(data) == 1 else None

    def cancel_order(self, inst_id: str, order_id: str, client_order_id: str | None = None) -> dict[str, Any]:
        body = {"instId": inst_id}
        if order_id:
            body["ordId"] = order_id
        elif client_order_id:
            body["clOrdId"] = client_order_id
        else:
            raise OKXDemoError("Cancellation requires an order id.")
        result = self.request("POST", "/api/v5/trade/cancel-order", payload=body)
        data = result.get("data", [])
        if len(data) != 1 or data[0].get("sCode", "0") != "0":
            raise OKXDemoError("OKX demo failed to cancel order.")
        return data[0]

    def fills(self, inst_id: str, order_id: str) -> list[dict[str, Any]]:
        result = self.request(
            "GET", "/api/v5/trade/fills",
            params={"instType": "SWAP", "instId": inst_id, "ordId": order_id, "limit": "100"},
        )
        return result.get("data", [])

    def fills_history(self, inst_id: str, limit: int = 100) -> list[dict[str, Any]]:
        result = self.request(
            "GET", "/api/v5/trade/fills-history",
            params={"instType": "SWAP", "instId": inst_id, "limit": str(min(100, max(1, int(limit))))},
        )
        return result.get("data", [])

    def algo_history(self, inst_id: str, client_algo_id: str | None = None) -> list[dict[str, Any]]:
        result = self.request(
            "GET", "/api/v5/trade/orders-algo-history",
            params={"ordType": "conditional", "instId": inst_id, "state": "effective", "limit": "100"},
        )
        data = result.get("data", [])
        if client_algo_id is not None:
            return [x for x in data if x.get("algoClOrdId") == client_algo_id]
        return data

    def place_stop_order(self, inst_id: str, closing_side: str, stop_px: str,
                         client_algo_id: str) -> dict[str, Any]:
        if inst_id != "BTC-USDT-SWAP" or closing_side not in {"buy", "sell"}:
            raise OKXDemoError("Only BTC-USDT-SWAP protective stops are allowed.")
        result = self.request("POST", "/api/v5/trade/order-algo", payload={
            "instId": inst_id,
            "tdMode": "isolated",
            "side": closing_side,
            "posSide": "net",
            "ordType": "conditional",
            "closeFraction": "1",
            "reduceOnly": True,
            "slTriggerPx": str(stop_px),
            "slTriggerPxType": "mark",
            "slOrdPx": "-1",
            "algoClOrdId": client_algo_id[:32],
        })
        data = result.get("data", [])
        if len(data) != 1 or data[0].get("sCode", "0") != "0":
            raise OKXDemoError("OKX demo rejected protective stop order.")
        return data[0]

    def pending_algos(self, inst_id: str) -> list[dict[str, Any]]:
        result = self.request("GET", "/api/v5/trade/orders-algo-pending", params={
            "ordType": "conditional", "instId": inst_id,
        })
        return result.get("data", [])

    def find_algo(self, inst_id: str, client_algo_id: str) -> dict[str, Any] | None:
        return next((x for x in self.pending_algos(inst_id) if x.get("algoClOrdId") == client_algo_id), None)

    def cancel_algo(self, inst_id: str, algo_id: str) -> dict[str, Any]:
        result = self.request(
            "POST", "/api/v5/trade/cancel-algos",
            payload=[{"instId": inst_id, "algoId": algo_id}],
        )
        data = result.get("data", [])
        if data and data[0].get("sCode", "0") != "0":
            raise OKXDemoError("OKX demo failed to cancel protective algo order.")
        return data[0] if data else {}

    def amend_algo_stop(self, inst_id: str, algo_id: str, new_stop_px: str) -> dict[str, Any]:
        result = self.request(
            "POST", "/api/v5/trade/amend-algos",
            payload=[{"instId": inst_id, "algoId": algo_id, "newSlTriggerPx": str(new_stop_px)}],
        )
        data = result.get("data", [])
        if data and data[0].get("sCode", "0") != "0":
            raise OKXDemoError("OKX demo failed to amend protective stop.")
        return data[0] if data else {}
