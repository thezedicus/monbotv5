#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  market_oracle_extension.py  —  Module d'extension quantitatif avancé      ║
║  Market Oracle Pro v4.0  |  Python 3.9+  |  macOS / Linux                  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES TERMINAL MAC :                                                    ║
║                                                                              ║
║  # Test standalone (analyse SPY avec données réelles ou synthétiques)       ║
║  python3 market_oracle_extension.py                                          ║
║  python3 market_oracle_extension.py --symbol AAPL                           ║
║  python3 market_oracle_extension.py --symbol BTC-USD --demo                 ║
║                                                                              ║
║  # Analyse multi-actifs                                                      ║
║  python3 market_oracle_extension.py --watchlist SPY,QQQ,AAPL,NVDA          ║
║                                                                              ║
║  INSTALLATION :                                                              ║
║  pip3 install yfinance pandas numpy scipy plotly streamlit                  ║
║                                                                              ║
║  INTÉGRATION dans bot_v3.py :                                                ║
║    from market_oracle_extension import QuantEngine, render_quant_dashboard  ║
║    engine = QuantEngine()                                                    ║
║    result = engine.full_analysis(df)                                         ║
║    print(result["global_signal"])                                            ║
║                                                                              ║
║  INTÉGRATION dans streamlit_app.py :                                         ║
║    from market_oracle_extension import render_quant_dashboard               ║
║    render_quant_dashboard(df, symbol="SPY")                                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import math
import json
import logging
import argparse
import warnings
from datetime import datetime, timedelta
from typing   import Dict, List, Optional, Tuple, Any

import numpy  as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/oracle.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("MarketOracle")
for _n in ("yfinance","urllib3","peewee"): logging.getLogger(_n).setLevel(logging.CRITICAL)

# ── Dépendances optionnelles ──────────────────────────────────────────────────
try:
    from scipy.stats   import zscore, skew, kurtosis
    from scipy.signal  import find_peaks, argrelextrema
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False
    logger.warning("scipy non installé — pip3 install scipy")

try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False

try:
    import plotly.graph_objects as go
    import plotly.express       as px
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION GLOBALE
# ══════════════════════════════════════════════════════════════════════════════

MODULE_VERSION          = "4.0"
MODULE_NAME             = "Market Oracle Pro — Quant Extension"

MONTE_CARLO_SIMS        = 1000
MONTE_CARLO_HORIZON     = 30
FRACTAL_LOOKBACK        = 5
SUPPORT_RESISTANCE_BINS = 30
REGIME_LOOKBACK         = 63
KELLY_WIN_RATE          = 0.54
KELLY_RR_RATIO          = 2.2

SIGNAL_WEIGHTS = {
    "momentum":       1.5,
    "mean_reversion": 1.2,
    "rsi":            1.3,
    "macd":           1.4,
    "volume":         1.0,
    "volatility":     0.8,
    "fractal":        0.7,
    "monte_carlo":    1.1,
    "regime":         1.6,
    "macro_alignment":1.3,
}

# ══════════════════════════════════════════════════════════════════════════════
# §1  UTILITAIRES
# ══════════════════════════════════════════════════════════════════════════════

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return default

def safe_last(s: pd.Series, default: float = 0.0) -> float:
    if s is None or s.empty: return default
    return safe_float(s.dropna().iloc[-1] if not s.dropna().empty else default)

def round2(v, n=2): return round(safe_float(v), n)

def signal_color(sig: str) -> str:
    return {
        "STRONG BUY": "🟢🟢",
        "BUY":         "🟢",
        "NEUTRAL":     "⚪",
        "SELL":        "🔴",
        "STRONG SELL": "🔴🔴",
    }.get(sig, "⚪")

def normalize(s: pd.Series) -> pd.Series:
    std = s.std()
    return (s - s.mean()) / std if std > 0 else s * 0

def synthetic_ohlcv(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Génère des données OHLCV synthétiques réalistes pour les tests."""
    rng    = np.random.default_rng(seed)
    prices = 460 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    dr     = prices * 0.012
    dates  = pd.bdate_range(end=pd.Timestamp.today(), periods=n)[-n:]
    return pd.DataFrame({
        "Open":   prices * np.exp(rng.normal(0, 0.003, n)),
        "High":   prices + np.abs(dr) * rng.uniform(0.3, 0.7, n),
        "Low":    prices - np.abs(dr) * rng.uniform(0.3, 0.7, n),
        "Close":  prices,
        "Volume": rng.integers(30_000_000, 120_000_000, n).astype(int),
    }, index=dates)


# ══════════════════════════════════════════════════════════════════════════════
# §2  INDICATEURS TECHNIQUES DE BASE
# ══════════════════════════════════════════════════════════════════════════════

def sma(series: pd.Series, period: int = 20) -> pd.Series:
    return series.rolling(period, min_periods=1).mean()

def ema(series: pd.Series, period: int = 20) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def rma(series: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's smoothing (RMA) — utilisé pour ATR et RSI Wilder."""
    α   = 1 / period
    arr = series.values.astype(float)
    out = np.full(len(arr), np.nan)
    i0  = next((i for i, v in enumerate(arr) if not np.isnan(v)), None)
    if i0 is None: return pd.Series(out, index=series.index)
    out[i0] = arr[i0]
    for i in range(i0 + 1, len(arr)):
        if not np.isnan(arr[i]):
            out[i] = (out[i-1] if not np.isnan(out[i-1]) else arr[i]) * (1-α) + arr[i] * α
    return pd.Series(out, index=series.index)

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    Δ  = series.diff()
    ag = rma(Δ.clip(lower=0), period)
    al = rma((-Δ).clip(lower=0), period)
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))

def calculate_macd(series: pd.Series,
                    fast: int = 12, slow: int = 26,
                    signal_p: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    macd_line   = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal_p)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    H, L, pc = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat([H-L, (H-pc).abs(), (L-pc).abs()], axis=1).max(axis=1)
    return rma(tr, period)

