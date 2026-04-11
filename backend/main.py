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
from analysis.special_days import get_full_premarket_context
from analysis.market_regime import (
    apply_regime_to_position,
    filter_by_regime,
    get_regime_config,
    get_regime_prompt_injection,
)
from analysis.gates import run_all_gates
from data.nse import get_circuit_filter_status, get_gift_nifty, get_nse_announcements
from data.nifty500 import NIFTY500_UNIVERSE
from data.upstox import get_historical_ohlcv, test_connection as test_upstox_connection
from analysis.screener import screen_universe
from db.recommendations import (
    get_todays_recommendations,
    get_win_rate,
    log_recommendation,
)
from db.supabase_client import supabase_client, test_connection as test_supabase_connection
from db.watchlist import add_symbol, get_active_watchlist, get_symbols_list, get_watchlist_by_sector, remove_symbol
from scheduler import get_scheduler_status, init_scheduler, morning_analysis_job, trigger_morning_now


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

app = FastAPI(title="Stock Agent API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:5177",
        "https://nse-bse-agent.vercel.app",
        "https://*.vercel.app",
    ],
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
    sector: str = "Uncategorised"
    exchange: str = "NSE"
    user_id: str = "sai_aditya"


class RemoveWatchlistRequest(BaseModel):
    symbol: str
    user_id: str = "sai_aditya"


class RunAnalysisRequest(BaseModel):
    user_id: str = "sai_aditya"


class AnalyseSelectedRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, max_length=10)
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


@app.get("/watchlist/by-sector", status_code=200, response_model=Dict[str, Any])
def watchlist_by_sector(user_id: str = "sai_aditya") -> Dict[str, Any]:
    return get_watchlist_by_sector(user_id=user_id)


