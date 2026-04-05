"""Claude-powered synthesis layer for converting TA signals into trade plans."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import google.generativeai as genai

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
    """Remove markdown code fences from Gemini responses."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


def _build_prompt(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    regime_context: str = "",
) -> str:
    current_price = signal_dict.get("current_price")
    ema_trend = (signal_dict.get("ema") or {}).get("trend")
    rsi_value = (signal_dict.get("rsi") or {}).get("value")
    rsi_signal = (signal_dict.get("rsi") or {}).get("signal")
    macd_cross = (signal_dict.get("macd") or {}).get("crossover")
    bb_pos = (signal_dict.get("bollinger") or {}).get("position")
    vol_ratio = signal_dict.get("volume_ratio")
    supports = (signal_dict.get("support_levels") or [])[:2]
    resistances = (signal_dict.get("resistance_levels") or [])[:2]
    atr_pct = (signal_dict.get("atr") or {}).get("pct_of_price")
    patterns = signal_dict.get("patterns") or []
    overall_signal = signal_dict.get("overall_signal")

    prompt = f"""
You are an expert NSE/BSE trader and technical analyst.

Analyse this stock setup and provide one actionable recommendation.

Stock: {symbol}
Current price: {current_price}
EMA trend direction: {ema_trend}
RSI: {rsi_value} ({rsi_signal})
MACD crossover: {macd_cross}
Bollinger position: {bb_pos}
Volume ratio: {vol_ratio}
Support levels (nearest 2): {supports}
Resistance levels (nearest 2): {resistances}
ATR % of price: {atr_pct}
Candlestick patterns: {patterns}
Overall TA signal: {overall_signal}

User context:
Capital available: {user_config.get("capital")}
Daily profit target: {user_config.get("daily_target")}
Risk per trade %: {user_config.get("risk_per_trade_pct")}

Return ONLY valid raw JSON in this exact schema and nothing else:
{{
  "action": "BUY or SELL or WATCH or SKIP",
  "style": "intraday or swing or positional",
  "entry_price": float,
  "target": float,
  "stop_loss": float,
  "hold_period": "Same day or 2-3 days or 1-2 weeks etc",
  "confidence": "HIGH or MEDIUM or LOW",
  "reasoning": "2-3 sentences explaining the trade setup",
  "risk_factors": "1-2 sentences on what could go wrong"
}}

Rules:
1) If the setup is not clear or risk is too high, return action: SKIP with reasoning explaining why.
2) Entry price should be near current price or next support/resistance level.
3) Target and SL must be based on actual support/resistance levels from the data above, not arbitrary percentages.
4) Respond with raw JSON only, no markdown, no code blocks, no preamble.
""".strip()
    if regime_context:
        prompt = regime_context + "\n\n" + prompt
    return prompt


def _fallback_skip(symbol: str, signal_dict: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "action": "SKIP",
        "style": "intraday",
        "entry_price": 0.0,
        "target": 0.0,
        "stop_loss": 0.0,
        "hold_period": "N/A",
        "risk_reward": 0.0,
        "confidence": "LOW",
        "reasoning": reason,
        "risk_factors": "Model output unavailable or invalid.",
        "overall_signal": signal_dict.get("overall_signal", "neutral"),
    }


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
            logger.error("get_user_config Supabase error: %s", resp.error)
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


