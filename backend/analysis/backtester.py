"""
Vectorbt backtesting engine with 24-hour in-memory cache.

Pipeline safety rule: ALL public functions catch exceptions and fall back to
safe defaults — the main analysis pipeline must never crash due to backtester
errors.

Cache key: symbol string (uppercase)
Cache TTL: 24 hours
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    symbol: str
    win_rate: float           # 0.0 – 1.0  (e.g. 0.62 = 62 %)
    total_trades: int
    avg_return_per_trade: float   # percentage (e.g. 1.25 = +1.25 %)
    max_drawdown: float           # percentage (e.g. -8.4 = -8.4 %)
    sharpe_ratio: float
    profit_factor: float          # gross_profit / gross_loss
    lookback_days: int
    computed_at: datetime = field(default_factory=lambda: datetime.now(IST))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "win_rate": round(self.win_rate, 4),
            "total_trades": self.total_trades,
            "avg_return_per_trade": round(self.avg_return_per_trade, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "profit_factor": round(self.profit_factor, 4),
            "lookback_days": self.lookback_days,
            "computed_at": self.computed_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# 24-hour in-memory cache
# ---------------------------------------------------------------------------

_CACHE: Dict[str, BacktestResult] = {}
_CACHE_TTL = timedelta(hours=24)


def _is_cache_valid(result: BacktestResult) -> bool:
    return (datetime.now(IST) - result.computed_at) < _CACHE_TTL


def _get_cached(symbol: str) -> Optional[BacktestResult]:
    key = symbol.strip().upper()
    result = _CACHE.get(key)
    if result and _is_cache_valid(result):
        return result
    if result:
        del _CACHE[key]   # expired
    return None


def _set_cache(result: BacktestResult) -> None:
    _CACHE[result.symbol.strip().upper()] = result


# ---------------------------------------------------------------------------
# Public: get_win_rate — safe for pipeline use
# ---------------------------------------------------------------------------

def get_win_rate(symbol: str) -> float:
    """
    Return cached win rate for symbol (0.0–1.0).

    Falls back to 0.5 if no cache entry exists — never triggers a live
    backtest on demand (safe for the realtime pipeline).
    """
    try:
        key = symbol.strip().upper()
        cached = _get_cached(key)
        if cached:
            logger.debug("Backtest cache hit for %s: win_rate=%.2f", key, cached.win_rate)
            return float(cached.win_rate)
        logger.debug("No backtest cache for %s — returning neutral 0.5", key)
        return 0.5
    except Exception as exc:
        logger.error("get_win_rate failed for %s: %s", symbol, exc)
        return 0.5


# ---------------------------------------------------------------------------
# Public: run_backtest — call explicitly, not from realtime pipeline
# ---------------------------------------------------------------------------

def run_backtest(symbol: str, lookback_days: int = 730) -> BacktestResult:
    """
    Fetch OHLCV history and run a vectorbt long-only backtest.

    Strategy: EMA-9 / EMA-21 crossover (buy on golden cross, sell on death
    cross). Commission 0.1 %, slippage 0.05 %, initial capital ₹50,000.

    Results are cached for 24 hours. Returns a BacktestResult with
    win_rate=0.5 and zeros on any failure — never raises.
    """
    key = symbol.strip().upper()

    # Return from cache if still valid
    cached = _get_cached(key)
    if cached:
        logger.info("Backtest cache hit for %s (%.0f h remaining)", key,
                    (_CACHE_TTL - (datetime.now(IST) - cached.computed_at)).seconds / 3600)
        return cached

    try:
        import vectorbt as vbt
        import pandas as pd
        from data.upstox import get_historical_ohlcv

        df = get_historical_ohlcv(symbol=key, interval="day", days=lookback_days)
        if df is None or len(df) < 50:
            raise ValueError(f"Insufficient OHLCV data for {key}: {len(df) if df is not None else 0} rows")

        close = df["close"].astype(float)

        # EMA crossover signals
        ema_fast = vbt.MA.run(close, 9, short_name="fast").ma
        ema_slow = vbt.MA.run(close, 21, short_name="slow").ma

        entries = (ema_fast > ema_slow) & (ema_fast.shift(1) <= ema_slow.shift(1))
        exits   = (ema_fast < ema_slow) & (ema_fast.shift(1) >= ema_slow.shift(1))

        pf = vbt.Portfolio.from_signals(
            close,
            entries,
            exits,
            init_cash=50_000,
            fees=0.001,      # 0.1 % commission
            slippage=0.0005, # 0.05 % slippage
            freq="D",
        )

        stats = pf.stats()

        total_trades = int(stats.get("Total Trades", 0))
        if total_trades == 0:
            win_rate = 0.5
            avg_ret   = 0.0
            pf_ratio  = 1.0
        else:
            win_rate = float(stats.get("Win Rate [%]", 50.0)) / 100.0
            avg_ret   = float(stats.get("Avg Winning Trade [%]", 0.0))
            gross_win  = float(stats.get("Gross Profit", 0.0) or 0.0)
            gross_loss = abs(float(stats.get("Gross Loss", 0.0) or 1.0))
            pf_ratio   = round(gross_win / gross_loss, 4) if gross_loss > 0 else 1.0

        result = BacktestResult(
            symbol=key,
            win_rate=max(0.0, min(1.0, win_rate)),
            total_trades=total_trades,
            avg_return_per_trade=avg_ret,
            max_drawdown=float(stats.get("Max Drawdown [%]", 0.0)),
            sharpe_ratio=float(stats.get("Sharpe Ratio", 0.0) or 0.0),
            profit_factor=pf_ratio,
            lookback_days=lookback_days,
        )
        _set_cache(result)
        logger.info(
            "Backtest complete for %s: win_rate=%.2f total_trades=%d",
            key, result.win_rate, result.total_trades,
        )
        return result

    except Exception as exc:
        logger.error("run_backtest failed for %s: %s", key, exc)
        fallback = BacktestResult(
            symbol=key,
            win_rate=0.5,
            total_trades=0,
            avg_return_per_trade=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            profit_factor=1.0,
            lookback_days=lookback_days,
        )
        return fallback


# ---------------------------------------------------------------------------
# Public: get_all_cached_results
# ---------------------------------------------------------------------------

def get_all_cached_results() -> Dict[str, Any]:
    """Return all currently valid cache entries as a dict keyed by symbol."""
    valid = {}
    for sym, result in list(_CACHE.items()):
        if _is_cache_valid(result):
            valid[sym] = result.to_dict()
    return valid
