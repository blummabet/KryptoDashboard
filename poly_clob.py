#!/usr/bin/env python3
"""poly_clob.py — Isolierter Polymarket-CLOB-Client für das Krypto-Projekt.

Portiert NUR die generischen Order-Primitive aus dem Betting-Repo (polymarket_bet.py):
  · read_balance()  — Live-USDC-Balance (get_balance_allowance COLLATERAL)
  · buy(token_id, usdc, price_hint)   — Market-BUY + GTC-Limit-Fallback (FOK-sicher)
  · sell(token_id, size, price_hint)  — Market-SELL + Balance-Shortfall- + Limit-Fallback

ISOLATION (Regel: Betting-Projekt NICHT stören):
  · Importiert AUSSCHLIESSLICH py_clob_client_v2 + requests + stdlib — KEINE Fußball-Module
    (kein cocobet_config, kein cocobet_dataset, kein telegram_trades) und KEINE Schreibzugriffe
    auf deren Dateien (picks_history.json etc.).
  · Nutzt zwar dieselbe Wallet (`POLY_PRIVATE_KEY`, `POLY_API_*`, `POLY_FUNDER_ADDRESS`), aber die
    Sicherheits-Gates (eigener Cap/Kill-Switch/Reserve/Live-Balance) liegen in execution.py.
  · Lazy imports → dieses Modul lädt auch OHNE installierte CLOB-Lib (nur echte Order-Calls schlagen
    dann fehl); dadurch laufen Dry-Run + Tests ohne die Library.

Voraussetzung auf dem Runner (dem geteilten Mac): dieselbe `py_clob_client_v2`, die der Betting-Bot
nutzt, muss importierbar sein. Order-Placement geht NUR von der Wohn-IP (Datacenter = geoblockt).
"""
from __future__ import annotations

import math
import os
import re

import requests

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137          # Polygon
TICK = "0.01"


def _build_client():
    """CLOB-Client + API-Creds bauen (POLY_PROXY, wie im Betting-Bot). Wirft bei fehlender Lib/Key."""
    from py_clob_client_v2.client import ClobClient
    from py_clob_client_v2.clob_types import ApiCreds
    from py_clob_client_v2 import SignatureTypeV2

    pk = os.environ.get("POLY_PRIVATE_KEY", "").strip()
    if not pk:
        raise RuntimeError("POLY_PRIVATE_KEY nicht gesetzt")
    funder = os.environ.get("POLY_FUNDER_ADDRESS", "").strip()

    kwargs = dict(host=CLOB_HOST, key=pk, chain_id=CHAIN_ID,
                  signature_type=SignatureTypeV2.POLY_PROXY)
    if funder:
        kwargs["funder"] = funder
    client = ClobClient(**kwargs)

    api_key = os.environ.get("POLY_API_KEY", "").strip()
    creds = None
    if api_key:
        creds = ApiCreds(api_key=api_key,
                         api_secret=os.environ.get("POLY_API_SECRET", "").strip(),
                         api_passphrase=os.environ.get("POLY_API_PASSPHRASE", "").strip())
    else:
        try:
            raw = client.derive_api_key()
            if isinstance(raw, ApiCreds):
                creds = raw
            elif isinstance(raw, dict):
                creds = ApiCreds(api_key=raw.get("key", raw.get("apiKey", "")),
                                 api_secret=raw.get("secret", ""),
                                 api_passphrase=raw.get("passphrase", ""))
        except Exception:
            creds = None
    if creds:
        try:
            client.set_api_creds(creds)
        except AttributeError:
            kwargs["creds"] = creds
            client = ClobClient(**kwargs)
    return client


def read_balance() -> float | None:
    """Live-USDC-Balance des Proxy-Wallets (in USDC), oder None bei Fehler (→ fail-safe)."""
    try:
        from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
        client = _build_client()
        resp = client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        for key in ("balance", "available", "allowance", "amount"):
            v = (resp or {}).get(key) if isinstance(resp, dict) else None
            if v is not None:
                return float(v) / 1_000_000.0      # Mikro-USDC → USDC
    except Exception as e:
        print(f"  ⚠️ read_balance: {e}")
    return None


