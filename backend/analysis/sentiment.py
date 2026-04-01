"""FinBERT sentiment module via HuggingFace Inference API."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus

import feedparser
import httpx
from dotenv import load_dotenv


logger = logging.getLogger(__name__)
FINBERT_MODEL = "ProsusAI/finbert"
HF_INFERENCE_URL = f"https://router.huggingface.co/hf-inference/models/{FINBERT_MODEL}"
NEWSAPI_URL = "https://newsapi.org/v2/everything"


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _neutral_result(symbol: str, error: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "sentiment_score": 0.0,
        "dominant_sentiment": "neutral",
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "headline_count": 0,
        "headlines_used": [],
        "model": FINBERT_MODEL,
        "error": error,
    }


def fetch_headlines(symbol: str, company_name: str = None) -> List[str]:
    """Fetch up to 10 latest headlines from NewsAPI, fallback to Google RSS."""
    _load_env()
    query = (company_name or symbol or "").strip()
    if not query:
        return []

    newsapi_key = (os.getenv("NEWSAPI_KEY") or "").strip()
    from_ts = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    try:
        if newsapi_key:
            params = {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 10,
                "from": from_ts,
            }
            headers = {"X-Api-Key": newsapi_key}
            with httpx.Client(timeout=20.0) as client:
                resp = client.get(NEWSAPI_URL, params=params, headers=headers)
            if resp.status_code == 200:
                payload = resp.json()
                articles = payload.get("articles") or []
                headlines = [
                    str(a.get("title", "")).strip()
                    for a in articles
                    if isinstance(a, dict) and str(a.get("title", "")).strip()
                ]
                if headlines:
                    return headlines[:10]
    except Exception as exc:
        logger.error("NewsAPI headline fetch failed for %s: %s", symbol, exc)

    # RSS fallback
    try:
        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(f'{symbol} NSE stock')}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        feed = feedparser.parse(rss_url)
        entries = getattr(feed, "entries", []) or []
        headlines = [str(e.get("title", "")).strip() for e in entries if str(e.get("title", "")).strip()]
        return headlines[:10]
    except Exception as exc:
        logger.error("Google RSS fallback failed for %s: %s", symbol, exc)
        return []


def analyse_sentiment_finbert(headlines: List[str]) -> Dict[str, Any]:
    """Analyse sentiment for headline list using FinBERT inference API."""
    _load_env()
    clean_headlines = [h.strip() for h in (headlines or []) if isinstance(h, str) and h.strip()][:10]
    if not clean_headlines:
        return _neutral_result(symbol="", error="No headlines available.")

    hf_key = (os.getenv("HUGGINGFACE_API_KEY") or "").strip()
    if not hf_key:
        return _neutral_result(symbol="", error="Missing HUGGINGFACE_API_KEY.")

    headers = {"Authorization": f"Bearer {hf_key}"}
    payload = {"inputs": clean_headlines}

    try:
        with httpx.Client(timeout=40.0) as client:
            resp = client.post(HF_INFERENCE_URL, headers=headers, json=payload)

        data = resp.json()
        if isinstance(data, dict) and "error" in data and "loading" in str(data["error"]).lower():
            time.sleep(10)
            with httpx.Client(timeout=40.0) as client:
                resp = client.post(HF_INFERENCE_URL, headers=headers, json=payload)
            data = resp.json()

        if not isinstance(data, list):
            return _neutral_result(symbol="", error=f"HuggingFace API error: {data!s}")

        positive = 0
        negative = 0
        neutral = 0

        for item in data:
            if not isinstance(item, list) or not item:
                continue
            best = max(
                (x for x in item if isinstance(x, dict)),
                key=lambda x: float(x.get("score") or 0.0),
                default=None,
            )
            label = str((best or {}).get("label", "neutral")).strip().lower()
            if label == "positive":
                positive += 1
            elif label == "negative":
                negative += 1
            else:
                neutral += 1

        total = len(clean_headlines)
        sentiment_score = round((positive - negative) / total, 4) if total else 0.0
        if positive > negative and positive >= neutral:
            dominant = "positive"
        elif negative > positive and negative >= neutral:
            dominant = "negative"
        else:
            dominant = "neutral"

        return {
            "sentiment_score": float(sentiment_score),
            "dominant_sentiment": dominant,
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "headline_count": total,
            "headlines_used": clean_headlines,
            "model": FINBERT_MODEL,
        }
    except Exception as exc:
        logger.error("FinBERT sentiment analysis failed: %s", exc)
        return _neutral_result(symbol="", error=f"FinBERT inference failed: {exc}")


def get_stock_sentiment(symbol: str) -> Dict[str, Any]:
    """Fetch headlines and compute sentiment; always returns a valid dict."""
    try:
        headlines = fetch_headlines(symbol=symbol)
        result = analyse_sentiment_finbert(headlines=headlines)
        result["symbol"] = symbol
        if "error" not in result:
            result["error"] = ""
        return result
    except Exception as exc:
        logger.error("get_stock_sentiment failed for %s: %s", symbol, exc)
        return _neutral_result(symbol=symbol, error=f"Unexpected sentiment failure: {exc}")


def get_sentiment_batch(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """Run stock sentiment sequentially with delay to limit rate."""
    output: Dict[str, Dict[str, Any]] = {}
    for idx, symbol in enumerate(symbols or []):
        try:
            output[symbol] = get_stock_sentiment(symbol=symbol)
        except Exception as exc:
            logger.error("Batch sentiment failed for %s: %s", symbol, exc)
            output[symbol] = _neutral_result(symbol=symbol, error=f"Batch item failed: {exc}")
        if idx < len(symbols or []) - 1:
            time.sleep(1)
    return output


def is_sentiment_gate_passed(sentiment_score: float) -> bool:
    """Gate fails only for strongly negative sentiment."""
    return float(sentiment_score) >= -0.3
