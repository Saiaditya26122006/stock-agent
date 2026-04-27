"""
Contextual Bandit for adaptive signal weighting.

Each 'arm' is one of the 6 TA signals used by the agent.
The bandit learns which signals actually lead to winning trades
by updating a Beta distribution (alpha, beta) per arm per regime.

Usage
-----
After each trade closes, call:
    bandit.update(signal_name, regime, won=True/False)

Before generating a recommendation, call:
    weights = bandit.get_weights(regime)
and pass them into the TA engine / Gemini prompt builder.

The state is persisted to JSON so it survives restarts.
"""

from __future__ import annotations

import json
import logging
import os
import random
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SIGNALS: List[str] = [
    "ema_trend",
    "rsi",
    "macd",
    "volume",
    "vwap",
    "candlestick",
]

REGIMES: List[str] = ["NORMAL", "CAUTION", "DANGER"]

# Prior: start optimistic — α=2 wins, β=1 loss (67% prior win rate)
ALPHA_PRIOR = 2.0
BETA_PRIOR  = 1.0

# Minimum trades before the bandit's weights are trusted enough to use
MIN_TRADES_TO_TRUST = 200

# Path to persist bandit state
DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "bandit_state.json"


# ---------------------------------------------------------------------------
# Beta distribution Thompson sampling helpers
# ---------------------------------------------------------------------------

def _thompson_sample(alpha: float, beta: float) -> float:
    """Draw one sample from Beta(alpha, beta)."""
    return random.betavariate(alpha, beta)


# ---------------------------------------------------------------------------
# SignalBandit class
# ---------------------------------------------------------------------------

class SignalBandit:
    """
    Multi-arm contextual bandit with one Beta distribution per (signal, regime).

    State dict shape:
        {
          "NORMAL":  {"ema_trend": [alpha, beta], "rsi": [alpha, beta], ...},
          "CAUTION": {...},
          "DANGER":  {...},
        }
    """

    def __init__(self, state_path: Path | str = DEFAULT_STATE_PATH) -> None:
        self.state_path = Path(state_path)
        self.state: Dict[str, Dict[str, List[float]]] = {}
        self.total_updates: int = 0
        self._load_or_init()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_or_init(self) -> None:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    saved = json.load(f)
                self.state = saved.get("state", {})
                self.total_updates = int(saved.get("total_updates", 0))
                logger.info("SignalBandit: loaded state (%d updates).", self.total_updates)
            except Exception as exc:
                logger.warning("SignalBandit: failed to load state (%s) — reinitialising.", exc)
                self._init_state()
        else:
            self._init_state()

    def _init_state(self) -> None:
        self.state = {
            regime: {sig: [ALPHA_PRIOR, BETA_PRIOR] for sig in SIGNALS}
            for regime in REGIMES
        }
        self.total_updates = 0
        logger.info("SignalBandit: initialised fresh state.")

    def save(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump({"state": self.state, "total_updates": self.total_updates}, f, indent=2)
        except Exception as exc:
            logger.error("SignalBandit: failed to save state: %s", exc)

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, signal: str, regime: str, won: bool) -> None:
        """
        Record the outcome of a trade that used `signal` in `regime`.

        Args:
            signal:  one of SIGNALS
            regime:  "NORMAL" | "CAUTION" | "DANGER"
            won:     True if trade hit target, False if hit SL / expired
        """
        regime = regime.upper() if regime else "NORMAL"
        if regime not in REGIMES:
            regime = "NORMAL"
        if signal not in SIGNALS:
            logger.debug("SignalBandit.update: unknown signal '%s', skipping.", signal)
            return

        ab = self.state.setdefault(regime, {}).setdefault(signal, [ALPHA_PRIOR, BETA_PRIOR])
        if won:
            ab[0] += 1.0   # alpha (wins)
        else:
            ab[1] += 1.0   # beta  (losses)

        self.total_updates += 1
        if self.total_updates % 10 == 0:
            self.save()

    def batch_update(self, outcomes: List[Dict]) -> None:
        """
        Batch-update from a list of outcome dicts.
        Each dict: {"signal": str, "regime": str, "won": bool}
        """
        for o in outcomes:
            self.update(
                signal=o.get("signal", ""),
                regime=o.get("regime", "NORMAL"),
                won=bool(o.get("won", False)),
            )
        self.save()

    # ------------------------------------------------------------------
    # Weight inference (Thompson sampling)
    # ------------------------------------------------------------------

    def get_weights(self, regime: str, n_samples: int = 200) -> Dict[str, float]:
        """
        Return normalised weights [0, 1] for each signal in the given regime
        via Thompson sampling.  Falls back to uniform if not enough data.

        Args:
            regime:    market regime string
            n_samples: how many Thompson samples to average (reduces variance)

        Returns:
            dict mapping signal name → weight (sum = 1.0 roughly)
        """
        regime = (regime or "NORMAL").upper()
        if regime not in REGIMES:
            regime = "NORMAL"

        # Before MIN_TRADES_TO_TRUST, return equal weights
        if self.total_updates < MIN_TRADES_TO_TRUST:
            equal = round(1.0 / len(SIGNALS), 4)
            return {s: equal for s in SIGNALS}

        regime_state = self.state.get(regime, {})

        # Average n_samples Thompson draws per arm
        totals: Dict[str, float] = {}
        for sig in SIGNALS:
            ab = regime_state.get(sig, [ALPHA_PRIOR, BETA_PRIOR])
            totals[sig] = sum(_thompson_sample(ab[0], ab[1]) for _ in range(n_samples)) / n_samples

        # Normalise to [0, 1] relative weights
        total = sum(totals.values()) or 1.0
        return {sig: round(v / total, 4) for sig, v in totals.items()}

    def get_raw_stats(self, regime: str) -> Dict[str, Dict]:
        """Return alpha, beta, and implied win rate per signal for a regime."""
        regime = (regime or "NORMAL").upper()
        regime_state = self.state.get(regime, {})
        result = {}
        for sig in SIGNALS:
            ab = regime_state.get(sig, [ALPHA_PRIOR, BETA_PRIOR])
            alpha, beta = ab
            implied_wr = round(alpha / (alpha + beta) * 100, 1)
            result[sig] = {"alpha": alpha, "beta": beta, "implied_win_rate_pct": implied_wr}
        return result

    def __repr__(self) -> str:
        return f"<SignalBandit updates={self.total_updates} trusted={self.total_updates >= MIN_TRADES_TO_TRUST}>"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bandit: SignalBandit | None = None


