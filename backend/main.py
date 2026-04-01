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
from analysis.feasibility import check_target_feasibility, get_india_vix, get_market_regime
from analysis.position_sizing import calculate_position_size
from analysis.risk_scorer import compute_risk_score, should_skip_stock
from analysis.sentiment import get_sentiment_batch
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
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_run_state_lock = threading.Lock()
_analysis_running = False
_scheduler = None


class ErrorResponse(BaseModel):
    error: str
    detail: str


class AddWatchlistRequest(BaseModel):
    symbol: str
    exchange: str = "NSE"
    user_id: str = "sai_aditya"


class RemoveWatchlistRequest(BaseModel):
    symbol: str
    user_id: str = "sai_aditya"


class RunAnalysisRequest(BaseModel):
    user_id: str = "sai_aditya"


def _now_ist() -> datetime:
    return datetime.now(IST)


def _market_status() -> str:
    now = _now_ist()
    if now.weekday() >= 5:
        return "closed"
    minutes = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= minutes <= 15 * 60 + 30:
        return "open"
    return "closed"


def _enter_analysis_lock() -> bool:
    global _analysis_running
    with _run_state_lock:
        if _analysis_running:
            return False
        _analysis_running = True
        return True


def _exit_analysis_lock() -> None:
    global _analysis_running
    with _run_state_lock:
        _analysis_running = False


def log_run_start(user_id: str) -> Optional[str]:
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
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "detail": detail})


