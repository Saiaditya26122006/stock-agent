"""Telegram sender utilities using python-telegram-bot."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Bot


logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _market_mood_emoji(market_mood: str) -> str:
    mood = (market_mood or "").upper()
    if mood == "NORMAL":
        return "🟢"
    if mood == "CAUTION":
        return "🟠"
    if mood == "DANGER":
        return "🔴"
    return "⚪"


async def send_message(text: str) -> bool:
    """Send a Telegram text message asynchronously."""
    _load_env()
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.error("Telegram send failed: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID.")
        return False

    try:
        bot = Bot(token=token)
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def _run_async(coro: Any) -> bool:
    """Run async telegram sender from both sync and async contexts."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # If we're already inside an event loop thread (FastAPI/ASGI), run in a
    # worker thread to safely call asyncio.run without nested-loop errors.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(coro)).result()


def send_morning_briefing_telegram(
    recommendations: list,
    market_mood: str,
    market_regime: str | None = None,
    india_vix: float | None = None,
    special_day_alert: str | None = None,
) -> bool:
    """Format and send a mobile-friendly morning Telegram briefing."""
    try:
        now_label = datetime.now(IST).strftime("%d %b %Y")
        mood_emoji = _market_mood_emoji(market_mood)
        actionable = []
        skipped = []
        for rec in recommendations or []:
            action = str(rec.get("action", "")).upper()
            if action in {"BUY", "SELL"}:
                actionable.append(rec)
            else:
                skipped.append(rec.get("symbol", "UNKNOWN"))

        regime = (market_regime or market_mood or "NORMAL").upper()
        vix_label = f"{float(india_vix):.2f}" if india_vix is not None else "N/A"
        lines = [
            f"🌅 MORNING BRIEFING — {now_label} {mood_emoji} {market_mood.upper()}",
            f"📊 Market: {regime} | VIX: {vix_label}",
            "──────────────────",
        ]
        if special_day_alert:
            lines.extend([str(special_day_alert), "──────────────────"])
        for rec in actionable:
            symbol = rec.get("symbol", "UNKNOWN")
            action = rec.get("action", "WATCH")
            sent_val = float(rec.get("sentiment_score", 0.0) or 0.0)
            if sent_val > 0.15:
                sent_label = "😊 Positive"
            elif sent_val < -0.15:
                sent_label = "😟 Negative"
            else:
                sent_label = "😐 Neutral"
            lines.extend(
                [
                    f"📈 {symbol} — {action}",
                    (
                        f"Entry: Rs.{rec.get('entry_price', 0)} | "
                        f"Target: Rs.{rec.get('target', 0)} | "
                        f"SL: Rs.{rec.get('stop_loss', 0)}"
                    ),
                    (
                        f"Risk: {rec.get('risk_score', 0)}/10 | "
                        f"Sentiment: {sent_label}"
                    ),
                    f"Hold: {rec.get('hold_period', 'N/A')}",
                    "──────────────────",
                ]
            )

        skipped_text = ", ".join(skipped) if skipped else "None"
        lines.append(f"Skipped today: {skipped_text}")
        lines.append(f"Total watchlist: {len(recommendations or [])} stocks analysed")
        return _run_async(send_message("\n".join(lines)))
    except Exception as exc:
        logger.error("Morning telegram briefing failed: %s", exc)
        return False


def send_alert(symbol: str, alert_type: str, message: str) -> bool:
    """Send intraday alert notification to Telegram."""
    try:
        text = f"⚠️ ALERT — {symbol}: {message}\nType: {alert_type}"
        return _run_async(send_message(text))
    except Exception as exc:
        logger.error("Telegram alert failed for %s: %s", symbol, exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = send_alert(symbol="TEST", alert_type="connectivity", message="Telegram test ping from stock-agent.")
    print("Telegram connection:", "OK" if ok else "FAILED")