def get_bandit() -> SignalBandit:
    global _bandit
    if _bandit is None:
        _bandit = SignalBandit()
    return _bandit


# ---------------------------------------------------------------------------
# Convenience helpers used by gemini_synthesis and scheduler
# ---------------------------------------------------------------------------

def get_signal_weights(regime: str) -> Dict[str, float]:
    """Get normalised signal weights for the current market regime."""
    return get_bandit().get_weights(regime)


def record_trade_outcome(
    signals_used: List[str],
    regime: str,
    won: bool,
) -> None:
    """
    Record a trade outcome against all signals that contributed to it.
    Call this from the outcome_logger after a position closes.

    Args:
        signals_used: list of signal names present in the signal_snapshot
        regime:       market regime at trade entry
        won:          True if hit_target, False if hit_sl / expired
    """
    bandit = get_bandit()
    for sig in signals_used:
        bandit.update(signal=sig, regime=regime, won=won)


if __name__ == "__main__":
    # Quick smoke test
    logging.basicConfig(level=logging.INFO)
    b = SignalBandit(state_path=Path("/tmp/bandit_test.json"))
    print("Initial weights (NORMAL):", b.get_weights("NORMAL"))

    # Simulate 250 trades where EMA and RSI win more often
    import random as _r
    for _ in range(250):
        regime = _r.choice(REGIMES)
        for sig in SIGNALS:
            won = _r.random() < (0.70 if sig in ("ema_trend", "rsi") else 0.45)
            b.update(sig, regime, won)

    print("Weights after 250 trades (NORMAL):", b.get_weights("NORMAL"))
    print("Stats (NORMAL):", b.get_raw_stats("NORMAL"))