def calculate_bbands(series: pd.Series, period: int = 20,
                      std_mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    m  = series.rolling(period).mean()
    s  = series.rolling(period).std(ddof=0)
    return m + std_mult * s, m, m - std_mult * s

def calculate_stochastic(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series]:
    hh = df["High"].rolling(period).max()
    ll = df["Low"].rolling(period).min()
    k  = 100 * (df["Close"] - ll) / (hh - ll).replace(0, np.nan)
    d  = k.rolling(3).mean()
    return k, d

def calculate_adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    H, L = df["High"], df["Low"]
    up   = H.diff()
    dn   = -L.diff()
    pdm  = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=H.index)
    ndm  = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=H.index)
    atr  = calculate_atr(df, period)
    pdi  = 100 * rma(pdm, period) / atr.replace(0, np.nan)
    ndi  = 100 * rma(ndm, period) / atr.replace(0, np.nan)
    dx   = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
    adx  = rma(dx, period)
    return adx, pdi, ndi

def calculate_vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).rolling(period).sum() / df["Volume"].rolling(period).sum().replace(0, np.nan)

def calculate_obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["Close"].diff().fillna(0)) * df["Volume"]).cumsum()

def calculate_cmf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    H, L, C, V = df["High"], df["Low"], df["Close"], df["Volume"]
    clv = ((C - L) - (H - C)) / (H - L).replace(0, np.nan)
    return (clv * V).rolling(period).sum() / V.rolling(period).sum().replace(0, np.nan)

def calculate_supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    atr  = calculate_atr(df, period)
    hl2  = (df["High"] + df["Low"]) / 2
    ub_r = hl2 + mult * atr
    lb_r = hl2 - mult * atr
    C    = df["Close"]
    trend= pd.Series(1, index=C.index, dtype=int)
    ub, lb = ub_r.copy(), lb_r.copy()
    for i in range(1, len(C)):
        ub.iloc[i] = ub_r.iloc[i] if (ub_r.iloc[i] < ub.iloc[i-1] or C.iloc[i-1] > ub.iloc[i-1]) else ub.iloc[i-1]
        lb.iloc[i] = lb_r.iloc[i] if (lb_r.iloc[i] > lb.iloc[i-1] or C.iloc[i-1] < lb.iloc[i-1]) else lb.iloc[i-1]
        if trend.iloc[i-1] == -1 and C.iloc[i] > ub.iloc[i]:   trend.iloc[i] = 1
        elif trend.iloc[i-1] == 1 and C.iloc[i] < lb.iloc[i]:  trend.iloc[i] = -1
        else:                                                    trend.iloc[i] = trend.iloc[i-1]
    return trend


# ══════════════════════════════════════════════════════════════════════════════
# §3  MODÈLES DE SIGNAL
# ══════════════════════════════════════════════════════════════════════════════

def momentum_signal(df: pd.DataFrame) -> Dict:
    """Signal momentum multi-période avec confirmation de tendance."""
    C        = df["Close"]
    sma10    = sma(C, 10)
    sma30    = sma(C, 30)
    sma50    = sma(C, 50)
    sma200   = sma(C, 200)

    mom5     = safe_float((C.iloc[-1] / C.iloc[-6]  - 1) * 100 if len(C) > 5  else 0)
    mom10    = safe_float((C.iloc[-1] / C.iloc[-11] - 1) * 100 if len(C) > 10 else 0)
    mom20    = safe_float((C.iloc[-1] / C.iloc[-21] - 1) * 100 if len(C) > 20 else 0)

    last     = safe_float(C.iloc[-1])
    s10_v    = safe_last(sma10);  s30_v = safe_last(sma30)
    s50_v    = safe_last(sma50);  s200_v = safe_last(sma200)

    score = 0
    details = []
    if s10_v > s30_v:              score += 1; details.append("SMA10 > SMA30 ✓")
    else:                          score -= 1
    if s30_v > s50_v:              score += 1; details.append("SMA30 > SMA50 ✓")
    else:                          score -= 1
    if last > s200_v:              score += 1; details.append("Prix > SMA200 ✓")
    else:                          score -= 1; details.append("Prix < SMA200 ✗")
    if mom10 > 2:                  score += 1; details.append(f"Mom10j +{mom10:.1f}% ✓")
    elif mom10 < -2:               score -= 1; details.append(f"Mom10j {mom10:.1f}% ✗")
    if mom20 > 4:                  score += 1
    elif mom20 < -4:               score -= 1

    sig = "BUY" if score >= 2 else "SELL" if score <= -2 else "NEUTRAL"
    return {
        "signal":    sig,
        "score":     score,
        "mom_5d":    round2(mom5),
        "mom_10d":   round2(mom10),
        "mom_20d":   round2(mom20),
        "details":   details,
    }


def mean_reversion_signal(df: pd.DataFrame) -> Dict:
    """Signal mean-reversion basé sur Bollinger + Z-score."""
    C        = df["Close"]
    bb_up, bb_mid, bb_dn = calculate_bbands(C, 20, 2.0)
    bb_up3, _, bb_dn3    = calculate_bbands(C, 20, 3.0)

    last   = safe_float(C.iloc[-1])
    bbu    = safe_last(bb_up);   bbm = safe_last(bb_mid);  bbd = safe_last(bb_dn)
    bb_pct = (last - bbd) / (bbu - bbd) if bbu != bbd else 0.5
    bb_w   = (bbu - bbd) / bbm if bbm else 0

    # Z-score
    z = 0.0
    if SCIPY_OK:
        tail = C.dropna().tail(60)
        if len(tail) > 10:
            z = safe_float(zscore(tail)[-1])
    else:
        tail = C.tail(60).dropna()
        if len(tail) > 10:
            mu  = tail.mean(); sigma = tail.std()
            z   = safe_float((last - mu) / sigma) if sigma > 0 else 0

    details = []
    if last < safe_last(bb_dn3):          sig = "STRONG BUY";  details.append("Prix sous BB 3σ — survente extrême ✓")
    elif bb_pct < 0.08:                    sig = "BUY";         details.append("Prix sous BB lower (2σ) ✓")
    elif last > safe_last(bb_up3):         sig = "STRONG SELL"; details.append("Prix sur BB 3σ — surachat extrême ✗")
    elif bb_pct > 0.92:                    sig = "SELL";        details.append("Prix sur BB upper (2σ) ✗")
    else:                                  sig = "NEUTRAL"

    if abs(z) > 2.5:
        details.append(f"Z-score extrême : {z:+.2f}")
    return {
        "signal":   sig,
        "bb_pct":   round2(bb_pct, 3),
        "bb_width": round2(bb_w, 4),
        "zscore":   round2(z),
        "details":  details,
    }


