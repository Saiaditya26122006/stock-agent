"""
Upstox REST API v2 connector (raw HTTP, no official SDK).

Intraday candles (5m / 15m / 1h) use Upstox historical v3 paths; daily / weekly
use v2, per current API capabilities.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
# NSE equity instrument keys: NSE_EQ|<ISIN>
INSTRUMENT_KEYS: Dict[str, str] = {
    "RELIANCE": "NSE_EQ|INE002A01018",
    "TCS": "NSE_EQ|INE467B01029",
    "INFY": "NSE_EQ|INE009A01021",
    "HDFCBANK": "NSE_EQ|INE040A01034",
    "TATAMOTORS": "NSE_EQ|INE155A01022",
    "WIPRO": "NSE_EQ|INE075A01022",
    "M&M": "NSE_EQ|INE101A01026",
}

_ALLOWED_INTERVALS = frozenset({"5minute", "15minute", "1hour", "day", "week"})
_MAX_RETRIES = 3
_RETRY_DELAY_SEC = 2.0


class DataFreshnessError(Exception):
    """Raised when OHLCV data is too stale for downstream technical analysis."""


def _env_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".env"


def _load_env() -> None:
    load_dotenv(_env_path())


def _encode_instrument_key(instrument_key: str) -> str:
    return quote(instrument_key, safe="")


def _parse_iso_to_ist(ts: str) -> datetime:
    """Parse API timestamp string and normalize to Asia/Kolkata."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    else:
        dt = dt.astimezone(IST)
    return dt


class UpstoxClient:
    """
    Thin HTTP client for Upstox: loads credentials from backend/.env, sets
    Authorization, retries transient failures, and surfaces readable errors.
    """

    base_url: str = "https://api.upstox.com/v2"

    def __init__(self) -> None:
        _load_env()
        token = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
        if not token:
            raise ValueError(
                "UPSTOX_ACCESS_TOKEN not set — historical data will use yfinance fallback."
            )
        analytics_token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
        self._token = token
        self._analytics_token = analytics_token or token
        self._headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        self._http = httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0))

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "UpstoxClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _error_message(self, resp: httpx.Response) -> str:
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                msg = payload.get("message") or payload.get("error") or payload.get("status")
                if msg:
                    return str(msg)
                return json.dumps(payload)[:800]
        except Exception:
            pass
        text = (resp.text or "").strip()
        return text[:800] if text else f"empty body (status {resp.status_code})"

    def request(
        self,
        method: str,
        url: str,
        *,
        context: str,
        headers: Optional[Dict[str, str]] = None,
        retryable: Optional[Callable[[httpx.Response], bool]] = None,
    ) -> httpx.Response:
        if retryable is None:
            retryable = lambda r: r.status_code in (429, 500, 502, 503, 504)

        last_err: Optional[BaseException] = None
        for attempt in range(_MAX_RETRIES):
            try:
                merged_headers = dict(self._headers)
                if headers:
                    merged_headers.update(headers)
                resp = self._http.request(method, url, headers=merged_headers)
                if retryable(resp) and attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                return resp
            except httpx.TimeoutException as e:
                last_err = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(
                    f"{context}: request timed out after {_MAX_RETRIES} attempts."
                ) from e
            except httpx.TransportError as e:
                last_err = e
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                raise RuntimeError(
                    f"{context}: network error after {_MAX_RETRIES} attempts — {e!s}"
                ) from e

        assert last_err is not None
        raise RuntimeError(f"{context}: unexpected retry loop exit — {last_err!s}")

    def _raise_http(self, resp: httpx.Response, context: str) -> None:
        if resp.status_code < 400:
            return
        msg = self._error_message(resp)
        raise RuntimeError(f"{context}: HTTP {resp.status_code} — {msg}")

    def get_profile(self) -> dict:
        url = f"{self.base_url}/user/profile"
        resp = self.request("GET", url, context="User profile")
        self._raise_http(resp, "User profile")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"User profile: unexpected status payload — {body!s}")
        return body.get("data") or {}

    def get_historical_candles_v2(
        self,
        instrument_key: str,
        interval: str,
        to_date: date,
        from_date: date,
    ) -> List[List[Any]]:
        enc = _encode_instrument_key(instrument_key)
        to_s = to_date.isoformat()
        from_s = from_date.isoformat()
        url = f"{self.base_url}/historical-candle/{enc}/{interval}/{to_s}/{from_s}"
        resp = self.request("GET", url, context="Historical candles (v2)")
        self._raise_http(resp, "Historical candles (v2)")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Historical candles (v2): bad payload — {body!s}")
        data = body.get("data") or {}
        return data.get("candles") or []

    def get_historical_candles_v3(
        self,
        instrument_key: str,
        unit: str,
        interval: str,
        to_date: date,
        from_date: date,
    ) -> List[List[Any]]:
        enc = _encode_instrument_key(instrument_key)
        to_s = to_date.isoformat()
        from_s = from_date.isoformat()
        base_v3 = self.base_url.replace("/v2", "/v3")
        url = f"{base_v3}/historical-candle/{enc}/{unit}/{interval}/{to_s}/{from_s}"
        resp = self.request("GET", url, context="Historical candles (v3)")
        self._raise_http(resp, "Historical candles (v3)")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Historical candles (v3): bad payload — {body!s}")
        data = body.get("data") or {}
        return data.get("candles") or []

    def get_full_quotes(self, instrument_key: str) -> dict:
        enc = quote(instrument_key, safe="")
        url = f"{self.base_url}/market-quote/quotes?instrument_key={enc}"
        resp = self.request("GET", url, context="Market quote")
        self._raise_http(resp, "Market quote")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Market quote: bad payload — {body!s}")
        data = body.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("Market quote: response data is not an object.")
        for _k, payload in data.items():
            if not isinstance(payload, dict):
                continue
            if payload.get("instrument_token") == instrument_key:
                return payload
        for payload in data.values():
            if isinstance(payload, dict):
                return payload
        raise RuntimeError("Market quote: no quote returned for this instrument.")

    def get_holdings(self) -> List[dict]:
        url = f"{self.base_url}/portfolio/long-term-holdings"
        resp = self.request("GET", url, context="Holdings")
        self._raise_http(resp, "Holdings")
        body = resp.json()
        if body.get("status") != "success":
            raise RuntimeError(f"Holdings: bad payload — {body!s}")
        data = body.get("data")
        if data is None:
            return []
        if not isinstance(data, list):
            raise RuntimeError("Holdings: expected a list in data.")
        return data


