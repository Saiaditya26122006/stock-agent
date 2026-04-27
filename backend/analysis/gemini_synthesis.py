"""Gemini-powered synthesis layer — short-term trade plans and long-term investment theses."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai

from db.supabase_client import supabase_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_DEFAULT_CONFIG = {
    "capital": 50000.0,
    "daily_target": 2000.0,
    "paper_mode": True,
    "risk_per_trade_pct": 2.0,
}


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _round_price(value: Any) -> float:
    try:
        return round(float(value), 2)
    except Exception:
        return 0.0


def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


def _gemini_client() -> Any:
    _load_env()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in .env")
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _build_short_term_prompt(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    confluence: str = "",
    timeframes: Dict[str, str] = None,
    regime_context: str = "",
) -> str:
    cp       = signal_dict.get("current_price")
    ema      = signal_dict.get("ema") or {}
    rsi      = signal_dict.get("rsi") or {}
    macd     = signal_dict.get("macd") or {}
    bb       = signal_dict.get("bollinger") or {}
    atr      = signal_dict.get("atr") or {}
    vwap     = signal_dict.get("vwap") or {}
    obv      = signal_dict.get("obv")
    vol      = signal_dict.get("volume_ratio")
    supports = (signal_dict.get("support_levels") or [])[:3]
    resists  = (signal_dict.get("resistance_levels") or [])[:3]
    patterns = signal_dict.get("patterns") or []
    overall  = signal_dict.get("overall_signal")

    tf_line = ""
    if timeframes:
        tf_line = f"Multi-timeframe signals: {timeframes}"

    prompt = f"""
You are an expert NSE/BSE short-term trader and technical analyst.

Analyse this intraday/swing trade setup and return ONE actionable recommendation.

Stock: {symbol}
Current price: ₹{cp}
Overall TA signal: {overall}
Multi-timeframe confluence: {confluence}
{tf_line}

--- Indicators ---
EMA9: {ema.get('ema9')} | EMA21: {ema.get('ema21')} | EMA50: {ema.get('ema50')} | EMA200: {ema.get('ema200')}
EMA trend: {ema.get('trend')}
RSI(14): {rsi.get('value')} → {rsi.get('signal')}
MACD crossover: {macd.get('crossover')} | Histogram: {macd.get('histogram')}
Bollinger position: {bb.get('position')} | Upper: {bb.get('upper')} | Lower: {bb.get('lower')}
VWAP: {vwap.get('value')} | Price vs VWAP: {vwap.get('bias')}
OBV: {obv}
Volume ratio (vs 20-day avg): {vol}x
ATR(14): {atr.get('value')} ({atr.get('pct_of_price')}% of price)
Support levels: {supports}
Resistance levels: {resists}
Candlestick patterns: {patterns}

--- User context ---
Capital: ₹{user_config.get('capital')}
Daily profit target: ₹{user_config.get('daily_target')}
Risk per trade: {user_config.get('risk_per_trade_pct')}%

Return ONLY valid raw JSON — no markdown, no code blocks, no preamble:
{{
  "action": "BUY or SELL or WATCH or SKIP",
  "horizon": "SHORT_TERM",
  "horizon_reasoning": "1 sentence — why this is a short-term setup, not long-term",
  "style": "intraday or swing",
  "short_term": {{
    "entry_price": float,
    "target": float,
    "stop_loss": float,
    "hold_period": "Same day / 2-3 days / This week",
    "exit_trigger": "Plain-English exit condition e.g. Exit if closes below ₹X or target ₹Y hit"
  }},
  "confidence": "HIGH or MEDIUM or LOW",
  "reasoning": "2-3 sentences on the setup",
  "risk_factors": "1-2 sentences on what could invalidate this"
}}

Rules:
1. SKIP if confluence is mixed and RSI is overbought or ATR > 4%.
2. Entry near current price or next key level.
3. Target and SL MUST be based on the support/resistance levels above.
4. If SKIP or WATCH, set all prices to 0.
""".strip()

    if regime_context:
        prompt = regime_context + "\n\n" + prompt
    return prompt


def _build_long_term_prompt(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    confluence: str = "",
    regime_context: str = "",
) -> str:
    cp      = signal_dict.get("current_price")
    ema     = signal_dict.get("ema") or {}
    rsi     = signal_dict.get("rsi") or {}
    vol     = signal_dict.get("volume_ratio")
    supports = (signal_dict.get("support_levels") or [])[:3]
    resists  = (signal_dict.get("resistance_levels") or [])[:3]
    overall = signal_dict.get("overall_signal")

    prompt = f"""
You are an expert NSE/BSE long-term investment advisor.

Analyse this stock for a medium-to-long-term investment and return ONE recommendation.