def rsi_signal(df: pd.DataFrame) -> Dict:
    """Signal RSI multi-période avec divergences."""
    C      = df["Close"]
    rsi14  = calculate_rsi(C, 14)
    rsi7   = calculate_rsi(C, 7)
    rsi21  = calculate_rsi(C, 21)

    r14    = safe_last(rsi14);  r7 = safe_last(rsi7);  r21 = safe_last(rsi21)

    # Divergence haussière / baissière
    div_bull = div_bear = False
    if len(C) > 10 and len(rsi14.dropna()) > 10:
        div_bull = bool(C.iloc[-1] < C.iloc[-6] and r14 > safe_last(rsi14.shift(5)))
        div_bear = bool(C.iloc[-1] > C.iloc[-6] and r14 < safe_last(rsi14.shift(5)))

    details = []
    if r14 < 20:      sig = "STRONG BUY";  details.append(f"RSI14={r14:.0f} — survente extrême ✓")
    elif r14 < 30:    sig = "BUY";         details.append(f"RSI14={r14:.0f} — survente ✓")
    elif r14 > 80:    sig = "STRONG SELL"; details.append(f"RSI14={r14:.0f} — surachat extrême ✗")
    elif r14 > 70:    sig = "SELL";        details.append(f"RSI14={r14:.0f} — surachat ✗")
    else:             sig = "NEUTRAL"

    if div_bull: details.append("Divergence RSI haussière détectée ✓")
    if div_bear: details.append("Divergence RSI baissière détectée ✗")

    return {
        "signal":    sig,
        "rsi_7":     round2(r7),
        "rsi_14":    round2(r14),
        "rsi_21":    round2(r21),
        "div_bull":  div_bull,
        "div_bear":  div_bear,
        "details":   details,
    }


def macd_signal(df: pd.DataFrame) -> Dict:
    """Signal MACD avec confirmation de croisement et force de tendance."""
    C                  = df["Close"]
    ml, sl, hist       = calculate_macd(C, 12, 26, 9)

    ml_v    = safe_last(ml);   sl_v = safe_last(sl);  hist_v = safe_last(hist)
    ml_prev = safe_last(ml.shift(1));  sl_prev = safe_last(sl.shift(1))
    hist_3  = [safe_float(hist.iloc[-i]) for i in range(1, 4)] if len(hist) >= 3 else [0,0,0]

    # Croisement
    cross_bull = ml_prev < sl_prev and ml_v > sl_v
    cross_bear = ml_prev > sl_prev and ml_v < sl_v

    # Force de la tendance (slope histogramme)
    hist_slope = hist_3[0] - hist_3[2] if len(hist_3) >= 3 else 0

    details = []
    if cross_bull:     sig = "BUY";  details.append("Croisement MACD haussier ✓")
    elif cross_bear:   sig = "SELL"; details.append("Croisement MACD baissier ✗")
    elif ml_v > sl_v:  sig = "BUY" if hist_slope > 0 else "NEUTRAL"
    else:              sig = "SELL" if hist_slope < 0 else "NEUTRAL"

    if abs(hist_v) > abs(hist_3[1]) * 1.3:
        details.append("Histogramme en accélération")

    return {
        "signal":      sig,
        "macd":        round2(ml_v, 5),
        "signal_line": round2(sl_v, 5),
        "histogram":   round2(hist_v, 5),
        "hist_slope":  round2(hist_slope, 5),
        "cross_bull":  cross_bull,
        "cross_bear":  cross_bear,
        "details":     details,
    }


def volume_signal(df: pd.DataFrame) -> Dict:
    """Analyse du volume : OBV, CMF, ratio, clustering."""
    C, V = df["Close"], df["Volume"]

    obv       = calculate_obv(df)
    obv_ema20 = ema(obv, 20)
    cmf       = calculate_cmf(df)

    vol_ratio = safe_float(V.iloc[-1] / V.rolling(20).mean().iloc[-1]) if len(V) > 20 else 1.0
    obv_v     = safe_last(obv);  obv_e = safe_last(obv_ema20)
    cmf_v     = safe_last(cmf)

    # Volume Z-score
    vol_z = 0.0
    if len(V) > 20:
        vm, vs = V.rolling(20).mean().iloc[-1], V.rolling(20).std().iloc[-1]
        vol_z  = safe_float((V.iloc[-1] - vm) / vs) if safe_float(vs) > 0 else 0.0

    details = []
    score   = 0
    if obv_v > obv_e:    score += 1; details.append("OBV > OBV_EMA20 (flux acheteur) ✓")
    else:                score -= 1
    if cmf_v > 0.10:     score += 1; details.append(f"CMF={cmf_v:.2f} — flux positif ✓")
    elif cmf_v < -0.10:  score -= 1; details.append(f"CMF={cmf_v:.2f} — flux négatif ✗")
    if vol_ratio > 1.5:  score += (1 if C.iloc[-1] > C.iloc[-2] else -1)
                         # Volume fort confirme direction
    sig = "BUY" if score >= 2 else "SELL" if score <= -2 else "NEUTRAL"
    return {
        "signal":     sig,
        "score":      score,
        "vol_ratio":  round2(vol_ratio),
        "vol_zscore": round2(vol_z),
        "cmf":        round2(cmf_v, 3),
        "obv_trend":  "UP" if obv_v > obv_e else "DOWN",
        "details":    details,
    }