_client: Optional[UpstoxClient] = None


def _get_client() -> UpstoxClient:
    global _client
    if _client is None:
        _client = UpstoxClient()
    return _client


def _resolve_instrument_key(symbol: str) -> str:
    return get_instrument_key(symbol)


def get_instrument_key(symbol: str) -> str:
    """
    Resolve instrument key for NSE equities with in-memory session caching.

    Resolution order:
    1) Fast path from INSTRUMENT_KEYS dict.
    2) Upstox instrument search API — matches on instrument_key starting with
       'NSE_EQ|' AND exact trading_symbol match (case-insensitive).
       Note: the search API returns exchange as 'NSE' not 'NSE_EQ', so we
       match on instrument_key prefix instead.
    3) Raise unknown-symbol ValueError if no mapping found.
    """
    key = symbol.strip().upper()
    if key in INSTRUMENT_KEYS:
        return INSTRUMENT_KEYS[key]

    client = _get_client()
    search_query = key
    if search_query == "M&M":
        search_query = "MM"
    query = quote(search_query, safe="")
    url = f"{client.base_url}/instruments/search?query={query}&asset_type=equity"
    resp = client.request(
        "GET",
        url,
        context="Instrument search",
        headers={"Authorization": f"Bearer {client._analytics_token}"},
    )
    client._raise_http(resp, "Instrument search")

    body = resp.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Instrument search: bad payload — {body!s}")

    data = body.get("data") or []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        data = []

    for row in data:
        if not isinstance(row, dict):
            continue
        instrument_key = str(row.get("instrument_key") or "").strip()
        trading_symbol = str(row.get("trading_symbol") or "").strip().upper()
        if instrument_key.startswith("NSE_EQ|") and trading_symbol == key:
            INSTRUMENT_KEYS[key] = instrument_key
            return instrument_key

    raise ValueError(
        f"Unknown symbol {symbol!r}: add it to INSTRUMENT_KEYS or use a mapped ticker."
    )


