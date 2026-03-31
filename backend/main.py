"""FastAPI orchestrator for the stock-agent backend."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from analysis.claude_synthesis import (
    format_morning_briefing,
    get_user_config,
    synthesise_all,
)
from analysis.ta_engine import analyse_stock
from data.upstox import get_historical_ohlcv, test_connection as test_upstox_connection
from db.recommendations import (
    get_todays_recommendations,
    get_win_rate,
    log_recommendation,
)
from db.supabase_client import supabase_client, test_connection as test_supabase_connection
from db.watchlist import add_symbol, get_active_watchlist, get_symbols_list, remove_symbol
from scheduler import get_scheduler_status, init_scheduler, morning_analysis_job, trigger_morning_now


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(title="Stock Agent API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_run_state_lock = threading.Lock()
_analysis_running = False
_scheduler = None


class ErrorResponse(BaseModel):
    """Standard error payload for all API errors."""

    error: str
    detail: str


class AddWatchlistRequest(BaseModel):
    """Request body for adding a symbol to watchlist."""

    symbol: str
    exchange: str = "NSE"
    user_id: str = "sai_aditya"


class RemoveWatchlistRequest(BaseModel):
    """Request body for removing (soft deleting) a watchlist symbol."""

    symbol: str
    user_id: str = "sai_aditya"


class RunAnalysisRequest(BaseModel):
    """Optional request body for running the analysis pipeline."""

    user_id: str = "sai_aditya"


def _now_ist() -> datetime:
    """Return current IST datetime."""

    return datetime.now(IST)


def _market_status() -> str:
    """Return a simple market status string based on IST trading hours."""

    now = _now_ist()
    if now.weekday() >= 5:
        return "closed"
    minutes = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= minutes <= 15 * 60 + 30:
        return "open"
    return "closed"


def _enter_analysis_lock() -> bool:
    """Acquire in-memory run lock; return False if already running."""

    global _analysis_running
    with _run_state_lock:
        if _analysis_running:
            return False
        _analysis_running = True
        return True


def _exit_analysis_lock() -> None:
    """Release in-memory run lock."""

    global _analysis_running
    with _run_state_lock:
        _analysis_running = False


def log_run_start(user_id: str) -> Optional[str]:
    """Insert a running row in `agent_runs` and return run_id."""

    try:
        now_iso = _now_ist().isoformat()
        payload = {
            "run_date": _now_ist().date().isoformat(),
            "started_at": now_iso,
            "status": "running",
            "stocks_analysed": 0,
            "recommendations_count": 0,
        }
        resp = supabase_client.table("agent_runs").insert(payload).execute()
        if getattr(resp, "error", None):
            logger.error("log_run_start error: %s", resp.error)
            return None
        rows = getattr(resp, "data", None) or []
        return rows[0].get("id") if rows else None
    except Exception as exc:
        logger.error("log_run_start failed for user %s: %s", user_id, exc)
        return None


def log_run_complete(run_id: str, stocks_analysed: int, recommendations_count: int) -> None:
    """Mark an `agent_runs` row as completed with final counts."""

    try:
        payload = {
            "status": "completed",
            "completed_at": _now_ist().isoformat(),
            "stocks_analysed": stocks_analysed,
            "recommendations_count": recommendations_count,
        }
        resp = supabase_client.table("agent_runs").update(payload).eq("id", run_id).execute()
        if getattr(resp, "error", None):
            logger.error("log_run_complete error for run_id=%s: %s", run_id, resp.error)
    except Exception as exc:
        logger.error("log_run_complete failed for run_id=%s: %s", run_id, exc)


@app.exception_handler(HTTPException)
def http_exception_handler(_request, exc: HTTPException) -> JSONResponse:
    """Return HTTP errors in {error, detail} format."""

    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": detail})


@app.exception_handler(Exception)
def unhandled_exception_handler(_request, exc: Exception) -> JSONResponse:
    """Return unhandled server errors in {error, detail} format."""

    logger.error("Unhandled API exception: %s", exc)
    return JSONResponse(status_code=500, content={"error": "server_error", "detail": str(exc)})


@app.on_event("startup")
def startup_event() -> None:
    """Run startup checks for Supabase and Upstox connectivity."""

    logger.info("Stock Agent API startup at %s", _now_ist().isoformat())
    if not test_supabase_connection():
        logger.warning("Supabase startup check failed.")
    if not test_upstox_connection():
        logger.warning("Upstox startup check failed.")
    global _scheduler
    try:
        _scheduler = init_scheduler(app)
    except Exception as exc:
        logger.error("Scheduler initialization failed: %s", exc)


@app.get("/health", status_code=200, response_model=Dict[str, str])
def health() -> Dict[str, str]:
    """Health endpoint for Railway checks."""

    return {"status": "ok", "timestamp": _now_ist().isoformat(), "version": "1.0.0"}


@app.get("/watchlist", status_code=200, response_model=Dict[str, Any])
def watchlist(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """Return active watchlist rows for a user."""

    rows = get_active_watchlist(user_id=user_id)
    return {"symbols": rows, "count": len(rows)}


@app.post("/watchlist/add", status_code=200, response_model=Dict[str, Any])
def watchlist_add(req: AddWatchlistRequest) -> Dict[str, Any]:
    """Add or reactivate a watchlist symbol."""

    result = add_symbol(symbol=req.symbol, exchange=req.exchange, user_id=req.user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to add symbol."))
    return result


@app.post("/watchlist/remove", status_code=200, response_model=Dict[str, Any])
def watchlist_remove(req: RemoveWatchlistRequest) -> Dict[str, Any]:
    """Soft-delete a watchlist symbol (active=false)."""

    result = remove_symbol(symbol=req.symbol, user_id=req.user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to remove symbol."))
    return result


@app.post("/run-analysis", status_code=200, response_model=Dict[str, Any])
def run_analysis(req: Optional[RunAnalysisRequest] = None) -> Dict[str, Any]:
    """Run full morning analysis pipeline synchronously for active watchlist symbols."""

    if req is None:
        req = RunAnalysisRequest()

    if not _enter_analysis_lock():
        raise HTTPException(status_code=429, detail="Analysis is already running. Please retry later.")

    run_id = None
    errors: List[Dict[str, str]] = []
    results: Dict[str, Any] = {}
    full_signals: Dict[str, Dict[str, Any]] = {}
    try:
        run_id = log_run_start(user_id=req.user_id)
        symbols = get_symbols_list(user_id=req.user_id)
        for symbol in symbols:
            try:
                df = get_historical_ohlcv(symbol=symbol, interval="day", days=90)
                signal = analyse_stock(symbol=symbol, timeframe="day", df=df)
                full_signals[symbol] = signal
                results[symbol] = {
                    "symbol": signal.get("symbol"),
                    "current_price": signal.get("current_price"),
                    "overall_signal": signal.get("overall_signal"),
                    "ema_trend": (signal.get("ema") or {}).get("trend"),
                    "rsi": (signal.get("rsi") or {}).get("value"),
                    "rsi_signal": (signal.get("rsi") or {}).get("signal"),
                    "macd_crossover": (signal.get("macd") or {}).get("crossover"),
                    "volume_ratio": signal.get("volume_ratio"),
                    "support_levels": signal.get("support_levels", []),
                    "resistance_levels": signal.get("resistance_levels", []),
                    "patterns": signal.get("patterns", []),
                    "atr_pct": (signal.get("atr") or {}).get("pct_of_price"),
                }
            except Exception as exc:
                logger.error("Analysis failed for symbol %s: %s", symbol, exc)
                errors.append({"symbol": symbol, "error": str(exc)})

        analysed = len(results)
        user_config = get_user_config(user_id=req.user_id)
        recommendations = synthesise_all(symbols_signals=full_signals, user_config=user_config)
        briefing = format_morning_briefing(
            all_recommendations=recommendations,
            user_config=user_config,
        )

        # Log actionable trades to recommendations_log
        for symbol, rec in recommendations.items():
            if rec.get("action") not in {"BUY", "SELL"}:
                continue
            signal = full_signals.get(symbol, {})
            rec_payload = {
                "user_id": req.user_id,
                "date": _now_ist().date().isoformat(),
                "stock": symbol,
                "style": rec.get("style", "intraday"),
                "entry_price": rec.get("entry_price", 0.0),
                "target": rec.get("target", 0.0),
                "stop_loss": rec.get("stop_loss", 0.0),
                "risk_score": (signal.get("atr") or {}).get("pct_of_price", 0.0) or 0.0,
                "sentiment_score": 0.0,
            }
            log_res = log_recommendation(rec_payload)
            if not log_res.get("success"):
                errors.append(
                    {
                        "symbol": symbol,
                        "error": f"Failed to log recommendation: {log_res.get('message')}",
                    }
                )

        if run_id:
            actionable_count = len(
                [r for r in recommendations.values() if r.get("action") in {"BUY", "SELL"}]
            )
            log_run_complete(
                run_id,
                stocks_analysed=analysed,
                recommendations_count=actionable_count,
            )

        return {
            "run_id": run_id,
            "timestamp": _now_ist().isoformat(),
            "stocks_analysed": analysed,
            "results": results,
            "recommendations": recommendations,
            "morning_briefing": briefing,
            "market_status": _market_status(),
            "errors": errors,
        }
    except Exception as exc:
        logger.error("run-analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis pipeline failed: {exc}") from exc
    finally:
        _exit_analysis_lock()


def run_analysis_pipeline(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """Internal callable pipeline for scheduler-triggered runs."""
    return run_analysis(RunAnalysisRequest(user_id=user_id))


@app.get("/recommendations/today", status_code=200, response_model=Dict[str, Any])
def recommendations_today(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """Return today's recommendations for the given user."""

    recs = get_todays_recommendations(user_id=user_id)
    return {"date": _now_ist().date().isoformat(), "recommendations": recs, "count": len(recs)}


@app.get("/recommendations/winrate", status_code=200, response_model=Dict[str, Any])
def recommendations_winrate(user_id: str = "sai_aditya", last_n: int = 20) -> Dict[str, Any]:
    """Return win-rate summary computed from recent closed recommendations."""

    return get_win_rate(user_id=user_id, last_n=last_n)


@app.get("/scheduler/status", status_code=200, response_model=Dict[str, Any])
def scheduler_status() -> Dict[str, Any]:
    """Return scheduler running state and next run times."""
    return get_scheduler_status()


@app.post("/scheduler/trigger-morning", status_code=200, response_model=Dict[str, Any])
async def scheduler_trigger_morning() -> Dict[str, Any]:
    """Manually trigger morning analysis job immediately."""
    try:
        if trigger_morning_now():
            return {"success": True, "message": "Morning job queued."}
        await morning_analysis_job()
        return {"success": True, "message": "Morning job executed directly."}
    except Exception as exc:
        logger.error("Manual morning trigger failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to trigger morning job: {exc}") from exc