def synthesise_recommendation(
    symbol: str,
    signal_dict: Dict[str, Any],
    user_config: Dict[str, Any],
    regime_context: str = "",
) -> Dict[str, Any]:
    _load_env()
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not gemini_api_key:
        return _fallback_skip(symbol, signal_dict, "Missing GEMINI_API_KEY in .env.")
    prompt = _build_prompt(
        symbol=symbol,
        signal_dict=signal_dict,
        user_config=user_config,
        regime_context=regime_context,
    )
    if regime_context:
        logger.info("Regime context injected into synthesis prompt for %s.", symbol)

    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        raw_text = response.text
    except Exception as exc:
        logger.error("Gemini API call failed for %s: %s", symbol, exc)
        return _fallback_skip(symbol, signal_dict, f"Gemini API call failed: {exc}")

    try:
        cleaned_text = _strip_markdown_fences(raw_text)
        parsed = json.loads(cleaned_text)
    except Exception:
        logger.error("JSON parse failed for %s. Raw response: %s", symbol, raw_text)
        return _fallback_skip(symbol, signal_dict, f"Invalid JSON response from model.")

    action = str(parsed.get("action", "SKIP")).upper()
    if action not in {"BUY", "SELL", "WATCH", "SKIP"}:
        action = "SKIP"

    style = str(parsed.get("style", "intraday")).lower()
    if style not in {"intraday", "swing", "positional"}:
        style = "intraday"

    entry = _round_price(parsed.get("entry_price", 0.0))
    target = _round_price(parsed.get("target", 0.0))
    stop = _round_price(parsed.get("stop_loss", 0.0))

    if action in {"WATCH", "SKIP"}:
        entry = 0.0
        target = 0.0
        stop = 0.0

    risk = abs(entry - stop)
    reward = abs(target - entry)
    risk_reward = round(reward / risk, 2) if risk > 0 else 0.0

    return {
        "symbol": symbol,
        "action": action,
        "style": style,
        "entry_price": entry,
        "target": target,
        "stop_loss": stop,
        "hold_period": str(parsed.get("hold_period", "N/A")),
        "risk_reward": risk_reward,
        "confidence": str(parsed.get("confidence", "LOW")).upper(),
        "reasoning": str(parsed.get("reasoning", "")),
        "risk_factors": str(parsed.get("risk_factors", "")),
        "overall_signal": signal_dict.get("overall_signal", "neutral"),
    }


def synthesise_all(
    symbols_signals: Dict[str, Dict[str, Any]],
    user_config: Dict[str, Any],
    regime_context: str = "",
) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for symbol, signal in symbols_signals.items():
        try:
            output[symbol] = synthesise_recommendation(
                symbol,
                signal,
                user_config,
                regime_context=regime_context,
            )
        except Exception as exc:
            logger.error("synthesise_all failed for %s: %s", symbol, exc)
            output[symbol] = _fallback_skip(symbol, signal, f"Synthesis failed: {exc}")
        time.sleep(1)
    return output


def format_morning_briefing(all_recommendations: Dict[str, Dict[str, Any]], user_config: Dict[str, Any]) -> str:
    now = datetime.now(IST)
    dt_label = now.strftime("%d-%m-%Y %H:%M")

    recs = [r for r in all_recommendations.values() if r.get("action") in {"BUY", "SELL"}]
    watchs = [r for r in all_recommendations.values() if r.get("action") == "WATCH"]
    skips = [r for r in all_recommendations.values() if r.get("action") == "SKIP"]

    lines = [
        f"🌅 MORNING BRIEFING — {dt_label} IST",
        "",
        "📊 MARKET OVERVIEW",
        f"Capital: Rs.{user_config.get('capital')} | Target: Rs.{user_config.get('daily_target')}",
        "",
        f"✅ RECOMMENDED TRADES ({len(recs)} found)",
    ]

    for rec in recs:
        lines.extend([
            f"📈 {rec.get('symbol')} — {rec.get('action')} ({rec.get('confidence')} confidence)",
            f"Entry: Rs.{rec.get('entry_price')} | Target: Rs.{rec.get('target')} | SL: Rs.{rec.get('stop_loss')}",
            f"Hold: {rec.get('hold_period')} | R:R = {rec.get('risk_reward')}",
            str(rec.get("reasoning", "")),
            f"⚠️ Risk: {rec.get('risk_factors')}",
            "",
        ])

    lines.append(f"👀 WATCHLIST ({len(watchs)} stocks)")
    for rec in watchs:
        lines.append(f"- {rec.get('symbol')}: {rec.get('reasoning', '')}")
    lines.append("")

    lines.append(f"⛔ SKIPPED ({len(skips)} stocks)")
    for rec in skips:
        lines.append(f"- {rec.get('symbol')}: {rec.get('reasoning', '')}")

    return "\n".join(lines).strip()