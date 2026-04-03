import logging
import asyncio
from unittest.mock import patch
from .eod_report import send_eod_report

def main():
    logging.basicConfig(level=logging.INFO)
    print("Testing send_eod_report() with dummy data...")

    dummy_summary = {
        "date": "2023-10-27",
        "total_open": 0,
        "wins": 3,
        "losses": 1,
        "still_open": 1,
        "win_rate": 75.0,
        "avg_pnl_pct": 2.5,
    }

    dummy_recs = [
        {"stock": "RELIANCE", "action": "BUY", "entry_price": 2500, "target": 2550, "stop_loss": 2480, "actual_exit": 2555, "outcome": "hit_target", "pnl": 2.2, "risk_score": 4, "reasoning": "Breakout"},
        {"stock": "TCS", "action": "SELL", "entry_price": 3500, "target": 3450, "stop_loss": 3530, "actual_exit": 3530, "outcome": "hit_sl", "pnl": -0.85, "risk_score": 6, "reasoning": "Resistance"},
        {"stock": "INFY", "action": "BUY", "entry_price": 1400, "target": 1450, "stop_loss": 1380, "actual_exit": None, "outcome": "still_open", "pnl": None, "risk_score": 5, "reasoning": "Pullback"},
    ]

    dummy_rolling = {
        "win_rate": 68.5,
        "avg_pnl_pct": 1.2,
    }

    dummy_config = {
        "daily_target": 5000.0,
        "paper_mode": True,
    }

    with patch('notifications.eod_report.run_outcome_logger', return_value=dummy_summary), \
         patch('notifications.eod_report.get_todays_recommendations', return_value=dummy_recs), \
         patch('notifications.eod_report.get_outcomes_summary', return_value=dummy_rolling), \
         patch('notifications.eod_report.get_user_config', return_value=dummy_config), \
         patch('notifications.eod_report.get_india_vix', return_value=12.5):
         
        res = send_eod_report(daily_summary=dummy_summary)
        
        if res:
            print("Success! Report generated and sent.")
            print(f"Verdict: {res.win_rate}% -> OK")
        else:
            print("Failed to generate report.")

if __name__ == "__main__":
    main()


