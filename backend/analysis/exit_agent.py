"""
PPO Exit Timing Agent — scaffold for learning when to exit open positions.

Architecture
------------
State  (11 features):
  pnl_pct           — current unrealised P&L as % of entry
  rsi               — current RSI (normalised 0-1)
  macd_histogram    — MACD histogram value (normalised)
  volume_ratio      — today vol / 20-day avg
  atr_pct           — ATR as % of price
  vwap_bias         — 1=above, 0=at, -1=below
  ema_trend         — 1=bullish, 0=neutral, -1=bearish
  bars_held         — number of bars position has been open (normalised)
  time_to_sl_pct    — distance from current price to stop-loss as %
  time_to_target_pct— distance from current price to target as %
  horizon_lt        — 1 if LONG_TERM position, 0 if SHORT_TERM

Actions (discrete, 3):
  0 = HOLD          — do nothing
  1 = EXIT_NOW      — close at market
  2 = TRAIL_SL      — tighten stop-loss by 0.5 × ATR

Reward:
  +pnl_pct on EXIT_NOW
  -0.01   on HOLD (time cost)
  +0.005  on TRAIL_SL if price subsequently moves favourably

The agent is trained only after MIN_TRAINING_EPISODES closed trades.
Until then, a simple rule-based fallback is used.

Dependencies: stable-baselines3, gymnasium, numpy
Install: pip install stable-baselines3 gymnasium numpy
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "exit_agent_ppo.zip"
MIN_TRAINING_EPISODES = 500   # require 500 closed trades before switching on PPO
OBS_DIM = 11
N_ACTIONS = 3   # HOLD, EXIT_NOW, TRAIL_SL

ACTION_HOLD      = 0
ACTION_EXIT_NOW  = 1
ACTION_TRAIL_SL  = 2

# ---------------------------------------------------------------------------
# Observation builder
# ---------------------------------------------------------------------------

def build_observation(
    pnl_pct: float,
    rsi: float,
    macd_histogram: float,
    volume_ratio: float,
    atr_pct: float,
    vwap_bias: float,         # already -1/0/1
    ema_trend: float,         # already -1/0/1
    bars_held: int,
    entry_price: float,
    current_price: float,
    stop_loss: float,
    target: float,
    is_long_term: bool,
) -> np.ndarray:
    """
    Build the 11-dimensional normalised observation vector for the exit agent.
    All values are clipped to [-5, 5] for training stability.
    """
    def _safe(v: Any, default: float = 0.0) -> float:
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    entry = _safe(entry_price, 1.0) or 1.0
    current = _safe(current_price, entry)
    sl = _safe(stop_loss, entry * 0.92)
    tgt = _safe(target, entry * 1.08)

    time_to_sl_pct   = ((current - sl)  / entry) * 100.0 if entry else 0.0
    time_to_tgt_pct  = ((tgt - current) / entry) * 100.0 if entry else 0.0

    obs = np.array([
        np.clip(_safe(pnl_pct)         / 10.0, -5, 5),
        np.clip(_safe(rsi, 50) / 100.0,          0, 1),
        np.clip(_safe(macd_histogram)  / 5.0,  -5, 5),
        np.clip(_safe(volume_ratio, 1) / 3.0,   0, 5),
        np.clip(_safe(atr_pct)         / 5.0,   0, 5),
        float(np.clip(_safe(vwap_bias),        -1, 1)),
        float(np.clip(_safe(ema_trend),        -1, 1)),
        np.clip(_safe(bars_held) / 30.0,        0, 5),
        np.clip(time_to_sl_pct  / 10.0,        -5, 5),
        np.clip(time_to_tgt_pct / 10.0,        -5, 5),
        1.0 if is_long_term else 0.0,
    ], dtype=np.float32)

    return obs


# ---------------------------------------------------------------------------
# Rule-based fallback (used before MIN_TRAINING_EPISODES)
# ---------------------------------------------------------------------------

def rule_based_exit_decision(
    pnl_pct: float,
    bars_held: int,
    is_long_term: bool,
    rsi: float = 50.0,
) -> Tuple[int, str]:
    """
    Simple heuristic exit rules used before the PPO model is trained.

    Returns: (action, reason)
    """
    # Long-term: only exit on deep loss or after 6+ months
    if is_long_term:
        if pnl_pct <= -8.0:
            return ACTION_EXIT_NOW, "Drawdown breach >8% — exit to preserve capital."
        if bars_held > 120 and pnl_pct > 15.0:
            return ACTION_TRAIL_SL, "Strong gain after 120 bars — tighten stop."
        return ACTION_HOLD, "Long-term position — hold unless thesis broken."

    # Short-term: tighter rules
    if pnl_pct >= 4.0 and rsi > 72:
        return ACTION_EXIT_NOW, "RSI overbought + 4% gain — take profit now."
    if pnl_pct <= -3.0:
        return ACTION_EXIT_NOW, "Loss exceeds 3% — cut position."
    if bars_held >= 5 and pnl_pct > 1.5:
        return ACTION_TRAIL_SL, "Profitable after 5 bars — trail stop to lock in gains."
    if bars_held >= 3 and -0.5 < pnl_pct < 0.5:
        return ACTION_EXIT_NOW, "Flat after 3 bars — no momentum, exit."
    return ACTION_HOLD, "Setup still valid — hold."


# ---------------------------------------------------------------------------
# PPO model wrapper
# ---------------------------------------------------------------------------

class ExitAgent:
    """
    Wraps a stable-baselines3 PPO model for exit timing decisions.
    Falls back to rule-based logic until the model is trained.
    """

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._model = None
        self._sb3_available = False
        self._try_load_sb3()

    def _try_load_sb3(self) -> None:
        try:
            from stable_baselines3 import PPO  # noqa: F401
            self._sb3_available = True
            if self.model_path.exists():
                from stable_baselines3 import PPO
                self._model = PPO.load(str(self.model_path))
                logger.info("ExitAgent: loaded PPO model from %s.", self.model_path)
            else:
                logger.info("ExitAgent: no trained model found at %s — using rules.", self.model_path)
        except ImportError:
            logger.info("ExitAgent: stable-baselines3 not installed — using rule-based fallback.")

    def predict(self, obs: np.ndarray) -> int:
        """Return action int (0=HOLD, 1=EXIT, 2=TRAIL_SL)."""
        if self._model is not None:
            action, _ = self._model.predict(obs, deterministic=True)
            return int(action)
        return ACTION_HOLD  # fallback

    def decide(
        self,
        pnl_pct: float,
        rsi: float,
        macd_histogram: float,
        volume_ratio: float,
        atr_pct: float,
        vwap_bias: float,
        ema_trend: float,
        bars_held: int,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        target: float,
        is_long_term: bool,
        n_closed_trades: int = 0,
    ) -> Dict[str, Any]:
        """
        Main decision method.  Returns dict with action, label, and reason.

        Uses rule-based fallback until MIN_TRAINING_EPISODES and no model file.
        """
        use_rules = (self._model is None) or (n_closed_trades < MIN_TRAINING_EPISODES)

        if use_rules:
            action, reason = rule_based_exit_decision(
                pnl_pct=pnl_pct,
                bars_held=bars_held,
                is_long_term=is_long_term,
                rsi=rsi,
            )
        else:
            obs = build_observation(
                pnl_pct=pnl_pct,
                rsi=rsi,
                macd_histogram=macd_histogram,
                volume_ratio=volume_ratio,
                atr_pct=atr_pct,
                vwap_bias=vwap_bias,
                ema_trend=ema_trend,
                bars_held=bars_held,
                entry_price=entry_price,
                current_price=current_price,
                stop_loss=stop_loss,
                target=target,
                is_long_term=is_long_term,
            )
            action = self.predict(obs)
            reason = {
                ACTION_HOLD:     "PPO model: continue holding.",
                ACTION_EXIT_NOW: "PPO model: exit signal triggered.",
                ACTION_TRAIL_SL: "PPO model: tighten trailing stop-loss.",
            }.get(action, "Unknown.")

        labels = {ACTION_HOLD: "HOLD", ACTION_EXIT_NOW: "EXIT_NOW", ACTION_TRAIL_SL: "TRAIL_SL"}
        return {
            "action": action,
            "label":  labels.get(action, "HOLD"),
            "reason": reason,
            "used_ppo": not use_rules,
        }

    # ------------------------------------------------------------------
    # Training scaffold
    # ------------------------------------------------------------------

    def train(
        self,
        trade_episodes: List[Dict],
        total_timesteps: int = 50_000,
    ) -> bool:
        """
        Train / fine-tune the PPO model on historical trade data.

        `trade_episodes` is a list of episode dicts, each containing:
            observations: List[np.ndarray]  — sequence of obs arrays
            actions:      List[int]         — expert action at each step
            rewards:      List[float]       — P&L reward at exit step

        This is a simplified imitation-learning-style training using
        a custom gymnasium environment built from the recorded episodes.
        Requires stable-baselines3 and gymnasium to be installed.

        Returns True if training succeeded.
        """
        if not self._sb3_available:
            logger.warning("ExitAgent.train: stable-baselines3 not installed. Skipping.")
            return False

        if len(trade_episodes) < MIN_TRAINING_EPISODES:
            logger.info(
                "ExitAgent.train: only %d episodes — need %d. Skipping.",
                len(trade_episodes), MIN_TRAINING_EPISODES,
            )
            return False

        try:
            from analysis.exit_env import ExitTimingEnv
            from stable_baselines3 import PPO
            import gymnasium as gym

            env = ExitTimingEnv(episodes=trade_episodes)
            model = PPO("MlpPolicy", env, verbose=0, n_steps=512, batch_size=64)
            model.learn(total_timesteps=total_timesteps)
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            model.save(str(self.model_path))
            self._model = model
            logger.info("ExitAgent: PPO trained and saved to %s.", self.model_path)
            return True
        except Exception as exc:
            logger.error("ExitAgent.train failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Gymnasium environment (used during training)
# ---------------------------------------------------------------------------

def build_exit_env_class():
    """
    Returns the ExitTimingEnv class.  Imported lazily so gymnasium is optional
    at runtime — only needed during training.
    """
    try:
        import gymnasium as gym
        from gymnasium import spaces

        class ExitTimingEnv(gym.Env):
            """
            Episodic environment replaying recorded trade sequences.
            Each episode = one historical trade with its daily observations.
            """
            metadata = {"render_modes": []}

            def __init__(self, episodes: List[Dict]) -> None:
                super().__init__()
                self.episodes = episodes
                self.ep_idx = 0
                self.step_idx = 0
                self.current_episode: Dict = {}

                self.observation_space = spaces.Box(
                    low=-5.0, high=5.0, shape=(OBS_DIM,), dtype=np.float32
                )
                self.action_space = spaces.Discrete(N_ACTIONS)

            def reset(self, *, seed=None, options=None):
                super().reset(seed=seed)
                self.ep_idx = (self.ep_idx + 1) % len(self.episodes)
                self.step_idx = 0
                self.current_episode = self.episodes[self.ep_idx]
                obs = self.current_episode["observations"][0]
                return obs.astype(np.float32), {}

            def step(self, action: int):
                ep = self.current_episode
                obs_list = ep["observations"]
                reward_list = ep.get("rewards", [0.0] * len(obs_list))

                terminated = False
                truncated  = False

                if action == ACTION_EXIT_NOW:
                    reward = float(reward_list[self.step_idx])
                    terminated = True
                elif action == ACTION_TRAIL_SL:
                    reward = 0.005
                else:
                    reward = -0.01  # time cost

                self.step_idx += 1
                if self.step_idx >= len(obs_list):
                    truncated = True
                    reward = float(reward_list[-1])

                next_obs = obs_list[min(self.step_idx, len(obs_list) - 1)]
                return next_obs.astype(np.float32), reward, terminated, truncated, {}

        return ExitTimingEnv

    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_exit_agent: ExitAgent | None = None


def get_exit_agent() -> ExitAgent:
    global _exit_agent
    if _exit_agent is None:
        _exit_agent = ExitAgent()
    return _exit_agent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = ExitAgent()
    result = agent.decide(
        pnl_pct=3.2, rsi=68, macd_histogram=0.5, volume_ratio=1.8,
        atr_pct=1.2, vwap_bias=1, ema_trend=1, bars_held=3,
        entry_price=500, current_price=516, stop_loss=485, target=540,
        is_long_term=False, n_closed_trades=50,
    )
    print("Exit decision:", result)