def _midpoint(token_id: str):
    try:
        r = requests.get(f"{CLOB_HOST}/midpoint", params={"token_id": token_id}, timeout=15)
        if r.ok:
            mid = float(r.json().get("mid", 0))
            if 0.01 <= mid <= 0.99:
                return mid
    except Exception:
        pass
    return None


def _parse_resp(resp):
    if resp and resp.get("success"):
        return resp.get("orderID") or resp.get("id") or "unknown", None
    return None, (resp or {}).get("errorMsg") or (resp or {}).get("error") or str(resp)


def _is_fok(err):
    s = (err or "").lower()
    return "fok" in s or "fully filled" in s or "fill" in s


def buy(token_id: str, usdc: float, price_hint: float | None = None) -> dict:
    """Market-BUY über USDC-Betrag; bei FOK GTC-Limit bei mid/hint +2pp."""
    from py_clob_client_v2.clob_types import (MarketOrderArgs, OrderArgs, OrderType,
                                              PartialCreateOrderOptions)
    from py_clob_client_v2 import Side
    client = _build_client()
    opt = PartialCreateOrderOptions(tick_size=TICK)
    try:
        oid, err = _parse_resp(client.create_and_post_market_order(
            order_args=MarketOrderArgs(token_id=token_id, amount=usdc, side=Side.BUY, order_type=OrderType.GTC),
            options=opt))
        if oid:
            return {"status": "placed", "orderId": oid, "method": "market"}
    except Exception as e:
        err = str(e)
    if not _is_fok(err):
        return {"status": "failed", "error": err}
    lp = price_hint if (price_hint and 0.01 <= price_hint <= 0.99) else _midpoint(token_id)
    if not lp:
        return {"status": "failed", "error": f"FOK, kein Limit-Preis ({err})"}
    price = min(0.99, round(lp + 0.02, 2))
    size = round(usdc / price, 4)
    try:
        oid2, err2 = _parse_resp(client.create_and_post_order(
            order_args=OrderArgs(token_id=token_id, price=price, size=size, side=Side.BUY), options=opt))
        return {"status": "placed", "orderId": oid2, "method": "limit_gtc"} if oid2 \
            else {"status": "failed", "error": err2}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def sell(token_id: str, size: float, price_hint: float | None = None) -> dict:
    """Market-SELL über Token-Menge; Balance-Shortfall-Retry; bei FOK GTC-Limit bei mid/hint −2pp."""
    from py_clob_client_v2.clob_types import (MarketOrderArgs, OrderArgs, OrderType,
                                              PartialCreateOrderOptions)
    from py_clob_client_v2 import Side
    client = _build_client()
    opt = PartialCreateOrderOptions(tick_size=TICK)

    def _market(sz):
        try:
            return _parse_resp(client.create_and_post_market_order(
                order_args=MarketOrderArgs(token_id=token_id, amount=sz, side=Side.SELL, order_type=OrderType.GTC),
                options=opt))
        except Exception as e:
            return None, str(e)

    oid, err = _market(size)
    if oid:
        return {"status": "placed", "orderId": oid, "method": "market_sell"}
    # Balance-Shortfall: echte gehaltene Menge aus der Fehlermeldung, einmal gekappt neu verkaufen.
    if err and "balance" in err.lower() and "enough" in err.lower():
        m = re.search(r"balance:\s*(\d+)", err)
        if m:
            safe = math.floor(int(m.group(1)) / 1_000_000.0 * 100) / 100.0
            if 0 < safe < size:
                size = safe
                oid_b, err_b = _market(size)
                if oid_b:
                    return {"status": "placed", "orderId": oid_b, "method": "market_sell_capped"}
                err = err_b or err
    if not _is_fok(err):
        return {"status": "failed", "error": err}
    lp = price_hint if (price_hint and 0.01 <= price_hint <= 0.99) else _midpoint(token_id)
    if not lp:
        return {"status": "failed", "error": f"FOK, kein Limit-Preis ({err})"}
    price = max(0.01, round(lp - 0.02, 2))
    try:
        oid2, err2 = _parse_resp(client.create_and_post_order(
            order_args=OrderArgs(token_id=token_id, price=price, size=size, side=Side.SELL), options=opt))
        return {"status": "placed", "orderId": oid2, "method": "limit_sell_gtc"} if oid2 \
            else {"status": "failed", "error": err2}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
