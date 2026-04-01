"""Composite 5-factor risk scoring engine."""

from __future__ import annotations

import logging
from typing import Any, Dict


logger = logging.getLogger(__name__)

WEIGHTS = {
    "confluence": 0.30,
    "volatility": 0.20,
    "sentiment": 0.15,
    "fo_signal": 0.15,
    "backtest": 0.20,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def score_signal_confluence(signal_dict: Dict) -> float:
    """Score TA agreement quality from 0.0 to 1.0."""
    try:
        signal = _safe_dict(signal_dict)
        overall = str(signal.get("overall_signal", "neutral")).strip().lower()
        overall_map = {
            "strong_buy": 1.0,
            "buy": 0.75,
            "neutral": 0.5,
            "sell": 0.25,
            "strong_sell": 0.0,
        }
        overall_score = overall_map.get(overall, 0.5)

        bullish = 0
        bearish = 0
        total_considered = 0

        ema_trend = str(_safe_dict(signal.get("ema")).get("trend", "")).strip().lower()
        if ema_trend in {"bullish", "bearish"}:
            total_considered += 1
            bullish += 1 if ema_trend == "bullish" else 0
            bearish += 1 if ema_trend == "bearish" else 0

        rsi_signal = str(_safe_dict(signal.get("rsi")).get("signal", "")).strip().lower()
        if rsi_signal in {"oversold", "overbought"}:
            total_considered += 1
            bullish += 1 if rsi_signal == "oversold" else 0
            bearish += 1 if rsi_signal == "overbought" else 0

        macd_cross = str(_safe_dict(signal.get("macd")).get("crossover", "")).strip().lower()
        if macd_cross in {"bullish", "bearish"}:
            total_considered += 1
            bullish += 1 if macd_cross == "bullish" else 0
            bearish += 1 if macd_cross == "bearish" else 0

        bb_pos = str(_safe_dict(signal.get("bollinger")).get("position", "")).strip().lower()
        if bb_pos in {"lower", "upper"}:
            total_considered += 1
            bullish += 1 if bb_pos == "lower" else 0
            bearish += 1 if bb_pos == "upper" else 0

        vwap_bias = str(_safe_dict(signal.get("vwap")).get("bias", "")).strip().lower()
        if vwap_bias in {"bullish", "bearish"}:
            total_considered += 1
            bullish += 1 if vwap_bias == "bullish" else 0
            bearish += 1 if vwap_bias == "bearish" else 0

        if total_considered == 0:
            indicator_score = 0.5
        else:
            # Scale bullish dominance into [0,1]
            indicator_score = (bullish - bearish + total_considered) / (2.0 * total_considered)
            indicator_score = _clamp(indicator_score, 0.0, 1.0)

        blended = (overall_score * 0.60) + (indicator_score * 0.40)
        return _clamp(float(blended), 0.0, 1.0)
    except Exception as exc:
        logger.error("score_signal_confluence failed: %s", exc)
        return 0.5


def score_volatility(signal_dict: Dict) -> float:
    """Inverse volatility score from 0.0 to 1.0 using ATR%."""
    try:
        signal = _safe_dict(signal_dict)
        atr_pct = _safe_dict(signal.get("atr")).get("pct_of_price")
        if atr_pct is None:
            return 0.5
        atr = float(atr_pct)
        if atr < 1.0:
            return 1.0
        if atr < 2.0:
            return 0.8
        if atr < 3.0:
            return 0.6
        if atr < 4.0:
            return 0.4
        return 0.2
    except Exception as exc:
        logger.error("score_volatility failed: %s", exc)
        return 0.5


def score_sentiment(sentiment_score: float) -> float:
    """Map sentiment -1..+1 to normalized 0..1."""
    try:
        raw = float(sentiment_score)
        return _clamp((raw + 1.0) / 2.0, 0.0, 1.0)
    except Exception as exc:
        logger.error("score_sentiment failed: %s", exc)
        return 0.5


def score_fo_signal(fo_data: Dict = None) -> float:
    """Phase-3 placeholder F&O score."""
    logger.debug("F&O scoring placeholder — returns 0.5 until Phase 3")
    _ = fo_data
    return 0.5


def score_backtest_winrate(symbol: str = None) -> float:
    """Phase-4 placeholder backtest score."""
    logger.debug("Backtest win rate placeholder — returns 0.5 until Phase 4")
    _ = symbol
    return 0.5


def compute_risk_score(
    signal_dict: Dict,
    sentiment_score: float = 0.0,
    fo_data: Dict = None,
    symbol: str = None,
) -> Dict[str, Any]:
    """Compute weighted 5-factor composite risk score."""
    try:
        confluence = score_signal_confluence(signal_dict)
        volatility = score_volatility(signal_dict)
        sentiment = score_sentiment(sentiment_score)
        fo_signal = score_fo_signal(fo_data)
        backtest = score_backtest_winrate(symbol=symbol)

        weighted = (
            confluence * WEIGHTS["confluence"]
            + volatility * WEIGHTS["volatility"]
            + sentiment * WEIGHTS["sentiment"]
            + fo_signal * WEIGHTS["fo_signal"]
            + backtest * WEIGHTS["backtest"]
        )
        risk_score = round(_clamp(weighted * 10.0, 1.0, 10.0), 2)

        if risk_score >= 8.0:
            tier = "strong"
            recommendation = "full_position"
        elif risk_score >= 5.0:
            tier = "moderate"
            recommendation = "half_position"
        elif risk_score >= 3.0:
            tier = "weak"
            recommendation = "quarter_position"
        else:
            tier = "skip"
            recommendation = "skip"

        logger.debug(
            "Risk components for %s: confluence=%.3f volatility=%.3f sentiment=%.3f fo=%.3f backtest=%.3f",
            symbol or "UNKNOWN",
            confluence,
            volatility,
            sentiment,
            fo_signal,
            backtest,
        )

        return {
            "risk_score": risk_score,
            "tier": tier,
            "recommendation": recommendation,
            "component_scores": {
                "confluence": confluence,
                "volatility": volatility,
                "sentiment": sentiment,
                "fo_signal": fo_signal,
                "backtest": backtest,
            },
            "weights_applied": dict(WEIGHTS),
        }
    except Exception as exc:
        logger.error("compute_risk_score failed: %s", exc)
        return {
            "risk_score": 5.0,
            "tier": "moderate",
            "recommendation": "half_position",
            "component_scores": {
                "confluence": 0.5,
                "volatility": 0.5,
                "sentiment": 0.5,
                "fo_signal": 0.5,
                "backtest": 0.5,
            },
            "weights_applied": dict(WEIGHTS),
        }


def should_skip_stock(risk_score: float, sentiment_score: float) -> bool:
    """Skip gate: low risk score or strongly negative sentiment."""
    try:
        return float(risk_score) < 3.0 or float(sentiment_score) < -0.3
    except Exception as exc:
        logger.error("should_skip_stock failed: %s", exc)
        return True