def _yfinance_ohlcv(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """
    Fallback OHLCV fetcher using yfinance (no auth required).
    Used automatically when Upstox token is missing or expired.
    Supports NSE stocks via '<SYMBOL>.NS' ticker format.
    """
    try:
        import yfinance as yf
        # Map Upstox intervals to yfinance intervals
        _yf_interval = {
            "15minute": "15m",
            "5minute":  "5m",
            "1hour":    "1h",
            "day":      "1d",
            "week":     "1wk",
        }.get(interval, "1d")

        ticker = f"{symbol}.NS"
        # yfinance requires period or start/end; use days to compute start
        to_d  = datetime.now(IST).date()
        from_d = to_d - timedelta(days=max(days, 1))

        # Intraday data only available for last 60 days on yfinance
        df_raw = yf.download(
            ticker,
            start=from_d.isoformat(),
            end=(to_d + timedelta(days=1)).isoformat(),
            interval=_yf_interval,
            progress=False,
            auto_adjust=True,
        )
        if df_raw is None or df_raw.empty:
            logger.warning("yfinance returned empty data for %s/%s", symbol, interval)
            return pd.DataFrame()

        # Flatten MultiIndex columns if present (yfinance >= 0.2 returns MultiIndex)
        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)

        df_raw = df_raw.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        df_raw.index.name = "date"
        df = df_raw[["open", "high", "low", "close", "volume"]].reset_index()
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("Asia/Kolkata", ambiguous="NaT", nonexistent="NaT")
        df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        logger.info("yfinance fallback: %s %s rows=%d", symbol, interval, len(df))
        return df
    except Exception as exc:
        logger.error("yfinance fallback failed for %s/%s: %s", symbol, interval, exc)
        return pd.DataFrame()


def get_historical_ohlcv(symbol: str, interval: str, days: int) -> pd.DataFrame:
    if days < 1:
        raise ValueError("days must be at least 1.")
    if interval not in _ALLOWED_INTERVALS:
        raise ValueError(
            f"interval must be one of {sorted(_ALLOWED_INTERVALS)}, got {interval!r}."
        )

    # Try Upstox first; fall back to yfinance if token is missing/expired (Railway)
    try:
        client = _get_client()
    except Exception as exc:
        logger.warning("Upstox client unavailable (%s) — falling back to yfinance", exc)
        return _yfinance_ohlcv(symbol, interval, days)

    ik = _resolve_instrument_key(symbol)
    to_d = datetime.now(IST).date()
    from_d = to_d - timedelta(days=days)

    try:
        if interval == "day":
            candles = client.get_historical_candles_v2(ik, "day", to_d, from_d)
        elif interval == "week":
            candles = client.get_historical_candles_v2(ik, "week", to_d, from_d)
        elif interval == "5minute":
            candles = client.get_historical_candles_v3(ik, "minutes", "5", to_d, from_d)
        elif interval == "15minute":
            candles = client.get_historical_candles_v3(ik, "minutes", "15", to_d, from_d)
        elif interval == "1hour":
            candles = client.get_historical_candles_v3(ik, "hours", "1", to_d, from_d)
        else:
            raise ValueError(f"Unsupported interval {interval!r}.")
    except Exception as exc:
        logger.warning("Upstox OHLCV fetch failed for %s/%s (%s) — falling back to yfinance",
                       symbol, interval, exc)
        return _yfinance_ohlcv(symbol, interval, days)

    rows: List[Tuple[datetime, float, float, float, float, float]] = []
    for c in candles:
        if not c or len(c) < 6:
            continue
        ts = _parse_iso_to_ist(str(c[0]))
        o, h, l_, cl, vol = float(c[1]), float(c[2]), float(c[3]), float(c[4]), float(c[5])
        rows.append((ts, o, h, l_, cl, vol))

    df = pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close", "volume"],
    )
    if df.empty:
        logger.warning("Upstox returned 0 candles for %s/%s — falling back to yfinance",
                       symbol, interval)
        return _yfinance_ohlcv(symbol, interval, days)

    df = df.sort_values("date", ascending=True).reset_index(drop=True)
    return df


