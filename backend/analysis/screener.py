"""Lightweight pre-screener for Nifty 500 stock discovery.

Computes 4 quick signals per symbol using 25-day daily OHLCV data and
F&O PCR. Only returns candidates that match >= 2 signals.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from data.upstox import get_historical_ohlcv
from data.nse import get_fo_pcr

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sector mapping — covers every symbol in NIFTY500_UNIVERSE
# ---------------------------------------------------------------------------

SECTOR_MAP: Dict[str, str] = {
    # IT
    "TCS": "IT", "INFY": "IT", "WIPRO": "IT", "HCLTECH": "IT", "TECHM": "IT",
    "LTIM": "IT", "MPHASIS": "IT", "COFORGE": "IT", "PERSISTENT": "IT",
    # Banking
    "HDFCBANK": "Banking", "ICICIBANK": "Banking", "KOTAKBANK": "Banking",
    "AXISBANK": "Banking", "SBIN": "Banking", "BANDHANBNK": "Banking",
    "FEDERALBNK": "Banking", "IDFCFIRSTB": "Banking", "INDUSINDBK": "Banking",
    "PNB": "Banking", "BANKBARODA": "Banking", "CANBK": "Banking",
    "AUBANK": "Banking",
    # Energy / Oil & Gas
    "RELIANCE": "Energy", "ONGC": "Energy", "BPCL": "Energy", "IOC": "Energy",
    "GAIL": "Energy", "PETRONET": "Energy", "ADANIGREEN": "Energy",
    "ADANIPOWER": "Energy", "TATAPOWER": "Energy", "TORNTPOWER": "Energy",
    "NTPC": "Energy", "POWERGRID": "Energy", "NHPC": "Energy", "SJVN": "Energy",
    # Pharma / Healthcare
    "SUNPHARMA": "Pharma", "DRREDDY": "Pharma", "CIPLA": "Pharma",
    "DIVISLAB": "Pharma", "LUPIN": "Pharma", "AUROPHARMA": "Pharma",
    "BIOCON": "Pharma", "TORNTPHARM": "Pharma", "ALKEM": "Pharma",
    "IPCALAB": "Pharma", "LAURUSLABS": "Pharma", "APOLLOHOSP": "Healthcare",
    "MAXHEALTH": "Healthcare",
    # Auto
    "TATAMOTORS": "Auto", "MARUTI": "Auto", "M&M": "Auto",
    "BAJAJ-AUTO": "Auto", "EICHERMOT": "Auto", "HEROMOTOCO": "Auto",
    "ASHOKLEY": "Auto", "TVSMOTOR": "Auto", "BALKRISIND": "Auto",
    "MRF": "Auto", "MOTHERSON": "Auto",
    # FMCG / Consumer
    "HINDUNILVR": "FMCG", "ITC": "FMCG", "NESTLEIND": "FMCG",
    "DABUR": "FMCG", "MARICO": "FMCG", "GODREJCP": "FMCG",
    "BRITANNIA": "FMCG", "COLPAL": "FMCG", "TATACONSUM": "FMCG",
    "PIDILITIND": "FMCG", "PAGEIND": "FMCG", "DMART": "FMCG",
    # Metals / Mining
    "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "VEDL": "Metals", "NMDC": "Metals", "NATIONALUM": "Metals",
    "HINDCOPPER": "Metals", "SAIL": "Metals", "COALINDIA": "Metals",
    # Infrastructure / Capital goods
    "LT": "Infrastructure", "SIEMENS": "Infrastructure", "ABB": "Infrastructure",
    "ADANIENT": "Infrastructure", "ADANIPORTS": "Infrastructure",
    "CONCOR": "Infrastructure",
    # Defence
    "BEL": "Defence", "HAL": "Defence",
    # PSU / Financials
    "IRCTC": "PSU", "IRFC": "PSU", "PFC": "NBFC", "RECLTD": "NBFC",
    "BAJFINANCE": "NBFC", "BAJAJFINSV": "NBFC", "CHOLAFIN": "NBFC",
    "SHRIRAMFIN": "NBFC", "MUTHOOTFIN": "NBFC", "MANAPPURAM": "NBFC",
    # Cement / Building materials
    "ULTRACEMCO": "Cement", "GRASIM": "Cement", "SHREECEM": "Cement",
    "AMBUJACEM": "Cement", "ACC": "Cement", "DALMIABJSL": "Cement",
    "RAMCOCEM": "Cement", "ASIANPAINT": "Building Materials",
    # Insurance
    "SBILIFE": "Insurance", "HDFCLIFE": "Insurance", "ICICIPRULI": "Insurance",
    # Telecom / Media
    "BHARTIARTL": "Telecom", "IDEA": "Telecom", "ZEEL": "Media",
    # Chemicals
    "PIIND": "Chemicals", "AARTI": "Chemicals", "DEEPAKNTR": "Chemicals",
    "ATUL": "Chemicals", "SRF": "Chemicals",
    # Real estate
    "DLF": "Real Estate", "GODREJPROP": "Real Estate",
    "OBEROIRLTY": "Real Estate", "PRESTIGE": "Real Estate",
    "LODHA": "Real Estate",
    # Consumer durables / electricals
    "TITAN": "Consumer Durables", "HAVELLS": "Consumer Durables",
    "VOLTAS": "Consumer Durables", "CROMPTON": "Consumer Durables",
    "WHIRLPOOL": "Consumer Durables", "DIXON": "Electronics",
    "POLYCAB": "Electronics", "KAYNES": "Electronics",
    # New-age / Internet
    "ZOMATO": "Internet", "PAYTM": "Internet", "NYKAA": "Internet",
    "TRENT": "Retail", "INDIGO": "Aviation",
}


# ---------------------------------------------------------------------------
# Screening thresholds
# ---------------------------------------------------------------------------

MOMENTUM_THRESHOLD_PCT = 1.5       # close vs prev close
VOLUME_SPIKE_RATIO = 1.5           # today vol / 20-day avg
NEAR_HIGH_PCT = 3.0                # within 3 % of 25-day high
PCR_BULLISH_THRESHOLD = 0.8        # call-heavy = bullish
MIN_SIGNAL_COUNT = 2               # minimum signals to qualify
INTER_CALL_SLEEP_SEC = 0.3         # rate-limit cushion


def _screen_single(symbol: str) -> Optional[Dict[str, Any]]:
    """Screen one symbol and return candidate dict or None."""
    try:
        df = get_historical_ohlcv(symbol=symbol, interval="day", days=40)
    except Exception as exc:
        logger.warning("Screener OHLCV fetch failed for %s: %s", symbol, exc)
        return None

    if df is None or len(df) < 2:
        logger.warning("Screener: insufficient data for %s (%d rows).", symbol, 0 if df is None else len(df))
        return None

    # Use last 25 rows max
    df = df.tail(25).reset_index(drop=True)
    if len(df) < 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]

    current_price = float(today["close"])
    prev_close = float(yesterday["close"])
    today_volume = float(today["volume"])

    # --- Signal 1: Price momentum ---
    if prev_close > 0:
        price_change_pct = ((current_price - prev_close) / prev_close) * 100.0
    else:
        price_change_pct = 0.0
    has_momentum = price_change_pct > MOMENTUM_THRESHOLD_PCT

    # --- Signal 2: Volume spike ---
    vol_series = df["volume"].iloc[:-1]  # exclude today
    avg_volume_20 = float(vol_series.tail(20).mean()) if len(vol_series) >= 1 else 0.0
    volume_ratio = (today_volume / avg_volume_20) if avg_volume_20 > 0 else 0.0
    has_volume_spike = volume_ratio > VOLUME_SPIKE_RATIO

    # --- Signal 3: Near 25-day high (proxy for 52-week high) ---
    high_25d = float(df["high"].max())
    if high_25d > 0:
        pct_from_high = ((high_25d - current_price) / high_25d) * 100.0
    else:
        pct_from_high = 100.0
    near_high = pct_from_high <= NEAR_HIGH_PCT

    # --- Signal 4: F&O activity (PCR < 0.8 = call-heavy bullish) ---
    has_fo_activity = False
    try:
        fo_data = get_fo_pcr(symbol)
        if fo_data.get("is_fo_stock") and fo_data.get("pcr", 1.0) < PCR_BULLISH_THRESHOLD:
            has_fo_activity = True
    except Exception as exc:
        logger.warning("Screener F&O PCR failed for %s: %s", symbol, exc)

    # Build signals list
    signals: List[str] = []
    if has_momentum:
        signals.append("momentum")
    if has_volume_spike:
        signals.append("volume_spike")
    if near_high:
        signals.append("near_52w_high")
    if has_fo_activity:
        signals.append("fo_activity")

    signal_count = len(signals)
    if signal_count < MIN_SIGNAL_COUNT:
        return None

    return {
        "symbol": symbol,
        "sector": SECTOR_MAP.get(symbol, "Other"),
        "current_price": round(current_price, 2),
        "price_change_pct": round(price_change_pct, 2),
        "volume_ratio": round(volume_ratio, 2),
        "signals": signals,
        "signal_count": signal_count,
    }


def screen_universe(symbols: List[str]) -> List[Dict[str, Any]]:
    """
    Screen a list of symbols with lightweight signals.

    Returns only candidates with signal_count >= MIN_SIGNAL_COUNT,
    sorted by signal_count descending.
    """
    candidates: List[Dict[str, Any]] = []
    total = len(symbols)

    for idx, symbol in enumerate(symbols):
        logger.info("Screening %d/%d: %s", idx + 1, total, symbol)
        try:
            result = _screen_single(symbol)
            if result is not None:
                candidates.append(result)
                logger.info(
                    "  -> %s qualifies: %d signals %s",
                    symbol,
                    result["signal_count"],
                    result["signals"],
                )
        except Exception as exc:
            logger.warning("Screener unexpected error for %s: %s", symbol, exc)

        # Rate-limit cushion between Upstox calls
        if idx < total - 1:
            time.sleep(INTER_CALL_SLEEP_SEC)

    # Sort by signal_count descending, then by price_change_pct descending
    candidates.sort(key=lambda c: (c["signal_count"], c["price_change_pct"]), reverse=True)
    logger.info("Screening complete: %d/%d symbols qualified.", len(candidates), total)
    return candidates