Stock: {symbol}
Current price: ₹{cp}
Overall TA signal: {overall}
Multi-timeframe confluence: {confluence}

--- Technical context (use for entry timing, not as the primary thesis) ---
EMA50: {ema.get('ema50')} | EMA200: {ema.get('ema200')} | EMA trend: {ema.get('trend')}
RSI(14): {rsi.get('value')} → {rsi.get('signal')}
Volume ratio vs 20-day avg: {vol}x
Support levels: {supports}
Resistance levels: {resists}

--- User context ---
Capital available for long-term: ₹{user_config.get('capital')}

Return ONLY valid raw JSON — no markdown, no code blocks, no preamble:
{{
  "action": "BUY or WATCH or SKIP",
  "horizon": "LONG_TERM",
  "horizon_reasoning": "1 sentence — why this is a long-term investment, not a short-term trade",
  "style": "positional",
  "long_term": {{
    "accumulate_below": float,
    "target_6m": float,
    "target_12m": float,
    "stop_loss_monthly_close": float,
    "suggested_horizon": "1 month / 3 months / 6 months / 1 year / 2 years",
    "thesis": "2-3 sentences on WHY this stock will grow (sector, fundamentals, macro)",
    "review_date": "e.g. July 2025",
    "exit_if": "Plain-English structural exit condition e.g. Exit if monthly close below ₹X"
  }},
  "confidence": "HIGH or MEDIUM or LOW",
  "reasoning": "2-3 sentences summarising the investment case",
  "risk_factors": "1-2 sentences on what could go wrong"
}}

