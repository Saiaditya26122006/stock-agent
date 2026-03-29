"""
Technical Analysis engine for NSE/BSE stocks using pandas-ta 0.3.14b.

This module operates on OHLCV DataFrames from `data.upstox.get_historical_ohlcv`
and produces structured SignalDicts per symbol and timeframe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_ta as ta  # noqa: F401  # required to register .ta accessor

from data.upstox import IST, get_historical_ohlcv


logger = logging.getLogger(__name__)


@dataclass
class SignalDictType:
    """Type hint helper (not enforced at runtime)."""

    symbol: str
    timeframe: str
    timestamp: str
    current_price: float
    ema: Dict[str, Any]
    rsi: Dict[str, Any]
    macd: Dict[str, Any]
    bollinger: Dict[str, Any]
    atr: Dict[str, Any]
    vwap: Dict[str, Any]
    obv: float
    volume_ratio: float
    support_levels: List[float]
    resistance_levels: List[float]
    patterns: List[str]
    overall_signal: str


IST_TZ = ZoneInfo("Asia/Kolkata")


def _round(value: Optional[float]) -> Optional[float]:
    """Round a float to 2 decimals, keeping None as None."""

    if value is None:
        return None
    try:
        return round(float(value), 2)
    except Exception:
        return None


def _safe_indicator(fn_name: str, fn, *args, **kwargs):
    """
    Wrapper around pandas-ta calls.

    If pandas-ta raises, log a warning and return None instead of crashing.
    """

    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("pandas-ta %s failed: %s", fn_name, exc)
        return None


def _compute_emas(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    """
    Compute EMA 9/21/50/200 and infer trend direction.

    Returns a dict with ema9/ema21/ema50/ema200 and 'trend' key.
    """

    result: Dict[str, Optional[float]] = {
        "ema9": None,
        "ema21": None,
        "ema50": None,
        "ema200": None,
        "trend": "neutral",
    }

    close = df.get("close")
    if close is None or close.empty:
        return result

    for length, key in ((9, "ema9"), (21, "ema21"), (50, "ema50"), (200, "ema200")):
        if len(close) < length:
            # Not enough candles for this EMA; leave as None
            continue
        ema_series = _safe_indicator("ema", df.ta.ema, length=length)
        if ema_series is None or ema_series.empty:
            continue
        result[key] = _round(ema_series.iloc[-1])

    e9, e21, e50 = result["ema9"], result["ema21"], result["ema50"]
    # EMA200 is not part of basic trend direction; it may remain None.
    if e9 is not None and e21 is not None and e50 is not None:
        if e9 > e21 > e50:
            result["trend"] = "bullish"
        elif e9 < e21 < e50:
            result["trend"] = "bearish"

    return result


def _compute_rsi(df: pd.DataFrame, length: int = 14) -> Dict[str, Any]:
    """
    Compute RSI and its qualitative signal.

    Returns {'value': float|None, 'signal': 'overbought'|'oversold'|'neutral'}.
    """

    result: Dict[str, Any] = {"value": None, "signal": "neutral"}
    if len(df) < length:
        return result

    rsi_series = _safe_indicator("rsi", df.ta.rsi, length=length)
    if rsi_series is None or rsi_series.empty:
        return result
    value = float(rsi_series.iloc[-1])
    result["value"] = _round(value)
    if value > 70:
        result["signal"] = "overbought"
    elif value < 30:
        result["signal"] = "oversold"
    return result


def _compute_macd(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute MACD (12,26,9) and detect crossovers in last 3 candles.

    Returns:
        {'macd': float|None, 'signal': float|None, 'histogram': float|None,
         'crossover': 'bullish_crossover'|'bearish_crossover'|'neutral'}
    """

    result: Dict[str, Any] = {
        "macd": None,
        "signal": None,
        "histogram": None,
        "crossover": "neutral",
    }
    if len(df) < 35:  # some warmup for MACD
        return result

    macd_df = _safe_indicator(
        "macd", df.ta.macd, fast=12, slow=26, signal=9
    )
    if macd_df is None or macd_df.empty:
        return result

    # pandas-ta default column names: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    macd_col = [c for c in macd_df.columns if c.startswith("MACD_")][0]
    sig_col = [c for c in macd_df.columns if c.startswith("MACDs_")][0]
    hist_col = [c for c in macd_df.columns if c.startswith("MACDh_")][0]

    macd_series = macd_df[macd_col]
    sig_series = macd_df[sig_col]
    hist_series = macd_df[hist_col]

    result["macd"] = _round(macd_series.iloc[-1])
    result["signal"] = _round(sig_series.iloc[-1])
    result["histogram"] = _round(hist_series.iloc[-1])

    # Detect crossovers within the last 3 completed candles
    lookback = 4  # need at least previous bar to detect crossing
    if len(macd_series) >= lookback:
        diff = macd_series - sig_series
        recent = diff.iloc[-lookback:]
        # Check for sign change with most recent bar's sign indicating direction
        sign = recent.apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        # Walk backwards to find most recent non-zero sign change
        for i in range(len(sign) - 1, 0, -1):
            if sign.iloc[i] != sign.iloc[i - 1]:
                # Crossing occurred at index i
                if i >= len(sign) - 3:  # within last 3 bars
                    if sign.iloc[i] > sign.iloc[i - 1]:
                        result["crossover"] = "bullish_crossover"
                    elif sign.iloc[i] < sign.iloc[i - 1]:
                        result["crossover"] = "bearish_crossover"
                break

    return result


