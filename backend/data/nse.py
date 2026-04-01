"""NSE public API ingestion helpers with safe fallbacks."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
NSE_BASE = "https://www.nseindia.com/api"
NSE_HOME = "https://www.nseindia.com"
TIMEOUT_SEC = 15.0
RETRIES = 2
RETRY_DELAY_SEC = 3.0
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

_client: Optional[httpx.Client] = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _ensure_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=TIMEOUT_SEC, headers=NSE_HEADERS, follow_redirects=True)
        try:
            # Establish cookie session first; NSE APIs often require this.
            _client.get(NSE_HOME)
        except Exception as exc:
            logger.warning("NSE cookie bootstrap failed: %s", exc)
    return _client


def _get_json(url: str) -> Optional[Any]:
    client = _ensure_client()
    last_err: Optional[Exception] = None
    for attempt in range(RETRIES + 1):
        try:
            resp = client.get(url)
            if resp.status_code == 200:
                return resp.json()
            logger.warning("NSE GET non-200 for %s: %s", url, resp.status_code)
        except Exception as exc:
            last_err = exc
            logger.warning("NSE GET failed for %s (attempt %d): %s", url, attempt + 1, exc)
        if attempt < RETRIES:
            time.sleep(RETRY_DELAY_SEC)
    if last_err:
        logger.warning("NSE GET exhausted retries for %s: %s", url, last_err)
    return None


def get_fii_dii_data() -> Dict[str, Any]:
    default = {
        "fii_net": 0.0,
        "dii_net": 0.0,
        "fii_buy": 0.0,
        "fii_sell": 0.0,
        "dii_buy": 0.0,
        "dii_sell": 0.0,
        "fii_mood": "NEUTRAL",
        "date": "",
        "source": "NSE",
    }
    try:
        data = _get_json(f"{NSE_BASE}/fiidiiTradeReact")
        if not isinstance(data, list) or not data:
            logger.warning("Unexpected FII/DII payload from NSE.")
            return default
        latest = data[0] if isinstance(data[0], dict) else {}
        fii_buy = _safe_float(latest.get("buyValueFII"))
        fii_sell = _safe_float(latest.get("sellValueFII"))
        dii_buy = _safe_float(latest.get("buyValueDII"))
        dii_sell = _safe_float(latest.get("sellValueDII"))
        fii_net = fii_buy - fii_sell
        dii_net = dii_buy - dii_sell
        if fii_net > 500:
            mood = "BULLISH"
        elif fii_net < -500:
            mood = "BEARISH"
        else:
            mood = "NEUTRAL"
        return {
            "fii_net": round(fii_net, 2),
            "dii_net": round(dii_net, 2),
            "fii_buy": round(fii_buy, 2),
            "fii_sell": round(fii_sell, 2),
            "dii_buy": round(dii_buy, 2),
            "dii_sell": round(dii_sell, 2),
            "fii_mood": mood,
            "date": str(latest.get("date") or ""),
            "source": "NSE",
        }
    except Exception as exc:
        logger.warning("get_fii_dii_data failed: %s", exc)
        return default


def get_india_vix_nse() -> Dict[str, Any]:
    default = {"vix": 15.0, "change": 0.0, "pct_change": 0.0, "regime": "NORMAL"}
    try:
        payload = _get_json(f"{NSE_BASE}/allIndices")
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            logger.warning("Unexpected allIndices payload for VIX.")
            return default
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("index", "")).strip().upper() == "INDIA VIX":
                vix = _safe_float(row.get("last"), 15.0)
                chg = _safe_float(row.get("variation"), 0.0)
                pct = _safe_float(row.get("percentChange"), 0.0)
                if vix > 20:
                    regime = "DANGER"
                elif vix >= 15:
                    regime = "CAUTION"
                else:
                    regime = "NORMAL"
                return {"vix": vix, "change": chg, "pct_change": pct, "regime": regime}
        return default
    except Exception as exc:
        logger.warning("get_india_vix_nse failed: %s", exc)
        return default


def get_circuit_filter_status(symbol: str) -> Dict[str, Any]:
    default = {
        "symbol": symbol,
        "at_upper_circuit": False,
        "at_lower_circuit": False,
        "at_circuit": False,
        "upper_cp": 0.0,
        "lower_cp": 0.0,
        "current_price": 0.0,
    }
    try:
        sym = quote_plus((symbol or "").strip().upper())
        payload = _get_json(f"{NSE_BASE}/quote-equity?symbol={sym}")
        if not isinstance(payload, dict):
            return default
        pinfo = payload.get("priceInfo") if isinstance(payload.get("priceInfo"), dict) else {}
        current = _safe_float(pinfo.get("lastPrice"), 0.0)
        upper = _safe_float(pinfo.get("upperCP"), 0.0)
        lower = _safe_float(pinfo.get("lowerCP"), 0.0)
        at_upper = upper > 0 and current >= (upper * 0.995)
        at_lower = lower > 0 and current <= (lower * 1.005)
        return {
            "symbol": symbol,
            "at_upper_circuit": bool(at_upper),
            "at_lower_circuit": bool(at_lower),
            "at_circuit": bool(at_upper or at_lower),
            "upper_cp": upper,
            "lower_cp": lower,
            "current_price": current,
        }
    except Exception as exc:
        logger.warning("get_circuit_filter_status failed for %s: %s", symbol, exc)
        return default


def get_nse_announcements(symbol: str) -> List[Dict[str, Any]]:
    try:
        sym = quote_plus((symbol or "").strip().upper())
        payload = _get_json(f"{NSE_BASE}/corp-info?symbol={sym}&corpType=announcement")
        if not isinstance(payload, list):
            return []
        out: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for row in payload:
            if not isinstance(row, dict):
                continue
            dt_raw = str(row.get("an_dt") or row.get("date") or "")
            desc = str(row.get("desc") or row.get("attchmntText") or "").strip()
            if not dt_raw:
                continue
            days_away = 999
            try:
                dt = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                days_away = (dt.date() - now.date()).days
            except Exception:
                # if parse fails, keep a very large day distance and skip
                pass
            if days_away <= 7:
                out.append(
                    {
                        "symbol": symbol,
                        "date": dt_raw,
                        "description": desc,
                        "days_away": int(days_away),
                    }
                )
        return out
    except Exception as exc:
        logger.warning("get_nse_announcements failed for %s: %s", symbol, exc)
        return []


def get_fo_pcr(symbol: str) -> Dict[str, Any]:
    default = {
        "symbol": symbol,
        "pcr": 1.0,
        "pcr_signal": "NEUTRAL",
        "is_fo_stock": False,
        "total_put_oi": 0,
        "total_call_oi": 0,
    }
    try:
        sym = quote_plus((symbol or "").strip().upper())
        payload = _get_json(f"{NSE_BASE}/option-chain-equities?symbol={sym}")
        if not isinstance(payload, dict):
            return default
        records = payload.get("records") if isinstance(payload.get("records"), dict) else {}
        data = records.get("data") if isinstance(records.get("data"), list) else []
        if not data:
            return default
        total_put_oi = 0
        total_call_oi = 0
        for row in data:
            if not isinstance(row, dict):
                continue
            pe = row.get("PE") if isinstance(row.get("PE"), dict) else {}
            ce = row.get("CE") if isinstance(row.get("CE"), dict) else {}
            total_put_oi += _safe_int(pe.get("openInterest"), 0)
            total_call_oi += _safe_int(ce.get("openInterest"), 0)
        pcr = (total_put_oi / total_call_oi) if total_call_oi > 0 else 1.0
        if pcr > 1.5:
            signal = "BULLISH"
        elif pcr < 0.7:
            signal = "BEARISH"
        else:
            signal = "NEUTRAL"
        return {
            "symbol": symbol,
            "pcr": float(round(pcr, 4)),
            "total_put_oi": int(total_put_oi),
            "total_call_oi": int(total_call_oi),
            "pcr_signal": signal,
            "is_fo_stock": True,
        }
    except Exception as exc:
        logger.warning("get_fo_pcr failed for %s: %s", symbol, exc)
        return default


def get_gift_nifty() -> Dict[str, Any]:
    default = {"gift_nifty": 0.0, "change": 0.0, "pct_change": 0.0, "bias": "NEUTRAL"}
    try:
        payload = _get_json(f"{NSE_BASE}/allIndices")
        rows = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                idx = str(row.get("index", "")).upper()
                if "GIFT" in idx or "SGX" in idx:
                    val = _safe_float(row.get("last"), 0.0)
                    chg = _safe_float(row.get("variation"), 0.0)
                    pct = _safe_float(row.get("percentChange"), 0.0)
                    if pct > 0.5:
                        bias = "BULLISH"
                    elif pct < -0.5:
                        bias = "BEARISH"
                    else:
                        bias = "NEUTRAL"
                    return {"gift_nifty": val, "change": chg, "pct_change": pct, "bias": bias}

        # Fallback proxy via Yahoo
        yahoo = _get_json("https://query1.finance.yahoo.com/v8/finance/chart/NIFTYBEES.NS")
        result = yahoo.get("chart", {}).get("result", []) if isinstance(yahoo, dict) else []
        if isinstance(result, list) and result:
            meta = result[0].get("meta", {}) if isinstance(result[0], dict) else {}
            last = _safe_float(meta.get("regularMarketPrice"), 0.0)
            prev = _safe_float(meta.get("chartPreviousClose"), 0.0)
            chg = round(last - prev, 4)
            pct = round((chg / prev) * 100.0, 4) if prev else 0.0
            if pct > 0.5:
                bias = "BULLISH"
            elif pct < -0.5:
                bias = "BEARISH"
            else:
                bias = "NEUTRAL"
            return {"gift_nifty": last, "change": chg, "pct_change": pct, "bias": bias}
        return default
    except Exception as exc:
        logger.warning("get_gift_nifty failed: %s", exc)
        return default


def get_full_premarket_data(symbols: List[str]) -> Dict[str, Any]:
    """Collect all NSE premarket intelligence with per-call isolation."""
    out = {
        "vix": {"vix": 15.0, "change": 0.0, "pct_change": 0.0, "regime": "NORMAL"},
        "fii_dii": {
            "fii_net": 0.0,
            "dii_net": 0.0,
            "fii_buy": 0.0,
            "fii_sell": 0.0,
            "dii_buy": 0.0,
            "dii_sell": 0.0,
            "fii_mood": "NEUTRAL",
            "date": "",
            "source": "NSE",
        },
        "gift_nifty": {"gift_nifty": 0.0, "change": 0.0, "pct_change": 0.0, "bias": "NEUTRAL"},
        "circuit_filters": {},
        "announcements": {},
        "fo_pcr": {},
        "timestamp": datetime.now(IST).isoformat(),
    }
    try:
        out["vix"] = get_india_vix_nse()
    except Exception as exc:
        logger.warning("Premarket VIX fetch failed: %s", exc)
    try:
        out["fii_dii"] = get_fii_dii_data()
    except Exception as exc:
        logger.warning("Premarket FII/DII fetch failed: %s", exc)
    try:
        out["gift_nifty"] = get_gift_nifty()
    except Exception as exc:
        logger.warning("Premarket Gift Nifty fetch failed: %s", exc)

    for symbol in symbols or []:
        try:
            out["circuit_filters"][symbol] = get_circuit_filter_status(symbol)
        except Exception as exc:
            logger.warning("Premarket circuit status failed for %s: %s", symbol, exc)
            out["circuit_filters"][symbol] = {
                "symbol": symbol,
                "at_upper_circuit": False,
                "at_lower_circuit": False,
                "at_circuit": False,
                "upper_cp": 0.0,
                "lower_cp": 0.0,
                "current_price": 0.0,
            }
        try:
            out["announcements"][symbol] = get_nse_announcements(symbol)
        except Exception as exc:
            logger.warning("Premarket announcements failed for %s: %s", symbol, exc)
            out["announcements"][symbol] = []
        try:
            out["fo_pcr"][symbol] = get_fo_pcr(symbol)
        except Exception as exc:
            logger.warning("Premarket PCR failed for %s: %s", symbol, exc)
            out["fo_pcr"][symbol] = {
                "symbol": symbol,
                "pcr": 1.0,
                "pcr_signal": "NEUTRAL",
                "is_fo_stock": False,
                "total_put_oi": 0,
                "total_call_oi": 0,
            }
    return out