def volatility_signal(df: pd.DataFrame) -> Dict:
    """
    Analyse de volatilité : GARCH approx., Parkinson, ATR, Keltner squeeze.
    Un squeeze (basses vol.) précède souvent un breakout = signal BUY en anticipation.
    """
    C, H, L = df["Close"], df["High"], df["Low"]

    atr    = calculate_atr(df, 14)
    atr_v  = safe_last(atr)
    atr_pct= atr_v / safe_float(C.iloc[-1]) * 100 if C.iloc[-1] else 0

    # Volatilité réalisée
    lr      = np.log(C / C.shift(1)).dropna()
    rv_5    = float(lr.tail(5).std()  * np.sqrt(252) * 100) if len(lr) >= 5  else 0
    rv_21   = float(lr.tail(21).std() * np.sqrt(252) * 100) if len(lr) >= 21 else 0

    # Parkinson volatility (OHLC)
    park_v = 0.0
    if len(H) >= 5:
        lh = np.log(H.tail(5) / L.tail(5).replace(0, np.nan))
        park_v = float(np.sqrt(1/(4*math.log(2)) * (lh**2).mean()) * np.sqrt(252) * 100)

    # Keltner Channel (squeeze = BB inside KC)
    bb_up, _, bb_dn = calculate_bbands(C, 20, 2.0)
    kc_m   = ema(C, 20)
    kc_up  = kc_m + 1.5 * atr
    kc_dn  = kc_m - 1.5 * atr
    squeeze= bool(safe_last(bb_up) < safe_last(kc_up) and safe_last(bb_dn) > safe_last(kc_dn))

    # ATR ratio (current vs 63-day average)
    atr_avg63 = safe_float(atr.rolling(63).mean().iloc[-1]) if len(atr) >= 63 else atr_v
    atr_ratio = atr_v / atr_avg63 if atr_avg63 > 0 else 1.0

    details = []
    sig     = "NEUTRAL"
    if squeeze:
        sig = "BUY"; details.append("⚡ SQUEEZE actif — breakout imminent potentiel ✓")
    elif atr_ratio < 0.7:
        sig = "BUY"; details.append("ATR bas (compression) — accumuler ✓")
    elif atr_ratio > 2.0:
        details.append(f"ATR élevé ({atr_ratio:.1f}x) — réduire exposition")
    if rv_5 > rv_21 * 1.5:
        details.append(f"Volatilité court-terme élevée (RV5={rv_5:.1f}%)")

    return {
        "signal":     sig,
        "atr_pct":    round2(atr_pct),
        "atr_ratio":  round2(atr_ratio),
        "rv_5d":      round2(rv_5),
        "rv_21d":     round2(rv_21),
        "parkinson":  round2(park_v),
        "squeeze":    squeeze,
        "details":    details,
    }


def fractal_signal(df: pd.DataFrame) -> Dict:
    """Détection de fractales de marché + supports/résistances clés."""
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    details  = []

    peaks    = valleys = []
    if SCIPY_OK and len(H) > 10:
        peaks, _   = find_peaks(H, distance=FRACTAL_LOOKBACK)
        valleys, _ = find_peaks(-L, distance=FRACTAL_LOOKBACK)
    else:
        # Fallback sans scipy
        for i in range(FRACTAL_LOOKBACK, len(H) - FRACTAL_LOOKBACK):
            if H[i] == max(H[i-FRACTAL_LOOKBACK:i+FRACTAL_LOOKBACK+1]):
                peaks = list(peaks) + [i]
            if L[i] == min(L[i-FRACTAL_LOOKBACK:i+FRACTAL_LOOKBACK+1]):
                valleys = list(valleys) + [i]

    # Niveaux supports / résistances (prix les plus touchés)
    price_range = np.linspace(min(L), max(H), SUPPORT_RESISTANCE_BINS)
    density     = np.zeros(len(price_range))
    for i, p in enumerate(price_range):
        density[i] = sum(1 for c in C if abs(c - p) / p < 0.005)
    top_idx     = np.argsort(density)[-4:][::-1]
    key_levels  = sorted([round(float(price_range[i]), 4) for i in top_idx])

    last_price  = float(C[-1])
    resistance  = [l for l in key_levels if l > last_price]
    support_lvl = [l for l in key_levels if l < last_price]

    # Signal : position par rapport aux niveaux clés
    sig = "NEUTRAL"
    if support_lvl:
        nearest_sup = max(support_lvl)
        if last_price - nearest_sup < last_price * 0.005:
            sig = "BUY"; details.append(f"Prix sur support clé ({nearest_sup:.2f}) ✓")
    if resistance:
        nearest_res = min(resistance)
        if nearest_res - last_price < last_price * 0.005:
            sig = "SELL"; details.append(f"Prix sur résistance clé ({nearest_res:.2f}) ✗")

    details.append(f"{len(peaks)} hauts fractaux / {len(valleys)} bas fractaux détectés")

    return {
        "signal":      sig,
        "peaks":       int(len(peaks)),
        "valleys":     int(len(valleys)),
        "key_levels":  key_levels,
        "resistances": resistance[:2],
        "supports":    support_lvl[-2:],
        "details":     details,
    }


def monte_carlo_signal(df: pd.DataFrame,
                         n_sims: int = MONTE_CARLO_SIMS,
                         horizon: int = MONTE_CARLO_HORIZON) -> Dict:
    """
    Monte-Carlo GBM + Jump Diffusion.
    Calcule la distribution des prix futurs et un signal probabiliste.
    """
    C          = df["Close"].dropna()
    last_price = safe_float(C.iloc[-1])

    lr     = np.log(C / C.shift(1)).dropna()
    mu     = float(lr.mean())
    sigma  = float(lr.std())

    # Jump diffusion paramètres
    jump_prob = 0.02
    jump_mu   = 0.0
    jump_sig  = 0.05

    rng = np.random.default_rng(2026)
    finals   = np.zeros(n_sims)
    paths    = np.zeros((n_sims, horizon))

    for s in range(n_sims):
        rand      = rng.normal(mu, sigma, horizon)
        jumps     = (rng.random(horizon) < jump_prob) * rng.normal(jump_mu, jump_sig, horizon)
        log_ret   = rand + jumps
        path      = last_price * np.exp(np.cumsum(log_ret))
        paths[s]  = path
        finals[s] = path[-1]

    ep  = float(np.mean(finals))
    p10 = float(np.percentile(finals, 10))
    p25 = float(np.percentile(finals, 25))
    p75 = float(np.percentile(finals, 75))
    p90 = float(np.percentile(finals, 90))

    prob_up   = float(np.mean(finals > last_price) * 100)
    prob_10pct= float(np.mean(finals > last_price * 1.10) * 100)
    max_dd    = float(np.mean([np.max(1 - paths[s]/pd.Series(paths[s]).cummax()) for s in range(min(100,n_sims))]))

    sig = ("STRONG BUY"  if prob_up > 70 else
           "BUY"          if prob_up > 55 else
           "STRONG SELL"  if prob_up < 30 else
           "SELL"          if prob_up < 45 else "NEUTRAL")

    return {
        "signal":           sig,
        "expected_price":   round2(ep),
        "expected_return":  round2((ep/last_price - 1)*100),
        "prob_up_pct":      round2(prob_up),
        "prob_10pct_gain":  round2(prob_10pct),
        "max_drawdown_est": round2(max_dd*100),
        "p10":              round2(p10),
        "p25":              round2(p25),
        "p75":              round2(p75),
        "p90":              round2(p90),
        "n_simulations":    n_sims,
        "horizon_days":     horizon,
    }