Rules:
1. SKIP if EMA200 is not available or EMA trend is bearish — long-term requires structural uptrend.
2. accumulate_below should be at or below current price (buy the dip).
3. target_12m must be at least 15% above current price to justify the hold period.
4. stop_loss_monthly_close should be a key structural support (monthly chart close level).
5. If SKIP or WATCH, set all price fields to 0.
""".strip()

    if regime_context:
        prompt = regime_context + "\n\n" + prompt
    return prompt


# ---------------------------------------------------------------------------
# Fallback helpers
# ---------------------------------------------------------------------------

def _fallback_skip(symbol: str, signal_dict: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "action": "SKIP",
        "horizon": "NONE",
        "horizon_reasoning": reason,
        "style": "intraday",
        "short_term": None,
        "long_term": None,
        "confidence": "LOW",
        "reasoning": reason,
        "risk_factors": "Model output unavailable or invalid.",
        "overall_signal": signal_dict.get("overall_signal", "neutral"),
        "entry_price": 0.0,
        "target": 0.0,
        "stop_loss": 0.0,
        "hold_period": "N/A",
        "risk_reward": 0.0,
    }


def _call_gemini(prompt: str) -> Optional[str]:
    try:
        client = _gemini_client()
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text
    except Exception as exc:
        logger.error("Gemini API call failed: %s", exc)
        return None


def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_strip_markdown_fences(raw))
    except Exception:
        logger.error("JSON parse failed. Raw: %s", raw[:300])
        return None


def _enrich_short_term(parsed: Dict[str, Any], signal_dict: Dict[str, Any]) -> Dict[str, Any]:
    action = str(parsed.get("action", "SKIP")).upper()
    if action not in {"BUY", "SELL", "WATCH", "SKIP"}:
        action = "SKIP"

    st = parsed.get("short_term") or {}
    entry = _round_price(st.get("entry_price", 0.0))
    target = _round_price(st.get("target", 0.0))
    stop = _round_price(st.get("stop_loss", 0.0))

    if action in {"WATCH", "SKIP"}:
        entry = target = stop = 0.0

    risk = abs(entry - stop)
    reward = abs(target - entry)
    rr = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "symbol": parsed.get("symbol", signal_dict.get("symbol", "")),
        "action": action,
        "horizon": "SHORT_TERM",
        "horizon_reasoning": str(parsed.get("horizon_reasoning", "")),
        "style": str(parsed.get("style", "intraday")).lower(),
        "short_term": {
            "entry_price": entry,
            "target": target,
            "stop_loss": stop,
            "hold_period": str(st.get("hold_period", "N/A")),
            "exit_trigger": str(st.get("exit_trigger", "")),
        },
        "long_term": None,
        # flat fields kept for backward compat with existing DB + frontend
        "entry_price": entry,
        "target": target,
        "stop_loss": stop,
        "hold_period": str(st.get("hold_period", "N/A")),
        "risk_reward": rr,
        "confidence": str(parsed.get("confidence", "LOW")).upper(),
        "reasoning": str(parsed.get("reasoning", "")),
        "risk_factors": str(parsed.get("risk_factors", "")),
        "overall_signal": signal_dict.get("overall_signal", "neutral"),
    }


def _enrich_long_term(parsed: Dict[str, Any], signal_dict: Dict[str, Any]) -> Dict[str, Any]:
    action = str(parsed.get("action", "SKIP")).upper()
    if action not in {"BUY", "WATCH", "SKIP"}:
        action = "SKIP"

    lt = parsed.get("long_term") or {}
    accum = _round_price(lt.get("accumulate_below", 0.0))
    t6    = _round_price(lt.get("target_6m", 0.0))
    t12   = _round_price(lt.get("target_12m", 0.0))
    sl_mc = _round_price(lt.get("stop_loss_monthly_close", 0.0))

    if action in {"WATCH", "SKIP"}:
        accum = t6 = t12 = sl_mc = 0.0

    cp    = float(signal_dict.get("current_price") or 0.0)
    risk  = abs(cp - sl_mc)
    reward = abs(t12 - cp)
    rr    = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "symbol": parsed.get("symbol", signal_dict.get("symbol", "")),
        "action": action,
        "horizon": "LONG_TERM",
        "horizon_reasoning": str(parsed.get("horizon_reasoning", "")),
        "style": "positional",
        "short_term": None,
        "long_term": {
            "accumulate_below": accum,
            "target_6m": t6,
            "target_12m": t12,
            "stop_loss_monthly_close": sl_mc,
            "suggested_horizon": str(lt.get("suggested_horizon", "6 months")),
            "thesis": str(lt.get("thesis", "")),
            "review_date": str(lt.get("review_date", "")),
            "exit_if": str(lt.get("exit_if", "")),
        },
        # flat fields for backward compat
        "entry_price": accum,
        "target": t12,
        "stop_loss": sl_mc,
        "hold_period": str(lt.get("suggested_horizon", "6 months")),
        "risk_reward": rr,
        "confidence": str(parsed.get("confidence", "LOW")).upper(),
        "reasoning": str(parsed.get("reasoning", "")),
        "risk_factors": str(parsed.get("risk_factors", "")),
        "overall_signal": signal_dict.get("overall_signal", "neutral"),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_user_config(user_id: str = "sai_aditya") -> Dict[str, Any]:
    try:
        resp = (
            supabase_client.table("user_config")
            .select("capital, daily_target, paper_mode, risk_per_trade_pct")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if getattr(resp, "error", None):
            logger.error("get_user_config error: %s", resp.error)
            return dict(_DEFAULT_CONFIG)
        rows = getattr(resp, "data", None) or []
        if not rows:
            return dict(_DEFAULT_CONFIG)
        row = rows[0]
        return {
            "capital": float(row.get("capital") or _DEFAULT_CONFIG["capital"]),
            "daily_target": float(row.get("daily_target") or _DEFAULT_CONFIG["daily_target"]),
            "paper_mode": bool(
                _DEFAULT_CONFIG["paper_mode"] if row.get("paper_mode") is None else row.get("paper_mode")
            ),
            "risk_per_trade_pct": float(
                row.get("risk_per_trade_pct") or _DEFAULT_CONFIG["risk_per_trade_pct"]
            ),
        }
    except Exception as exc:
        logger.error("get_user_config failed: %s", exc)
        return dict(_DEFAULT_CONFIG)


def synthesise_short_term(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    confluence: str = "unknown",
    timeframes: Dict[str, str] = None,
    regime_context: str = "",
) -> Dict[str, Any]:
    prompt = _build_short_term_prompt(
        symbol, signal_dict, user_config, confluence, timeframes or {}, regime_context
    )
    raw = _call_gemini(prompt)
    if not raw:
        return _fallback_skip(symbol, signal_dict, "Gemini API call failed.")
    parsed = _parse_response(raw)
    if not parsed:
        return _fallback_skip(symbol, signal_dict, "Invalid JSON from Gemini.")
    parsed["symbol"] = symbol
    return _enrich_short_term(parsed, signal_dict)


def synthesise_long_term(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    confluence: str = "unknown",
    regime_context: str = "",
) -> Dict[str, Any]:
    prompt = _build_long_term_prompt(
        symbol, signal_dict, user_config, confluence, regime_context
    )
    raw = _call_gemini(prompt)
    if not raw:
        return _fallback_skip(symbol, signal_dict, "Gemini API call failed.")
    parsed = _parse_response(raw)
    if not parsed:
        return _fallback_skip(symbol, signal_dict, "Invalid JSON from Gemini.")
    parsed["symbol"] = symbol
    return _enrich_long_term(parsed, signal_dict)


def synthesise_recommendation(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    horizon: str = "SHORT_TERM",
    confluence: str = "unknown",
    timeframes: Dict[str, str] = None,
    regime_context: str = "",
) -> Dict[str, Any]:
    """Route to short-term or long-term synthesis based on horizon."""
    if horizon == "LONG_TERM":
        return synthesise_long_term(symbol, signal_dict, user_config, confluence, regime_context)
    return synthesise_short_term(symbol, signal_dict, user_config, confluence, timeframes or {}, regime_context)


def synthesise_all(
    symbols_signals: Dict[str, Dict[str, Any]],
    user_config: Dict[str, Any],
    regime_context: str = "",
    horizon_map: Dict[str, str] = None,
    confluence_map: Dict[str, str] = None,
    timeframes_map: Dict[str, Dict[str, str]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Synthesise recommendations for all symbols.

    horizon_map:    symbol → 'SHORT_TERM' | 'LONG_TERM' | 'BOTH'
    confluence_map: symbol → confluence string
    timeframes_map: symbol → {tf: signal_str}
    """
    horizon_map    = horizon_map or {}
    confluence_map = confluence_map or {}
    timeframes_map = timeframes_map or {}

    output: Dict[str, Dict[str, Any]] = {}
    for symbol, signal in symbols_signals.items():
        try:
            h  = horizon_map.get(symbol, "SHORT_TERM")
            c  = confluence_map.get(symbol, "unknown")
            tf = timeframes_map.get(symbol, {})

            if h == "BOTH":
                # Generate both, return the one with higher confidence
                st = synthesise_short_term(symbol, signal, user_config, c, tf, regime_context)
                time.sleep(1)
                lt = synthesise_long_term(symbol, signal, user_config, c, regime_context)
                conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
                output[symbol] = st if conf_rank.get(st["confidence"], 0) >= conf_rank.get(lt["confidence"], 0) else lt
            else:
                output[symbol] = synthesise_recommendation(symbol, signal, user_config, h, c, tf, regime_context)
        except Exception as exc:
            logger.error("synthesise_all failed for %s: %s", symbol, exc)
            output[symbol] = _fallback_skip(symbol, signal, f"Synthesis error: {exc}")
        time.sleep(1)
    return output


