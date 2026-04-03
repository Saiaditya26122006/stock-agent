from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from db.outcome_logger import run_outcome_logger, get_outcomes_summary
from db.recommendations import get_todays_recommendations
from db.supabase_client import supabase_client
from analysis.claude_synthesis import get_user_config
from analysis.feasibility import get_india_vix, get_market_regime
from notifications.email_sender import send_eod_report as email_send_eod_report
from notifications.telegram_sender import send_message, _run_async

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

@dataclass
class EODReportData:
    date: str
    total_recommendations: int
    wins: int
    losses: int
    still_open: int
    win_rate: float
    avg_pnl_pct: float
    today_recommendations: List[Dict[str, Any]]
    rolling_win_rate: float
    rolling_avg_pnl_pct: float
    daily_target: float
    paper_mode: bool
    market_regime: str

def _get_jinja_env() -> Environment:
    templates_path = Path(__file__).resolve().parent.parent / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=select_autoescape(["html", "xml"]),
    )

def _determine_verdict(win_rate: float, total_trades: int) -> str:
    if total_trades == 0:
        return "NO TRADES"
    if win_rate >= 55.0:
        return "STRONG"
    if win_rate >= 45.0:
        return "SOLID"
    if win_rate >= 35.0:
        return "BELOW TARGET"
    return "POOR"

def send_eod_report(daily_summary: Dict[str, Any] | None = None) -> EODReportData | None:
    try:
        # 1. Run outcome logger to get today's summary if not provided
        if daily_summary is None:
            daily_summary = run_outcome_logger(user_id="sai_aditya")
        
        # 2. Get today's recommendations
        today_recs = get_todays_recommendations(user_id="sai_aditya")
        recs_list = []
        for r in today_recs:
            if r.get("action") not in ["BUY", "SELL"]:
                continue
            
            outcome = r.get("outcome", "still_open")
            if outcome in ("hit_target", "paper_hit_target"):
                status_color = "GREEN"
            elif outcome in ("hit_sl", "paper_hit_sl"):
                status_color = "RED"
            else:
                status_color = "GREY"
                
            recs_list.append({
                "stock": r.get("stock", ""),
                "action": r.get("action", ""),
                "entry_price": r.get("entry_price", 0.0),
                "target": r.get("target", 0.0),
                "stop_loss": r.get("stop_loss", 0.0),
                "actual_exit": r.get("actual_exit", None),
                "outcome": outcome,
                "pnl": r.get("pnl", None),
                "risk_score": r.get("risk_score", 0.0),
                "reasoning": r.get("reasoning", ""),
                "status_color": status_color
            })
            
        # 3. Get 30-day rolling stats
        rolling_summary = get_outcomes_summary(user_id="sai_aditya", last_days=30)
        
        # 4. Get user config
        user_config = get_user_config(user_id="sai_aditya")
        
        # 5. Get market regime
        vix = get_india_vix()
        regime = get_market_regime(vix)
        
        date_str = datetime.now(IST).strftime("%d %b %Y")
        
        report_data = EODReportData(
            date=date_str,
            total_recommendations=daily_summary.get("wins", 0) + daily_summary.get("losses", 0) + daily_summary.get("still_open", 0),
            wins=daily_summary.get("wins", 0),
            losses=daily_summary.get("losses", 0),
            still_open=daily_summary.get("still_open", 0),
            win_rate=daily_summary.get("win_rate", 0.0),
            avg_pnl_pct=daily_summary.get("avg_pnl_pct", 0.0),
            today_recommendations=recs_list,
            rolling_win_rate=rolling_summary.get("win_rate", 0.0),
            rolling_avg_pnl_pct=rolling_summary.get("avg_pnl_pct", 0.0),
            daily_target=user_config.get("daily_target", 0.0),
            paper_mode=user_config.get("paper_mode", True),
            market_regime=regime
        )
        
        # 6. Render HTML
        template = _get_jinja_env().get_template("eod_report.html")
        html = template.render(
            date=date_str,
            total_recommendations=report_data.total_recommendations,
            wins=report_data.wins,
            losses=report_data.losses,
            still_open=report_data.still_open,
            win_rate=report_data.win_rate,
            avg_pnl_pct=report_data.avg_pnl_pct,
            today_recommendations=report_data.today_recommendations,
            rolling_win_rate=report_data.rolling_win_rate,
            rolling_avg_pnl_pct=report_data.rolling_avg_pnl_pct,
            daily_target=report_data.daily_target,
            paper_mode=report_data.paper_mode,
            market_regime=report_data.market_regime,
            verdict=_determine_verdict(report_data.win_rate, report_data.total_recommendations),
            timestamp=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
        )
        
        # 7. Send Emails and Telegram
        subject = f"📊 EOD Report — {date_str} | {report_data.wins}W {report_data.losses}L | WR: {report_data.win_rate:.0%}"
        email_ok = email_send_eod_report(html_content=html)
        
        if report_data.total_recommendations == 0:
            tg_text = f"📊 EOD {date_str} | No trades today | Market: {regime}"
        else:
            tg_text = f"📊 EOD {date_str} | Trades: {report_data.total_recommendations} | W:{report_data.wins} L:{report_data.losses} | P&L: {report_data.avg_pnl_pct:+.1f}% | WR: {report_data.win_rate:.0f}%"
            
        tg_ok = _run_async(send_message(tg_text))
        
        if not email_ok or not tg_ok:
            logger.warning("EOD report push partial failure. Email: %s, TG: %s", email_ok, tg_ok)
            
        return report_data
    except Exception as exc:
        logger.error("send_eod_report failed: %s", exc)
        return None