def regime_signal(df: pd.DataFrame) -> Dict:
    """Détection de régime de marché via clustering de volatilité + tendance."""
    C    = df["Close"].dropna()
    atr  = calculate_atr(df.dropna(), 14)
    adx, pdi, ndi = calculate_adx(df.dropna(), 14)

    adx_v  = safe_last(adx)
    pdi_v  = safe_last(pdi)
    ndi_v  = safe_last(ndi)
    rv21   = float(np.log(C/C.shift(1)).dropna().tail(21).std() * np.sqrt(252) * 100) if len(C) > 21 else 15

    ema20_v = safe_last(ema(C, 20))
    ema50_v = safe_last(ema(C, 50))
    ema200_v= safe_last(ema(C, 200))
    last    = safe_float(C.iloc[-1])

    st = calculate_supertrend(df.dropna())
    st_v = safe_last(st)

    bull = 0; bear = 0
    if adx_v > 25 and pdi_v > ndi_v: bull += 2
    if adx_v > 25 and ndi_v > pdi_v: bear += 2
    if ema20_v > ema50_v > ema200_v:  bull += 2
    if ema20_v < ema50_v < ema200_v:  bear += 2
    if last > ema200_v:               bull += 1
    else:                             bear += 1
    if st_v > 0:                      bull += 1
    else:                             bear += 1

    net = bull - bear
    if adx_v < 18 or abs(net) < 2:   regime = "RANGING"
    elif net >= 5:                     regime = "STRONG_BULL"
    elif net >= 2:                     regime = "BULL"
    elif net <= -5:                    regime = "STRONG_BEAR"
    else:                              regime = "BEAR"

    sig_map = {"STRONG_BULL":"BUY","BULL":"BUY","RANGING":"NEUTRAL",
                "BEAR":"SELL","STRONG_BEAR":"SELL"}
    return {
        "signal":        sig_map[regime],
        "regime":        regime,
        "adx":           round2(adx_v),
        "pdi":           round2(pdi_v),
        "ndi":           round2(ndi_v),
        "rv_21d":        round2(rv21),
        "bull_score":    bull,
        "bear_score":    bear,
        "supertrend":    int(st_v),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §4  SCORING GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def _score_one(signal: str) -> float:
    return {"STRONG BUY":2.0,"BUY":1.0,"NEUTRAL":0.0,"SELL":-1.0,"STRONG SELL":-2.0}.get(signal, 0.0)

def aggregate_signals(results: Dict[str, Dict],
                       weights: Dict[str, float] = None) -> Dict:
    """
    Agrège tous les signaux en un score composite pondéré.
    Retourne un signal global et une confiance 0-100%.
    """
    W     = weights or SIGNAL_WEIGHTS
    total = 0.0
    max_w = 0.0
    breakdown = {}

    for name, res in results.items():
        if res is None: continue
        sig = res.get("signal","NEUTRAL")
        w   = W.get(name, 1.0)
        sc  = _score_one(sig) * w
        total += sc
        max_w += 2.0 * w  # max possible (STRONG BUY)
        breakdown[name] = {"signal": sig, "weight": w, "contribution": round2(sc)}

    norm    = total / max_w if max_w > 0 else 0   # -1 à +1
    conf    = abs(norm) * 100

    if norm >= 0.60:     gsig = "STRONG BUY"
    elif norm >= 0.25:   gsig = "BUY"
    elif norm <= -0.60:  gsig = "STRONG SELL"
    elif norm <= -0.25:  gsig = "SELL"
    else:                gsig = "NEUTRAL"

    return {
        "global_signal":   gsig,
        "composite_score": round2(norm * 10, 2),  # -10 à +10
        "confidence_pct":  round2(conf),
        "breakdown":       breakdown,
        "total_models":    len([r for r in results.values() if r]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §5  RISK MANAGER INTÉGRÉ
# ══════════════════════════════════════════════════════════════════════════════

def compute_risk_metrics(df: pd.DataFrame, capital: float = 10_000) -> Dict:
    """
    Métriques de risque complètes : VaR, CVaR, Kelly, stops.
    """
    C    = df["Close"].dropna()
    lr   = np.log(C / C.shift(1)).dropna()
    atr  = calculate_atr(df.dropna(), 14)

    last    = safe_float(C.iloc[-1])
    atr_v   = safe_last(atr)
    mu      = float(lr.mean())
    sigma   = float(lr.std())

    # VaR paramétrique
    from scipy.stats import norm as sp_norm
    try:
        z95 = sp_norm.ppf(0.05); z99 = sp_norm.ppf(0.01)
    except Exception:
        z95 = -1.645; z99 = -2.326
    var95  = abs(mu + z95 * sigma) * 100
    var99  = abs(mu + z99 * sigma) * 100

    # CVaR (Expected Shortfall)
    sorted_r = lr.sort_values()
    n95      = max(1, int(len(sorted_r) * 0.05))
    cvar95   = abs(float(sorted_r.head(n95).mean())) * 100

    # Max drawdown
    cm  = (1 + lr).cumprod()
    pk  = cm.cummax()
    mdd = float(((cm - pk) / pk).min()) * 100

    # Sharpe / Sortino
    rf      = 0.04 / 252
    excess  = lr - rf
    sharpe  = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0
    dn      = excess[excess < 0]
    sortino = float(excess.mean() / dn.std() * np.sqrt(252)) if len(dn) > 0 and dn.std() > 0 else 0

    # Niveaux de trading
    stop_l  = round(last - atr_v * 2.0, 4)
    tp_l    = round(last + atr_v * 4.0, 4)
    stop_s  = round(last + atr_v * 2.0, 4)
    tp_s    = round(last - atr_v * 4.0, 4)

    # Kelly sizing
    wr     = KELLY_WIN_RATE
    rr     = KELLY_RR_RATIO
    kelly  = max(0, (wr * rr - (1-wr)) / rr) * 0.25  # 25% Kelly
    risk_amt = capital * 0.02  # 2% risque par trade
    stop_d   = abs(last - stop_l)
    size_r   = risk_amt / stop_d if stop_d > 0 else 0

    return {
        "price":        round(last, 4),
        "atr":          round(atr_v, 4),
        "atr_pct":      round2(atr_v/last*100),
        "var_95_pct":   round2(var95),
        "var_99_pct":   round2(var99),
        "cvar_95_pct":  round2(cvar95),
        "max_drawdown": round2(mdd),
        "sharpe_1y":    round2(sharpe),
        "sortino_1y":   round2(sortino),
        "stop_long":    stop_l,
        "tp_long":      tp_l,
        "stop_short":   stop_s,
        "tp_short":     tp_s,
        "rr_ratio":     round2(abs(tp_l-last)/max(abs(last-stop_l),1e-9)),
        "kelly_pct":    round2(kelly*100),
        "size_shares":  round(size_r, 4),
        "capital":      capital,
    }


# ══════════════════════════════════════════════════════════════════════════════
# §6  QUANT ENGINE — ORCHESTRATEUR
# ══════════════════════════════════════════════════════════════════════════════

class QuantEngine:
    """
    Moteur d'analyse quantitative complet.
    Orchestre tous les modèles de signal et produit un rapport structuré.

    Usage :
        engine = QuantEngine()
        result = engine.full_analysis(df, symbol="SPY", capital=10000)
        engine.print_report(result)
    """

    def full_analysis(self, df: pd.DataFrame,
                       symbol: str = "ACTIF",
                       capital: float = 10_000,
                       run_mc: bool = True,
                       n_mc: int = MONTE_CARLO_SIMS) -> Dict:
        """Analyse complète — tous les modèles."""
        if df is None or df.empty or len(df) < 30:
            return {"error": "DataFrame insuffisant (min 30 barres requises)"}

        # S'assurer que les colonnes sont bien nommées
        df = df.copy()
        df.columns = [c.strip().title() for c in df.columns]

        models = {}
        ts     = datetime.utcnow().isoformat()

        logger.info(f"[{symbol}] Analyse quant — {len(df)} barres")

        # Modèles de signal
        try: models["momentum"]       = momentum_signal(df)
        except Exception as e: logger.warning(f"Momentum: {e}"); models["momentum"] = None

        try: models["mean_reversion"] = mean_reversion_signal(df)
        except Exception as e: logger.warning(f"MeanRev: {e}"); models["mean_reversion"] = None

        try: models["rsi"]            = rsi_signal(df)
        except Exception as e: logger.warning(f"RSI: {e}"); models["rsi"] = None

        try: models["macd"]           = macd_signal(df)
        except Exception as e: logger.warning(f"MACD: {e}"); models["macd"] = None

        try: models["volume"]         = volume_signal(df)
        except Exception as e: logger.warning(f"Volume: {e}"); models["volume"] = None

        try: models["volatility"]     = volatility_signal(df)
        except Exception as e: logger.warning(f"Volatility: {e}"); models["volatility"] = None

        try: models["fractal"]        = fractal_signal(df)
        except Exception as e: logger.warning(f"Fractal: {e}"); models["fractal"] = None

        try: models["regime"]         = regime_signal(df)
        except Exception as e: logger.warning(f"Regime: {e}"); models["regime"] = None

        if run_mc:
            try: models["monte_carlo"] = monte_carlo_signal(df, n_sims=n_mc)
            except Exception as e: logger.warning(f"MC: {e}"); models["monte_carlo"] = None

        # Scoring global
        agg = aggregate_signals(models)

        # Métriques de risque
        try:    risk = compute_risk_metrics(df, capital)
        except Exception as e: logger.warning(f"Risk: {e}"); risk = {}

        return {
            "symbol":          symbol,
            "timestamp":       ts,
            "n_bars":          len(df),
            "global_signal":   agg["global_signal"],
            "composite_score": agg["composite_score"],
            "confidence_pct":  agg["confidence_pct"],
            "breakdown":       agg["breakdown"],
            "models":          models,
            "risk":            risk,
        }

    def print_report(self, result: Dict) -> None:
        """Affichage terminal structuré et coloré du rapport."""
        if "error" in result:
            print(f"\n  ❌ Erreur : {result['error']}")
            return

        sym  = result.get("symbol","ACTIF")
        gsig = result.get("global_signal","NEUTRAL")
        sc   = result.get("composite_score", 0)
        conf = result.get("confidence_pct", 0)
        ts   = result.get("timestamp","")[:16].replace("T"," ")

        print(f"\n{'═'*72}")
        print(f"  {signal_color(gsig)} MARKET ORACLE PRO — {sym} | {ts} UTC")
        print(f"{'═'*72}")
        print(f"  Signal Global  : {gsig:14s}  Score : {sc:+.1f}/10  Confiance : {conf:.0f}%")
        print(f"{'─'*72}")

        print(f"\n  MODÈLES INDIVIDUELS ({result.get('n_bars',0)} barres) :")
        print(f"  {'Modèle':20s} {'Signal':16s} {'Détails'}")
        print(f"  {'─'*68}")
        for name, data in (result.get("models") or {}).items():
            if not data: continue
            sig = data.get("signal","N/A")
            ic  = signal_color(sig)
            det = " | ".join((data.get("details") or [])[:2])[:45]
            print(f"  {name:20s} {ic}{sig:12s}  {det}")

        r = result.get("risk", {})
        if r:
            print(f"\n  RISQUE :")
            print(f"  ATR = {r.get('atr_pct',0):.2f}%  |  VaR 95% = {r.get('var_95_pct',0):.2f}%  "
                  f"|  Max DD = {r.get('max_drawdown',0):.2f}%")
            print(f"  Sharpe = {r.get('sharpe_1y',0):.2f}  |  Sortino = {r.get('sortino_1y',0):.2f}")
            print(f"  Stop Long = {r.get('stop_long',0):.4f}  |  TP Long = {r.get('tp_long',0):.4f}  "
                  f"|  R:R = {r.get('rr_ratio',0):.2f}x")
            print(f"  Kelly sizing = {r.get('kelly_pct',0):.1f}%  |  "
                  f"Taille = {r.get('size_shares',0):.4f} unités")

        mc = (result.get("models") or {}).get("monte_carlo")
        if mc:
            print(f"\n  MONTE-CARLO ({mc.get('n_simulations',0)} sim / {mc.get('horizon_days',30)}j) :")
            print(f"  Prob. hausse = {mc.get('prob_up_pct',50):.1f}%  |  "
                  f"Prix attendu = {mc.get('expected_price',0):.2f}  |  "
                  f"Retour attendu = {mc.get('expected_return',0):+.2f}%")
            print(f"  P10={mc.get('p10',0):.2f}  P25={mc.get('p25',0):.2f}  "
                  f"P75={mc.get('p75',0):.2f}  P90={mc.get('p90',0):.2f}")

        print(f"\n{'═'*72}")


# ══════════════════════════════════════════════════════════════════════════════
# §7  RENDER STREAMLIT  (appelé depuis streamlit_app.py)
# ══════════════════════════════════════════════════════════════════════════════

def render_quant_dashboard(df: pd.DataFrame,
                             symbol: str = "ACTIF",
                             capital: float = 10_000) -> None:
    """
    Section Streamlit complète pour l'analyse quantitative.
    Appeler depuis streamlit_app.py après import.
    """
    try:
        import streamlit as st
        import plotly.graph_objects as go
    except ImportError:
        print("pip3 install streamlit plotly")
        return

    engine = QuantEngine()
    result = engine.full_analysis(df, symbol=symbol, capital=capital)

    if "error" in result:
        st.error(f"Erreur analyse : {result['error']}")
        return

    gsig  = result["global_signal"]
    score = result["composite_score"]
    conf  = result["confidence_pct"]

    # ── Header signal global ──────────────────────────────────────────────────
    color_map = {
        "STRONG BUY":  "#30d158",
        "BUY":          "#34c759",
        "NEUTRAL":      "#636366",
        "SELL":         "#ff453a",
        "STRONG SELL":  "#ff375f",
    }
    sig_color = color_map.get(gsig, "#636366")

    st.markdown(f"""
    <div style="background:linear-gradient(135deg,#1c1c1e,#2c2c2e);
                border-radius:16px;padding:20px 24px;margin-bottom:16px;
                border:.5px solid #38383a;">
      <div style="font-size:13px;color:#636366;text-transform:uppercase;
                  letter-spacing:.5px;margin-bottom:6px">Signal Global</div>
      <div style="display:flex;align-items:center;gap:16px">
        <div style="font-size:28px;font-weight:700;color:{sig_color}">{gsig}</div>
        <div>
          <div style="font-size:13px;color:#ebebf599">Score composite : <b>{score:+.1f}/10</b></div>
          <div style="font-size:13px;color:#ebebf599">Confiance : <b>{conf:.0f}%</b></div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Métriques des modèles ─────────────────────────────────────────────────
    models = result.get("models", {})
    model_names = [k for k, v in models.items() if v]
    if model_names:
        cols = st.columns(min(len(model_names), 4))
        for i, name in enumerate(model_names):
            data = models[name]
            sig  = data.get("signal","N/A") if data else "N/A"
            col  = cols[i % 4]
            c    = color_map.get(sig, "#636366")
            col.markdown(f"""
            <div style="background:#1c1c1e;border-radius:12px;padding:12px;
                        border-left:3px solid {c};margin-bottom:8px">
              <div style="font-size:10px;color:#636366;text-transform:uppercase">{name}</div>
              <div style="font-size:16px;font-weight:700;color:{c}">{sig}</div>
            </div>
            """, unsafe_allow_html=True)

    # ── Chart principal ───────────────────────────────────────────────────────
    st.markdown("#### 📈 Analyse technique complète")
    if PLOTLY_OK:
        fig = go.Figure()
        C   = df["Close"]; H = df["High"]; L = df["Low"]

        # Candlesticks
        if "Open" in df.columns:
            fig.add_trace(go.Candlestick(
                x=df.index, open=df["Open"], high=H, low=L, close=C,
                name="OHLC",
                increasing_line_color="#30d158",
                decreasing_line_color="#ff453a",
                increasing_fillcolor="rgba(48,209,88,.3)",
                decreasing_fillcolor="rgba(255,69,58,.3)",
            ))
        else:
            fig.add_trace(go.Scatter(
                x=df.index, y=C, mode="lines", name="Close",
                line=dict(color="#0a84ff", width=1.5)
            ))

        # EMAs
        for period, color in [(20,"#ff9f0a"),(50,"#64d2ff"),(200,"#bf5af2")]:
            e = ema(C, period)
            fig.add_trace(go.Scatter(
                x=df.index, y=e, mode="lines", name=f"EMA{period}",
                line=dict(color=color, width=1, dash="dot"),
                opacity=0.8
            ))

        # Bollinger Bands
        bb_up_s, _, bb_dn_s = calculate_bbands(C, 20)
        fig.add_trace(go.Scatter(
            x=list(df.index) + list(df.index[::-1]),
            y=list(bb_up_s) + list(bb_dn_s[::-1]),
            fill="toself", fillcolor="rgba(10,132,255,.06)",
            line=dict(color="rgba(0,0,0,0)"), name="BB ±2σ"
        ))

        # Niveaux support/résistance
        frac = models.get("fractal") or {}
        for lvl in (frac.get("resistances") or []):
            fig.add_hline(y=lvl, line_dash="dash", line_color="#ff453a",
                           opacity=0.5, annotation_text=f"R {lvl:.2f}")
        for lvl in (frac.get("supports") or []):
            fig.add_hline(y=lvl, line_dash="dash", line_color="#30d158",
                           opacity=0.5, annotation_text=f"S {lvl:.2f}")

        # Stop / TP
        risk = result.get("risk", {})
        if risk.get("stop_long"):
            fig.add_hline(y=risk["stop_long"], line_color="#ff453a",
                           line_width=1.5, annotation_text="Stop Long")
        if risk.get("tp_long"):
            fig.add_hline(y=risk["tp_long"], line_color="#30d158",
                           line_width=1.5, annotation_text="TP Long")

        fig.update_layout(
            height=500, template="plotly_dark",
            paper_bgcolor="#000", plot_bgcolor="#1c1c1e",
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", y=1.02),
            xaxis_rangeslider_visible=False,
            font=dict(family="SF Pro Display, system-ui", color="#ebebf5"),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi_data = models.get("rsi") or {}
    if PLOTLY_OK:
        rsi_s = calculate_rsi(df["Close"], 14)
        fig2  = go.Figure()
        fig2.add_trace(go.Scatter(x=df.index, y=rsi_s, mode="lines",
                                   name="RSI 14", line=dict(color="#0a84ff", width=1.5)))
        fig2.add_hline(y=70, line_color="#ff453a", line_dash="dash", opacity=0.5)
        fig2.add_hline(y=30, line_color="#30d158", line_dash="dash", opacity=0.5)
        fig2.add_hrect(y0=70, y1=100, fillcolor="rgba(255,69,58,.08)", line_width=0)
        fig2.add_hrect(y0=0, y1=30, fillcolor="rgba(48,209,88,.08)", line_width=0)
        fig2.update_layout(
            height=150, template="plotly_dark",
            paper_bgcolor="#000", plot_bgcolor="#1c1c1e",
            margin=dict(l=0,r=0,t=20,b=0), showlegend=False,
            yaxis=dict(range=[0,100]),
            font=dict(color="#ebebf5"),
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Monte-Carlo ───────────────────────────────────────────────────────────
    mc = models.get("monte_carlo") or {}
    if mc and PLOTLY_OK:
        st.markdown("#### 🎲 Monte-Carlo — Distribution des prix dans 30j")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prob. hausse", f"{mc.get('prob_up_pct',50):.1f}%")
        c2.metric("Prix attendu", f"{mc.get('expected_price',0):.2f}")
        c3.metric("Retour attendu", f"{mc.get('expected_return',0):+.2f}%")
        c4.metric("Prob. +10%", f"{mc.get('prob_10pct_gain',0):.1f}%")

        fig3 = go.Figure()
        fig3.add_trace(go.Box(
            y=[mc.get("p10",0), mc.get("p25",0), mc.get("expected_price",0),
               mc.get("p75",0), mc.get("p90",0)],
            name="Distribution MC",
            marker_color="#0a84ff",
        ))
        fig3.update_layout(height=250, template="plotly_dark",
                            paper_bgcolor="#000", plot_bgcolor="#1c1c1e",
                            margin=dict(l=0,r=0,t=10,b=0))
        st.plotly_chart(fig3, use_container_width=True)

    # ── Risk metrics ──────────────────────────────────────────────────────────
    risk = result.get("risk", {})
    if risk:
        st.markdown("#### 🛡️ Métriques de risque")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("VaR 95% / jour",   f"{risk.get('var_95_pct',0):.2f}%")
        r2.metric("CVaR 95%",          f"{risk.get('cvar_95_pct',0):.2f}%")
        r3.metric("Sharpe 1 an",       f"{risk.get('sharpe_1y',0):.2f}")
        r4.metric("Sortino 1 an",      f"{risk.get('sortino_1y',0):.2f}")
        r5, r6, r7, r8 = st.columns(4)
        r5.metric("Max Drawdown",      f"{risk.get('max_drawdown',0):.2f}%")
        r6.metric("ATR %",             f"{risk.get('atr_pct',0):.2f}%")
        r7.metric("Stop Long",         f"{risk.get('stop_long',0):.4f}")
        r8.metric("TP Long (R:R 2x)", f"{risk.get('tp_long',0):.4f}")

    # ── JSON détaillé ─────────────────────────────────────────────────────────
    with st.expander("🔍 Détail JSON complet de l'analyse"):
        st.json({k:v for k,v in result.items() if k not in ("models",)})
        st.json({"models": {k: v for k, v in (result.get("models") or {}).items() if v}})


# ══════════════════════════════════════════════════════════════════════════════
# §8  CLI — EXÉCUTION DIRECTE
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"{MODULE_NAME} v{MODULE_VERSION} — Analyse quantitative standalone",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--symbol",    type=str, default="SPY",
                         help="Symbole Yahoo Finance (défaut: SPY)")
    parser.add_argument("--watchlist", type=str, default="",
                         help="Multi-actifs ex: SPY,QQQ,AAPL,BTC-USD")
    parser.add_argument("--demo",      action="store_true",
                         help="Utiliser des données synthétiques (pas d'internet)")
    parser.add_argument("--capital",   type=float, default=10_000,
                         help="Capital pour le sizing (défaut: 10000$)")
    parser.add_argument("--n-mc",      type=int, default=500,
                         help="Simulations Monte-Carlo (défaut: 500)")
    parser.add_argument("--no-mc",     action="store_true",
                         help="Ignorer Monte-Carlo (plus rapide)")
    parser.add_argument("--json",      action="store_true",
                         help="Sortie JSON brute")
    args = parser.parse_args()

    print(f"\n  {MODULE_NAME}  v{MODULE_VERSION}")
    print(f"  Python {sys.version.split()[0]}  |  {datetime.utcnow():%Y-%m-%d %H:%M} UTC\n")

    engine    = QuantEngine()
    all_syms  = ([s.strip() for s in args.watchlist.split(",") if s.strip()]
                  if args.watchlist else [args.symbol])

    for sym in all_syms:
        # Chargement des données
        df = None
        if not args.demo and YF_OK:
            try:
                print(f"  📡 Téléchargement {sym}...", end=" ", flush=True)
                raw = yf.download(sym, period="1y", interval="1d",
                                   progress=False, auto_adjust=True, timeout=15)
                if raw is not None and not raw.empty:
                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = raw.columns.droplevel(1)
                    raw.columns = [c.strip().title() for c in raw.columns]
                    df = raw.dropna(subset=["Close"])
                    print(f"OK ({len(df)} barres)")
                else:
                    print("vide → synthétique")
            except Exception as e:
                print(f"❌ {e} → synthétique")

        if df is None or df.empty or len(df) < 30:
            seed = abs(hash(sym)) % 100000
            df   = synthetic_ohlcv(500, seed=seed)
            print(f"  ⚠️  Données synthétiques utilisées pour {sym}")

        result = engine.full_analysis(
            df, symbol=sym, capital=args.capital,
            run_mc=not args.no_mc, n_mc=args.n_mc
        )

        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            engine.print_report(result)

        if len(all_syms) > 1:
            print()

    if len(all_syms) > 1:
        print(f"\n  ✅  {len(all_syms)} actifs analysés")


if __name__ == "__main__":
    main()