@app.post("/watchlist/add", status_code=200, response_model=Dict[str, Any])
def watchlist_add(req: AddWatchlistRequest) -> Dict[str, Any]:
    result = add_symbol(symbol=req.symbol, exchange=req.exchange, user_id=req.user_id, sector=req.sector)
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
    regime_config: Dict[str, Any] = get_regime_config(15.0)
    premarket_context: Dict[str, Any] = {}
    india_vix = 15.0
    market_regime = "NORMAL"
    try:
        run_id = log_run_start(user_id=req.user_id)
        symbols = get_symbols_list(user_id=req.user_id)
        try:
            india_vix = float(get_india_vix())
            market_regime = get_market_regime(india_vix)
            regime_config = get_regime_config(india_vix)
            logger.info("Market regime: %s | VIX: %.2f", market_regime, india_vix)
            logger.info("Regime config: %s", regime_config)
            if market_regime == "DANGER":
                logger.warning("DANGER regime detected — trade filtering will be stricter.")
        except Exception as exc:
            logger.error("Pre-market feasibility fetch failed: %s", exc)
            india_vix = 15.0
            market_regime = "NORMAL"
            regime_config = get_regime_config(india_vix)
        try:
            gift_nifty_data = get_gift_nifty()
            premarket_context = get_full_premarket_context(gift_nifty_data)
            gift_info = premarket_context.get("gift_nifty", {})
            logger.info(
                "Gift Nifty: %+0.2f%% | Signal: %s",
                float(gift_info.get("pct_change", 0.0)),
                gift_info.get("signal", "neutral"),
            )
            special = premarket_context.get("special_day", {})
            event_name = special.get("event") or "No special events"
            logger.info("Special day check: %s", event_name)
            if special.get("is_special_day"):
                logger.warning("Special day active: %s", event_name)
        except Exception as exc:
            logger.error("Premarket context build failed: %s", exc)
            premarket_context = get_full_premarket_context({})

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
                # Run 5-gate pre-trade validation
                try:
                    circuit_data = get_circuit_filter_status(symbol)
                except Exception as _gate_nse_exc:
                    logger.warning("Circuit status fetch failed for %s: %s", symbol, _gate_nse_exc)
                    circuit_data = {}
                try:
                    announcements = get_nse_announcements(symbol)
                except Exception as _gate_ann_exc:
                    logger.warning("Announcements fetch failed for %s: %s", symbol, _gate_ann_exc)
                    announcements = []
                sym_sent_for_gate = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
                gate_result = run_all_gates(
                    symbol=symbol,
                    signal_dict=signal,
                    sentiment_score=sym_sent_for_gate,
                    circuit_data=circuit_data,
                    announcements=announcements,
                )
                if gate_result.get("hard_failure"):
                    reason = gate_result.get("failure_reason", "pre_trade_gate_hard_fail")
                    skipped_symbols.append({"symbol": symbol, "reason": reason})
                    logger.info("Skipped %s: gate hard failure — %s", symbol, reason)
                else:
                    filtered_signals[symbol] = signal

        analysed = len(symbols)
        user_config = get_user_config(user_id=req.user_id)
        regime_context = get_regime_prompt_injection(regime_config)
        recommendations = synthesise_all(
            symbols_signals=filtered_signals,
            user_config=user_config,
            regime_context=regime_context,
        )

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
                    min_risk = float(regime_config.get("min_risk_score", 5.0))
                    if float(rec["risk_score"]) < min_risk:
                        rec["action"] = "SKIP"
                        rec["reasoning"] = (
                            f"{rec.get('reasoning', '')} | Regime gate: risk_score below {min_risk}"
                        ).strip(" |")
                        skipped_symbols.append(
                            {"symbol": symbol, "reason": f"regime_min_risk_below_{min_risk}"}
                        )
                        continue
                    sizing_result = calculate_position_size(
                        capital=float(user_config.get("capital", 0.0)),
                        risk_score=float((risk_score_results.get(symbol) or {}).get("risk_score", 5.0)),
                        entry_price=float(rec.get("entry_price", 0.0) or 0.0),
                        stop_loss=float(rec.get("stop_loss", 0.0) or 0.0),
                    )
                    try:
                        sizing_result = apply_regime_to_position(sizing_result, regime_config)
                    except Exception as regime_exc:
                        logger.error("Regime override failed for %s: %s", symbol, regime_exc)
                    try:
                        modifier = float(premarket_context.get("combined_position_modifier", 1.0))
                        if sizing_result.get("action") == "trade":
                            scaled_shares = int(float(sizing_result.get("shares", 0)) * modifier)
                            scaled_shares = int(scaled_shares)  # ensure integer floor semantics
                            if scaled_shares <= 0:
                                sizing_result = {
                                    "action": "skip",
                                    "shares": 0,
                                    "position_value": 0.0,
                                    "risk_amount": 0.0,
                                    "risk_pct_used": 0.0,
                                    "entry_price": float(sizing_result.get("entry_price", 0.0)),
                                    "stop_loss": float(sizing_result.get("stop_loss", 0.0)),
                                    "capital": float(sizing_result.get("capital", 0.0)),
                                    "capital_at_risk_pct": 0.0,
                                    "reason": "premarket_modifier_reduced_position_to_zero",
                                    "premarket_modifier": modifier,
                                }
                            else:
                                entry_p = float(sizing_result.get("entry_price", 0.0))
                                cap = float(sizing_result.get("capital", 0.0))
                                pos_val = round(scaled_shares * entry_p, 2)
                                sizing_result["shares"] = scaled_shares
                                sizing_result["position_value"] = pos_val
                                sizing_result["capital_at_risk_pct"] = round((pos_val / cap) * 100.0, 2) if cap > 0 else 0.0
                                sizing_result["premarket_modifier"] = modifier
                    except Exception as pm_exc:
                        logger.error("Premarket modifier apply failed for %s: %s", symbol, pm_exc)
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
            recommendations = filter_by_regime(recommendations, regime_config)
        except Exception as exc:
            logger.error("Regime recommendation filtering failed: %s", exc)

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

            if actionable_count == 0:
                try:
                    from notifications.telegram_sender import _run_async, send_message as send_telegram_message
                    from notifications.email_sender import _send_html_email as send_email

                    date_str = _now_ist().strftime("%d %b %Y")
                    tg_msg = (
                        f"🔴 NO TRADES TODAY — {date_str}\n"
                        f"Market: {market_regime} | VIX: {india_vix:.2f}\n\n"
                        f"All {analysed} stocks skipped — no setups met the minimum risk score threshold for current market conditions.\n\n"
                        "💡 Agent is protecting your capital. Check back tomorrow."
                    )
                    _run_async(send_telegram_message(tg_msg))

                    email_subject = f"🔴 No Trades Today — {date_str} | Agent Protecting Capital"
                    email_body = f"""<html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        <h2 style="color: #dc2626;">No Trades Today — {date_str}</h2>
                        <p><strong>Market Regime:</strong> {market_regime}</p>
                        <p><strong>VIX Level:</strong> {india_vix:.2f}</p>
                        <p><strong>Stocks Analysed:</strong> {analysed}</p>
                        <p><strong>Reason:</strong> All {analysed} stocks skipped — no setups met the minimum risk score threshold for current market conditions.</p>
                        <hr style="border: 0; border-top: 1px solid #eee; margin: 20px 0;" />
                        <p>💡 <em>Agent is protecting your capital. The morning analysis pipeline ran successfully and completed evaluating all configured watchlist stocks. Check back tomorrow for new opportunities.</em></p>
                    </body>
                    </html>"""
                    send_email(html_content=email_body, subject=email_subject)
                except Exception as exc:
                    logger.error("Failed to push zero-trade notification: %s", exc)

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
            "regime_config": regime_config,
            "premarket_context": premarket_context,
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


