"""Pre-trade 5-gate validation system."""

from __future__ import annotations

import logging
from typing import Any, Dict, List


logger = logging.getLogger(__name__)


def _safe_pass_gate(gate: int, name: str, reason: str = "") -> Dict[str, Any]:
    return {
        "gate": gate,
        "name": name,
        "passed": True,
        "warning": False,
        "reason": reason or "passed",
        "flag": "",
    }


def run_gate_1_circuit(circuit_data: Dict) -> Dict[str, Any]:
    """Hard fail if stock is currently at upper/lower circuit."""
    try:
        at_circuit = bool((circuit_data or {}).get("at_circuit", False))
        if at_circuit:
            return {
                "gate": 1,
                "name": "circuit_filter",
                "passed": False,
                "warning": False,
                "reason": "circuit_filter: stock at upper/lower circuit limit",
                "flag": "",
            }
        return _safe_pass_gate(1, "circuit_filter", "circuit_filter: stock not at circuit")
    except Exception as exc:
        logger.info("Gate 1 error; defaulting to pass: %s", exc)
        return _safe_pass_gate(1, "circuit_filter", "circuit_filter: pass fallback due to error")


def run_gate_2_liquidity(signal_dict: Dict) -> Dict[str, Any]:
    """Hard fail if volume ratio is below 0.5x average."""
    try:
        volume_ratio = (signal_dict or {}).get("volume_ratio")
        if volume_ratio is None:
            return _safe_pass_gate(2, "liquidity", "liquidity: volume ratio missing, pass by default")
        vr = float(volume_ratio)
        if vr < 0.5:
            return {
                "gate": 2,
                "name": "liquidity",
                "passed": False,
                "warning": False,
                "reason": f"liquidity: volume {vr:.2f}x below 50% of 20-day average",
                "flag": "",
            }
        return _safe_pass_gate(2, "liquidity", f"liquidity: volume {vr:.2f}x acceptable")
    except Exception as exc:
        logger.info("Gate 2 error; defaulting to pass: %s", exc)
        return _safe_pass_gate(2, "liquidity", "liquidity: pass fallback due to error")


def run_gate_3_event_risk(announcements: List[Dict]) -> Dict[str, Any]:
    """Warning gate: event risk within 3 days halves position size."""
    try:
        rows = announcements or []
        soonest: int | None = None
        for item in rows:
            if not isinstance(item, dict):
                continue
            days = item.get("days_away")
            try:
                d = int(days)
            except Exception:
                continue
            if d <= 3 and (soonest is None or d < soonest):
                soonest = d
        if soonest is not None:
            return {
                "gate": 3,
                "name": "event_risk",
                "passed": True,
                "warning": True,
                "reason": f"event_risk: NSE announcement in {soonest} days — position halved",
                "flag": "event_risk",
            }
        return _safe_pass_gate(3, "event_risk", "event_risk: no near-term announcements")
    except Exception as exc:
        logger.info("Gate 3 error; defaulting to pass: %s", exc)
        return _safe_pass_gate(3, "event_risk", "event_risk: pass fallback due to error")


def run_gate_4_sentiment(sentiment_score: float) -> Dict[str, Any]:
    """Hard fail on strongly negative sentiment."""
    try:
        score = float(sentiment_score)
        if score < -0.3:
            return {
                "gate": 4,
                "name": "sentiment",
                "passed": False,
                "warning": False,
                "reason": f"sentiment: score {score:.2f} below -0.3 threshold",
                "flag": "",
            }
        return _safe_pass_gate(4, "sentiment", f"sentiment: score {score:.2f} acceptable")
    except Exception as exc:
        logger.info("Gate 4 error; defaulting to pass: %s", exc)
        return _safe_pass_gate(4, "sentiment", "sentiment: pass fallback due to error")


def run_gate_5_volatility(signal_dict: Dict) -> Dict[str, Any]:
    """Warning gate: high ATR volatility reduces position size."""
    try:
        atr_pct = ((signal_dict or {}).get("atr") or {}).get("pct_of_price")
        if atr_pct is None:
            return _safe_pass_gate(5, "volatility", "volatility: ATR missing, no warning")
        atr = float(atr_pct)
        if atr > 4.0:
            return {
                "gate": 5,
                "name": "volatility",
                "passed": True,
                "warning": True,
                "reason": f"volatility: ATR {atr:.2f}% exceeds 4% threshold — position reduced",
                "flag": "high_volatility",
            }
        return _safe_pass_gate(5, "volatility", f"volatility: ATR {atr:.2f}% acceptable")
    except Exception as exc:
        logger.info("Gate 5 error; defaulting to pass: %s", exc)
        return _safe_pass_gate(5, "volatility", "volatility: pass fallback due to error")