def format_morning_briefing(
    all_recommendations: Dict[str, Dict[str, Any]],
    user_config: Dict[str, Any],
) -> str:
    now = datetime.now(IST)
    dt_label = now.strftime("%d-%m-%Y %H:%M")

    short_recs = [r for r in all_recommendations.values() if r.get("action") in {"BUY", "SELL"} and r.get("horizon") != "LONG_TERM"]
    long_recs  = [r for r in all_recommendations.values() if r.get("action") == "BUY" and r.get("horizon") == "LONG_TERM"]
    watchs     = [r for r in all_recommendations.values() if r.get("action") == "WATCH"]
    skips      = [r for r in all_recommendations.values() if r.get("action") == "SKIP"]

    lines = [
        f"🌅 MORNING BRIEFING — {dt_label} IST",
        "",
        f"Capital: ₹{user_config.get('capital')} | Daily target: ₹{user_config.get('daily_target')}",
        "",
        f"⚡ SHORT-TERM TRADES ({len(short_recs)} setups)",
    ]
    for rec in short_recs:
        st = rec.get("short_term") or {}
        lines.extend([
            f"📈 {rec.get('symbol')} — {rec.get('action')} ({rec.get('confidence')})",
            f"   Entry ₹{st.get('entry_price') or rec.get('entry_price')} | "
            f"Target ₹{st.get('target') or rec.get('target')} | "
            f"SL ₹{st.get('stop_loss') or rec.get('stop_loss')}",
            f"   Hold: {st.get('hold_period') or rec.get('hold_period')} | R:R {rec.get('risk_reward')}",
            f"   {rec.get('reasoning', '')}",
            f"   Exit: {st.get('exit_trigger', '')}",
            "",
        ])

    lines.append(f"🌱 LONG-TERM INVESTMENTS ({len(long_recs)} picks)")
    for rec in long_recs:
        lt = rec.get("long_term") or {}
        lines.extend([
            f"📊 {rec.get('symbol')} — ACCUMULATE below ₹{lt.get('accumulate_below')}",
            f"   Target 12m: ₹{lt.get('target_12m')} | SL (monthly close): ₹{lt.get('stop_loss_monthly_close')}",
            f"   Horizon: {lt.get('suggested_horizon')} | Review: {lt.get('review_date')}",
            f"   Thesis: {lt.get('thesis', '')}",
            "",
        ])

    lines.append(f"👀 WATCH ({len(watchs)})  |  ⛔ SKIPPED ({len(skips)})")
    for rec in watchs:
        lines.append(f"- {rec.get('symbol')}: {rec.get('reasoning', '')}")

    return "\n".join(lines).strip()