# ---------------------------------------------------------------------------
# Stock Discovery Layer
# ---------------------------------------------------------------------------


@app.get("/discover-stocks", status_code=200, response_model=None)
def discover_stocks() -> Dict[str, Any]:
    """Scan the Nifty 500 universe with lightweight signals.

    This endpoint may take 60-90 seconds due to sequential Upstox API calls
    with rate-limit sleeps.  Consider calling from the frontend with a long
    timeout / spinner.
    """
    india_vix = 15.0
    regime = "NORMAL"
    try:
        india_vix = float(get_india_vix())
        regime = get_market_regime(india_vix)
    except Exception as exc:
        logger.error("discover-stocks VIX fetch failed: %s", exc)

    try:
        candidates = screen_universe(NIFTY500_UNIVERSE)
    except Exception as exc:
        logger.error("discover-stocks screening failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Screening failed: {exc}") from exc

    return {
        "vix": round(india_vix, 2),
        "regime": regime,
        "scanned_count": len(NIFTY500_UNIVERSE),
        "candidates_count": len(candidates),
        "candidates": candidates,
        "timestamp": _now_ist().isoformat(),
    }


@app.post("/analyse-selected", status_code=200, response_model=None)
def analyse_selected(req: AnalyseSelectedRequest) -> Dict[str, Any]:
    """Run the full analysis pipeline on user-selected discovery symbols.

    Mirrors /run-analysis logic scoped to the provided symbol list.
    Max 10 symbols per request.
    """
    if len(req.symbols) > 10:
        raise HTTPException(
            status_code=400,
            detail="Too many symbols. Maximum 10 per request.",
        )

    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols:
        raise HTTPException(status_code=400, detail="No valid symbols provided.")

    errors: List[Dict[str, str]] = []
    results: Dict[str, Any] = {}
    full_signals: Dict[str, Dict[str, Any]] = {}
    sentiment_results: Dict[str, Dict[str, Any]] = {}
    risk_score_results: Dict[str, Dict[str, Any]] = {}
    skipped_symbols: List[Dict[str, str]] = []
    regime_config: Dict[str, Any] = get_regime_config(15.0)
    india_vix = 15.0
    market_regime = "NORMAL"

    # ---- VIX / regime context (identical to /run-analysis) ----
    try:
        india_vix = float(get_india_vix())
        market_regime = get_market_regime(india_vix)
        regime_config = get_regime_config(india_vix)
        logger.info("analyse-selected regime: %s | VIX: %.2f", market_regime, india_vix)
    except Exception as exc:
        logger.error("analyse-selected VIX fetch failed: %s", exc)
        india_vix = 15.0
        market_regime = "NORMAL"
        regime_config = get_regime_config(india_vix)

    # ---- TA engine for each symbol ----
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
            logger.error("analyse-selected TA failed for %s: %s", symbol, exc)
            errors.append({"symbol": symbol, "error": str(exc)})

    # ---- Sentiment ----
    try:
        sentiment_results = get_sentiment_batch(symbols)
    except Exception as exc:
        logger.error("analyse-selected sentiment batch failed: %s", exc)
        sentiment_results = {s: {"symbol": s, "sentiment_score": 0.0, "error": str(exc)} for s in symbols}

    # ---- Risk scoring + gates (same as /run-analysis) ----
    filtered_signals: Dict[str, Dict[str, Any]] = {}
    for symbol, signal in full_signals.items():
        try:
            sym_sent = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
            risk_payload = compute_risk_score(signal_dict=signal, sentiment_score=sym_sent, symbol=symbol)
        except Exception as exc:
            logger.error("Risk scoring failed for %s: %s", symbol, exc)
            risk_payload = {
                "risk_score": 5.0, "tier": "moderate",
                "recommendation": "half_position",
                "component_scores": {}, "weights_applied": {},
            }
        risk_score_results[symbol] = risk_payload

        try:
            should_skip = should_skip_stock(
                risk_score=float(risk_payload.get("risk_score", 5.0)),
                sentiment_score=float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0)),
            )
        except Exception as exc:
            logger.error("Skip gate failed for %s: %s", symbol, exc)
            should_skip = False

        if should_skip:
            skipped_symbols.append({"symbol": symbol, "reason": "risk_or_sentiment_gate"})
        else:
            try:
                circuit_data = get_circuit_filter_status(symbol)
            except Exception:
                circuit_data = {}
            try:
                announcements = get_nse_announcements(symbol)
            except Exception:
                announcements = []
            sym_sent_for_gate = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
            gate_result = run_all_gates(
                symbol=symbol, signal_dict=signal,
                sentiment_score=sym_sent_for_gate,
                circuit_data=circuit_data, announcements=announcements,
            )
            if gate_result.get("hard_failure"):
                skipped_symbols.append({"symbol": symbol, "reason": gate_result.get("failure_reason", "gate_fail")})
            else:
                filtered_signals[symbol] = signal

    # ---- Gemini synthesis with regime context ----
    user_config = get_user_config(user_id=req.user_id)
    regime_context = get_regime_prompt_injection(regime_config)
    recommendations = synthesise_all(
        symbols_signals=filtered_signals,
        user_config=user_config,
        regime_context=regime_context,
    )

    # Back-fill skipped symbols
    for skipped in skipped_symbols:
        sym = skipped.get("symbol", "")
        if sym and sym not in recommendations:
            recommendations[sym] = {
                "symbol": sym, "action": "SKIP", "style": "intraday",
                "entry_price": 0.0, "target": 0.0, "stop_loss": 0.0,
                "hold_period": "N/A", "confidence": "LOW",
                "reasoning": skipped.get("reason", "Filtered by gate."),
                "risk_reward": 0.0,
            }

    # ---- Position sizing + regime overrides ----
    for symbol, rec in recommendations.items():
        try:
            rec["risk_score"] = float((risk_score_results.get(symbol) or {}).get("risk_score", 5.0))
            rec["sentiment_score"] = float((sentiment_results.get(symbol) or {}).get("sentiment_score", 0.0))
            if rec.get("action") in {"BUY", "SELL"}:
                min_risk = float(regime_config.get("min_risk_score", 5.0))
                if float(rec["risk_score"]) < min_risk:
                    rec["action"] = "SKIP"
                    rec["reasoning"] = (
                        f"{rec.get('reasoning', '')} | Regime gate: risk_score below {min_risk}"
                    ).strip(" |")
                    continue
                sizing_result = calculate_position_size(
                    capital=float(user_config.get("capital", 0.0)),
                    risk_score=float((risk_score_results.get(symbol) or {}).get("risk_score", 5.0)),
                    entry_price=float(rec.get("entry_price", 0.0) or 0.0),
                    stop_loss=float(rec.get("stop_loss", 0.0) or 0.0),
                )
                try:
                    sizing_result = apply_regime_to_position(sizing_result, regime_config)
                except Exception as regime_exc:
                    logger.error("Regime override failed for %s: %s", symbol, regime_exc)
                rec["position_sizing"] = sizing_result
                if sizing_result.get("action") == "skip":
                    rec["action"] = "SKIP"
                    rec["reasoning"] = (
                        f"{rec.get('reasoning', '')} | Position sizing skip: {sizing_result.get('reason')}"
                    ).strip(" |")
        except Exception as exc:
            logger.error("Position sizing enrichment failed for %s: %s", symbol, exc)

    try:
        recommendations = filter_by_regime(recommendations, regime_config)
    except Exception as exc:
        logger.error("Regime filtering failed for analyse-selected: %s", exc)

    # ---- Log to Supabase recommendations_log ----
    for symbol, rec in recommendations.items():
        if rec.get("action") not in {"BUY", "SELL"}:
            continue
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
            errors.append({"symbol": symbol, "error": f"Log failed: {log_res.get('message')}"})

    return {
        "timestamp": _now_ist().isoformat(),
        "stocks_analysed": len(symbols),
        "results": results,
        "recommendations": recommendations,
        "market_regime": market_regime,
        "india_vix": india_vix,
        "sentiment_results": sentiment_results,
        "risk_scores": risk_score_results,
        "regime_config": regime_config,
        "skipped_symbols": skipped_symbols,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Backtester endpoints
# ---------------------------------------------------------------------------

@app.post("/backtest/{symbol}", status_code=200, response_model=Dict[str, Any])
def run_backtest_endpoint(symbol: str, lookback_days: int = 730) -> Dict[str, Any]:
    """Run vectorbt backtest for a symbol and return full result. Results are cached 24 h."""
    try:
        from analysis.backtester import run_backtest
        result = run_backtest(symbol=symbol.upper(), lookback_days=lookback_days)
        return result.to_dict()
    except Exception as exc:
        logger.error("Backtest endpoint failed for %s: %s", symbol, exc)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc


@app.get("/backtest/results", status_code=200, response_model=Dict[str, Any])
def get_backtest_results() -> Dict[str, Any]:
    """Return all currently cached backtest results (keyed by symbol)."""
    try:
        from analysis.backtester import get_all_cached_results
        return get_all_cached_results()
    except Exception as exc:
        logger.error("get_backtest_results failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to fetch cached results: {exc}") from exc


# ---------------------------------------------------------------------------
# Outcome logger endpoints
# ---------------------------------------------------------------------------

@app.post("/outcomes/log-today", status_code=200, response_model=Dict[str, Any])
def log_outcomes_today(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """Manually trigger outcome logger for today's open recommendations."""
    try:
        from db.outcome_logger import run_outcome_logger
        from notifications.eod_report import send_eod_report
        
        # Log outcomes
        summary = run_outcome_logger(user_id=user_id)
        
        # Trigger EOD report
        report = send_eod_report(daily_summary=summary)
        
        return {
            "summary": summary,
            "report_generated": report is not None
        }
    except Exception as exc:
        logger.error("log_outcomes_today endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Outcome logging failed: {exc}") from exc

@app.get("/eod/latest", status_code=200, response_model=Dict[str, Any])
def get_latest_eod(user_id: str = "sai_aditya") -> Dict[str, Any]:
    """Return the most recent EOD report summary based on today's logs."""
    try:
        from db.outcome_logger import run_outcome_logger, get_outcomes_summary
        
        # Use idempotent outcome logger run to get today's state safely
        daily_summary = run_outcome_logger(user_id=user_id)
        rolling_summary = get_outcomes_summary(user_id=user_id, last_days=30)
        
        return {
            "today": daily_summary,
            "rolling_30_day": rolling_summary
        }
    except Exception as exc:
        logger.error("get_latest_eod endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Latest EOD fetch failed: {exc}") from exc


@app.get("/outcomes/summary", status_code=200, response_model=Dict[str, Any])
def outcomes_summary(user_id: str = "sai_aditya", last_days: int = 30) -> Dict[str, Any]:
    """Return aggregate outcome stats for the last N days."""
    try:
        from db.outcome_logger import get_outcomes_summary
        return get_outcomes_summary(user_id=user_id, last_days=last_days)
    except Exception as exc:
        logger.error("outcomes_summary endpoint failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Summary fetch failed: {exc}") from exc