def run_all_gates(
    symbol: str,
    signal_dict: Dict,
    sentiment_score: float,
    circuit_data: Dict = None,
    announcements: List[Dict] = None,
) -> Dict[str, Any]:
    """Run all 5 gates sequentially; stop only on hard failures."""
    safe = {
        "symbol": symbol,
        "passed": True,
        "hard_failure": False,
        "gate_results": [],
        "failed_gate": 0,
        "failure_reason": "",
        "warnings": [],
        "position_modifier": 1.0,
        "flags": [],
    }
    try:
        gate_results: List[Dict[str, Any]] = []
        warnings: List[str] = []
        flags: List[str] = []
        modifier = 1.0

        g1 = run_gate_1_circuit(circuit_data or {})
        gate_results.append(g1)
        logger.info("Gate result %s %s: %s", symbol, g1["name"], g1["reason"])
        if not g1["passed"]:
            safe.update(
                {
                    "passed": False,
                    "hard_failure": True,
                    "gate_results": gate_results,
                    "failed_gate": 1,
                    "failure_reason": g1["reason"],
                }
            )
            return safe

        g2 = run_gate_2_liquidity(signal_dict or {})
        gate_results.append(g2)
        logger.info("Gate result %s %s: %s", symbol, g2["name"], g2["reason"])
        if not g2["passed"]:
            safe.update(
                {
                    "passed": False,
                    "hard_failure": True,
                    "gate_results": gate_results,
                    "failed_gate": 2,
                    "failure_reason": g2["reason"],
                }
            )
            return safe

        g3 = run_gate_3_event_risk(announcements or [])
        gate_results.append(g3)
        logger.info("Gate result %s %s: %s", symbol, g3["name"], g3["reason"])
        if g3.get("warning"):
            warnings.append(g3["reason"])
            flags.append(g3.get("flag", ""))
            modifier *= 0.5

        g4 = run_gate_4_sentiment(sentiment_score)
        gate_results.append(g4)
        logger.info("Gate result %s %s: %s", symbol, g4["name"], g4["reason"])
        if not g4["passed"]:
            safe.update(
                {
                    "passed": False,
                    "hard_failure": True,
                    "gate_results": gate_results,
                    "failed_gate": 4,
                    "failure_reason": g4["reason"],
                    "warnings": warnings,
                    "flags": [f for f in flags if f],
                    "position_modifier": modifier,
                }
            )
            return safe

        g5 = run_gate_5_volatility(signal_dict or {})
        gate_results.append(g5)
        logger.info("Gate result %s %s: %s", symbol, g5["name"], g5["reason"])
        if g5.get("warning"):
            warnings.append(g5["reason"])
            flags.append(g5.get("flag", ""))
            modifier *= 0.75

        safe.update(
            {
                "passed": True,
                "hard_failure": False,
                "gate_results": gate_results,
                "failed_gate": 0,
                "failure_reason": "",
                "warnings": warnings,
                "position_modifier": round(modifier, 3),
                "flags": [f for f in flags if f],
            }
        )
        return safe
    except Exception as exc:
        logger.info("run_all_gates error for %s; defaulting to pass: %s", symbol, exc)
        safe["warnings"] = ["gate_engine_error_fallback_pass"]
        return safe


def format_gate_result_for_log(gate_result: Dict) -> str:
    """Human-readable summary for gate outcomes."""
    try:
        symbol = str((gate_result or {}).get("symbol", "UNKNOWN"))
        passed = bool((gate_result or {}).get("passed", False))
        warnings = (gate_result or {}).get("warnings", []) or []
        if passed and not warnings:
            return f"✅ {symbol}: All gates passed"
        if passed and warnings:
            return f"⚠️ {symbol}: Passed with warnings — {'; '.join(str(w) for w in warnings)}"
        failed_gate = int((gate_result or {}).get("failed_gate", 0))
        failure_reason = str((gate_result or {}).get("failure_reason", "unknown failure"))
        return f"❌ {symbol}: Gate {failed_gate} failed — {failure_reason}"
    except Exception:
        return "❌ UNKNOWN: Gate formatting error"