def get_live_quote(symbol: str) -> Dict[str, Any]:
    client = _get_client()
    ik = _resolve_instrument_key(symbol)
    q = client.get_full_quotes(ik)
    ohlc = q.get("ohlc") or {}
    open_ = float(ohlc.get("open") or 0.0)
    high = float(ohlc.get("high") or 0.0)
    low = float(ohlc.get("low") or 0.0)
    close = float(ohlc.get("close") or 0.0)
    last_price = float(q.get("last_price") or 0.0)
    volume = float(q.get("volume") or 0.0)
    net_change = float(q.get("net_change") or 0.0)
    prev_close = last_price - net_change
    if prev_close:
        change_pct = (net_change / prev_close) * 100.0
    else:
        change_pct = 0.0

    ts_raw = q.get("timestamp") or q.get("last_trade_time")
    if ts_raw:
        try:
            if isinstance(ts_raw, (int, float)) or (
                isinstance(ts_raw, str) and ts_raw.isdigit()
            ):
                ms = int(float(ts_raw))
                dt = datetime.fromtimestamp(ms / 1000.0, tz=IST)
            else:
                dt = _parse_iso_to_ist(str(ts_raw))
            ts_out = dt.isoformat()
        except Exception:
            ts_out = datetime.now(IST).isoformat()
    else:
        ts_out = datetime.now(IST).isoformat()

    return {
        "symbol": str(q.get("symbol") or symbol.upper()),
        "last_price": last_price,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "change": net_change,
        "change_pct": change_pct,
        "timestamp": ts_out,
    }


def get_portfolio() -> List[Dict[str, Any]]:
    client = _get_client()
    raw = client.get_holdings()
    out: List[Dict[str, Any]] = []
    for row in raw:
        qty = int(row.get("quantity") or 0)
        avg = float(row.get("average_price") or 0.0)
        cur = float(row.get("last_price") or row.get("close_price") or 0.0)
        pnl = float(row.get("pnl") or 0.0)
        cost = avg * qty
        if cost:
            pnl_pct = (pnl / cost) * 100.0
        else:
            pnl_pct = 0.0
        sym = str(row.get("trading_symbol") or row.get("tradingsymbol") or "")
        out.append({
            "symbol": sym,
            "quantity": qty,
            "avg_price": avg,
            "current_price": cur,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })
    return out


def freshness_check(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty:
        raise DataFreshnessError("No candles in DataFrame — cannot assess freshness.")
    if "date" not in df.columns:
        raise ValueError("DataFrame must include a 'date' column.")

    series = pd.to_datetime(df["date"], errors="coerce")
    last_ts = series.max()
    if pd.isna(last_ts):
        raise DataFreshnessError("Could not parse candle dates — data may be invalid.")

    if getattr(last_ts, "tzinfo", None) is None:
        last_ts = last_ts.tz_localize(IST)
    else:
        last_ts = last_ts.tz_convert(IST)

    last_date: date = last_ts.date()
    now = datetime.now(IST)
    today = now.date()
    staleness_days = (today - last_date).days

    if staleness_days > 2:
        raise DataFreshnessError(
            f"OHLCV data is stale: last candle date is {last_date.isoformat()} "
            f"({staleness_days} calendar days behind today in IST). "
            f"Downstream TA is blocked until fresher data is available."
        )

    before_open = now.hour < 9 or (now.hour == 9 and now.minute < 15)
    if before_open:
        y = today - timedelta(days=1)
        is_fresh = last_date in (today, y)
        msg = (
            f"Pre-open IST: last candle {last_date.isoformat()} "
            f"(expects today or yesterday)."
        )
    else:
        is_fresh = last_date == today
        msg = f"Regular session IST: last candle {last_date.isoformat()} (expects today)."

    return {
        "is_fresh": bool(is_fresh),
        "last_date": last_date.isoformat(),
        "message": msg,
    }


def test_connection() -> bool:
    try:
        client = _get_client()
        instrument_key = INSTRUMENT_KEYS["RELIANCE"]
        url = (
            f"{client.base_url}/market-quote/quotes"
            f"?instrument_key={quote(instrument_key, safe='')}"
        )
        resp = client.request(
            "GET",
            url,
            context="Market quote connectivity check",
            retryable=None,
        )
        if resp.status_code == 200:
            print("Upstox connection succeeded: market quote endpoint returned 200.")
            return True

        msg = ""
        try:
            payload = resp.json()
            if isinstance(payload, dict):
                msg = (
                    payload.get("message")
                    or payload.get("error")
                    or payload.get("status")
                    or ""
                )
        except Exception:
            msg = ""
        if not msg:
            msg = (resp.text or "").strip()[:200] or "no error message returned"
        print(f"Upstox connection failed: HTTP {resp.status_code} - {msg}")
        return False
    except ValueError as e:
        print(f"Upstox connection failed: {e}")
        return False
    except RuntimeError as e:
        print(f"Upstox connection failed: {e}")
        return False
    except httpx.HTTPError as e:
        print(f"Upstox connection failed: HTTP error — {e!s}")
        return False
    except Exception as e:
        print(f"Upstox connection failed: unexpected error — {e!s}")
        return False