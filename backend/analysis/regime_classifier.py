"""
Multi-signal Market Regime Classifier.

Combines 5 signals to classify the current market as:
    NORMAL  — neutral / trending, trade normally
    CAUTION — mild stress, reduce position size / tighten SL
    DANGER  — high volatility / bear, avoid new entries / paper trade only

Signals used
------------
1. India VIX                — primary volatility gauge
2. NSE Advance-Decline ratio— market breadth
3. Nifty 50 EMA trend       — directional bias
4. FII net flow (optional)  — institutional sentiment
5. Nifty vs 20-day high/low — breakout or breakdown zone

A RandomForest classifier is trained when enough labelled data (>180 trading
days) is available.  Until then, a fast rule-based classifier is used.

Usage
-----
    from analysis.regime_classifier import get_regime
    regime = get_regime()   # "NORMAL" | "CAUTION" | "DANGER"
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_PATH  = Path(__file__).resolve().parent.parent / "data" / "regime_clf.pkl"
CACHE_PATH  = Path(__file__).resolve().parent.parent / "data" / "regime_cache.json"
REGIMES     = ("NORMAL", "CAUTION", "DANGER")
MIN_SAMPLES = 180  # days before switching to ML classifier
CACHE_TTL_SECONDS = 3600  # 1 hour cache to avoid hammering the APIs


# ---------------------------------------------------------------------------
# Feature builder
# ---------------------------------------------------------------------------

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def fetch_regime_features() -> Dict[str, float]:
    """
    Fetch all 5 regime signals and return as a feature dict.
    Any fetch failure is logged and falls back to a neutral value.
    """
    features: Dict[str, float] = {}

    # 1. India VIX
    try:
        from data.nse import get_india_vix
        features["vix"] = _safe_float(get_india_vix(), 15.0)
    except Exception as exc:
        logger.warning("RegimeClassifier: VIX fetch failed: %s", exc)
        features["vix"] = 15.0

    # 2. Nifty 50 EMA trend via daily OHLCV
    try:
        from data.upstox import get_historical_ohlcv
        df = get_historical_ohlcv(symbol="NIFTY_50", interval="day", days=50)
        if df is not None and len(df) >= 21:
            close = df["close"].values.astype(float)
            ema20 = _ema(close, 20)[-1]
            ema50 = _ema(close, 50)[-1] if len(close) >= 50 else ema20
            last  = close[-1]
            # +1 = bullish (price > EMA20 > EMA50), -1 = bearish, 0 = mixed
            if last > ema20 and ema20 > ema50:
                features["nifty_ema_trend"] = 1.0
            elif last < ema20 and ema20 < ema50:
                features["nifty_ema_trend"] = -1.0
            else:
                features["nifty_ema_trend"] = 0.0
            # Nifty vs 20-day high/low zone
            high20 = float(df["high"].tail(20).max())
            low20  = float(df["low"].tail(20).min())
            rng = high20 - low20 if high20 != low20 else 1.0
            features["nifty_range_pct"] = (last - low20) / rng  # 0=at low, 1=at high
        else:
            features["nifty_ema_trend"] = 0.0
            features["nifty_range_pct"] = 0.5
    except Exception as exc:
        logger.warning("RegimeClassifier: Nifty OHLCV fetch failed: %s", exc)
        features["nifty_ema_trend"] = 0.0
        features["nifty_range_pct"] = 0.5

    # 3. NSE Advance-Decline ratio
    try:
        from data.nse import get_advance_decline
        ad = get_advance_decline()
        advances = _safe_float(ad.get("advances"), 1)
        declines = _safe_float(ad.get("declines"), 1)
        total = advances + declines
        features["ad_ratio"] = (advances / total) if total > 0 else 0.5
    except Exception as exc:
        logger.warning("RegimeClassifier: A-D ratio fetch failed: %s", exc)
        features["ad_ratio"] = 0.5

    # 4. FII net flow (optional — neutral if unavailable)
    try:
        from data.nse import get_fii_net_flow
        fii = _safe_float(get_fii_net_flow(), 0.0)
        # Normalise to ±1 range (assuming ±5000 Cr is extreme)
        features["fii_flow"] = float(np.clip(fii / 5000.0, -1.0, 1.0))
    except Exception as exc:
        logger.debug("RegimeClassifier: FII flow fetch failed (optional): %s", exc)
        features["fii_flow"] = 0.0

    return features


def _ema(values: np.ndarray, period: int) -> np.ndarray:
    """Simple vectorised EMA."""
    alpha = 2.0 / (period + 1)
    result = np.zeros_like(values)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1 - alpha) * result[i - 1]
    return result


def features_to_vector(features: Dict[str, float]) -> np.ndarray:
    """Convert feature dict to fixed-length numpy vector."""
    return np.array([
        features.get("vix", 15.0),
        features.get("nifty_ema_trend", 0.0),
        features.get("nifty_range_pct", 0.5),
        features.get("ad_ratio", 0.5),
        features.get("fii_flow", 0.0),
    ], dtype=np.float32)


# ---------------------------------------------------------------------------
# Rule-based classifier (always available)
# ---------------------------------------------------------------------------

def rule_based_regime(features: Dict[str, float]) -> str:
    """
    Fast heuristic regime classification.
    Produces identical output to the ML model on well-understood market states.
    """
    vix         = features.get("vix", 15.0)
    ema_trend   = features.get("nifty_ema_trend", 0.0)
    ad_ratio    = features.get("ad_ratio", 0.5)
    fii_flow    = features.get("fii_flow", 0.0)
    range_pct   = features.get("nifty_range_pct", 0.5)

    # Compute a danger score [0-10]
    danger_score = 0

    if vix >= 22:
        danger_score += 4
    elif vix >= 17:
        danger_score += 2
    elif vix < 13:
        danger_score -= 1  # very calm

    if ema_trend == -1.0:
        danger_score += 2
    elif ema_trend == 1.0:
        danger_score -= 1

    if ad_ratio < 0.35:
        danger_score += 2
    elif ad_ratio > 0.65:
        danger_score -= 1

    if fii_flow < -0.4:
        danger_score += 1
    elif fii_flow > 0.4:
        danger_score -= 1

    if range_pct < 0.15:   # near 20-day low
        danger_score += 1

    if danger_score >= 5:
        return "DANGER"
    if danger_score >= 2:
        return "CAUTION"
    return "NORMAL"


# ---------------------------------------------------------------------------
# ML classifier (RandomForest — trained when enough labelled data exists)
# ---------------------------------------------------------------------------

class RegimeClassifier:
    """
    Wraps a scikit-learn RandomForest for regime classification.
    Falls back to rule-based if sklearn is unavailable or model not trained.
    """

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        self.model_path = model_path
        self._model = None
        self._sklearn_available = False
        self._try_load()

    def _try_load(self) -> None:
        try:
            import sklearn  # noqa: F401
            self._sklearn_available = True
            if self.model_path.exists():
                import joblib
                self._model = joblib.load(str(self.model_path))
                logger.info("RegimeClassifier: loaded model from %s.", self.model_path)
        except ImportError:
            logger.info("RegimeClassifier: scikit-learn not installed — rule-based only.")
        except Exception as exc:
            logger.warning("RegimeClassifier: failed to load model: %s", exc)

    def predict(self, features: Dict[str, float]) -> str:
        """Classify regime. Returns "NORMAL" | "CAUTION" | "DANGER"."""
        if self._model is None:
            return rule_based_regime(features)
        try:
            vec = features_to_vector(features).reshape(1, -1)
            pred = self._model.predict(vec)[0]
            return str(pred) if str(pred) in REGIMES else rule_based_regime(features)
        except Exception as exc:
            logger.warning("RegimeClassifier.predict failed: %s", exc)
            return rule_based_regime(features)

    def train(self, X: List[List[float]], y: List[str]) -> bool:
        """
        Train the RandomForest on labelled feature vectors.

        Args:
            X: list of feature vectors (one per trading day)
            y: list of regime labels ("NORMAL"/"CAUTION"/"DANGER")

        Returns True on success.
        """
        if not self._sklearn_available:
            logger.warning("RegimeClassifier.train: scikit-learn not installed. Skipping.")
            return False

        if len(X) < MIN_SAMPLES:
            logger.info("RegimeClassifier.train: only %d samples — need %d.", len(X), MIN_SAMPLES)
            return False

        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.preprocessing import LabelEncoder
            import joblib

            X_arr = np.array(X, dtype=np.float32)
            clf = RandomForestClassifier(
                n_estimators=200,
                max_depth=6,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=42,
            )
            clf.fit(X_arr, y)
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(clf, str(self.model_path))
            self._model = clf
            logger.info("RegimeClassifier: trained and saved (n=%d).", len(X))
            return True
        except Exception as exc:
            logger.error("RegimeClassifier.train failed: %s", exc)
            return False

    def feature_importances(self) -> Dict[str, float]:
        """Return feature importances if model is trained."""
        if self._model is None:
            return {}
        try:
            names = ["vix", "nifty_ema_trend", "nifty_range_pct", "ad_ratio", "fii_flow"]
            return dict(zip(names, self._model.feature_importances_.tolist()))
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Caching layer + public API
# ---------------------------------------------------------------------------

_classifier: RegimeClassifier | None = None
_cache: Dict[str, Any] = {}


def _load_cache() -> Dict[str, Any]:
    import json, time
    try:
        if CACHE_PATH.exists():
            with open(CACHE_PATH) as f:
                data = json.load(f)
            if time.time() - data.get("ts", 0) < CACHE_TTL_SECONDS:
                return data
    except Exception:
        pass
    return {}


def _save_cache(regime: str, features: Dict[str, float]) -> None:
    import json, time
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CACHE_PATH, "w") as f:
            json.dump({"regime": regime, "features": features, "ts": time.time()}, f)
    except Exception:
        pass


def get_classifier() -> RegimeClassifier:
    global _classifier
    if _classifier is None:
        _classifier = RegimeClassifier()
    return _classifier


def get_regime(use_cache: bool = True) -> str:
    """
    Public API — returns the current market regime.

    Caches the result for CACHE_TTL_SECONDS to avoid repeated API calls.
    """
    if use_cache:
        cached = _load_cache()
        if cached.get("regime"):
            logger.debug("RegimeClassifier: returning cached regime '%s'.", cached["regime"])
            return cached["regime"]

    features = fetch_regime_features()
    regime = get_classifier().predict(features)
    _save_cache(regime, features)
    logger.info("RegimeClassifier: current regime = %s (vix=%.1f ad=%.2f)",
                regime, features.get("vix", 0), features.get("ad_ratio", 0))
    return regime


def get_regime_with_features(use_cache: bool = True) -> Dict[str, Any]:
    """Return regime + all feature values in one call."""
    if use_cache:
        cached = _load_cache()
        if cached.get("regime"):
            return {"regime": cached["regime"], "features": cached.get("features", {})}

    features = fetch_regime_features()
    regime = get_classifier().predict(features)
    _save_cache(regime, features)
    return {"regime": regime, "features": features}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = get_regime_with_features(use_cache=False)
    print("Regime:", result["regime"])
    print("Features:", result["features"])