@app.exception_handler(Exception)
def unhandled_exception_handler(_request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled API exception: %s", exc)
    return JSONResponse(status_code=500, content={"error": "server_error", "detail": str(exc)})


@app.on_event("startup")
def startup_event() -> None:
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
    return {"status": "ok", "timestamp": _now_ist().isoformat(), "version": "1.0.0"}


@app.get("/watchlist", status_code=200, response_model=Dict[str, Any])
def watchlist(user_id: str = "sai_aditya") -> Dict[str, Any]:
    rows = get_active_watchlist(user_id=user_id)
    return {"symbols": rows, "count": len(rows)}


@app.post("/watchlist/add", status_code=200, response_model=Dict[str, Any])
def watchlist_add(req: AddWatchlistRequest) -> Dict[str, Any]:
    result = add_symbol(symbol=req.symbol, exchange=req.exchange, user_id=req.user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to add symbol."))
    return result


@app.post("/watchlist/remove", status_code=200, response_model=Dict[str, Any])
def watchlist_remove(req: RemoveWatchlistRequest) -> Dict[str, Any]:
    result = remove_symbol(symbol=req.symbol, user_id=req.user_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Failed to remove symbol."))
    return result


@app.post("/run-analysis", status_code=200, response_model=Dict[str, Any])
def run_analysis(req: Optional[RunAnalysisRequest] = None) -> Dict[str, Any]:
    if req is None:
        req = RunAnalysisRequest()

    if not _enter_analysis_lock():
        raise HTTPException(status_code=429, detail="Analysis is already running. Please retry later.")

    run_id = None
    errors: List[Dict[str, str]] = []
    results: Dict[str, Any] = {}
    full_signals: Dict[str, Dict[str, Any]] = {}
    sentiment_results: Dict[str, Dict[str, Any]] = {}
    risk_score_results: Dict[str, Dict[str, Any]] = {}
    skipped_symbols: List[Dict[str, str]] = []
    feasibility_result: Dict[str, Any] = {}
    india_vix = 15.0
    market_regime = "NORMAL"
    try:
        run_id = log_run_start(user_id=req.user_id)
        symbols = get_symbols_list(user_id=req.user_id)
        try:
            india_vix = float(get_india_vix())
            market_regime = get_market_regime(india_vix)
            logger.info("Market regime: %s | VIX: %.2f", market_regime, india_vix)
            if market_regime == "DANGER":
                logger.warning("DANGER regime detected — trade filtering will be stricter.")
        except Exception as exc:
            logger.error("Pre-market feasibility fetch failed: %s", exc)
            india_vix = 15.0
            market_regime = "NORMAL"

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

        try:
            sentiment_results = get_sentiment_batch(symbols)
            logger.info("Sentiment fetched for %d stocks.", len(sentiment_results))
        except Exception as exc:
            logger.error("Sentiment batch failed: %s", exc)
            sentiment_results = {s: {"symbol": s, "sentiment_score": 0.0, "error": str(exc)} for s in symbols}

        filtered_signals: Dict[str, Dict[str, Any]] = {}
        for symbol, signal in full_signals.items():
            try:
                sym_sent = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
                risk_payload = compute_risk_score(signal_dict=signal, sentiment_score=sym_sent, symbol=symbol)
            except Exception as exc:
                logger.error("Risk scoring failed for %s: %s", symbol, exc)
                risk_payload = {
                    "risk_score": 5.0,
                    "tier": "moderate",
                    "recommendation": "half_position",
                    "component_scores": {},
                    "weights_applied": {},
                }
            risk_score_results[symbol] = risk_payload
            logger.info("Risk score computed for %s: %.2f", symbol, float(risk_payload.get("risk_score", 5.0)))
            try:
                should_skip = should_skip_stock(
                    risk_score=float(risk_payload.get("risk_score", 5.0)),
                    sentiment_score=float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0)),
                )
            except Exception as exc:
                logger.error("Skip gate failed for %s: %s", symbol, exc)
                should_skip = False
            if should_skip:
                reason = "risk_score_or_sentiment_gate_failed"
                skipped_symbols.append({"symbol": symbol, "reason": reason})
                logger.info("Skipped %s at pre-trade gate: %s", symbol, reason)
            else:
                filtered_signals[symbol] = signal

        analysed = len(results)
        user_config = get_user_config(user_id=req.user_id)
        recommendations = synthesise_all(symbols_signals=filtered_signals, user_config=user_config)

        for skipped in skipped_symbols:
            sym = skipped.get("symbol", "")
            if sym and sym not in recommendations:
                recommendations[sym] = {
                    "symbol": sym,
                    "action": "SKIP",
                    "style": "intraday",
                    "entry_price": 0.0,
                    "target": 0.0,
                    "stop_loss": 0.0,
                    "hold_period": "N/A",
                    "confidence": "LOW",
                    "reasoning": skipped.get("reason", "Filtered by gate."),
                    "risk_reward": 0.0,
                }

        for symbol, rec in recommendations.items():
            try:
                rec["risk_score"] = float((risk_score_results.get(symbol) or {}).get("risk_score", 5.0))
                rec["sentiment_score"] = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
                if rec.get("action") in {"BUY", "SELL"}:
                    sizing_result = calculate_position_size(
                        capital=float(user_config.get("capital", 0.0)),
                        risk_score=float((risk_score_results.get(symbol) or {}).get("risk_score", 5.0)),
                        entry_price=float(rec.get("entry_price", 0.0) or 0.0),
                        stop_loss=float(rec.get("stop_loss", 0.0) or 0.0),
                    )
                    rec["position_sizing"] = sizing_result
                    logger.info("Position size computed for %s: %s", symbol, sizing_result.get("reason"))
                    if sizing_result.get("action") == "skip":
                        rec["action"] = "SKIP"
                        rec["reasoning"] = (
                            f"{rec.get('reasoning', '')} | Position sizing skip: {sizing_result.get('reason')}"
                        ).strip(" |")
            except Exception as exc:
                logger.error("Position sizing enrichment failed for %s: %s", symbol, exc)

        try:
            feasibility_result = check_target_feasibility(
                capital=float(user_config.get("capital", 0.0)),
                daily_target=float(user_config.get("daily_target", 0.0)),
                india_vix=float(india_vix),
                signal_dicts=list(full_signals.values()),
            )
        except Exception as exc:
            logger.error("Feasibility check failed: %s", exc)
            feasibility_result = {
                "capital": float(user_config.get("capital", 0.0)),
                "daily_target": float(user_config.get("daily_target", 0.0)),
                "required_return_pct": 0.0,
                "india_vix": float(india_vix),
                "market_regime": market_regime,
                "avg_intraday_move_pct": 2.0,
                "effective_move_pct": 2.0,
                "realistic_target": 0.0,
                "is_achievable": False,
                "adjusted_target": 0.0,
                "message": "Feasibility fallback used.",
            }

        briefing = format_morning_briefing(
            all_recommendations=recommendations,
            user_config=user_config,
        )

        # Log ALL recommendations to recommendations_log (not just BUY/SELL)
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
                    "risk_score": (risk_score_results.get(symbol) or {}).get("risk_score", 0.0),
                    "sentiment_score": (sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0),
                    "action": rec.get("action", "SKIP"),
                    "reasoning": rec.get("reasoning", ""),
                    "hold_period": rec.get("hold_period", "N/A"),
                    "confidence": rec.get("confidence", "LOW"),
            }
            log_res = log_recommendation(rec_payload)
            if not log_res.get("success"):
                errors.append({
                    "symbol": symbol,
                    "error": f"Failed to log recommendation: {log_res.get('message')}",
                })

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
            "market_regime": market_regime,
            "india_vix": india_vix,
            "sentiment_results": sentiment_results,
            "risk_scores": risk_score_results,
            "feasibility": feasibility_result,
            "skipped_symbols": skipped_symbols,
            "errors": errors,
        }
    except Exception as exc:
        logger.error("run-analysis failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Analysis pipeline failed: {exc}") from exc
    finally:
        _exit_analysis_lock()


def run_analysis_pipeline(user_id: str = "sai_aditya") -> Dict[str, Any]:
    return run_analysis(RunAnalysisRequest(user_id=user_id))


@app.get("/recommendations/today", status_code=200, response_model=Dict[str, Any])
def recommendations_today(user_id: str = "sai_aditya") -> Dict[str, Any]:
    recs = get_todays_recommendations(user_id=user_id)
    return {"date": _now_ist().date().isoformat(), "recommendations": recs, "count": len(recs)}


@app.get("/recommendations/winrate", status_code=200, response_model=Dict[str, Any])
def recommendations_winrate(user_id: str = "sai_aditya", last_n: int = 20) -> Dict[str, Any]:
    return get_win_rate(user_id=user_id, last_n=last_n)


@app.get("/scheduler/status", status_code=200, response_model=Dict[str, Any])
def scheduler_status() -> Dict[str, Any]:
    return get_scheduler_status()


@app.post("/scheduler/trigger-morning", status_code=200, response_model=Dict[str, Any])
async def scheduler_trigger_morning() -> Dict[str, Any]:
    try:
        if trigger_morning_now():
            return {"success": True, "message": "Morning job queued."}
        await morning_analysis_job()
        return {"success": True, "message": "Morning job executed directly."}
    except Exception as exc:
        logger.error("Manual morning trigger failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to trigger morning job: {exc}") from exc