def _compute_bollinger(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute Bollinger Bands (20, 2 std) and price position.

    Returns dict with upper, middle, lower, and 'position' key.
    """

    result: Dict[str, Any] = {
        "upper": None,
        "middle": None,
        "lower": None,
        "position": "inside",
    }
    if len(df) < 20:
        return result

    bb = _safe_indicator("bbands", df.ta.bbands, length=20, std=2)
    if bb is None or bb.empty:
        return result

    # Expected columns: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    lower_col = [c for c in bb.columns if c.startswith("BBL_")][0]
    mid_col = [c for c in bb.columns if c.startswith("BBM_")][0]
    upper_col = [c for c in bb.columns if c.startswith("BBU_")][0]

    lower = float(bb[lower_col].iloc[-1])
    mid = float(bb[mid_col].iloc[-1])
    upper = float(bb[upper_col].iloc[-1])
    price = float(df["close"].iloc[-1])

    pos = "inside"
    if price > upper:
        pos = "above_upper"
    elif price < lower:
        pos = "below_lower"

    result.update(
        {
            "upper": _round(upper),
            "middle": _round(mid),
            "lower": _round(lower),
            "position": pos,
        }
    )
    return result


def _compute_atr(df: pd.DataFrame, length: int = 14) -> Dict[str, Any]:
    """
    Compute ATR and its value as a percentage of current price.
    """

    result: Dict[str, Any] = {"value": None, "pct_of_price": None}
    if len(df) < length + 1:
        return result

    atr_series = _safe_indicator("atr", df.ta.atr, length=length)
    if atr_series is None or atr_series.empty:
        return result

    atr_val = float(atr_series.iloc[-1])
    price = float(df["close"].iloc[-1])
    pct = (atr_val / price * 100.0) if price else None
    result["value"] = _round(atr_val)
    result["pct_of_price"] = _round(pct)
    return result


def _compute_vwap(df: pd.DataFrame, timeframe: str) -> Dict[str, Any]:
    """
    Compute session VWAP and bias (only for intraday timeframes).
    """

    if timeframe not in ("5minute", "15minute"):
        return {"value": None, "bias": None}

    # VWAP expects a DatetimeIndex in many setups; ensure index is datetime
    df_idx = df.copy()
    if "date" in df_idx.columns:
        df_idx = df_idx.set_index("date")
    df_idx.index = pd.DatetimeIndex(df_idx.index)

    vwap_series = _safe_indicator(
        "vwap",
        df_idx.ta.vwap,
        high="high",
        low="low",
        close="close",
        volume="volume",
    )
    if vwap_series is None or vwap_series.empty:
        return {"value": None, "bias": None}

    vwap_val = float(vwap_series.iloc[-1])
    price = float(df["close"].iloc[-1])
    bias: Optional[str]
    if price > vwap_val:
        bias = "above"
    elif price < vwap_val:
        bias = "below"
    else:
        bias = "neutral"

    return {"value": _round(vwap_val), "bias": bias}


def _compute_obv_and_volume_ratio(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
    """
    Compute OBV and current volume / 20-period average volume.
    """

    obv_series = _safe_indicator(
        "obv", df.ta.obv, close="close", volume="volume"
    )
    obv_val: Optional[float] = None
    if obv_series is not None and not obv_series.empty:
        obv_val = _round(float(obv_series.iloc[-1]))

    vol = df.get("volume")
    if vol is None or len(vol) < 20:
        vol_ratio: Optional[float] = None
    else:
        avg_vol = float(vol.tail(20).mean())
        cur_vol = float(vol.iloc[-1])
        vol_ratio = _round(cur_vol / avg_vol) if avg_vol else None

    return obv_val, vol_ratio


def _find_pivots(df: pd.DataFrame) -> Tuple[List[float], List[float]]:
    """
    Detect simple swing highs/lows using a 2-bar look-back and look-forward.

    A swing low is lower than the two candles before and after it.
    A swing high is higher than the two candles before and after it.
    Returns last 3 of each (most recent first), rounded to 2 decimals.
    """

    n = len(df)
    if n < 10:
        return [], []

    lows = df["low"].values
    highs = df["high"].values
    swing_lows: List[float] = []
    swing_highs: List[float] = []

    for i in range(2, n - 2):
        low = lows[i]
        if low < lows[i - 1] and low < lows[i - 2] and low < lows[i + 1] and low < lows[i + 2]:
            swing_lows.append(float(low))

        high = highs[i]
        if high > highs[i - 1] and high > highs[i - 2] and high > highs[i + 1] and high > highs[i + 2]:
            swing_highs.append(float(high))

    # Take last 3 occurrences, closest to the current bar first
    swing_lows = [*_reversed_last_n(swing_lows, 3)]
    swing_highs = [*_reversed_last_n(swing_highs, 3)]

    return [*_rounded_list(swing_lows)], [*_rounded_list(swing_highs)]


def _reversed_last_n(values: List[float], n: int) -> List[float]:
    """Return up to n items from the end of list, in most-recent-first order."""

    if not values:
        return []
    sub = values[-n:]
    sub.reverse()
    return sub


def _rounded_list(values: List[float]) -> List[float]:
    """Round list of floats to 2 decimals."""

    return [round(float(v), 2) for v in values]


def _detect_candle_patterns(df: pd.DataFrame) -> List[str]:
    """
    Detect basic candlestick patterns on the last candle manually.

    Patterns checked:
        - doji
        - hammer
        - shooting_star
        - bullish_engulfing
        - bearish_engulfing
    """

    patterns: List[str] = []
    if len(df) < 2:
        return patterns

    try:
        last = df.iloc[-1]
        prev = df.iloc[-2]

        body = abs(float(last["close"]) - float(last["open"]))
        candle_range = float(last["high"]) - float(last["low"])

        if candle_range == 0:
            return patterns

        body_ratio = body / candle_range

        # Doji: body is less than 10% of total range
        if body_ratio < 0.1:
            patterns.append("doji")

        # Hammer: small body at top, long lower shadow
        lower_shadow = min(last["open"], last["close"]) - last["low"]
        upper_shadow = last["high"] - max(last["open"], last["close"])
        if lower_shadow > 2 * body and upper_shadow < body and body_ratio < 0.3:
            patterns.append("hammer")

        # Shooting star: small body at bottom, long upper shadow
        if upper_shadow > 2 * body and lower_shadow < body and body_ratio < 0.3:
            patterns.append("shooting_star")

        # Bullish engulfing
        if (
            last["close"] > last["open"]
            and prev["close"] < prev["open"]
            and last["open"] < prev["close"]
            and last["close"] > prev["open"]
        ):
            patterns.append("bullish_engulfing")

        # Bearish engulfing
        if (
            last["close"] < last["open"]
            and prev["close"] > prev["open"]
            and last["open"] > prev["close"]
            and last["close"] < prev["open"]
        ):
            patterns.append("bearish_engulfing")

    except Exception as e:  # pragma: no cover - defensive
        logging.warning(f"Pattern detection failed: {e}")

    return patterns


def _score_overall_signal(
    ema_trend: str,
    rsi_sig: str,
    macd_sig: str,
    bb_pos: str,
    vwap_bias: Optional[str],
    volume_ratio: Optional[float],
) -> str:
    """
    Combine multiple indicator states into a single overall signal.

    Bullish signals:
        - EMA trend is bullish
        - RSI is not overbought
        - MACD bullish crossover
        - price above VWAP
        - Bollinger not above upper band
        - volume_ratio > 1.5

    Bearish signals:
        - EMA trend is bearish
        - RSI oversold (reversal warning)
        - MACD bearish crossover
        - price below VWAP
        - Bollinger below lower band
        - volume_ratio < 0.5
    """

    bullish = 0
    bearish = 0

    # EMA trend
    if ema_trend == "bullish":
        bullish += 1
    elif ema_trend == "bearish":
        bearish += 1

    # RSI
    if rsi_sig != "overbought":
        bullish += 1
    if rsi_sig == "oversold":
        bearish += 1

    # MACD crossovers
    if macd_sig == "bullish_crossover":
        bullish += 1
    elif macd_sig == "bearish_crossover":
        bearish += 1

    # VWAP bias
    if vwap_bias == "above":
        bullish += 1
    elif vwap_bias == "below":
        bearish += 1

    # Bollinger band location
    if bb_pos != "above_upper":
        bullish += 1
    if bb_pos == "below_lower":
        bearish += 1

    # Volume ratio
    if volume_ratio is not None:
        if volume_ratio > 1.5:
            bullish += 1
        elif volume_ratio < 0.5:
            bearish += 1

    if bullish >= 5 and bullish > bearish:
        return "strong_buy"
    if bullish >= 3 and bullish > bearish:
        return "buy"
    if bearish >= 5 and bearish > bullish:
        return "strong_sell"
    if bearish >= 3 and bearish > bullish:
        return "sell"
    return "neutral"


def analyse_stock(symbol: str, timeframe: str, df: pd.DataFrame) -> Dict[str, Any]:
    """
    Run full technical analysis for a single stock and timeframe.

    Args:
        symbol: Stock symbol (e.g. 'RELIANCE').
        timeframe: One of '5minute', '15minute', '1hour', 'day', 'week'.
        df: OHLCV DataFrame with columns [date, open, high, low, close, volume].

    Returns:
        SignalDict as a nested dictionary with indicator values and overall signal.
    """

    if df is None or df.empty:
        raise ValueError("analyse_stock requires a non-empty OHLCV DataFrame.")

    # Ensure date is datetime and sorted ascending
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=False, errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)

    last_close = float(df["close"].iloc[-1])

    ema = _compute_emas(df)
    rsi = _compute_rsi(df)
    macd = _compute_macd(df)
    boll = _compute_bollinger(df)
    atr = _compute_atr(df)
    vwap = _compute_vwap(df, timeframe=timeframe)
    obv_val, vol_ratio = _compute_obv_and_volume_ratio(df)
    supports, resistances = _find_pivots(df)
    patterns = _detect_candle_patterns(df)

    overall = _score_overall_signal(
        ema_trend=ema.get("trend", "neutral"),
        rsi_sig=rsi.get("signal", "neutral"),
        macd_sig=macd.get("crossover", "neutral"),
        bb_pos=boll.get("position", "inside"),
        vwap_bias=vwap.get("bias"),
        volume_ratio=vol_ratio,
    )

    ts = datetime.now(IST_TZ).isoformat()

    signal: Dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": ts,
        "current_price": _round(last_close),
        "ema": {
            "ema9": ema["ema9"],
            "ema21": ema["ema21"],
            "ema50": ema["ema50"],
            "ema200": ema["ema200"],
            "trend": ema["trend"],
        },
        "rsi": {
            "value": _round(rsi.get("value")),
            "signal": rsi.get("signal", "neutral"),
        },
        "macd": {
            "macd": _round(macd.get("macd")),
            "signal": _round(macd.get("signal")),
            "histogram": _round(macd.get("histogram")),
            "crossover": macd.get("crossover", "neutral"),
        },
        "bollinger": {
            "upper": _round(boll.get("upper")),
            "middle": _round(boll.get("middle")),
            "lower": _round(boll.get("lower")),
            "position": boll.get("position", "inside"),
        },
        "atr": {
            "value": _round(atr.get("value")),
            "pct_of_price": _round(atr.get("pct_of_price")),
        },
        "vwap": {
            "value": _round(vwap.get("value")),
            "bias": vwap.get("bias"),
        },
        "obv": _round(obv_val),
        "volume_ratio": _round(vol_ratio),
        "support_levels": supports,
        "resistance_levels": resistances,
        "patterns": patterns,
        "overall_signal": overall,
    }
    return signal


def analyse_all_timeframes(symbol: str, upstox_client: Any = None) -> Dict[str, Dict[str, Any]]:
    """
    Analyse a symbol across all configured timeframes.

    This function fetches OHLCV data internally via `get_historical_ohlcv`.
    The `upstox_client` parameter is accepted for future compatibility but is
    not currently used because the connector manages its own client instance.

    Returns:
        Dict keyed by timeframe -> SignalDict.
    """

    timeframes = {
        "5minute": 5,
        "15minute": 10,
        "1hour": 30,
        "day": 90,
        "week": 365,
    }

    results: Dict[str, Dict[str, Any]] = {}
    for tf, days in timeframes.items():
        try:
            df = get_historical_ohlcv(symbol, tf, days)
            if df is None or df.empty:
                raise ValueError(f"No OHLCV data returned for {symbol} {tf}.")
            results[tf] = analyse_stock(symbol, tf, df)
        except Exception as exc:
            logger.error(
                "Failed to analyse %s for timeframe %s: %s", symbol, tf, exc
            )
            continue

    return results


def _signal_strength_score(signal: str) -> int:
    """Map overall_signal string to a numeric strength score."""

    mapping = {
        "strong_buy": 2,
        "buy": 1,
        "neutral": 0,
        "sell": -1,
        "strong_sell": -2,
    }
    return mapping.get(signal, 0)


def _is_bullish(signal: str) -> bool:
    """Return True if an overall_signal is bullish in nature."""

    return signal in ("buy", "strong_buy")


def _is_bearish(signal: str) -> bool:
    """Return True if an overall_signal is bearish in nature."""

    return signal in ("sell", "strong_sell")


def get_summary(all_timeframe_results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Summarise multi-timeframe signals into a compact overview.

    Args:
        all_timeframe_results: Output of analyse_all_timeframes().

    Returns:
        Dict with top-level view of intraday (15m), swing (day), positional (week)
        and a confluence + strongest timeframe assessment.
    """

    if not all_timeframe_results:
        raise ValueError("get_summary requires non-empty analysis results.")

    # Choose representative signals
    sym = next(iter(all_timeframe_results.values())).get("symbol")

    intraday_sig = (
        (all_timeframe_results.get("15minute") or {}).get("overall_signal", "neutral")
    )
    swing_sig = (
        (all_timeframe_results.get("day") or {}).get("overall_signal", "neutral")
    )
    positional_sig = (
        (all_timeframe_results.get("week") or {}).get("overall_signal", "neutral")
    )

    # Confluence across the three main horizons
    if _is_bullish(intraday_sig) and _is_bullish(swing_sig) and _is_bullish(
        positional_sig
    ):
        confluence = "aligned_bullish"
    elif _is_bearish(intraday_sig) and _is_bearish(swing_sig) and _is_bearish(
        positional_sig
    ):
        confluence = "aligned_bearish"
    else:
        confluence = "mixed"

    # Strongest timeframe by absolute strength score, across all analysed frames
    strongest_tf: Optional[str] = None
    strongest_score: Optional[int] = None
    for tf, sig in all_timeframe_results.items():
        score = _signal_strength_score(sig.get("overall_signal", "neutral"))
        if strongest_score is None or abs(score) > abs(strongest_score):
            strongest_score = score
            strongest_tf = tf

    return {
        "symbol": sym,
        "intraday_signal": intraday_sig,
        "swing_signal": swing_sig,
        "positional_signal": positional_sig,
        "confluence": confluence,
        "strongest_timeframe": strongest_tf,
    }

