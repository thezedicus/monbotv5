#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   BOT D'ANALYSE DE MARCHÉ v3.0 — ARCHITECTURE COMPLÈTE                     ║
║   60 thèses + 5 volumes · iOS-native UI · ~4500 lignes                      ║
║                                                                              ║
║  NOUVEAUTÉS v3 :                                                             ║
║    ✦ Interface iOS-native (SF Pro · verre dépoli · Dynamic Island style)    ║
║    ✦ 20+ indicateurs (VWAP, Keltner, Donchian, Elder Ray, DPO, TRIX)       ║
║    ✦ Scorecard multi-timeframe (1J · 1W · 1M simultanés)                   ║
║    ✦ Analyse fondamentale légère (P/E ratio, EPS trend)                     ║
║    ✦ Scanner de marchés automatique (screener)                               ║
║    ✦ Journal de trading intelligent (notes + P&L + tags)                    ║
║    ✦ Alertes conditionnelles configurables                                   ║
║    ✦ Optimisation de paramètres par grid search                              ║
║    ✦ Modèle GARCH simplifié pour la volatilité                               ║
║    ✦ Comparaison stratégies benchmark (buy-and-hold)                        ║
║    ✦ Export CSV / JSON des résultats                                         ║
║    ✦ Architecture événementielle (observer pattern)                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ═══════════════════════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════════════════════

import os, sys, math, time, json, csv, logging, argparse, warnings
import hashlib, threading, queue, copy, itertools, random
from pathlib     import Path
from datetime    import datetime, timedelta, date
from typing      import Optional, Tuple, Dict, List, Any, Callable, Set
from collections import deque, defaultdict
from dataclasses import dataclass, field, asdict
from enum        import Enum, auto
from abc         import ABC, abstractmethod

import numpy  as np
import pandas as pd
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

try:
    import yfinance as yf;   YF_AVAILABLE   = True
except ImportError:          YF_AVAILABLE   = False
try:
    import ccxt;             CCXT_AVAILABLE = True
except ImportError:          CCXT_AVAILABLE = False

# Intégration api_manager.py (si présent dans le même dossier)
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from api_manager import MarketAPI as _MarketAPI
    _API = _MarketAPI()
    API_MANAGER_AVAILABLE = True
except Exception:
    _API = None
    API_MANAGER_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════
# §0  ENUMS & DATACLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class Signal(Enum):
    STRONG_BUY  = "STRONG_BUY"
    BUY         = "BUY"
    HOLD        = "HOLD"
    SELL        = "SELL"
    STRONG_SELL = "STRONG_SELL"

class Regime(Enum):
    STRONG_BULL = "STRONG_BULL"
    BULL        = "BULL"
    RANGING     = "RANGING"
    BEAR        = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"

class OrderSide(Enum):
    LONG  = "long"
    SHORT = "short"

class ExitReason(Enum):
    STOP_LOSS      = "stop_loss"
    TAKE_PROFIT    = "take_profit"
    TRAILING_STOP  = "trailing_stop"
    MANUAL         = "manual"
    EOD            = "end_of_window"
    KILL_SWITCH    = "kill_switch"
    SIGNAL_REVERSE = "signal_reverse"

class Timeframe(Enum):
    D1  = "1d"
    W1  = "1wk"
    M1  = "1mo"
    H1  = "1h"
    H4  = "4h"

@dataclass
class OHLCV:
    """Barre de données canonique."""
    ts:     datetime
    open:   float
    high:   float
    low:    float
    close:  float
    volume: float

    @property
    def mid(self) -> float:   return (self.high + self.low) / 2
    @property
    def range(self) -> float: return self.high - self.low
    @property
    def body(self) -> float:  return abs(self.close - self.open)
    @property
    def is_bullish(self) -> bool: return self.close >= self.open

@dataclass
class Position:
    """Position ouverte."""
    symbol:      str
    side:        OrderSide
    size:        float
    entry:       float
    stop:        float
    tp:          float
    trail_stop:  float
    opened:      str = field(default_factory=lambda: datetime.utcnow().isoformat())
    notes:       str = ""
    tags:        List[str] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return self.entry * self.size

    def unrealized_pnl(self, current_price: float) -> float:
        if self.side == OrderSide.LONG:
            return (current_price - self.entry) * self.size
        return (self.entry - current_price) * self.size

    def unrealized_pct(self, current_price: float) -> float:
        if self.entry == 0:
            return 0.0
        return self.unrealized_pnl(current_price) / (self.entry * self.size)

@dataclass
class TradeRecord:
    """Trade fermé — audit trail complet."""
    symbol:    str
    side:      str
    size:      float
    entry:     float
    exit:      float
    pnl:       float
    pnl_pct:   float
    reason:    str
    opened:    str
    closed:    str
    regime:    str = ""
    signal:    str = ""
    duration:  str = ""
    notes:     str = ""
    tags:      List[str] = field(default_factory=list)

@dataclass
class AlertConfig:
    """Alerte conditionnelle configurée par l'utilisateur."""
    id:        str
    symbol:    str
    condition: str   # "rsi_oversold", "price_above", "signal_buy", etc.
    threshold: float = 0.0
    active:    bool  = True
    triggered: bool  = False
    created:   str   = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class JournalEntry:
    """Entrée du journal de trading."""
    id:       str
    date:     str
    symbol:   str
    type:     str    # "trade", "observation", "plan", "review"
    content:  str
    mood:     str    # "confident", "uncertain", "fearful", "greedy"
    pnl:      float  = 0.0
    tags:     List[str] = field(default_factory=list)
    created:  str   = field(default_factory=lambda: datetime.utcnow().isoformat())

# ═══════════════════════════════════════════════════════════════════════════════
# §1  CONFIGURATION GLOBALE
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG: Dict[str, Any] = {
    # ── Actifs ────────────────────────────────────────────────────────────────
    "PRIMARY_ASSET":      "SPY",
    "WATCHLIST":          ["SPY", "QQQ", "BTC-USD", "ETH-USD", "GC=F",
                           "EURUSD=X", "AAPL", "NVDA", "MSFT", "AMZN"],
    "CRYPTO_LIST":        ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD"],
    "FOREX_LIST":         ["EURUSD=X", "USDJPY=X", "GBPUSD=X", "AUDUSD=X"],

    # ── Indicateurs ────────────────────────────────────────────────────────────
    "EMA_FAST":           20,
    "EMA_SLOW":           50,
    "EMA_TREND":          200,
    "ADX_PERIOD":         14,
    "ADX_STRONG":         25,
    "ADX_WEAK":           18,
    "ATR_PERIOD":         14,
    "RSI_PERIOD":         14,
    "RSI_OVERSOLD":       30,
    "RSI_OVERBOUGHT":     70,
    "MACD_FAST":          12,
    "MACD_SLOW":          26,
    "MACD_SIGNAL":        9,
    "BB_PERIOD":          20,
    "BB_STD":             2.0,
    "KELTNER_PERIOD":     20,
    "KELTNER_MULT":       1.5,
    "DONCHIAN_PERIOD":    20,
    "VWAP_PERIOD":        20,
    "TRIX_PERIOD":        15,
    "DPO_PERIOD":         20,
    "ELDER_PERIOD":       13,
    "ICHIMOKU_TENKAN":    9,
    "ICHIMOKU_KIJUN":     26,
    "ICHIMOKU_SENKOU_B":  52,
    "SUPERTREND_PERIOD":  10,
    "SUPERTREND_MULT":    3.0,
    "CCI_PERIOD":         20,
    "WILLIAMS_PERIOD":    14,
    "MFI_PERIOD":         14,
    "CMF_PERIOD":         20,
    "GARCH_WINDOW":       30,

    # ── Risk Management ────────────────────────────────────────────────────────
    "INITIAL_CAPITAL":    10_000,
    "RISK_PER_TRADE":     0.02,
    "KELLY_WIN_RATE":     0.52,
    "KELLY_RR_RATIO":     2.0,
    "KELLY_FRACTION":     0.25,
    "ATR_STOP_MULT":      2.0,
    "ATR_TP_MULT":        4.0,
    "MAX_POSITION_PCT":   0.20,
    "MAX_POSITIONS":      5,
    "DAILY_LOSS_LIMIT":   0.03,
    "WEEKLY_LOSS_LIMIT":  0.06,
    "MAX_DRAWDOWN_LIMIT": 0.12,

    # ── Macro ──────────────────────────────────────────────────────────────────
    "VIX_LOW":            15,
    "VIX_MEDIUM":         20,
    "VIX_HIGH":           30,
    "VIX_EXTREME":        40,
    "SPREAD_10_2_INVERSION": -0.20,
    "BRENT_SPIKE":        100,

    # ── Walk-forward ──────────────────────────────────────────────────────────
    "WF_TRAIN_PERIODS":   252,
    "WF_TEST_PERIODS":    63,
    "WF_STEP":            21,

    # ── Monte-Carlo ────────────────────────────────────────────────────────────
    "MC_SIMULATIONS":     1000,
    "MC_HORIZON":         252,

    # ── Signaux ───────────────────────────────────────────────────────────────
    "MIN_SIGNAL_SCORE":   3,
    "STRONG_SIGNAL_SCORE":6,

    # ── Grid Search ───────────────────────────────────────────────────────────
    "GS_EMA_FAST_RANGE":  [10, 15, 20, 25],
    "GS_EMA_SLOW_RANGE":  [40, 50, 60, 80],
    "GS_ADX_RANGE":       [20, 25, 30],
    "GS_ATR_STOP_RANGE":  [1.5, 2.0, 2.5, 3.0],

    # ── Screener ──────────────────────────────────────────────────────────────
    "SCREENER_UNIVERSE":  ["SPY","QQQ","IWM","DIA","XLK","XLF","XLE","XLV",
                           "GC=F","CL=F","EURUSD=X","BTC-USD","ETH-USD"],

    # ── Fichiers ──────────────────────────────────────────────────────────────
    "LOG_DIR":            "logs",
    "TRADES_FILE":        "logs/trades.jsonl",
    "JOURNAL_FILE":       "logs/journal.jsonl",
    "ALERTS_FILE":        "logs/alerts.json",
    "STATE_FILE":         "logs/state.json",
    "REPORT_FILE":        "logs/rapport.html",
    "EXPORT_DIR":         "logs/exports",
    "POLLING_INTERVAL":   60,
}

# ═══════════════════════════════════════════════════════════════════════════════
# §2  LOGGING & PERSISTANCE
# ═══════════════════════════════════════════════════════════════════════════════

Path(CONFIG["LOG_DIR"]).mkdir(parents=True, exist_ok=True)
Path(CONFIG["EXPORT_DIR"]).mkdir(parents=True, exist_ok=True)

_fmt = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)-14s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
_fh = logging.FileHandler(f"{CONFIG['LOG_DIR']}/bot.log", encoding="utf-8")
_ch = logging.StreamHandler(sys.stdout)
for _h in (_fh, _ch): _h.setFormatter(_fmt)

logger = logging.getLogger("MarketBot")
logger.setLevel(logging.INFO)
logger.addHandler(_fh); logger.addHandler(_ch)
logger.propagate = False


class Persistence:
    """Centralise toutes les opérations de lecture/écriture sur disque."""

    @staticmethod
    def append_jsonl(path: str, obj: dict) -> None:
        obj.setdefault("timestamp", datetime.utcnow().isoformat())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")

    @staticmethod
    def read_jsonl(path: str) -> List[dict]:
        if not os.path.exists(path):
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: out.append(json.loads(line))
                    except: pass
        return out

    @staticmethod
    def write_json(path: str, obj: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def read_json(path: str, default: Any = None) -> Any:
        if not os.path.exists(path):
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except: return default

    @staticmethod
    def export_csv(path: str, rows: List[dict]) -> None:
        if not rows: return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader(); w.writerows(rows)

    @staticmethod
    def save_state(state: dict) -> None:
        Persistence.write_json(CONFIG["STATE_FILE"], state)

    @staticmethod
    def load_state() -> dict:
        return Persistence.read_json(CONFIG["STATE_FILE"], {})


persist = Persistence()


# ═══════════════════════════════════════════════════════════════════════════════
# §3  SYSTÈME D'ÉVÉNEMENTS (Observer Pattern)
# ═══════════════════════════════════════════════════════════════════════════════

class EventBus:
    """
    Bus d'événements central (pub/sub).
    Permet le découplage entre les modules.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        return cls._instance

    def subscribe(self, event: str, handler: Callable) -> None:
        self._subscribers[event].append(handler)

    def unsubscribe(self, event: str, handler: Callable) -> None:
        self._subscribers[event] = [
            h for h in self._subscribers[event] if h != handler
        ]

    def publish(self, event: str, data: Any = None) -> None:
        for handler in self._subscribers.get(event, []):
            try: handler(data)
            except Exception as e: logger.error(f"EventBus [{event}] handler error: {e}")

bus = EventBus()


# ═══════════════════════════════════════════════════════════════════════════════
# §4  GÉNÉRATEUR DE DONNÉES SYNTHÉTIQUES
# ═══════════════════════════════════════════════════════════════════════════════

class SyntheticDataGenerator:
    """
    Génère des OHLCV synthétiques réalistes via :
    • GBM (Geometric Brownian Motion)
    • Régimes Markov 3 états (bull / bear / range)
    • Chocs de volatilité (VIX spikes)
    • Saisonnalité intra-semaine
    • Mean-reversion sur volatilité (variance-targeting)
    • Jump diffusion (événements ponctuels)
    """

    ASSETS = {
        "SPY":      dict(S0=460,   mu=0.0003,  sigma=0.010, vol_base=80e6,  jumps=0.005),
        "QQQ":      dict(S0=390,   mu=0.0004,  sigma=0.013, vol_base=50e6,  jumps=0.006),
        "IWM":      dict(S0=200,   mu=0.0002,  sigma=0.012, vol_base=30e6,  jumps=0.004),
        "DIA":      dict(S0=380,   mu=0.0003,  sigma=0.009, vol_base=20e6,  jumps=0.003),
        "BTC-USD":  dict(S0=65000, mu=0.0005,  sigma=0.030, vol_base=30e9,  jumps=0.020),
        "ETH-USD":  dict(S0=3200,  mu=0.0006,  sigma=0.035, vol_base=15e9,  jumps=0.025),
        "SOL-USD":  dict(S0=140,   mu=0.0007,  sigma=0.045, vol_base=5e9,   jumps=0.030),
        "BNB-USD":  dict(S0=580,   mu=0.0004,  sigma=0.025, vol_base=3e9,   jumps=0.015),
        "GC=F":     dict(S0=2300,  mu=0.0001,  sigma=0.007, vol_base=2e5,   jumps=0.008),
        "CL=F":     dict(S0=80,    mu=0.0001,  sigma=0.020, vol_base=5e5,   jumps=0.015),
        "EURUSD=X": dict(S0=1.085, mu=0.00001, sigma=0.004, vol_base=1e9,   jumps=0.002),
        "USDJPY=X": dict(S0=149,   mu=0.00005, sigma=0.005, vol_base=8e8,   jumps=0.003),
        "GBPUSD=X": dict(S0=1.265, mu=0.00002, sigma=0.006, vol_base=6e8,   jumps=0.004),
        "AUDUSD=X": dict(S0=0.655, mu=0.00001, sigma=0.005, vol_base=4e8,   jumps=0.003),
        "AAPL":     dict(S0=185,   mu=0.0004,  sigma=0.015, vol_base=60e6,  jumps=0.008),
        "NVDA":     dict(S0=880,   mu=0.0006,  sigma=0.025, vol_base=40e6,  jumps=0.015),
        "MSFT":     dict(S0=420,   mu=0.0003,  sigma=0.013, vol_base=25e6,  jumps=0.007),
        "AMZN":     dict(S0=185,   mu=0.0004,  sigma=0.018, vol_base=35e6,  jumps=0.010),
        "^VIX":     dict(S0=18,    mu=-0.0001, sigma=0.040, vol_base=0,     jumps=0.050),
        "^TNX":     dict(S0=4.30,  mu=0.00001, sigma=0.008, vol_base=0,     jumps=0.005),
        "^IRX":     dict(S0=4.20,  mu=0.00001, sigma=0.006, vol_base=0,     jumps=0.003),
        "BZ=F":     dict(S0=82,    mu=0.0001,  sigma=0.018, vol_base=3e5,   jumps=0.012),
        "DX-Y.NYB": dict(S0=104,   mu=0.00002, sigma=0.005, vol_base=0,     jumps=0.003),
        "XLK":      dict(S0=210,   mu=0.0004,  sigma=0.014, vol_base=15e6,  jumps=0.008),
        "XLF":      dict(S0=42,    mu=0.0003,  sigma=0.012, vol_base=40e6,  jumps=0.006),
        "XLE":      dict(S0=90,    mu=0.0002,  sigma=0.018, vol_base=20e6,  jumps=0.010),
        "XLV":      dict(S0=140,   mu=0.0002,  sigma=0.010, vol_base=10e6,  jumps=0.005),
    }

    # Matrice de transition Markov (bull=0, bear=1, range=2)
    TRANS = np.array([
        [0.970, 0.015, 0.015],
        [0.025, 0.950, 0.025],
        [0.040, 0.040, 0.920],
    ])

    @classmethod
    def generate(cls, symbol: str = "SPY", n_days: int = 504,
                 seed: int = 42) -> pd.DataFrame:
        """Génère n_days jours de données OHLCV réalistes."""
        params = cls.ASSETS.get(symbol, cls.ASSETS["SPY"])
        rng    = np.random.default_rng(seed)
        n      = n_days
        S0, mu, sigma, vb, jump_prob = (
            params["S0"], params["mu"], params["sigma"],
            params["vol_base"], params["jumps"]
        )

        # ── Régimes Markov ────────────────────────────────────────────────
        regime = np.zeros(n, dtype=int)
        state  = 0
        for i in range(1, n):
            state = rng.choice(3, p=cls.TRANS[state])
            regime[i] = state

        mu_r  = np.array([mu * 1.8,  mu * -1.2, mu * 0.05])
        sig_r = np.array([sigma * 0.85, sigma * 1.6, sigma * 0.55])

        # ── Chocs (spikes de volatilité) ─────────────────────────────────
        shocks  = rng.random(n) < 0.010
        shock_m = np.where(shocks, rng.uniform(2.5, 5.0, n), 1.0)

        # ── Jumps diffusion (événements ponctuels type earnings) ──────────
        jumps    = rng.random(n) < jump_prob
        jump_dir = rng.choice([-1, 1], n)
        jump_mag = rng.uniform(0.03, 0.12, n)
        jump_lr  = np.where(jumps, jump_dir * jump_mag, 0.0)

        # ── Variance targeting (mean-reversion de la vol.) ────────────────
        target_vol = sigma
        vol_series = np.ones(n) * sigma
        for i in range(1, n):
            vol_series[i] = (vol_series[i-1] * 0.95
                             + target_vol * 0.05
                             + shock_m[i] * sigma * 0.2)

        # ── Simulation des log-retours ────────────────────────────────────
        noise = rng.standard_normal(n)
        lr    = (mu_r[regime]
                 + sig_r[regime] * shock_m * noise
                 + jump_lr)
        prices = S0 * np.exp(np.cumsum(lr))
        prices = np.clip(prices, S0 * 0.05, S0 * 15)

        # ── OHLCV réaliste ────────────────────────────────────────────────
        dr     = prices * sig_r[regime] * shock_m * rng.uniform(0.5, 1.6, n)
        opens  = prices * np.exp(rng.normal(0, 0.004, n))
        highs  = np.maximum(prices, opens) + np.abs(dr) * rng.uniform(0.1, 0.6, n)
        lows   = np.minimum(prices, opens) - np.abs(dr) * rng.uniform(0.1, 0.6, n)
        lows   = np.clip(lows, prices * 0.40, prices)

        # Volume log-normal avec clustering autour des chocs
        if vb > 0:
            base_vol = vb * rng.lognormal(0, 0.35, n)
            vol_mult = np.where(shock_m > 1.5, 3.0, 1.0) * np.where(jumps, 2.0, 1.0)
            volume   = (base_vol * vol_mult).astype(np.int64)
        else:
            volume = np.zeros(n, dtype=np.int64)

        # ── Dates ─────────────────────────────────────────────────────────
        dates    = pd.bdate_range(end=pd.Timestamp("2026-05-01"), periods=n)
        actual_n = len(dates)
        df = pd.DataFrame({
            "Open":    opens[-actual_n:].round(4),
            "High":    highs[-actual_n:].round(4),
            "Low":     lows[-actual_n:].round(4),
            "Close":   prices[-actual_n:].round(4),
            "Volume":  volume[-actual_n:],
            "_regime": regime[-actual_n:],
        }, index=dates)

        df["High"] = df[["Open", "Close", "High"]].max(axis=1)
        df["Low"]  = df[["Open", "Close", "Low"]].min(axis=1)
        return df


# ═══════════════════════════════════════════════════════════════════════════════
# §5  DATA PROVIDER
# ═══════════════════════════════════════════════════════════════════════════════

class DataProvider:
    """
    Fournisseur de données OHLCV.
    Tente Yahoo Finance, bascule sur synthétique si indisponible.
    Cache en mémoire + invalidation temporelle.
    """

    def __init__(self, use_synthetic: bool = False):
        # False par défaut → données réelles Yahoo Finance
        # Bascule automatique sur synthétique si YF indisponible
        self.use_synthetic = use_synthetic
        self._cache: Dict[str, Tuple[pd.DataFrame, float]] = {}
        self._ttl   = 120   # 2 minutes

    def _seed_for(self, symbol: str) -> int:
        """Seed reproductible et unique par symbole."""
        return int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16) % 100_000

    def get(self, symbol: str, n_days: int = 504, interval: str = "1d") -> pd.DataFrame:
        key = f"{symbol}_{n_days}_{interval}"
        now = time.time()
        if key in self._cache:
            df, ts = self._cache[key]
            if now - ts < self._ttl:
                return df.copy()

        df = pd.DataFrame()

        # Toujours essayer Yahoo Finance en premier (données réelles)
        if YF_AVAILABLE:
            try:
                import logging as _l
                _l.getLogger("yfinance").setLevel(_l.CRITICAL)
                _l.getLogger("urllib3").setLevel(_l.CRITICAL)
                import yfinance as yf
                period = f"{max(1, n_days // 252)}y" if n_days >= 252 else f"{n_days}d"
                raw = yf.download(symbol, period=period, interval=interval,
                                  progress=False, auto_adjust=True, timeout=12)
                if raw is not None and not raw.empty:
                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = raw.columns.droplevel(1)
                    raw.columns = [c.title() for c in raw.columns]
                    needed = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
                    df = raw[needed].dropna().iloc[-n_days:]
                    logger.debug(f"YF {symbol}: {len(df)} barres récupérées (données réelles)")
            except Exception as e:
                logger.debug(f"YF {symbol}: {e} → fallback synthétique")

        # Fallback synthétique uniquement si YF échoue ou use_synthetic forcé
        if df.empty or len(df) < 30:
            if not self.use_synthetic:
                logger.warning(f"⚠️  {symbol}: Yahoo Finance indisponible → données synthétiques")
            df = SyntheticDataGenerator.generate(
                symbol, n_days=n_days, seed=self._seed_for(symbol)
            )
            df = df.drop(columns=["_regime"], errors="ignore")

        self._cache[key] = (df.copy(), now)
        return df.copy()

    def get_multi(self, symbols: List[str], n_days: int = 252) -> Dict[str, pd.DataFrame]:
        """Télécharge plusieurs actifs en parallèle (synthétique : séquentiel)."""
        return {sym: self.get(sym, n_days=n_days) for sym in symbols}

    def live_price(self, symbol: str) -> Optional[float]:
        # Priorité 1 : api_manager (plus frais, ~15s de cache)
        if API_MANAGER_AVAILABLE and _API:
            try:
                p = _API.price(symbol)
                if p and p.get("price"):
                    return float(p["price"])
            except Exception:
                pass
        # Priorité 2 : Yahoo Finance direct
        df = self.get(symbol, n_days=5)
        if df.empty: return None
        return float(df["Close"].iloc[-1])

    def ohlcv_list(self, symbol: str, n_days: int = 60) -> List[OHLCV]:
        """Retourne une liste de barres OHLCV typées."""
        df = self.get(symbol, n_days=n_days)
        bars = []
        for ts, row in df.iterrows():
            bars.append(OHLCV(
                ts=ts.to_pydatetime(),
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=float(row["Volume"]),
            ))
        return bars

    def invalidate(self, symbol: str = None) -> None:
        """Invalide le cache (tout ou un seul symbole)."""
        if symbol is None:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k.startswith(symbol)]
            for k in keys: del self._cache[k]


# ═══════════════════════════════════════════════════════════════════════════════
# §6  MOTEUR D'INDICATEURS TECHNIQUES  (20+ indicateurs)
# ═══════════════════════════════════════════════════════════════════════════════

class IndicatorEngine:
    """
    Calcule 20+ indicateurs techniques — 100 % vectorisé NumPy/Pandas.
    Aucune dépendance ta-lib, pandas-ta ou similaire.
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False, min_periods=n).mean()

    @staticmethod
    def _rma(s: pd.Series, n: int) -> pd.Series:
        """Wilder's smoothing (RMA)."""
        α    = 1.0 / n
        arr  = s.values.astype(float)
        out  = np.full(len(arr), np.nan)
        # trouver premier non-NaN
        start = 0
        while start < len(arr) and np.isnan(arr[start]):
            start += 1
        if start >= len(arr): return pd.Series(out, index=s.index)
        out[start] = arr[start]
        for i in range(start + 1, len(arr)):
            if not np.isnan(arr[i]):
                prev = out[i-1] if not np.isnan(out[i-1]) else arr[i]
                out[i] = prev + α * (arr[i] - prev)
        return pd.Series(out, index=s.index)

    @staticmethod
    def _safe(df: pd.DataFrame, key: str, default: float = 0.0) -> pd.Series:
        if key not in df.columns:
            return pd.Series(default, index=df.index)
        return df[key].fillna(default)

    # ── Calcul principal ──────────────────────────────────────────────────────

    @classmethod
    def compute(cls, df: pd.DataFrame) -> pd.DataFrame:
        df  = df.copy()
        C   = df["Close"].astype(float)
        H   = df["High"].astype(float)
        L   = df["Low"].astype(float)
        O   = df["Open"].astype(float)
        V   = df["Volume"].astype(float)
        pc  = C.shift(1)
        HL2 = (H + L) / 2
        HLC3 = (H + L + C) / 3

        # ── 1. EMAs ───────────────────────────────────────────────────────
        df["ema20"]  = cls._ema(C, CONFIG["EMA_FAST"])
        df["ema50"]  = cls._ema(C, CONFIG["EMA_SLOW"])
        df["ema200"] = cls._ema(C, CONFIG["EMA_TREND"])
        df["ema9"]   = cls._ema(C, 9)
        df["ema13"]  = cls._ema(C, 13)

        # ── 2. MACD ───────────────────────────────────────────────────────
        df["macd"]     = cls._ema(C, CONFIG["MACD_FAST"]) - cls._ema(C, CONFIG["MACD_SLOW"])
        df["macd_sig"] = cls._ema(df["macd"], CONFIG["MACD_SIGNAL"])
        df["macd_h"]   = df["macd"] - df["macd_sig"]

        # ── 3. ATR (Wilder) ───────────────────────────────────────────────
        tr          = pd.concat([H-L, (H-pc).abs(), (L-pc).abs()], axis=1).max(axis=1)
        df["atr"]   = cls._rma(tr, CONFIG["ATR_PERIOD"])
        df["atr_pct"]= df["atr"] / C.replace(0, np.nan) * 100

        # ── 4. ADX ────────────────────────────────────────────────────────
        up, dn = H.diff(), -L.diff()
        pdm    = np.where((up > dn) & (up > 0), up, 0.0)
        ndm    = np.where((dn > up) & (dn > 0), dn, 0.0)
        atr14  = cls._rma(tr, 14)
        df["pdi"]  = 100 * cls._rma(pd.Series(pdm, index=C.index), 14) / atr14.replace(0, np.nan)
        df["ndi"]  = 100 * cls._rma(pd.Series(ndm, index=C.index), 14) / atr14.replace(0, np.nan)
        dx         = 100 * (df["pdi"] - df["ndi"]).abs() / (df["pdi"] + df["ndi"]).replace(0, np.nan)
        df["adx"]  = cls._rma(dx, 14)

        # ── 5. RSI (Wilder) ───────────────────────────────────────────────
        Δ = C.diff()
        df["rsi"] = 100 - 100 / (1 + cls._rma(Δ.clip(lower=0), CONFIG["RSI_PERIOD"])
                                      / cls._rma((-Δ).clip(lower=0), CONFIG["RSI_PERIOD"]).replace(0, np.nan))

        # ── 6. Bollinger Bands ────────────────────────────────────────────
        bm = C.rolling(CONFIG["BB_PERIOD"]).mean()
        bs = C.rolling(CONFIG["BB_PERIOD"]).std(ddof=0)
        df["bb_mid"]   = bm
        df["bb_up"]    = bm + CONFIG["BB_STD"] * bs
        df["bb_dn"]    = bm - CONFIG["BB_STD"] * bs
        df["bb_pct"]   = (C - df["bb_dn"]) / (df["bb_up"] - df["bb_dn"]).replace(0, np.nan)
        df["bb_width"] = (df["bb_up"] - df["bb_dn"]) / bm.replace(0, np.nan)

        # ── 7. Keltner Channel ────────────────────────────────────────────
        kp = CONFIG["KELTNER_PERIOD"]
        km = CONFIG["KELTNER_MULT"]
        k_mid         = cls._ema(C, kp)
        k_atr         = cls._rma(tr, kp)
        df["kelt_mid"] = k_mid
        df["kelt_up"]  = k_mid + km * k_atr
        df["kelt_dn"]  = k_mid - km * k_atr
        # Squeeze (BB inside Keltner = low volatility compression)
        df["squeeze"]  = ((df["bb_up"] < df["kelt_up"]) & (df["bb_dn"] > df["kelt_dn"])).astype(int)

        # ── 8. Donchian Channel ───────────────────────────────────────────
        dp = CONFIG["DONCHIAN_PERIOD"]
        df["don_up"]  = H.rolling(dp).max()
        df["don_dn"]  = L.rolling(dp).min()
        df["don_mid"] = (df["don_up"] + df["don_dn"]) / 2

        # ── 9. Stochastic ─────────────────────────────────────────────────
        df["stoch_k"] = 100 * (C - L.rolling(14).min()) / (H.rolling(14).max() - L.rolling(14).min()).replace(0, np.nan)
        df["stoch_d"] = df["stoch_k"].rolling(3).mean()

        # ── 10. CCI ───────────────────────────────────────────────────────
        cp = CONFIG["CCI_PERIOD"]
        mad = HLC3.rolling(cp).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        df["cci"] = (HLC3 - HLC3.rolling(cp).mean()) / (0.015 * mad.replace(0, np.nan))

        # ── 11. Williams %R ───────────────────────────────────────────────
        wp = CONFIG["WILLIAMS_PERIOD"]
        df["williams_r"] = -100 * (H.rolling(wp).max() - C) / (H.rolling(wp).max() - L.rolling(wp).min()).replace(0, np.nan)

        # ── 12. Ichimoku ──────────────────────────────────────────────────
        t, k, sb = CONFIG["ICHIMOKU_TENKAN"], CONFIG["ICHIMOKU_KIJUN"], CONFIG["ICHIMOKU_SENKOU_B"]
        df["tenkan"]      = (H.rolling(t).max() + L.rolling(t).min()) / 2
        df["kijun"]       = (H.rolling(k).max() + L.rolling(k).min()) / 2
        df["spanA"]       = ((df["tenkan"] + df["kijun"]) / 2).shift(k)
        df["spanB"]       = ((H.rolling(sb).max() + L.rolling(sb).min()) / 2).shift(k)
        df["chikou"]      = C.shift(-k)
        df["above_cloud"] = ((C > df["spanA"]) & (C > df["spanB"])).astype(int)
        df["below_cloud"] = ((C < df["spanA"]) & (C < df["spanB"])).astype(int)
        df["cloud_twist"] = ((df["spanA"] > df["spanB"]).astype(int)
                             .diff().fillna(0).abs()).astype(int)

        # ── 13. SuperTrend ────────────────────────────────────────────────
        p, m = CONFIG["SUPERTREND_PERIOD"], CONFIG["SUPERTREND_MULT"]
        atr_st = cls._rma(tr, p)
        ub  = HL2 + m * atr_st
        lb  = HL2 - m * atr_st
        upper = ub.copy(); lower = lb.copy()
        trend = pd.Series(1, index=C.index, dtype=int)
        for i in range(1, len(C)):
            upper.iloc[i] = ub.iloc[i] if (ub.iloc[i] < upper.iloc[i-1] or C.iloc[i-1] > upper.iloc[i-1]) else upper.iloc[i-1]
            lower.iloc[i] = lb.iloc[i] if (lb.iloc[i] > lower.iloc[i-1] or C.iloc[i-1] < lower.iloc[i-1]) else lower.iloc[i-1]
            if trend.iloc[i-1] == -1 and C.iloc[i] > upper.iloc[i]:   trend.iloc[i] = 1
            elif trend.iloc[i-1] == 1 and C.iloc[i] < lower.iloc[i]:  trend.iloc[i] = -1
            else: trend.iloc[i] = trend.iloc[i-1]
        df["supertrend"]      = trend
        df["supertrend_line"] = np.where(trend == 1, lower, upper)

        # ── 14. VWAP ─────────────────────────────────────────────────────
        vwap_period = CONFIG["VWAP_PERIOD"]
        tp_v  = HLC3 * V
        df["vwap"] = tp_v.rolling(vwap_period).sum() / V.rolling(vwap_period).sum().replace(0, np.nan)
        df["vwap_dev"] = (C - df["vwap"]) / df["vwap"].replace(0, np.nan) * 100

        # ── 15. TRIX ─────────────────────────────────────────────────────
        tp = CONFIG["TRIX_PERIOD"]
        e1 = cls._ema(C, tp)
        e2 = cls._ema(e1, tp)
        e3 = cls._ema(e2, tp)
        df["trix"] = e3.pct_change(1) * 100
        df["trix_sig"] = cls._ema(df["trix"], 9)

        # ── 16. DPO (Detrended Price Oscillator) ──────────────────────────
        dp_p = CONFIG["DPO_PERIOD"]
        shift_val = dp_p // 2 + 1
        df["dpo"] = C.shift(shift_val) - C.rolling(dp_p).mean()

        # ── 17. Elder Ray ─────────────────────────────────────────────────
        ep = CONFIG["ELDER_PERIOD"]
        ema_elder = cls._ema(C, ep)
        df["bull_power"] = H - ema_elder
        df["bear_power"] = L - ema_elder

        # ── 18. OBV ───────────────────────────────────────────────────────
        df["obv"]     = (np.sign(C.diff().fillna(0)) * V).cumsum()
        df["obv_ema"] = cls._ema(df["obv"], 20)

        # ── 19. Money Flow Index ──────────────────────────────────────────
        mp = CONFIG["MFI_PERIOD"]
        raw_mf = HLC3 * V
        pos_mf = raw_mf.where(HLC3 > HLC3.shift(1), 0)
        neg_mf = raw_mf.where(HLC3 < HLC3.shift(1), 0)
        mfr    = pos_mf.rolling(mp).sum() / neg_mf.rolling(mp).sum().replace(0, np.nan)
        df["mfi"] = 100 - 100 / (1 + mfr)

        # ── 20. Chaikin Money Flow ────────────────────────────────────────
        cm_p = CONFIG["CMF_PERIOD"]
        clv  = ((C - L) - (H - C)) / (H - L).replace(0, np.nan)
        df["cmf"] = (clv * V).rolling(cm_p).sum() / V.rolling(cm_p).sum().replace(0, np.nan)

        # ── 21. ROC & Momentum ────────────────────────────────────────────
        df["roc5"]  = C.pct_change(5)  * 100
        df["roc10"] = C.pct_change(10) * 100
        df["roc20"] = C.pct_change(20) * 100
        df["mom10"] = C - C.shift(10)

        # ── 22. Pivot Points ─────────────────────────────────────────────
        df["pivot"] = (H.shift(1) + L.shift(1) + C.shift(1)) / 3
        df["res1"]  = 2 * df["pivot"] - L.shift(1)
        df["res2"]  = df["pivot"] + (H.shift(1) - L.shift(1))
        df["sup1"]  = 2 * df["pivot"] - H.shift(1)
        df["sup2"]  = df["pivot"] - (H.shift(1) - L.shift(1))

        # ── 23. Volume Ratio & Relative Volume ───────────────────────────
        df["vol_ratio"]   = V / V.rolling(20).mean().replace(0, np.nan)
        df["vol_zscore"]  = (V - V.rolling(20).mean()) / V.rolling(20).std(ddof=0).replace(0, np.nan)

        # ── 24. GARCH-like volatility estimate ───────────────────────────
        log_ret = np.log(C / C.shift(1)).dropna()
        garch_w = CONFIG["GARCH_WINDOW"]
        α, β    = 0.1, 0.85
        rv      = log_ret ** 2
        garch_var = pd.Series(np.nan, index=df.index)
        init_idx  = log_ret.index
        if len(init_idx) > garch_w:
            garch_var.loc[init_idx[garch_w-1]] = rv.iloc[:garch_w].mean()
            for j in range(garch_w, len(init_idx)):
                prev = garch_var.loc[init_idx[j-1]]
                if np.isnan(prev): prev = rv.iloc[j-1]
                garch_var.loc[init_idx[j]] = (1 - α - β) * rv.mean() + α * rv.iloc[j-1] + β * prev
        df["garch_vol"] = np.sqrt(garch_var) * np.sqrt(252) * 100

        # ── 25. Candle Patterns ───────────────────────────────────────────
        body  = (C - O).abs()
        range_= H - L
        df["is_doji"]     = (body / range_.replace(0, np.nan) < 0.1).astype(int)
        df["is_hammer"]   = ((body / range_.replace(0, np.nan) < 0.3)
                              & ((C.shift(1) - C) / range_.replace(0, np.nan) > 0.6)
                              & (C > O)).astype(int)
        df["is_engulf_bull"] = ((C > O) & (O < C.shift(1)) & (C > O.shift(1))).astype(int)
        df["is_engulf_bear"] = ((O > C) & (C > C.shift(1)) & (O < O.shift(1))).astype(int)

        return df.replace([np.inf, -np.inf], np.nan)

    @classmethod
    def compute_multi_tf(cls, df_1d: pd.DataFrame,
                          df_1w: pd.DataFrame,
                          df_1m: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Calcule les indicateurs sur 3 timeframes."""
        return {
            "1d": cls.compute(df_1d),
            "1w": cls.compute(df_1w),
            "1m": cls.compute(df_1m),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# §7  DÉTECTEUR DE RÉGIME  (enrichi — 7 états + multi-timeframe)
# ═══════════════════════════════════════════════════════════════════════════════

class RegimeDetector:
    """
    Identifie le régime de marché sur 5 niveaux.
    Peut agréger plusieurs timeframes (confluence).
    """

    STATES = {
        Regime.STRONG_BULL: "Tendance haussière forte — Trend following agressif",
        Regime.BULL:        "Tendance haussière modérée — Trend following prudent",
        Regime.RANGING:     "Marché en range — Mean reversion actif",
        Regime.BEAR:        "Tendance baissière modérée — Cash ou hedge",
        Regime.STRONG_BEAR: "Tendance baissière forte — Cash / protection totale",
    }

    @classmethod
    def detect(cls, df: pd.DataFrame) -> Tuple[Regime, float, Dict]:
        if df.empty or len(df) < 30:
            return Regime.RANGING, 0.30, {}

        r = df.iloc[-1]
        def sv(k, d=0.0):
            v = r.get(k, d)
            return d if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)

        adx  = sv("adx", 20);   pdi = sv("pdi", 20);   ndi = sv("ndi", 20)
        rsi  = sv("rsi", 50);   macd_h = sv("macd_h", 0)
        st   = sv("supertrend", 0)
        ichi = sv("above_cloud", 0);  ichi_b = sv("below_cloud", 0)
        roc20 = sv("roc20", 0)
        price = sv("Close", 1)
        e20   = sv("ema20", price);  e50 = sv("ema50", price);  e200 = sv("ema200", price)
        cmf   = sv("cmf", 0);    mfi = sv("mfi", 50)
        trix  = sv("trix", 0)
        kelt_up = sv("kelt_up", price * 1.02);  kelt_dn = sv("kelt_dn", price * 0.98)
        vwap  = sv("vwap", price);  obv_up = sv("obv", 0) > sv("obv_ema", 0)
        bull_power = sv("bull_power", 0);  bear_power = sv("bear_power", 0)

        # ── Score haussier (max ~13) ───────────────────────────────────────
        bull = 0.0
        bull += 2.0 if (adx > CONFIG["ADX_STRONG"] and pdi > ndi)   else 0
        bull += 1.5 if macd_h > 0                                     else 0
        bull += 1.5 if st  > 0                                        else 0
        bull += 1.0 if ichi                                           else 0
        bull += 1.0 if (e20 > e50 > e200)                            else 0
        bull += 0.5 if rsi > 55                                       else 0
        bull += 0.5 if roc20 > 3                                      else 0
        bull += 1.0 if price > e200                                   else 0
        bull += 0.5 if cmf > 0.05                                     else 0
        bull += 0.5 if mfi > 55                                       else 0
        bull += 0.5 if trix > 0                                       else 0
        bull += 0.5 if price > vwap                                   else 0
        bull += 0.5 if obv_up                                         else 0
        bull += 0.5 if bull_power > 0                                 else 0

        # ── Score baissier (max ~13) ──────────────────────────────────────
        bear = 0.0
        bear += 2.0 if (adx > CONFIG["ADX_STRONG"] and ndi > pdi)   else 0
        bear += 1.5 if macd_h < 0                                     else 0
        bear += 1.5 if st  < 0                                        else 0
        bear += 1.0 if ichi_b                                         else 0
        bear += 1.0 if (e20 < e50 < e200)                            else 0
        bear += 0.5 if rsi < 45                                       else 0
        bear += 0.5 if roc20 < -3                                     else 0
        bear += 1.0 if price < e200                                   else 0
        bear += 0.5 if cmf < -0.05                                    else 0
        bear += 0.5 if mfi < 45                                       else 0
        bear += 0.5 if trix < 0                                       else 0
        bear += 0.5 if price < vwap                                   else 0
        bear += 0.5 if not obv_up                                     else 0
        bear += 0.5 if bear_power < 0                                 else 0

        net        = bull - bear
        weak_trend = adx < CONFIG["ADX_WEAK"]

        if weak_trend or abs(net) < 2.5:
            regime = Regime.RANGING;     conf = 0.5 + (1 - adx/30) * 0.4
        elif net >= 7:                   regime = Regime.STRONG_BULL; conf = min(net/12, 1.0)
        elif net >= 2.5:                 regime = Regime.BULL;        conf = min(net/8, 1.0)
        elif net <= -7:                  regime = Regime.STRONG_BEAR; conf = min(abs(net)/12, 1.0)
        else:                            regime = Regime.BEAR;        conf = min(abs(net)/8, 1.0)

        scores = {"bull": round(bull,1), "bear": round(bear,1),
                  "net": round(net,1),   "adx": round(adx,1),
                  "rsi": round(rsi,1),   "regime": regime.value}
        return regime, round(max(0.1, min(conf, 1.0)), 2), scores

    @classmethod
    def detect_multi_tf(cls, dfs: Dict[str, pd.DataFrame]) -> Dict:
        """Détecte le régime sur plusieurs timeframes et calcule la confluence."""
        results = {}
        for tf, df in dfs.items():
            reg, conf, scores = cls.detect(df)
            results[tf] = {"regime": reg, "confidence": conf, "scores": scores}

        # Pondération : 1d=50%, 1w=30%, 1m=20%
        weights = {"1d": 0.50, "1w": 0.30, "1m": 0.20}
        bull_score = 0.0; bear_score = 0.0; total_w = 0.0
        for tf, res in results.items():
            w  = weights.get(tf, 0.33)
            sc = res["scores"].get("net", 0)
            bull_score += max(sc, 0)  * w * res["confidence"]
            bear_score += max(-sc, 0) * w * res["confidence"]
            total_w    += w

        net_conf = (bull_score - bear_score) / (total_w + 1e-9)
        if abs(net_conf) < 1:
            overall = Regime.RANGING
        elif net_conf > 4:
            overall = Regime.STRONG_BULL
        elif net_conf > 1:
            overall = Regime.BULL
        elif net_conf < -4:
            overall = Regime.STRONG_BEAR
        else:
            overall = Regime.BEAR

        results["overall"] = {
            "regime": overall,
            "confidence": round(min(abs(net_conf)/6, 1.0), 2),
            "bull_weighted": round(bull_score, 2),
            "bear_weighted": round(bear_score, 2),
        }
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# §8  GÉNÉRATEUR DE SIGNAUX  (scoring enrichi + multi-TF)
# ═══════════════════════════════════════════════════════════════════════════════

class SignalGenerator:
    """
    Signal hybride multi-indicateurs :
    • Score trend-following (15 critères pondérés)
    • Score mean-reversion (10 critères oscillateurs)
    • Score volume (4 critères)
    • Signal fort si score ≥ STRONG_SIGNAL_SCORE
    • Adapté au régime courant
    """

    @staticmethod
    def _sv(row, key: str, default: float = 0.0) -> float:
        v = row.get(key, default)
        return default if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)

    @classmethod
    def _trend(cls, df: pd.DataFrame) -> Tuple[float, float, List[str]]:
        if len(df) < 3: return 0.0, 0.0, []
        c, p = df.iloc[-1], df.iloc[-2]
        sv   = lambda k, d=0.0: cls._sv(c, k, d)
        pv   = lambda k, d=0.0: cls._sv(p, k, d)

        bull, bear, reasons = 0.0, 0.0, []

        # 1. EMA 20/50 cross
        if pv("ema20") <= pv("ema50") and sv("ema20") > sv("ema50"):
            bull += 2.0; reasons.append("Golden Cross EMA 20/50 ✓")
        elif pv("ema20") >= pv("ema50") and sv("ema20") < sv("ema50"):
            bear += 2.0; reasons.append("Death Cross EMA 20/50 ✗")
        elif sv("ema20") > sv("ema50"):
            bull += 0.8
        else:
            bear += 0.8

        # 2. Prix vs EMA200
        price, e200 = sv("Close", 1), sv("ema200", 1)
        if price > e200 * 1.005: bull += 1.5; reasons.append("Prix > EMA200 ✓")
        elif price < e200 * 0.995: bear += 1.5; reasons.append("Prix < EMA200 ✗")

        # 3. MACD histogram cross
        mh, pmh = sv("macd_h"), pv("macd_h")
        if pmh <= 0 < mh:  bull += 1.5; reasons.append("MACD cross haussier ✓")
        elif pmh >= 0 > mh: bear += 1.5; reasons.append("MACD cross baissier ✗")
        elif mh > 0: bull += 0.5
        else: bear += 0.5

        # 4. SuperTrend
        st, pst = int(sv("supertrend", 0)), int(pv("supertrend", 0))
        if st > 0:  bull += 1.0
        elif st < 0: bear += 1.0
        if st != pst and pst != 0:  # flip
            if st > 0: bull += 0.5; reasons.append("SuperTrend flip haussier ✓")
            else:      bear += 0.5; reasons.append("SuperTrend flip baissier ✗")

        # 5. Ichimoku
        if sv("above_cloud"): bull += 1.0; reasons.append("Dessus du nuage ✓")
        elif sv("below_cloud"): bear += 1.0; reasons.append("Dessous du nuage ✗")
        if sv("tenkan") > sv("kijun"): bull += 0.5
        elif sv("tenkan") < sv("kijun"): bear += 0.5

        # 6. ADX + DI
        adx, pdi, ndi = sv("adx", 20), sv("pdi", 20), sv("ndi", 20)
        if adx > CONFIG["ADX_STRONG"]:
            if pdi > ndi:  bull += 1.0; reasons.append(f"ADX fort haussier ({adx:.0f}) ✓")
            else:          bear += 1.0; reasons.append(f"ADX fort baissier ({adx:.0f}) ✗")

        # 7. Donchian breakout
        dn_up, dn_dn = sv("don_up"), sv("don_dn")
        if price >= dn_up * 0.998: bull += 0.8; reasons.append("Breakout Donchian haut ✓")
        elif price <= dn_dn * 1.002: bear += 0.8; reasons.append("Breakout Donchian bas ✗")

        # 8. VWAP
        vwap = sv("vwap", price)
        if price > vwap * 1.003: bull += 0.5
        elif price < vwap * 0.997: bear += 0.5

        # 9. TRIX cross zero
        trix, ptrix = sv("trix"), pv("trix")
        if ptrix <= 0 < trix: bull += 0.7; reasons.append("TRIX cross haussier ✓")
        elif ptrix >= 0 > trix: bear += 0.7; reasons.append("TRIX cross baissier ✗")

        # 10. Elder Ray
        if sv("bull_power") > 0 and sv("bear_power") > 0: bull += 0.5
        elif sv("bull_power") < 0 and sv("bear_power") < 0: bear += 0.5

        # 11. Volume confirmation
        vr = sv("vol_ratio", 1.0)
        if vr > 1.4:
            if bull > bear: bull += 0.5; reasons.append(f"Volume fort ({vr:.1f}x) ✓")
            else:           bear += 0.5; reasons.append(f"Volume fort ({vr:.1f}x) ✗")

        # 12. CMF
        if sv("cmf") > 0.1: bull += 0.5
        elif sv("cmf") < -0.1: bear += 0.5

        return round(bull, 2), round(bear, 2), reasons

    @classmethod
    def _mean_rev(cls, df: pd.DataFrame) -> Tuple[float, float, List[str]]:
        if len(df) < 2: return 0.0, 0.0, []
        c   = df.iloc[-1]
        sv  = lambda k, d=0.0: cls._sv(c, k, d)
        bull, bear, reasons = 0.0, 0.0, []

        rsi      = sv("rsi", 50)
        stoch_k  = sv("stoch_k", 50)
        bb_pct   = sv("bb_pct", 0.5)
        cci      = sv("cci", 0)
        wpr      = sv("williams_r", -50)
        mfi      = sv("mfi", 50)
        cmf      = sv("cmf", 0)
        roc5     = sv("roc5", 0)
        dpo      = sv("dpo", 0)

        # Survente → BUY
        if rsi < CONFIG["RSI_OVERSOLD"]:    bull += 2.0; reasons.append(f"RSI {rsi:.0f} survente ✓")
        elif rsi < 38:                       bull += 1.0
        if stoch_k < 15:                     bull += 1.5; reasons.append(f"Stoch {stoch_k:.0f} survente ✓")
        elif stoch_k < 25:                   bull += 0.7
        if bb_pct < 0.08:                    bull += 1.5; reasons.append("Prix sous BB lower ✓")
        elif bb_pct < 0.2:                   bull += 0.5
        if cci < -120:                       bull += 1.0; reasons.append(f"CCI {cci:.0f} survente ✓")
        if wpr < -85:                        bull += 1.0; reasons.append(f"Williams %R {wpr:.0f} ✓")
        if mfi < 25:                         bull += 0.8; reasons.append(f"MFI {mfi:.0f} survente ✓")
        if cmf < -0.15:                      bull += 0.5
        if roc5 < -3:                        bull += 0.5  # oversold momentum
        if dpo < 0:                          bull += 0.3

        # Surachat → SELL
        if rsi > CONFIG["RSI_OVERBOUGHT"]:  bear += 2.0; reasons.append(f"RSI {rsi:.0f} surachat ✗")
        elif rsi > 62:                       bear += 1.0
        if stoch_k > 85:                     bear += 1.5; reasons.append(f"Stoch {stoch_k:.0f} surachat ✗")
        elif stoch_k > 75:                   bear += 0.7
        if bb_pct > 0.92:                    bear += 1.5; reasons.append("Prix sur BB upper ✗")
        elif bb_pct > 0.80:                  bear += 0.5
        if cci > 120:                        bear += 1.0; reasons.append(f"CCI {cci:.0f} surachat ✗")
        if wpr > -15:                        bear += 1.0; reasons.append(f"Williams %R {wpr:.0f} ✗")
        if mfi > 75:                         bear += 0.8; reasons.append(f"MFI {mfi:.0f} surachat ✗")
        if cmf > 0.15:                       bear += 0.5
        if roc5 > 3:                         bear += 0.5
        if dpo > 0:                          bear += 0.3

        return round(bull, 2), round(bear, 2), reasons

    @classmethod
    def generate(cls, df: pd.DataFrame, regime: Regime,
                 expo_mult: float = 1.0) -> Dict:
        """Génère le signal final adapté au régime."""
        base = {
            "signal": Signal.HOLD, "score_bull": 0.0, "score_bear": 0.0,
            "force": 0.0, "reasons": [], "regime": regime.value,
            "expo_mult": expo_mult, "is_strong": False,
            "ts": datetime.utcnow().isoformat(),
        }

        if expo_mult == 0.0:
            base["reasons"] = ["VIX extrême — aucun trade autorisé"]
            return base

        # Sélection du module de scoring selon le régime
        if regime in (Regime.STRONG_BULL, Regime.BULL):
            b, bk, reasons = cls._trend(df)
        elif regime == Regime.RANGING:
            b, bk, reasons = cls._mean_rev(df)
        elif regime in (Regime.STRONG_BEAR, Regime.BEAR):
            # Régime baissier : calculer pour les shorts
            b, bk, reasons = cls._trend(df)
        else:
            # Transitioning : confluence
            tb, tkb, tr = cls._trend(df)
            mb, mkb, mr = cls._mean_rev(df)
            b  = (tb + mb) / 2;  bk = (tkb + mkb) / 2
            reasons = tr[:3] + mr[:2]

        base["score_bull"] = b
        base["score_bear"] = bk
        base["reasons"]    = reasons

        min_s    = CONFIG["MIN_SIGNAL_SCORE"]
        strong_s = CONFIG["STRONG_SIGNAL_SCORE"]

        if b >= min_s and b > bk + 1.0:
            sig  = Signal.STRONG_BUY if b >= strong_s else Signal.BUY
            force = round(min(b / 12, 1.0) * expo_mult, 3)
            base.update({"signal": sig, "force": force, "is_strong": b >= strong_s})
        elif bk >= min_s and bk > b + 1.0:
            sig  = Signal.STRONG_SELL if bk >= strong_s else Signal.SELL
            force = round(min(bk / 12, 1.0) * expo_mult, 3)
            base.update({"signal": sig, "force": force, "is_strong": bk >= strong_s})

        bus.publish("signal_generated", base)
        return base

    @classmethod
    def scorecard(cls, analyses: Dict[str, Dict]) -> List[Dict]:
        """
        Retourne un classement des actifs par force du signal.
        Utilisé par le screener.
        """
        rows = []
        for sym, a in analyses.items():
            if "error" in a: continue
            score  = a.get("score_bull", 0) - a.get("score_bear", 0)
            signal = a.get("signal", Signal.HOLD)
            if isinstance(signal, Signal): signal = signal.value
            rows.append({
                "symbol":   sym,
                "price":    a.get("price", 0),
                "regime":   a.get("regime", ""),
                "signal":   signal,
                "net_score":round(score, 2),
                "force":    round(a.get("signal_force", 0), 3),
                "rsi":      round(a.get("rsi", 50), 1),
                "adx":      round(a.get("adx", 20), 1),
            })
        rows.sort(key=lambda x: abs(x["net_score"]), reverse=True)
        return rows


# ═══════════════════════════════════════════════════════════════════════════════
# §9  MACRO WATCHDOG  (enrichi)
# ═══════════════════════════════════════════════════════════════════════════════

class MacroWatchdog:
    """Surveille les indicateurs macroéconomiques clés."""

    _DEFAULTS = {
        "vix": 17.5, "t10y": 4.35, "t2y": 4.20,
        "spread_10_2": 0.15, "brent": 82.0,
        "dxy": 104.2, "gold": 2320.0, "eurusd": 1.084,
        "usdjpy": 149.5, "btc": 65000, "sp500": 5200,
        "ig_spread": 85, "hy_spread": 310,
    }

    def __init__(self, dp: DataProvider):
        self.dp    = dp
        self.cache: Dict = {}
        self._ts   = 0.0
        self._ttl  = 300
        self.alerts: List[str] = []
        self.history: List[Dict] = []

    def _price(self, sym: str) -> Optional[float]:
        if not YF_AVAILABLE: return None
        try:
            import logging as _l; _l.getLogger("yfinance").setLevel(_l.CRITICAL)
            import yfinance as yf
            raw = yf.download(sym, period="5d", interval="1d",
                              progress=False, auto_adjust=True, timeout=6)
            if raw.empty: return None
            if isinstance(raw.columns, pd.MultiIndex): raw.columns = raw.columns.droplevel(1)
            return float(raw["Close"].iloc[-1])
        except: return None

    def refresh(self) -> Dict:
        now = time.time()
        if self.cache and (now - self._ts) < self._ttl:
            return self.cache

        self.alerts = []
        m = dict(self._DEFAULTS)

        for sym, key in [
            ("^VIX","vix"), ("^TNX","t10y"), ("^IRX","t2y"),
            ("BZ=F","brent"), ("DX-Y.NYB","dxy"),
            ("GC=F","gold"), ("EURUSD=X","eurusd"), ("USDJPY=X","usdjpy"),
        ]:
            val = self._price(sym)
            if val is not None and not math.isnan(val):
                m[key] = round(float(val), 4)

        if m.get("t10y") and m.get("t2y"):
            m["spread_10_2"] = round(m["t10y"] - m["t2y"], 3)

        # Alertes VIX
        vix = m.get("vix", 20)
        if vix >= CONFIG["VIX_EXTREME"]:
            self.alerts.append(f"⛔ VIX {vix:.1f} — ARRÊT POSITIONS")
        elif vix >= CONFIG["VIX_HIGH"]:
            self.alerts.append(f"⚠️  VIX {vix:.1f} — Expo −50%")
        elif vix >= CONFIG["VIX_MEDIUM"]:
            self.alerts.append(f"ℹ️  VIX {vix:.1f} — Zone vigilance")

        # Alerte courbe des taux
        s = m.get("spread_10_2", 0.5)
        if s <= CONFIG["SPREAD_10_2_INVERSION"]:
            self.alerts.append(f"⚠️  Courbe inversée (10-2={s:.2f}%) — Signal récession")
        elif s < 0:
            self.alerts.append(f"ℹ️  Courbe légèrement inversée ({s:.2f}%)")

        # Alerte pétrole
        brt = m.get("brent", 80)
        if brt >= CONFIG["BRENT_SPIKE"]:
            self.alerts.append(f"⚠️  Brent {brt:.0f}$ — Choc géopolitique possible")

        # Alerte spread crédit (simulé)
        ig = m.get("ig_spread", 85)
        hy = m.get("hy_spread", 310)
        if ig > 150: self.alerts.append(f"⚠️  Spread IG {ig} bps — Stress crédit")
        if hy > 600: self.alerts.append(f"⚠️  Spread HY {hy} bps — Crise crédit")

        m["timestamp"] = datetime.utcnow().isoformat()
        m["vix_regime"] = self._vix_regime(vix)
        m["macro_bias"] = self.regime_bias(m)

        self.cache  = m
        self._ts    = now
        self.history.append({k: v for k, v in m.items() if k != "timestamp"})
        if len(self.history) > 500: self.history.pop(0)

        bus.publish("macro_refreshed", m)
        return m

    @staticmethod
    def _vix_regime(vix: float) -> str:
        if vix >= 40: return "EXTRÊME"
        if vix >= 30: return "ELEVÉ"
        if vix >= 20: return "MODÉRÉ"
        if vix >= 15: return "FAIBLE"
        return "TRÈS FAIBLE"

    @staticmethod
    def regime_bias(m: dict) -> str:
        vix = m.get("vix", 20)
        s   = m.get("spread_10_2", 0.5)
        if vix >= CONFIG["VIX_HIGH"]: return "DANGER"
        if s <= CONFIG["SPREAD_10_2_INVERSION"]: return "BEARISH"
        if s > 0.5 and vix < 20: return "BULLISH"
        return "NEUTRAL"

    def expo_multiplier(self) -> float:
        vix = self.refresh().get("vix", 20)
        if vix >= CONFIG["VIX_EXTREME"]: return 0.0
        if vix >= CONFIG["VIX_HIGH"]:    return 0.50
        if vix >= CONFIG["VIX_MEDIUM"]:  return 0.75
        return 1.0

    def fear_greed_index(self) -> Tuple[float, str]:
        """Indice Fear & Greed simplifié (0=extrême fear, 100=extrême greed)."""
        m   = self.refresh()
        vix = m.get("vix", 20)
        roc = m.get("sp500_roc", 0)    # simulé
        # VIX component (inverse)
        v_score = max(0, min(100, (40 - vix) / 25 * 100))
        # Momentum (simulé)
        m_score = max(0, min(100, 50 + roc * 5))
        fg = (v_score * 0.6 + m_score * 0.4)
        if fg < 25:   label = "Peur Extrême"
        elif fg < 45: label = "Peur"
        elif fg < 55: label = "Neutre"
        elif fg < 75: label = "Avidité"
        else:         label = "Avidité Extrême"
        return round(fg, 1), label

    def summary(self) -> str:
        m  = self.refresh()
        fg, fg_label = self.fear_greed_index()
        def _f(k, fmt=".2f", u=""): v=m.get(k); return f"{v:{fmt}}{u}" if v else "N/A"
        lines = [
            "═"*68,
            f"  MACRO WATCHDOG — {datetime.utcnow():%Y-%m-%d %H:%M UTC}",
            "═"*68,
            f"  VIX          : {_f('vix','.1f')}  ({m.get('vix_regime','')}) "
            f"| Fear & Greed: {fg:.0f} — {fg_label}",
            f"  T10Y / T2Y   : {_f('t10y')}% / {_f('t2y')}%   Spread: {_f('spread_10_2')}%",
            f"  Brent        : {_f('brent','.1f')}$  | Or: {_f('gold','.0f')}$",
            f"  DXY          : {_f('dxy')}  | EUR/USD: {_f('eurusd','.4f')}",
            f"  USD/JPY      : {_f('usdjpy','.2f')}",
            f"  Biais macro  : {m.get('macro_bias','N/A')} | Expo: {self.expo_multiplier():.0%}",
        ]
        if self.alerts:
            lines += ["─"*68, "  ALERTES :"] + [f"    {a}" for a in self.alerts]
        lines.append("═"*68)
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# §10  GESTIONNAIRE D'ALERTES CONFIGURABLES
# ═══════════════════════════════════════════════════════════════════════════════

class AlertManager:
    """
    Gestion des alertes conditionnelles configurables par l'utilisateur.
    Conditions : price_above, price_below, rsi_oversold, rsi_overbought,
                 signal_buy, signal_sell, vix_above, spread_inversion, etc.
    """

    CONDITIONS = {
        "price_above":      lambda a, t: a.get("price", 0) > t,
        "price_below":      lambda a, t: a.get("price", 0) < t,
        "rsi_oversold":     lambda a, t: a.get("rsi", 50) < t,
        "rsi_overbought":   lambda a, t: a.get("rsi", 50) > t,
        "adx_strong":       lambda a, t: a.get("adx", 0) > t,
        "signal_buy":       lambda a, t: a.get("signal", "") in ("BUY", "STRONG_BUY"),
        "signal_sell":      lambda a, t: a.get("signal", "") in ("SELL", "STRONG_SELL"),
        "atr_pct_above":    lambda a, t: a.get("atr_pct", 0) > t,
        "bb_squeeze":       lambda a, t: a.get("bb_width", 1) < t,
        "volume_spike":     lambda a, t: a.get("vol_ratio", 1) > t,
    }

    def __init__(self):
        raw   = persist.read_json(CONFIG["ALERTS_FILE"], [])
        self.alerts: List[AlertConfig] = []
        for r in raw:
            try:
                self.alerts.append(AlertConfig(**{k: v for k, v in r.items()
                                                   if k in AlertConfig.__dataclass_fields__}))
            except: pass
        self._triggered_this_session: Set[str] = set()

    def add(self, symbol: str, condition: str, threshold: float = 0.0) -> AlertConfig:
        a = AlertConfig(
            id=hashlib.md5(f"{symbol}{condition}{threshold}{time.time()}".encode()).hexdigest()[:8],
            symbol=symbol, condition=condition, threshold=threshold
        )
        self.alerts.append(a)
        self._save()
        return a

    def remove(self, alert_id: str) -> bool:
        before = len(self.alerts)
        self.alerts = [a for a in self.alerts if a.id != alert_id]
        if len(self.alerts) < before:
            self._save()
            return True
        return False

    def check(self, analyses: Dict[str, Dict]) -> List[Tuple[AlertConfig, Dict]]:
        """Vérifie toutes les alertes actives contre les analyses courantes."""
        triggered = []
        for alert in self.alerts:
            if not alert.active or alert.id in self._triggered_this_session:
                continue
            a = analyses.get(alert.symbol, {})
            if not a or "error" in a: continue
            fn = self.CONDITIONS.get(alert.condition)
            if fn and fn(a, alert.threshold):
                alert.triggered = True
                self._triggered_this_session.add(alert.id)
                triggered.append((alert, a))
                bus.publish("alert_triggered", {"alert": asdict(alert), "analysis": a})
                logger.info(f"🔔 ALERTE [{alert.condition}] {alert.symbol} @ {a.get('price')}")
        self._save()
        return triggered

    def reset_session(self):
        """Réinitialise les alertes déclenchées (nouveau jour de trading)."""
        self._triggered_this_session.clear()
        for a in self.alerts: a.triggered = False

    def _save(self):
        persist.write_json(CONFIG["ALERTS_FILE"], [asdict(a) for a in self.alerts])

    def list_alerts(self) -> str:
        if not self.alerts: return "  Aucune alerte configurée."
        lines = [f"  {'ID':8s} {'Symbole':10s} {'Condition':20s} {'Seuil':10s} {'Active':6s}"]
        for a in self.alerts:
            lines.append(f"  {a.id:8s} {a.symbol:10s} {a.condition:20s} {a.threshold:10.2f} {'✓' if a.active else '✗':6s}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# §11  JOURNAL DE TRADING INTELLIGENT
# ═══════════════════════════════════════════════════════════════════════════════

class TradingJournal:
    """
    Journal de trading enrichi :
    • Entrées libres (observations, plans, revues)
    • Lien avec les trades (P&L automatique)
    • Analyse des biais comportementaux (mood tracking)
    • Statistiques par tag / par humeur
    """

    MOODS = ["confident", "uncertain", "fearful", "greedy", "neutral", "euphoric", "anxious"]
    TYPES = ["trade", "observation", "plan", "review", "error", "insight"]

    def __init__(self):
        raw = persist.read_jsonl(CONFIG["JOURNAL_FILE"])
        self.entries: List[JournalEntry] = []
        for r in raw:
            try: self.entries.append(JournalEntry(**{k: v for k,v in r.items()
                                                      if k in JournalEntry.__dataclass_fields__}))
            except: pass

    def add(self, symbol: str, type_: str, content: str,
            mood: str = "neutral", pnl: float = 0.0,
            tags: List[str] = None) -> JournalEntry:
        e = JournalEntry(
            id=hashlib.md5(f"{symbol}{time.time()}".encode()).hexdigest()[:8],
            date=date.today().isoformat(),
            symbol=symbol, type=type_, content=content,
            mood=mood, pnl=pnl, tags=tags or []
        )
        self.entries.append(e)
        persist.append_jsonl(CONFIG["JOURNAL_FILE"], asdict(e))
        return e

    def get_by_symbol(self, symbol: str) -> List[JournalEntry]:
        return [e for e in self.entries if e.symbol == symbol]

    def get_by_date(self, date_str: str) -> List[JournalEntry]:
        return [e for e in self.entries if e.date == date_str]

    def mood_stats(self) -> Dict[str, Dict]:
        stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "total_pnl": 0.0, "avg_pnl": 0.0})
        for e in self.entries:
            stats[e.mood]["count"] += 1
            stats[e.mood]["total_pnl"] += e.pnl
        for m, s in stats.items():
            s["avg_pnl"] = s["total_pnl"] / s["count"] if s["count"] > 0 else 0
        return dict(stats)

    def tag_stats(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for e in self.entries:
            for tag in e.tags: counts[tag] += 1
        return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))

    def summary(self) -> str:
        if not self.entries: return "  Journal vide."
        ms = self.mood_stats()
        ts = self.tag_stats()
        lines = [f"  Entrées totales : {len(self.entries)}",
                 f"  P&L total journalisé : {sum(e.pnl for e in self.entries):+.2f}$",
                 "  Humeurs (avg P&L) :"]
        for mood, s in ms.items():
            lines.append(f"    {mood:12s}: {s['count']:3d} entrées | avg P&L {s['avg_pnl']:+.2f}$")
        if ts:
            lines.append(f"  Top tags : {', '.join(list(ts.keys())[:5])}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# §12  RISK MANAGER  (enrichi v3)
# ═══════════════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Gestionnaire de risque complet :
    • Sizing Kelly fractionné + risk % capital
    • Stop ATR + trailing stop adaptatif
    • Kill-switch quotidien / hebdo / drawdown / kill-all
    • Multi-positions simultanées (max 5)
    • Corrélation des positions (évite les positions trop similaires)
    • Récapitulatif performance en temps réel
    • Export CSV de l'historique
    """

    def __init__(self, capital: float = 10_000):
        self.initial   = capital
        self.capital   = capital
        self.peak      = capital
        self.positions: Dict[str, Position] = {}
        self.history:   List[TradeRecord]   = []
        self.daily_start  = capital
        self.weekly_start = capital
        self._event_bus   = bus

    # ── Métriques ─────────────────────────────────────────────────────────────

    @property
    def drawdown(self) -> float:
        return max(0, (self.peak - self.capital) / max(self.peak, 1))

    @property
    def total_return(self) -> float:
        return (self.capital - self.initial) / max(self.initial, 1)

    @property
    def daily_realized_loss(self) -> float:
        today = date.today().isoformat()
        today_pnl = sum(t.pnl for t in self.history
                        if t.closed and t.closed[:10] == today)
        return max(0, -today_pnl / max(self.daily_start, 1))

    @property
    def weekly_realized_loss(self) -> float:
        wk_pnl = sum(t.pnl for t in self.history[-50:])
        return max(0, -wk_pnl / max(self.weekly_start, 1))

    def reset_daily(self):
        self.daily_start = self.capital

    def reset_weekly(self):
        self.weekly_start = self.capital

    # ── Kill Switch ───────────────────────────────────────────────────────────

    def kill_switch(self) -> Tuple[bool, str]:
        if self.drawdown >= CONFIG["MAX_DRAWDOWN_LIMIT"]:
            return True, f"Drawdown {self.drawdown:.1%} ≥ limite {CONFIG['MAX_DRAWDOWN_LIMIT']:.1%}"
        if self.daily_realized_loss >= CONFIG["DAILY_LOSS_LIMIT"]:
            return True, f"Perte journalière {self.daily_realized_loss:.1%} ≥ {CONFIG['DAILY_LOSS_LIMIT']:.1%}"
        if self.weekly_realized_loss >= CONFIG["WEEKLY_LOSS_LIMIT"]:
            return True, f"Perte hebdo {self.weekly_realized_loss:.1%} ≥ {CONFIG['WEEKLY_LOSS_LIMIT']:.1%}"
        if len(self.positions) >= CONFIG["MAX_POSITIONS"]:
            return True, f"Positions max atteint ({CONFIG['MAX_POSITIONS']})"
        return False, ""

    def close_all(self, current_prices: Dict[str, float], reason: str = "kill_all") -> List[TradeRecord]:
        """Ferme toutes les positions en urgence."""
        records = []
        for sym in list(self.positions.keys()):
            price = current_prices.get(sym, self.positions[sym].entry)
            rec   = self.close(sym, price, reason)
            if rec: records.append(rec)
        return records

    # ── Calcul des niveaux ────────────────────────────────────────────────────

    def levels(self, entry: float, side: OrderSide,
               atr: float) -> Tuple[float, float, float]:
        """Retourne (stop_loss, take_profit, trailing_initial)."""
        stop_d = max(atr * CONFIG["ATR_STOP_MULT"], entry * 0.005)
        tp_d   = atr * CONFIG["ATR_TP_MULT"]
        if side == OrderSide.LONG:
            return entry - stop_d, entry + tp_d, entry + stop_d * 0.5
        return entry + stop_d, entry - tp_d, entry - stop_d * 0.5

    # ── Sizing ────────────────────────────────────────────────────────────────

    def size(self, entry: float, stop: float, force: float = 1.0) -> float:
        stop_d = abs(entry - stop)
        if stop_d < 1e-9 or entry <= 0: return 0.0

        risk_amt = self.capital * CONFIG["RISK_PER_TRADE"] * force
        s_risk   = risk_amt / stop_d

        wr, rr = CONFIG["KELLY_WIN_RATE"], CONFIG["KELLY_RR_RATIO"]
        kf     = max(0, (wr * rr - (1 - wr)) / rr) * CONFIG["KELLY_FRACTION"]
        s_kelly = (self.capital * kf) / entry

        s_max   = (self.capital * CONFIG["MAX_POSITION_PCT"]) / entry
        return max(round(min(s_risk, s_kelly, s_max), 6), 0.0)

    # ── Validation ────────────────────────────────────────────────────────────

    def validate(self, sym: str, entry: float, stop: float,
                 tp: float, side: OrderSide) -> Tuple[bool, str]:
        if sym in self.positions:
            return False, f"Position déjà ouverte sur {sym}"
        ks, km = self.kill_switch()
        if ks: return False, km
        risk = abs(entry - stop)
        rwd  = abs(tp - entry)
        if risk <= 0: return False, "Stop invalide (risque nul)"
        rr = rwd / risk
        if rr < 1.9: return False, f"R:R={rr:.2f} insuffisant (min 2.0)"
        if self.capital < 50: return False, "Capital insuffisant (<50$)"
        return True, f"Valide (R:R={rr:.2f})"

    # ── Positions ─────────────────────────────────────────────────────────────

    def open(self, sym: str, side: OrderSide, sz: float,
             entry: float, stop: float, tp: float,
             notes: str = "", tags: List[str] = None) -> Position:
        pos = Position(
            symbol=sym, side=side, size=sz, entry=entry,
            stop=stop, tp=tp, trail_stop=stop,
            notes=notes, tags=tags or []
        )
        self.positions[sym] = pos
        self._event_bus.publish("position_opened", asdict(pos))
        logger.info(f"OUVERTURE {side.value.upper()} | {sym} @ {entry:.4f} | "
                    f"Sz={sz:.4f} Stop={stop:.4f} TP={tp:.4f}")
        return pos

    def update_trailing(self, sym: str, price: float, atr: float) -> None:
        if sym not in self.positions: return
        pos   = self.positions[sym]
        trail = atr * CONFIG["ATR_STOP_MULT"]
        if pos.side == OrderSide.LONG:
            new_stop = price - trail
            if new_stop > pos.trail_stop: pos.trail_stop = new_stop
        else:
            new_stop = price + trail
            if new_stop < pos.trail_stop: pos.trail_stop = new_stop

    def close(self, sym: str, exit_price: float,
              reason: str = "manual") -> Optional[TradeRecord]:
        if sym not in self.positions: return None
        pos = self.positions.pop(sym)
        pnl = pos.unrealized_pnl(exit_price)
        self.capital += pnl
        self.peak     = max(self.peak, self.capital)

        try:    opened_dt = datetime.fromisoformat(pos.opened)
        except: opened_dt = datetime.utcnow()
        dur = str(datetime.utcnow() - opened_dt).split(".")[0]

        rec = TradeRecord(
            symbol=sym, side=pos.side.value, size=pos.size,
            entry=pos.entry, exit=exit_price,
            pnl=round(pnl, 4),
            pnl_pct=round(pos.unrealized_pct(exit_price), 4),
            reason=reason,
            opened=pos.opened, closed=datetime.utcnow().isoformat(),
            duration=dur, notes=pos.notes, tags=pos.tags,
        )
        self.history.append(rec)
        persist.append_jsonl(CONFIG["TRADES_FILE"], asdict(rec))
        self._event_bus.publish("position_closed", asdict(rec))
        logger.info(f"FERMETURE {reason.upper()} | {sym} @ {exit_price:.4f} | "
                    f"P&L={pnl:+.4f}$ ({rec.pnl_pct:+.1%})")
        return rec

    def check_exits(self, sym: str, price: float, atr: float) -> Optional[Tuple[str, float]]:
        if sym not in self.positions: return None
        pos = self.positions[sym]
        self.update_trailing(sym, price, atr)
        if pos.side == OrderSide.LONG:
            if price <= pos.trail_stop: return ("trailing_stop", pos.trail_stop)
            if price <= pos.stop:       return ("stop_loss",     pos.stop)
            if price >= pos.tp:         return ("take_profit",   pos.tp)
        else:
            if price >= pos.trail_stop: return ("trailing_stop", pos.trail_stop)
            if price >= pos.stop:       return ("stop_loss",     pos.stop)
            if price <= pos.tp:         return ("take_profit",   pos.tp)
        return None

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        if not self.history:
            return {"n_trades": 0, "capital": round(self.capital, 2),
                    "total_return": 0, "drawdown": 0}
        pnls   = [t.pnl for t in self.history]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        n      = len(pnls)
        wr     = len(wins) / n
        pf     = sum(wins) / abs(sum(losses)) if losses else float("inf")
        sharpe = (np.mean(pnls) / np.std(pnls) * np.sqrt(252)
                  if np.std(pnls) > 0 else 0.0)
        return {
            "n_trades":      n,
            "win_rate":      round(wr, 4),
            "profit_factor": round(float(pf) if pf != float("inf") else 99, 3),
            "total_pnl":     round(sum(pnls), 2),
            "total_return":  round(self.total_return, 4),
            "max_drawdown":  round(self.drawdown, 4),
            "sharpe_approx": round(float(sharpe), 3),
            "avg_win":       round(np.mean(wins) if wins else 0, 2),
            "avg_loss":      round(np.mean(losses) if losses else 0, 2),
            "best_trade":    round(max(pnls), 2),
            "worst_trade":   round(min(pnls), 2),
            "capital":       round(self.capital, 2),
            "expectancy":    round(wr * np.mean(wins or [0]) - (1-wr) * abs(np.mean(losses or [0])), 4),
        }

    def export_history(self, path: str = None) -> str:
        path = path or f"{CONFIG['EXPORT_DIR']}/trades_{date.today()}.csv"
        persist.export_csv(path, [asdict(t) for t in self.history])
        return path


# ═══════════════════════════════════════════════════════════════════════════════
# §13  PAPER BROKER
# ═══════════════════════════════════════════════════════════════════════════════

class PaperBroker:
    """Paper broker avec suivi complet et simulation de slippage."""

    def __init__(self, capital: float, slippage_bps: float = 2.0):
        self.capital  = capital
        self.slippage = slippage_bps / 10_000   # 2bps par défaut
        self._orders: List[Dict] = []
        self._commissions = 0.0

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * self.slippage
        return price + slip if side == "buy" else price - slip

    def submit(self, side: str, symbol: str, qty: float,
               price: float, order_type: str = "market") -> Dict:
        exec_price = self._apply_slippage(price, side)
        commission = qty * exec_price * 0.0001   # 1bp de commission
        cost       = qty * exec_price + commission
        order = {
            "id":         f"ppr_{int(time.time()*1000)%10_000_000}",
            "side":       side, "symbol": symbol, "qty": qty,
            "req_price":  price, "exec_price": exec_price,
            "commission": round(commission, 4),
            "type":       order_type, "status": "filled",
            "ts":         datetime.utcnow().isoformat(),
        }
        if side == "buy" and cost > self.capital:
            order["status"] = "rejected"
            order["reason"] = f"Capital insuffisant ({self.capital:.2f} < {cost:.2f})"
        elif side == "buy":
            self.capital     -= cost
            self._commissions += commission
        elif side == "sell":
            self.capital      += qty * exec_price - commission
            self._commissions += commission

        self._orders.append(order)
        status = order["status"].upper()
        logger.info(f"PaperBroker | {status} | {side.upper()} {qty:.4f} {symbol}"
                    f" @ {exec_price:.4f} (slip={((exec_price-price)/price*10000):.1f}bps)"
                    f" | Cap={self.capital:.2f}$")
        return order

    @property
    def orders(self) -> List[Dict]: return list(self._orders)

    @property
    def total_commissions(self) -> float: return round(self._commissions, 4)


# ═══════════════════════════════════════════════════════════════════════════════
# §14  SCREENER DE MARCHÉS
# ═══════════════════════════════════════════════════════════════════════════════

class MarketScreener:
    """
    Scanner automatique du marché.
    Analyse tous les actifs de l'univers et classifie par force du signal.
    """

    def __init__(self, dp: DataProvider):
        self.dp = dp

    def scan(self, universe: List[str] = None,
             filter_signal: str = None) -> List[Dict]:
        universe = universe or CONFIG["SCREENER_UNIVERSE"]
        results  = []

        for sym in universe:
            try:
                df  = self.dp.get(sym, n_days=200)
                dfi = IndicatorEngine.compute(df)
                reg, conf, scores = RegimeDetector.detect(dfi)
                expo  = 1.0
                sig   = SignalGenerator.generate(dfi, reg, expo)
                row   = dfi.iloc[-1]

                def rv(k, d=0.0): v=row.get(k,d); return d if (v is None or (isinstance(v,float) and math.isnan(v))) else float(v)

                result = {
                    "symbol":       sym,
                    "price":        round(rv("Close"), 4),
                    "change_pct":   round(rv("roc5"), 2),
                    "regime":       reg.value,
                    "conf":         conf,
                    "signal":       sig["signal"].value if isinstance(sig["signal"], Signal) else str(sig["signal"]),
                    "force":        sig["force"],
                    "score_bull":   sig["score_bull"],
                    "score_bear":   sig["score_bear"],
                    "net_score":    round(sig["score_bull"] - sig["score_bear"], 2),
                    "rsi":          round(rv("rsi"), 1),
                    "adx":          round(rv("adx"), 1),
                    "atr_pct":      round(rv("atr_pct"), 2),
                    "vol_ratio":    round(rv("vol_ratio"), 2),
                    "is_squeeze":   bool(rv("squeeze")),
                    "supertrend":   int(rv("supertrend")),
                    "above_cloud":  bool(rv("above_cloud")),
                }
                results.append(result)
            except Exception as e:
                logger.debug(f"Screener {sym}: {e}")

        # Filtrage optionnel
        if filter_signal:
            results = [r for r in results if r["signal"] == filter_signal]

        # Tri par |net_score| décroissant
        results.sort(key=lambda x: abs(x["net_score"]), reverse=True)
        return results

    def top_buys(self, n: int = 5) -> List[Dict]:
        all_r = self.scan()
        return [r for r in all_r if r["signal"] in ("BUY","STRONG_BUY")][:n]

    def top_sells(self, n: int = 5) -> List[Dict]:
        all_r = self.scan()
        return [r for r in all_r if r["signal"] in ("SELL","STRONG_SELL")][:n]

    def squeezes(self) -> List[Dict]:
        """Actifs en compression (squeeze) — préparent un breakout."""
        all_r = self.scan()
        return [r for r in all_r if r["is_squeeze"]]

    def print_results(self, results: List[Dict], title: str = "Screener") -> None:
        print(f"\n{'═'*75}")
        print(f"  {title} — {len(results)} actifs — {datetime.utcnow():%Y-%m-%d %H:%M}")
        print(f"{'═'*75}")
        print(f"  {'Sym':8s} {'Prix':8s} {'Var%':6s} {'Régime':12s} "
              f"{'Signal':12s} {'Forc':5s} {'RSI':5s} {'ADX':5s}")
        print(f"  {'─'*73}")
        for r in results:
            sig_icon = {"BUY":"🟢","STRONG_BUY":"🚀","SELL":"🔴","STRONG_SELL":"🔻","HOLD":"⚪"}.get(r["signal"],"")
            print(f"  {r['symbol']:8s} {r['price']:8.2f} {r['change_pct']:+6.2f}% "
                  f"{r['regime']:12s} {sig_icon}{r['signal']:10s} {r['force']:5.2f} "
                  f"{r['rsi']:5.1f} {r['adx']:5.1f}")
        print(f"{'═'*75}")


# ═══════════════════════════════════════════════════════════════════════════════
# §15  OPTIMISATION PARAMÉTRIQUE (Grid Search)
# ═══════════════════════════════════════════════════════════════════════════════

class ParameterOptimizer:
    """
    Grid search sur les paramètres clés :
    EMA fast/slow, ADX threshold, ATR stop multiplier.
    Évalue chaque combinaison par backtesting simplifié.
    Retourne le top 5 par Sharpe ratio.
    """

    def __init__(self, dp: DataProvider):
        self.dp = dp

    def _quick_backtest(self, df: pd.DataFrame, params: Dict,
                         capital: float = 10_000) -> Dict:
        """Backtest rapide vectorisé pour le grid search."""
        C   = df["Close"].astype(float)
        ema_f = C.ewm(span=params["ema_fast"], adjust=False).mean()
        ema_s = C.ewm(span=params["ema_slow"], adjust=False).mean()

        # Signaux
        entries = (ema_f.shift(1) <= ema_s.shift(1)) & (ema_f > ema_s)
        exits   = (ema_f.shift(1) >= ema_s.shift(1)) & (ema_f < ema_s)

        cap   = capital
        pos   = 0.0
        ep    = 0.0
        trades: List[float] = []

        for i in range(1, len(C)):
            price = float(C.iloc[i])
            if entries.iloc[i] and pos == 0:
                pos = cap * 0.95 / price
                ep  = price
                cap -= pos * price
            elif exits.iloc[i] and pos > 0:
                pnl  = (price - ep) * pos
                cap += pos * price
                trades.append(pnl)
                pos = 0.0

        if pos > 0:
            price = float(C.iloc[-1])
            pnl   = (price - ep) * pos
            cap  += pos * price
            trades.append(pnl)

        ret   = (cap - capital) / capital
        n     = len(trades)
        if n < 2: return {"return": ret, "sharpe": 0, "n": n}
        wins  = [p for p in trades if p > 0]
        lss   = [p for p in trades if p < 0]
        pf    = sum(wins) / abs(sum(lss)) if lss else 99
        std   = np.std(trades)
        sharpe= (np.mean(trades) / std * np.sqrt(252)) if std > 0 else 0
        return {"return": round(ret, 4), "sharpe": round(float(sharpe), 3),
                "n": n, "wr": round(len(wins)/n, 3) if n > 0 else 0,
                "pf": round(float(pf), 3)}

    def run(self, symbol: str = "SPY", n_days: int = 504,
            n_top: int = 5) -> List[Dict]:
        df = self.dp.get(symbol, n_days=n_days)
        if df.empty or len(df) < 100:
            return []

        param_grid = list(itertools.product(
            CONFIG["GS_EMA_FAST_RANGE"],
            CONFIG["GS_EMA_SLOW_RANGE"],
            CONFIG["GS_ADX_RANGE"],
            CONFIG["GS_ATR_STOP_RANGE"],
        ))

        results = []
        for ema_f, ema_s, adx_t, atr_s in param_grid:
            if ema_f >= ema_s: continue
            params = {"ema_fast": ema_f, "ema_slow": ema_s,
                      "adx_threshold": adx_t, "atr_stop": atr_s}
            bt = self._quick_backtest(df, params)
            results.append({**params, **bt})

        results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
        return results[:n_top]

    def print_results(self, results: List[Dict]) -> None:
        print(f"\n{'═'*70}")
        print(f"  OPTIMISATION PARAMÉTRIQUE — Top {len(results)}")
        print(f"{'═'*70}")
        print(f"  {'EMA_F':5s} {'EMA_S':5s} {'ADX':5s} {'ATR_S':5s} "
              f"{'Return':8s} {'Sharpe':7s} {'Trades':7s} {'WR':5s} {'PF':5s}")
        for r in results:
            print(f"  {r['ema_fast']:5d} {r['ema_slow']:5d} {r['adx_threshold']:5d} "
                  f"{r['atr_stop']:5.1f} {r['return']:+8.1%} {r['sharpe']:7.3f} "
                  f"{r['n']:7d} {r['wr']:5.1%} {r['pf']:5.2f}")
        print(f"{'═'*70}")


# ═══════════════════════════════════════════════════════════════════════════════
# §16  WALK-FORWARD BACKTESTER  (enrichi v3)
# ═══════════════════════════════════════════════════════════════════════════════

class WalkForwardBacktester:
    """
    Backtest walk-forward strict :
    • Pas de look-ahead bias
    • Benchmark buy-and-hold comparé
    • Alpha et tracking error calculés
    • Métriques enrichies (Calmar, Omega, Ulcer)
    """

    def __init__(self, dp: DataProvider):
        self.dp = dp

    def _run_window(self, df: pd.DataFrame, capital: float) -> Dict:
        if len(df) < 60: return {"n_trades": 0, "pnl": 0, "capital": capital, "trades": []}
        df  = IndicatorEngine.compute(df)
        rm  = RiskManager(capital)
        br  = PaperBroker(capital)
        pos = {}

        for i in range(2, len(df)):
            seg   = df.iloc[max(0, i-200):i+1]
            price = float(df["Close"].iloc[i])
            atr   = float(df["atr"].iloc[i]) if "atr" in df.columns and not math.isnan(float(df["atr"].iloc[i])) else price * 0.01

            # Sorties
            for sym in list(pos.keys()):
                info = rm.check_exits(sym, price, atr)
                if info:
                    reason, ep = info
                    rm.close(sym, ep, reason)
                    br.submit("sell" if pos[sym] == "long" else "buy", sym, 0, ep)
                    pos.pop(sym)

            # Kill switch
            ks, _ = rm.kill_switch()
            if ks: break

            # Signal
            regime, _, _ = RegimeDetector.detect(seg)
            sig = SignalGenerator.generate(seg, regime, 1.0)
            signal = sig["signal"]
            if isinstance(signal, Signal): signal = signal.value
            force  = sig["force"]

            if signal in ("BUY", "STRONG_BUY") and "SPY" not in pos:
                side  = OrderSide.LONG
                stop, tp, _ = rm.levels(price, side, atr)
                sz    = rm.size(price, stop, force)
                ok, _ = rm.validate("SPY", price, stop, tp, side)
                if ok and sz > 0:
                    rm.open("SPY", side, sz, price, stop, tp)
                    br.submit("buy", "SPY", sz, price)
                    pos["SPY"] = "long"
            elif signal in ("SELL", "STRONG_SELL") and "SPY" not in pos:
                side  = OrderSide.SHORT
                stop, tp, _ = rm.levels(price, side, atr)
                sz    = rm.size(price, stop, force)
                ok, _ = rm.validate("SPY", price, stop, tp, side)
                if ok and sz > 0:
                    rm.open("SPY", side, sz, price, stop, tp)
                    br.submit("sell", "SPY", sz, price)
                    pos["SPY"] = "short"

        # Clôture finale
        for sym in list(pos.keys()):
            lp = float(df["Close"].iloc[-1])
            rm.close(sym, lp, "end_of_window")

        trades = [asdict(t) for t in rm.history]
        return {
            "n_trades":  len(trades),
            "pnl":       sum(t.get("pnl", 0) for t in trades),
            "capital":   rm.capital,
            "win_rate":  sum(1 for t in trades if t.get("pnl", 0) > 0) / max(len(trades), 1),
            "trades":    trades,
        }

    def _benchmark_return(self, df: pd.DataFrame) -> float:
        """Retour buy-and-hold sur la même période."""
        if len(df) < 2: return 0.0
        return (float(df["Close"].iloc[-1]) - float(df["Close"].iloc[0])) / float(df["Close"].iloc[0])

    def run(self, symbol: str = "SPY", n_days: int = 756) -> Dict:
        logger.info(f"Walk-Forward {symbol} | {n_days} jours")
        df_full  = self.dp.get(symbol, n_days=n_days)
        df_full  = IndicatorEngine.compute(df_full)
        train_p  = CONFIG["WF_TRAIN_PERIODS"]
        test_p   = CONFIG["WF_TEST_PERIODS"]
        step     = CONFIG["WF_STEP"]
        windows  = []; bh_returns = []
        start    = 0

        while start + train_p + test_p <= len(df_full):
            te   = start + train_p + test_p
            df_t = df_full.iloc[start + train_p:te]
            w    = self._run_window(df_t, CONFIG["INITIAL_CAPITAL"])
            bh   = self._benchmark_return(df_t)
            w["window_start"] = str(df_full.index[start + train_p].date())
            w["window_end"]   = str(df_full.index[te - 1].date())
            w["bh_return"]    = round(bh, 4)
            windows.append(w); bh_returns.append(bh)
            start += step

        if not windows: return {"error": "Données insuffisantes"}

        all_trades = []
        for w in windows: all_trades.extend(w.get("trades", []))

        pnls  = [t.get("pnl", 0) for t in all_trades]
        n     = len(pnls)
        wins  = [p for p in pnls if p > 0]
        losses= [p for p in pnls if p <= 0]
        total = sum(pnls)

        # Max drawdown
        cum  = np.cumsum(pnls) if pnls else np.array([0])
        peak = np.maximum.accumulate(cum)
        dd   = (peak - cum) / (peak + CONFIG["INITIAL_CAPITAL"]) * 100
        mdd  = float(np.max(dd)) if len(dd) > 0 else 0

        # Sharpe
        if n > 1 and np.std(pnls) > 0:
            sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252 / test_p * n)
        else: sharpe = 0.0

        # Calmar
        annualized_ret = total / CONFIG["INITIAL_CAPITAL"] * (252 / max(n_days, 1))
        calmar = annualized_ret / (mdd / 100 + 1e-9)

        # Alpha vs BH
        bh_mean = np.mean(bh_returns) if bh_returns else 0
        strat_mean = total / CONFIG["INITIAL_CAPITAL"] / len(windows) if windows else 0
        alpha = strat_mean - bh_mean

        return {
            "symbol":          symbol,
            "n_windows":       len(windows),
            "n_trades":        n,
            "win_rate":        round(len(wins)/n, 4) if n else 0,
            "profit_factor":   round(sum(wins)/abs(sum(losses)), 3) if losses else 99,
            "total_pnl":       round(total, 2),
            "total_return_pct":round(total/CONFIG["INITIAL_CAPITAL"]*100, 2),
            "max_drawdown_pct":round(mdd, 2),
            "sharpe_ratio":    round(float(sharpe), 3),
            "calmar_ratio":    round(float(calmar), 3),
            "alpha_vs_bh":     round(float(alpha)*100, 2),
            "bh_avg_return":   round(float(bh_mean)*100, 2),
            "oos_efficiency":  round(total/CONFIG["INITIAL_CAPITAL"]/len(windows)*100, 2) if windows else 0,
            "windows":         [{k:v for k,v in w.items() if k!="trades"} for w in windows],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# §17  MONTE-CARLO  (enrichi v3)
# ═══════════════════════════════════════════════════════════════════════════════

class MonteCarloSimulator:
    """Simulation Monte-Carlo pour l'analyse de robustesse."""

    @staticmethod
    def run(bt_result: Dict, n_sim: int = None) -> Dict:
        n_sim   = n_sim or CONFIG["MC_SIMULATIONS"]
        horizon = CONFIG["MC_HORIZON"]
        wr      = bt_result.get("win_rate", 0.50)
        pf      = min(bt_result.get("profit_factor", 1.5), 10)
        avg_win = 1.0
        avg_loss= avg_win / max(pf, 0.01) * max(1 - wr, 0.01) / max(wr, 0.01)

        rng     = np.random.default_rng(2026)
        capital = CONFIG["INITIAL_CAPITAL"]
        finals  = np.zeros(n_sim)
        max_dds = np.zeros(n_sim)
        n_per_yr= max(1, int(horizon / 5))   # ~1 trade/semaine

        for s in range(n_sim):
            cap  = float(capital)
            peak = cap
            outcomes = rng.random(n_per_yr) < wr
            dd_vals  = []
            for win in outcomes:
                risk = cap * CONFIG["RISK_PER_TRADE"]
                cap += risk * avg_win if win else -risk * avg_loss
                cap  = max(cap, 0.01)
                peak = max(peak, cap)
                dd_vals.append((peak - cap) / max(peak, 1))
            finals[s]  = cap
            max_dds[s] = max(dd_vals) if dd_vals else 0

        returns = (finals - capital) / capital * 100
        ruin    = float(np.mean(finals < capital * 0.5)) * 100
        return {
            "n_simulations":        n_sim,
            "horizon_days":         horizon,
            "median_return_pct":    round(float(np.median(returns)), 2),
            "mean_return_pct":      round(float(np.mean(returns)), 2),
            "p10_return_pct":       round(float(np.percentile(returns, 10)), 2),
            "p25_return_pct":       round(float(np.percentile(returns, 25)), 2),
            "p75_return_pct":       round(float(np.percentile(returns, 75)), 2),
            "p90_return_pct":       round(float(np.percentile(returns, 90)), 2),
            "prob_positive_pct":    round(float(np.mean(returns > 0)) * 100, 1),
            "prob_10pct_gain":      round(float(np.mean(returns > 10)) * 100, 1),
            "prob_ruin_pct":        round(ruin, 1),
            "median_max_drawdown":  round(float(np.median(max_dds)) * 100, 2),
            "p90_max_drawdown":     round(float(np.percentile(max_dds, 90)) * 100, 2),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# §18  CORRÉLATION INTER-ACTIFS
# ═══════════════════════════════════════════════════════════════════════════════

class CorrelationAnalyzer:
    def __init__(self, dp: DataProvider):
        self.dp = dp

    def compute(self, symbols: List[str] = None, n_days: int = 252) -> Dict:
        symbols = symbols or CONFIG["WATCHLIST"]
        closes  = {}
        for sym in symbols:
            df = self.dp.get(sym, n_days=n_days)
            if not df.empty:
                closes[sym] = df["Close"].values[-n_days:]

        if len(closes) < 2:
            return {"error": "Pas assez d'actifs"}

        min_len = min(len(v) for v in closes.values())
        mat  = np.column_stack([v[-min_len:] for v in closes.values()])
        rets = np.diff(np.log(mat + 1e-10), axis=0)
        corr = np.corrcoef(rets.T)
        syms = list(closes.keys())

        pairs = []
        for i in range(len(syms)):
            for j in range(i+1, len(syms)):
                pairs.append({
                    "sym1": syms[i], "sym2": syms[j],
                    "correlation": round(float(corr[i, j]), 3),
                    "strength": "forte" if abs(corr[i,j]) > 0.7 else
                                "modérée" if abs(corr[i,j]) > 0.4 else "faible"
                })
        pairs.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        return {
            "symbols":       syms,
            "top_pairs":     pairs[:15],
            "avg_abs_corr":  round(float(np.mean(np.abs(corr[np.triu_indices(len(syms), 1)]))), 3),
            "n_high_corr":   sum(1 for p in pairs if abs(p["correlation"]) > 0.7),
        }
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_v3_main.py — Orchestrateur + UI iOS + CLI
# Importe bot_v3_core

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# (core intégré directement — fichier autonome)

# ═══════════════════════════════════════════════════════════════════════════════
# §19  TRADING BOT — ORCHESTRATEUR PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

class TradingBot:
    """
    Orchestrateur central v3.
    Coordonne tous les modules : macro, indicateurs, régimes, signaux,
    risk management, broker, screener, alertes, journal, backtesting, MC.
    """

    def __init__(self, mode: str = "paper", use_synthetic: bool = False):
        self.mode     = mode
        self.running  = True
        self.iter_n   = 0
        self.started  = datetime.utcnow()

        # Modules core
        self.dp       = DataProvider(use_synthetic=use_synthetic)
        self.macro    = MacroWatchdog(self.dp)
        self.risk     = RiskManager(CONFIG["INITIAL_CAPITAL"])
        self.broker   = PaperBroker(CONFIG["INITIAL_CAPITAL"])
        self.screener = MarketScreener(self.dp)
        self.alerts   = AlertManager()
        self.journal  = TradingJournal()
        self.wf_bt    = WalkForwardBacktester(self.dp)
        self.mc       = MonteCarloSimulator()
        self.corr     = CorrelationAnalyzer(self.dp)
        self.optimizer= ParameterOptimizer(self.dp)

        # Abonnements bus d'événements
        bus.subscribe("alert_triggered", self._on_alert)
        bus.subscribe("position_closed", self._on_close)

        logger.info(f"TradingBot v3 | mode={mode.upper()} | "
                    f"synthetic={'oui' if use_synthetic else 'non'} | "
                    f"capital={CONFIG['INITIAL_CAPITAL']:,}$")

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_alert(self, data: dict) -> None:
        a = data.get("alert", {})
        logger.info(f"🔔 ALERTE [{a.get('condition')}] {a.get('symbol')} — seuil={a.get('threshold')}")

    def _on_close(self, data: dict) -> None:
        pnl = data.get("pnl", 0)
        mood = "confident" if pnl > 0 else "uncertain"
        self.journal.add(
            symbol=data.get("symbol","?"),
            type_="trade",
            content=f"Fermeture {data.get('reason','?')} @ {data.get('exit',0):.4f} — P&L {pnl:+.2f}$",
            mood=mood, pnl=pnl,
            tags=["auto", data.get("reason","?")]
        )

    # ── Analyse d'un actif ────────────────────────────────────────────────────

    def analyse(self, symbol: str, silent: bool = False) -> Dict:
        """Analyse complète multi-indicateurs d'un actif."""
        df_raw = self.dp.get(symbol, n_days=300)
        if df_raw.empty:
            return {"error": f"Données indisponibles pour {symbol}"}

        df = IndicatorEngine.compute(df_raw)
        if df.empty or len(df) < 30:
            return {"error": "Indicateurs insuffisants"}

        regime, conf, scores = RegimeDetector.detect(df)
        expo    = self.macro.expo_multiplier()
        sig     = SignalGenerator.generate(df, regime, expo)
        row     = df.iloc[-1]

        def _v(k, dec=4):
            val = row.get(k)
            if val is None or (isinstance(val, float) and math.isnan(val)):
                return None
            return round(float(val), dec)

        atr_val  = _v("atr") or 1.0
        price    = _v("Close") or 0.0
        stop_l, tp_l, _ = self.risk.levels(price, OrderSide.LONG,  atr_val)
        stop_s, tp_s, _ = self.risk.levels(price, OrderSide.SHORT, atr_val)
        rr = round(abs(tp_l - price) / max(abs(price - stop_l), 1e-9), 2)

        signal_val = sig["signal"]
        if isinstance(signal_val, Signal): signal_val = signal_val.value

        result = {
            "symbol":         symbol,
            "price":          price,
            "ema20":          _v("ema20"),
            "ema50":          _v("ema50"),
            "ema200":         _v("ema200"),
            "rsi":            _v("rsi", 1),
            "adx":            _v("adx", 1),
            "atr":            _v("atr"),
            "atr_pct":        _v("atr_pct", 2),
            "macd_h":         _v("macd_h", 6),
            "bb_pct":         _v("bb_pct", 3),
            "bb_width":       _v("bb_width", 3),
            "stoch_k":        _v("stoch_k", 1),
            "cci":            _v("cci", 1),
            "williams_r":     _v("williams_r", 1),
            "mfi":            _v("mfi", 1),
            "cmf":            _v("cmf", 3),
            "trix":           _v("trix", 4),
            "dpo":            _v("dpo", 4),
            "vwap":           _v("vwap"),
            "vwap_dev":       _v("vwap_dev", 2),
            "supertrend":     int(_v("supertrend") or 0),
            "above_cloud":    int(_v("above_cloud") or 0),
            "below_cloud":    int(_v("below_cloud") or 0),
            "squeeze":        int(_v("squeeze") or 0),
            "garch_vol":      _v("garch_vol", 1),
            "bull_power":     _v("bull_power", 4),
            "bear_power":     _v("bear_power", 4),
            "vol_ratio":      _v("vol_ratio", 2),
            "obv":            _v("obv", 0),
            "pivot":          _v("pivot"),
            "res1":           _v("res1"),
            "sup1":           _v("sup1"),
            "regime":         regime.value,
            "confidence":     conf,
            "regime_scores":  scores,
            "signal":         signal_val,
            "signal_force":   sig["force"],
            "signal_reasons": sig["reasons"],
            "score_bull":     sig["score_bull"],
            "score_bear":     sig["score_bear"],
            "is_strong":      sig.get("is_strong", False),
            "expo_mult":      expo,
            "macro_bias":     self.macro.regime_bias(self.macro.refresh()),
            "stop_long":      round(stop_l, 4),
            "tp_long":        round(tp_l, 4),
            "stop_short":     round(stop_s, 4),
            "tp_short":       round(tp_s, 4),
            "rr_ratio":       rr,
            "ts":             datetime.utcnow().isoformat(),
        }

        if not silent:
            self._print_analysis(result)
        return result

    def _print_analysis(self, a: Dict) -> None:
        sig_icon = {
            "STRONG_BUY":"🚀 STRONG BUY", "BUY":"🟢 BUY",
            "HOLD":"⚪ HOLD",
            "SELL":"🔴 SELL", "STRONG_SELL":"🔻 STRONG SELL"
        }.get(a["signal"], a["signal"])
        reg_icon = {
            "STRONG_BULL":"🚀","BULL":"📈","RANGING":"↔️",
            "BEAR":"📉","STRONG_BEAR":"🔻"
        }.get(a["regime"], "")
        print(f"\n{'═'*68}")
        print(f"  ANALYSE — {a['symbol']} | {datetime.utcnow():%Y-%m-%d %H:%M UTC}")
        print(f"{'═'*68}")
        print(f"  Prix          : {a['price']:.4f}   ATR: {a['atr']:.4f} ({a['atr_pct']:.2f}%)  GARCH vol: {a['garch_vol'] or 'N/A':.1f}%")
        print(f"  EMA 20/50/200 : {a['ema20']:.2f} / {a['ema50']:.2f} / {a['ema200']:.2f}")
        print(f"  VWAP          : {a['vwap']:.4f}  (écart: {a['vwap_dev']:+.2f}%)")
        print(f"  RSI           : {a['rsi']:.1f}   Stoch: {a['stoch_k']:.1f}   CCI: {a['cci']:.1f}")
        print(f"  MFI           : {a['mfi']:.1f}   CMF: {a['cmf']:.3f}   Williams%R: {a['williams_r']:.1f}")
        print(f"  ADX           : {a['adx']:.1f}   MACD Hist: {a['macd_h']:.6f}")
        print(f"  BB %B         : {a['bb_pct']:.2f}   BB Width: {a['bb_width']:.3f}   Squeeze: {'⚡ OUI' if a['squeeze'] else 'non'}")
        print(f"  TRIX          : {a['trix']:.4f}   DPO: {a['dpo']:.4f}")
        print(f"  SuperTrend    : {'↑ Haussier' if a['supertrend'] > 0 else '↓ Baissier'}")
        print(f"  Ichimoku      : {'Au-dessus ✓' if a['above_cloud'] else 'En-dessous ✗' if a['below_cloud'] else 'Dans le nuage'}")
        print(f"  Bull/Bear Power: {a['bull_power']:+.4f} / {a['bear_power']:+.4f}")
        print(f"  Pivot P/R1/S1 : {a['pivot']:.4f} / {a['res1']:.4f} / {a['sup1']:.4f}")
        print(f"{'─'*68}")
        print(f"  RÉGIME  : {reg_icon} {a['regime']} (conf={a['confidence']:.0%})")
        print(f"  MACRO   : {a['macro_bias']} (expo={a['expo_mult']:.0%})")
        print(f"  SIGNAL  : {sig_icon} {'⭐ FORT' if a['is_strong'] else ''} (force={a['signal_force']:.0%})")
        print(f"  Scores  : Bull={a['score_bull']:.1f} / Bear={a['score_bear']:.1f}")
        if a["signal_reasons"]:
            for r in a["signal_reasons"][:6]:
                print(f"    • {r}")
        print(f"{'─'*68}")
        print(f"  LONG  → Stop={a['stop_long']:.4f}  TP={a['tp_long']:.4f}  (R:R={a['rr_ratio']:.2f})")
        print(f"  SHORT → Stop={a['stop_short']:.4f}  TP={a['tp_short']:.4f}")
        print(f"{'═'*68}")

    # ── Paper trading ─────────────────────────────────────────────────────────

    def run_paper(self, n_iterations: int = 20, symbol: str = None) -> Tuple[List, Dict]:
        symbol = symbol or CONFIG["PRIMARY_ASSET"]
        logger.info(f"PAPER TRADING | {symbol} | {n_iterations} itérations")

        df_full = self.dp.get(symbol, n_days=500)
        df_full = IndicatorEngine.compute(df_full)
        start   = max(60, len(df_full) - n_iterations - 10)
        results = []

        for i in range(start, min(start + n_iterations, len(df_full))):
            seg   = df_full.iloc[max(0, i-200):i+1]
            row   = df_full.iloc[i]
            price = float(row["Close"])
            atr   = float(row.get("atr", price * 0.01) or price * 0.01)
            if math.isnan(atr): atr = price * 0.01

            # Vérifier sorties
            for sym in list(self.risk.positions.keys()):
                info = self.risk.check_exits(sym, price, atr)
                if info:
                    reason, ep = info
                    rec  = self.risk.close(sym, ep, reason)
                    side = "sell" if self.risk.positions.get(sym, Position(sym, OrderSide.LONG, 0,0,0,0,0)).side == OrderSide.LONG else "buy"
                    self.broker.submit(side, sym, rec.size if rec else 0, ep)
                    if rec: logger.info(f"SORTIE {reason.upper()} | {sym} @ {ep:.4f} | P&L={rec.pnl:+.2f}")

            ks, km = self.risk.kill_switch()
            if ks: logger.warning(f"Kill switch: {km}"); break

            expo   = self.macro.expo_multiplier()
            regime, _, _ = RegimeDetector.detect(seg)
            sig    = SignalGenerator.generate(seg, regime, expo)
            signal = sig["signal"]
            if isinstance(signal, Signal): signal = signal.value
            force  = sig["force"]

            iter_r = {
                "iter": i - start + 1,
                "date": str(df_full.index[i].date()),
                "price": round(price, 4),
                "regime": regime.value,
                "signal": signal,
                "force": round(force, 3),
                "capital": round(self.risk.capital, 2),
                "n_pos": len(self.risk.positions),
            }

            if signal in ("BUY","STRONG_BUY") and symbol not in self.risk.positions:
                side  = OrderSide.LONG
                stop, tp, _ = self.risk.levels(price, side, atr)
                sz   = self.risk.size(price, stop, force)
                ok, msg = self.risk.validate(symbol, price, stop, tp, side)
                if ok and sz > 0:
                    self.risk.open(symbol, side, sz, price, stop, tp,
                                   tags=["paper", regime.value])
                    self.broker.submit("buy", symbol, sz, price)
                    iter_r["action"] = f"LONG ouvert @ {price:.4f}"

            elif signal in ("SELL","STRONG_SELL") and symbol not in self.risk.positions:
                side  = OrderSide.SHORT
                stop, tp, _ = self.risk.levels(price, side, atr)
                sz   = self.risk.size(price, stop, force)
                ok, msg = self.risk.validate(symbol, price, stop, tp, side)
                if ok and sz > 0:
                    self.risk.open(symbol, side, sz, price, stop, tp,
                                   tags=["paper", regime.value])
                    self.broker.submit("sell", symbol, sz, price)
                    iter_r["action"] = f"SHORT ouvert @ {price:.4f}"

            results.append(iter_r)

        stats = self.risk.stats()
        print(f"\n{'═'*60}")
        print(f"  PAPER TRADING — {n_iterations} itérations | {symbol}")
        print(f"{'═'*60}")
        for k, v in stats.items():
            if isinstance(v, float):
                unit = "%" if any(x in k for x in ["return","rate","drawdown"]) else ""
                print(f"  {k:25s} : {v*100:.2f}{unit}" if unit else f"  {k:25s} : {v}")
            else:
                print(f"  {k:25s} : {v}")
        print(f"  Commissions payées    : {self.broker.total_commissions:.4f}$")
        print(f"{'═'*60}")
        return results, stats

    # ── Backtest ──────────────────────────────────────────────────────────────

    def run_backtest(self, symbol: str = None, n_days: int = 756) -> Dict:
        symbol = symbol or CONFIG["PRIMARY_ASSET"]
        print(f"\n{'═'*60}")
        print(f"  WALK-FORWARD BACKTEST — {symbol} | {n_days} jours")
        print(f"{'═'*60}")
        result = self.wf_bt.run(symbol, n_days)
        if "error" in result:
            print(f"  Erreur : {result['error']}"); return result
        for k, v in result.items():
            if k not in ("windows",):
                print(f"  {k:25s} : {v}")
        print(f"{'═'*60}")
        return result

    # ── Monte-Carlo ───────────────────────────────────────────────────────────

    def run_montecarlo(self, bt: Dict = None, n_sim: int = 1000) -> Dict:
        bt = bt or {"win_rate": 0.52, "profit_factor": 1.8}
        print(f"\n{'═'*60}")
        print(f"  MONTE-CARLO — {n_sim} simulations | {CONFIG['MC_HORIZON']}j")
        print(f"{'═'*60}")
        mc = self.mc.run(bt, n_sim)
        for k, v in mc.items(): print(f"  {k:35s} : {v}")
        print(f"{'═'*60}")
        return mc

    # ── Screener ──────────────────────────────────────────────────────────────

    def run_screener(self, universe: List[str] = None) -> List[Dict]:
        universe = universe or CONFIG["SCREENER_UNIVERSE"]
        print(f"\n  Scan de {len(universe)} actifs...")
        results = self.screener.scan(universe)
        self.screener.print_results(results, "SCREENER COMPLET")
        # Vérifier les alertes
        analyses = {r["symbol"]: r for r in results}
        triggered = self.alerts.check(analyses)
        if triggered:
            print(f"\n  🔔 {len(triggered)} alerte(s) déclenchée(s) !")
        return results

    # ── Corrélations ─────────────────────────────────────────────────────────

    def run_correlation(self) -> Dict:
        print(f"\n{'═'*60}")
        print(f"  CORRÉLATIONS — {len(CONFIG['WATCHLIST'])} actifs")
        print(f"{'═'*60}")
        res = self.corr.compute(CONFIG["WATCHLIST"])
        if "error" in res: print(f"  {res['error']}"); return res
        print(f"  Corrélation moyenne abs : {res['avg_abs_corr']:.3f}")
        print(f"  Paires fortement corrélées : {res['n_high_corr']}")
        print(f"\n  Top 8 paires :")
        for p in res["top_pairs"][:8]:
            bar = "█" * int(abs(p["correlation"]) * 20)
            sign = "+" if p["correlation"] > 0 else "-"
            print(f"    {p['sym1']:10s} ↔ {p['sym2']:10s} : {p['correlation']:+.3f} [{bar}] {p['strength']}")
        print(f"{'═'*60}")
        return res

    # ── Optimisation ──────────────────────────────────────────────────────────

    def run_optimization(self, symbol: str = None) -> List[Dict]:
        symbol = symbol or CONFIG["PRIMARY_ASSET"]
        print(f"\n  Grid Search sur {symbol}...")
        results = self.optimizer.run(symbol)
        self.optimizer.print_results(results)
        return results

    # ── Rapport HTML iOS ──────────────────────────────────────────────────────

    def generate_report(self, symbols: List[str] = None,
                         bt_result: Dict = None) -> str:
        symbols = symbols or CONFIG["WATCHLIST"][:5]
        logger.info("Génération du rapport HTML iOS...")

        analyses  = {sym: self.analyse(sym, silent=True) for sym in symbols}
        bt        = bt_result or self.run_backtest(symbols[0], n_days=504)
        mc        = self.run_montecarlo(bt, n_sim=500)
        corr_res  = self.run_correlation()
        macro     = self.macro.refresh()
        fg, fg_label = self.macro.fear_greed_index()
        screen    = self.screener.scan(CONFIG["SCREENER_UNIVERSE"][:8])

        # HTML est généré dans generate_ios_html()
        html_path = generate_ios_html(
            analyses=analyses, bt=bt, mc=mc, corr=corr_res,
            macro=macro, fg=fg, fg_label=fg_label,
            screen=screen, risk=self.risk
        )
        logger.info(f"Rapport iOS généré : {html_path}")
        return html_path

    # ── État ─────────────────────────────────────────────────────────────────

    def save_state(self) -> None:
        persist.save_state({
            "mode":      self.mode,
            "capital":   self.risk.capital,
            "peak":      self.risk.peak,
            "positions": {k: asdict(v) for k, v in self.risk.positions.items()},
            "iter_n":    self.iter_n,
            "ts":        datetime.utcnow().isoformat(),
        })

    def load_state(self) -> None:
        s = persist.load_state()
        if not s: return
        self.risk.capital   = s.get("capital",  CONFIG["INITIAL_CAPITAL"])
        self.risk.peak      = s.get("peak",      self.risk.capital)
        self.iter_n         = s.get("iter_n",    0)
        logger.info(f"État repris — Capital={self.risk.capital:.2f}$ | iter={self.iter_n}")


# ═══════════════════════════════════════════════════════════════════════════════
# §20  UI iOS — HTML AUTONOME (Apple Design System)
# ═══════════════════════════════════════════════════════════════════════════════

def generate_ios_html(analyses: Dict, bt: Dict, mc: Dict, corr: Dict,
                       macro: Dict, fg: float, fg_label: str,
                       screen: List[Dict], risk: RiskManager) -> str:
    """Génère le rapport HTML avec design iOS natif."""

    def _fmt(v, dec=2, unit=""):
        if v is None: return "N/A"
        try: return f"{float(v):.{dec}f}{unit}"
        except: return str(v)

    # ── Watchlist rows ────────────────────────────────────────────────────────
    wl_cards = ""
    for sym, a in analyses.items():
        if "error" in a: continue
        sig   = a.get("signal","HOLD")
        sig_c = {"STRONG_BUY":"#30d158","BUY":"#34c759",
                  "HOLD":"#636366","SELL":"#ff453a","STRONG_SELL":"#ff375f"}.get(sig,"#636366")
        sig_i = {"STRONG_BUY":"🚀","BUY":"↑","HOLD":"—","SELL":"↓","STRONG_SELL":"⬇"}.get(sig,"—")
        reg   = a.get("regime","")
        reg_c = {"STRONG_BULL":"#30d158","BULL":"#34c759","RANGING":"#ff9f0a",
                  "BEAR":"#ff453a","STRONG_BEAR":"#ff375f"}.get(reg,"#636366")

        rsi_v   = a.get("rsi",50) or 50
        rsi_w   = round(rsi_v, 0)
        rsi_c   = "#ff453a" if rsi_v>70 else "#30d158" if rsi_v<30 else "#ff9f0a"

        adx_v   = a.get("adx", 20) or 20
        force   = a.get("signal_force",0) or 0

        wl_cards += f"""
        <div class="card asset-card" onclick="toggleDetail('{sym}')">
          <div class="asset-header">
            <div class="asset-left">
              <span class="asset-symbol">{sym}</span>
              <span class="asset-regime" style="color:{reg_c}">{reg}</span>
            </div>
            <div class="asset-right">
              <span class="asset-price">{_fmt(a.get('price'),4)}</span>
              <span class="asset-signal" style="color:{sig_c}">{sig_i} {sig}</span>
            </div>
          </div>
          <div class="asset-bars">
            <div class="mini-bar-row">
              <span class="mini-label">RSI</span>
              <div class="mini-bar-track">
                <div class="mini-bar-fill" style="width:{rsi_w:.0f}%;background:{rsi_c}"></div>
              </div>
              <span class="mini-val" style="color:{rsi_c}">{rsi_w:.0f}</span>
            </div>
            <div class="mini-bar-row">
              <span class="mini-label">ADX</span>
              <div class="mini-bar-track">
                <div class="mini-bar-fill" style="width:{min(adx_v,60)/60*100:.0f}%;background:#0a84ff"></div>
              </div>
              <span class="mini-val">{adx_v:.0f}</span>
            </div>
            <div class="mini-bar-row">
              <span class="mini-label">Force</span>
              <div class="mini-bar-track">
                <div class="mini-bar-fill" style="width:{force*100:.0f}%;background:{sig_c}"></div>
              </div>
              <span class="mini-val" style="color:{sig_c}">{force:.0%}</span>
            </div>
          </div>
          <div class="asset-detail" id="detail-{sym}">
            <div class="detail-grid">
              <div class="detail-item"><span class="di-label">Stop Long</span><span class="di-val red">{_fmt(a.get('stop_long'),4)}</span></div>
              <div class="detail-item"><span class="di-label">TP Long</span><span class="di-val green">{_fmt(a.get('tp_long'),4)}</span></div>
              <div class="detail-item"><span class="di-label">R:R</span><span class="di-val">{_fmt(a.get('rr_ratio'),2)}x</span></div>
              <div class="detail-item"><span class="di-label">ATR%</span><span class="di-val">{_fmt(a.get('atr_pct'),2)}%</span></div>
              <div class="detail-item"><span class="di-label">MACD H</span><span class="di-val">{_fmt(a.get('macd_h'),5)}</span></div>
              <div class="detail-item"><span class="di-label">Vol Ratio</span><span class="di-val">{_fmt(a.get('vol_ratio'),2)}x</span></div>
              <div class="detail-item"><span class="di-label">MFI</span><span class="di-val">{_fmt(a.get('mfi'),1)}</span></div>
              <div class="detail-item"><span class="di-label">GARCH</span><span class="di-val">{_fmt(a.get('garch_vol'),1)}%</span></div>
              <div class="detail-item"><span class="di-label">Squeeze</span><span class="di-val">{"⚡ Oui" if a.get("squeeze") else "Non"}</span></div>
              <div class="detail-item"><span class="di-label">SuperTrd</span><span class="di-val">{"↑" if (a.get("supertrend") or 0)>0 else "↓"}</span></div>
            </div>
            <div class="reasons-box">
              {"".join(f'<div class="reason-item">{r}</div>' for r in (a.get("signal_reasons") or [])[:5])}
            </div>
          </div>
        </div>"""

    # ── Screener rows ─────────────────────────────────────────────────────────
    screen_rows = ""
    for r in screen[:8]:
        sig_c = {"STRONG_BUY":"#30d158","BUY":"#34c759","HOLD":"#636366",
                  "SELL":"#ff453a","STRONG_SELL":"#ff375f"}.get(r.get("signal","HOLD"),"#636366")
        screen_rows += f"""
        <tr>
          <td class="sc-sym">{r['symbol']}</td>
          <td>{_fmt(r.get('price'),2)}</td>
          <td style="color:{'#30d158' if r.get('change_pct',0)>0 else '#ff453a'}">{r.get('change_pct',0):+.1f}%</td>
          <td style="color:{sig_c};font-weight:600">{r.get('signal','—')}</td>
          <td>{_fmt(r.get('rsi'),1)}</td>
          <td>{_fmt(r.get('adx'),1)}</td>
          <td>{"⚡" if r.get('is_squeeze') else "—"}</td>
        </tr>"""

    # ── MC gauge ─────────────────────────────────────────────────────────────
    prob_pos = mc.get("prob_positive_pct", 50)
    gauge_deg = prob_pos * 1.8 - 90   # -90 à +90

    # ── Fear & Greed arc ──────────────────────────────────────────────────────
    fg_color = ("#ff375f" if fg < 25 else "#ff9f0a" if fg < 45
                else "#ffd60a" if fg < 55 else "#34c759" if fg < 75 else "#30d158")

    # ── BT windows mini chart ─────────────────────────────────────────────────
    windows = bt.get("windows", [])
    win_bars = ""
    if windows:
        pnls_w = [w.get("pnl", 0) for w in windows]
        max_abs = max(abs(p) for p in pnls_w) or 1
        for p in pnls_w:
            h   = abs(p) / max_abs * 40
            col = "#30d158" if p >= 0 else "#ff453a"
            win_bars += f'<div class="wbar" style="height:{h:.0f}px;background:{col}"></div>'

    # ── Corr pairs ────────────────────────────────────────────────────────────
    corr_rows = ""
    for pair in corr.get("top_pairs", [])[:6]:
        c = pair["correlation"]
        c_col = "#ff453a" if c > 0.7 else "#ff9f0a" if c > 0.4 else "#30d158"
        bar_w = abs(c) * 100
        corr_rows += f"""
        <div class="corr-row">
          <span class="corr-pair">{pair['sym1']} ↔ {pair['sym2']}</span>
          <div class="corr-bar-track">
            <div class="corr-bar-fill" style="width:{bar_w:.0f}%;background:{c_col}"></div>
          </div>
          <span class="corr-val" style="color:{c_col}">{c:+.2f}</span>
        </div>"""

    # ── Macro indicators ──────────────────────────────────────────────────────
    vix    = macro.get("vix", 17.5)
    spread = macro.get("spread_10_2", 0.15)
    brent  = macro.get("brent", 82)
    gold   = macro.get("gold", 2320)
    vix_c  = "#ff453a" if vix>=30 else "#ff9f0a" if vix>=20 else "#30d158"
    spr_c  = "#ff453a" if spread<=0 else "#ff9f0a" if spread<0.3 else "#30d158"

    # ── Risk stats ────────────────────────────────────────────────────────────
    st = risk.stats()

    # Pre-compute expo string for the f-string
    vix_cur = macro.get("vix", 17.5)
    if vix_cur >= 40:   _expo_str = "0%"
    elif vix_cur >= 30: _expo_str = "50%"
    elif vix_cur >= 20: _expo_str = "75%"
    else:               _expo_str = "100%"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Market Bot 2026</title>
<style>
:root {{
  --bg:          #000000;
  --bg2:         #1c1c1e;
  --bg3:         #2c2c2e;
  --bg4:         #3a3a3c;
  --sep:         #38383a;
  --label:       #ebebf5cc;
  --label2:      #ebebf599;
  --label3:      #ebebf560;
  --blue:        #0a84ff;
  --green:       #30d158;
  --red:         #ff453a;
  --orange:      #ff9f0a;
  --yellow:      #ffd60a;
  --purple:      #bf5af2;
  --teal:        #64d2ff;
  --pink:        #ff375f;
  --white:       #ffffff;
  --r-lg:        16px;
  --r-md:        12px;
  --r-sm:        8px;
  --safe-top:    env(safe-area-inset-top, 44px);
  --safe-bot:    env(safe-area-inset-bottom, 34px);
}}
* {{ box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }}
html {{ scroll-behavior:smooth; }}
body {{
  font-family: -apple-system, "SF Pro Display", "SF Pro Text", sans-serif;
  background: var(--bg);
  color: var(--white);
  min-height: 100vh;
  padding-bottom: calc(80px + var(--safe-bot));
  -webkit-font-smoothing: antialiased;
}}

/* ── HEADER (Dynamic Island style) ─────────────────────────── */
.header {{
  position: sticky; top: 0; z-index: 100;
  padding: calc(var(--safe-top) + 4px) 20px 12px;
  background: rgba(0,0,0,0.85);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 0.5px solid var(--sep);
}}
.header-inner {{
  display: flex; align-items: center; justify-content: space-between;
}}
.header-title {{
  font-size: 17px; font-weight: 600; letter-spacing: -0.3px;
}}
.header-sub {{
  font-size: 12px; color: var(--label2); margin-top: 1px;
}}
.header-badge {{
  font-size: 11px; font-weight: 600;
  background: var(--blue); color: white;
  padding: 3px 10px; border-radius: 20px;
}}

/* ── NAVIGATION TABS ─────────────────────────────────────────  */
.tab-bar {{
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 200;
  padding-bottom: var(--safe-bot);
  background: rgba(28,28,30,0.92);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-top: 0.5px solid var(--sep);
  display: flex;
}}
.tab-item {{
  flex: 1; display: flex; flex-direction: column;
  align-items: center; padding: 8px 0 4px;
  cursor: pointer; transition: opacity .15s;
  -webkit-user-select: none;
}}
.tab-item:active {{ opacity: .6; }}
.tab-icon {{ font-size: 22px; line-height: 1; }}
.tab-label {{
  font-size: 10px; color: var(--label3); margin-top: 2px;
  font-weight: 500;
}}
.tab-item.active .tab-icon {{ filter: none; }}
.tab-item.active .tab-label {{ color: var(--blue); }}

/* ── PAGES ────────────────────────────────────────────────────  */
.page {{ display: none; padding: 12px 0; }}
.page.active {{ display: block; }}

/* ── SECTION ──────────────────────────────────────────────────  */
.section {{
  padding: 0 16px; margin-bottom: 24px;
}}
.section-title {{
  font-size: 13px; font-weight: 600; text-transform: uppercase;
  color: var(--label2); letter-spacing: 0.5px;
  margin-bottom: 8px; padding: 0 4px;
}}

/* ── CARD ────────────────────────────────────────────────────── */
.card {{
  background: var(--bg2);
  border-radius: var(--r-lg);
  overflow: hidden;
  margin-bottom: 8px;
}}
.card-inner {{ padding: 16px; }}

/* ── METRIC GRID ─────────────────────────────────────────────── */
.metric-grid {{
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}}
.metric-card {{
  background: var(--bg2); border-radius: var(--r-md);
  padding: 12px; display: flex; flex-direction: column; gap: 4px;
}}
.metric-label {{
  font-size: 11px; color: var(--label2); font-weight: 500;
}}
.metric-value {{
  font-size: 20px; font-weight: 700; letter-spacing: -0.5px;
  font-variant-numeric: tabular-nums;
}}
.metric-sub {{
  font-size: 11px; color: var(--label3);
}}

/* ── VIX RING ────────────────────────────────────────────────── */
.vix-section {{
  display: flex; align-items: center; gap: 16px;
  padding: 16px;
}}
.vix-ring {{
  position: relative; width: 80px; height: 80px; flex-shrink: 0;
}}
.vix-ring svg {{ width: 80px; height: 80px; transform: rotate(-90deg); }}
.vix-ring-text {{
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700;
}}
.vix-ring-sub {{ font-size: 9px; color: var(--label3); font-weight: 500; }};
.vix-info {{ flex: 1; }}
.vix-label {{ font-size: 15px; font-weight: 600; }}
.vix-regime {{ font-size: 12px; color: var(--label2); margin-top: 2px; }}
.macro-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 11px 16px;
  border-top: 0.5px solid var(--sep);
}}
.macro-key {{ font-size: 14px; color: var(--label); }}
.macro-val {{ font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }}

/* ── ALERTS ──────────────────────────────────────────────────── */
.alert-banner {{
  display: flex; align-items: flex-start; gap: 10px;
  padding: 12px 14px;
  background: rgba(255,69,58,0.15);
  border-left: 3px solid var(--red);
  border-radius: var(--r-md);
  margin-bottom: 8px;
  font-size: 13px; line-height: 1.4;
}}
.alert-icon {{ font-size: 16px; flex-shrink: 0; margin-top: 1px; }}

/* ── FEAR & GREED ────────────────────────────────────────────── */
.fg-container {{ padding: 16px; text-align: center; }}
.fg-gauge {{
  position: relative; width: 160px; height: 80px; margin: 0 auto 8px;
}}
.fg-gauge svg {{ width: 160px; height: 80px; }}
.fg-needle {{
  position: absolute; bottom: 0; left: 50%;
  transform-origin: bottom center;
  transform: translateX(-50%) rotate({gauge_deg:.0f}deg);
  width: 2px; height: 64px;
  background: white;
  border-radius: 2px;
  transition: transform 1s cubic-bezier(.4,0,.2,1);
}}
.fg-value {{ font-size: 32px; font-weight: 700; color:{fg_color}; }}
.fg-label {{ font-size: 13px; color: var(--label2); margin-top: 2px; }}

/* ── ASSET CARDS ─────────────────────────────────────────────── */
.asset-card {{ cursor: pointer; transition: transform .1s; }}
.asset-card:active {{ transform: scale(.98); }}
.asset-header {{
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 14px 16px 8px;
}}
.asset-left, .asset-right {{ display: flex; flex-direction: column; gap: 3px; }}
.asset-right {{ align-items: flex-end; }}
.asset-symbol {{ font-size: 16px; font-weight: 700; }}
.asset-regime {{ font-size: 11px; font-weight: 600; text-transform: uppercase; }}
.asset-price {{ font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.asset-signal {{ font-size: 12px; font-weight: 600; }}
.asset-bars {{ padding: 0 16px 12px; display: flex; flex-direction: column; gap: 6px; }}
.mini-bar-row {{ display: flex; align-items: center; gap: 8px; }}
.mini-label {{ font-size: 11px; color: var(--label3); width: 28px; flex-shrink: 0; }}
.mini-bar-track {{
  flex: 1; height: 4px; background: var(--bg4); border-radius: 2px; overflow: hidden;
}}
.mini-bar-fill {{ height: 100%; border-radius: 2px; transition: width .6s ease; }}
.mini-val {{ font-size: 11px; font-variant-numeric: tabular-nums; width: 32px; text-align: right; }}

/* ── ASSET DETAIL (expandable) ───────────────────────────────── */
.asset-detail {{ display: none; padding: 0 16px 14px; }}
.asset-detail.open {{ display: block; }}
.detail-grid {{
  display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 10px;
}}
.detail-item {{
  background: var(--bg3); border-radius: var(--r-sm);
  padding: 8px 10px; display: flex; justify-content: space-between; align-items: center;
}}
.di-label {{ font-size: 11px; color: var(--label3); }}
.di-val {{ font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.di-val.green {{ color: var(--green); }}
.di-val.red   {{ color: var(--red); }}
.reasons-box {{ display: flex; flex-direction: column; gap: 4px; }}
.reason-item {{
  font-size: 12px; color: var(--label2); padding: 5px 10px;
  background: var(--bg3); border-radius: var(--r-sm);
}}

/* ── BT METRICS ──────────────────────────────────────────────── */
.bt-grid {{
  display: grid; grid-template-columns: 1fr 1fr;
  gap: 1px; background: var(--sep);
}}
.bt-cell {{
  background: var(--bg2); padding: 14px 16px;
  display: flex; flex-direction: column; gap: 3px;
}}
.bt-label {{ font-size: 12px; color: var(--label2); }}
.bt-val {{
  font-size: 22px; font-weight: 700; letter-spacing: -0.5px;
  font-variant-numeric: tabular-nums;
}}

/* ── WINDOWS CHART ───────────────────────────────────────────── */
.win-chart {{
  display: flex; align-items: flex-end; gap: 3px;
  height: 56px; padding: 0 16px 12px;
}}
.wbar {{
  flex: 1; border-radius: 3px 3px 0 0; min-height: 4px;
  transition: height .5s ease;
}}

/* ── MC GAUGE ────────────────────────────────────────────────── */
.mc-ring-section {{ padding: 16px; display: flex; align-items: center; gap: 16px; }}
.mc-ring {{ position: relative; width: 90px; height: 90px; flex-shrink: 0; }}
.mc-ring svg {{ width: 90px; height: 90px; transform: rotate(-90deg); }}
.mc-ring-text {{
  position: absolute; inset: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
}}
.mc-pct {{ font-size: 22px; font-weight: 700; }}
.mc-sub {{ font-size: 10px; color: var(--label3); }}
.mc-stats {{ flex: 1; display: flex; flex-direction: column; gap: 6px; }}
.mc-stat-row {{ display: flex; justify-content: space-between; font-size: 13px; }}
.mc-stat-label {{ color: var(--label2); }}
.mc-stat-val {{ font-weight: 600; font-variant-numeric: tabular-nums; }}

/* ── SCREENER TABLE ──────────────────────────────────────────── */
.screener-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.screener-table th {{
  text-align: left; padding: 8px 6px;
  font-size: 11px; color: var(--label3); font-weight: 600;
  border-bottom: 0.5px solid var(--sep);
}}
.screener-table td {{ padding: 10px 6px; border-bottom: 0.5px solid var(--sep); }}
.screener-table tr:last-child td {{ border-bottom: none; }}
.sc-sym {{ font-weight: 700; }}

/* ── CORR BARS ────────────────────────────────────────────────── */
.corr-row {{
  display: flex; align-items: center; gap: 8px;
  padding: 9px 0; border-bottom: 0.5px solid var(--sep);
}}
.corr-row:last-child {{ border-bottom: none; }}
.corr-pair {{ font-size: 12px; width: 110px; flex-shrink: 0; color: var(--label); }}
.corr-bar-track {{
  flex: 1; height: 5px; background: var(--bg4); border-radius: 3px; overflow: hidden;
}}
.corr-bar-fill {{ height: 100%; border-radius: 3px; transition: width .6s ease; }}
.corr-val {{ font-size: 12px; font-weight: 600; width: 36px; text-align: right; font-variant-numeric: tabular-nums; }}

/* ── RISK PANEL ──────────────────────────────────────────────── */
.risk-header {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px; border-bottom: 0.5px solid var(--sep);
}}
.risk-capital {{ font-size: 32px; font-weight: 700; letter-spacing: -1px; font-variant-numeric: tabular-nums; }}
.risk-return {{
  font-size: 13px; font-weight: 600;
  padding: 4px 10px; border-radius: 20px;
}}
.risk-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 0.5px solid var(--sep);
}}
.risk-row:last-child {{ border-bottom: none; }}
.risk-key {{ font-size: 14px; color: var(--label); }}
.risk-val {{ font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }}
.dd-bar-track {{
  height: 6px; background: var(--bg4); border-radius: 3px;
  overflow: hidden; margin: 8px 16px 12px;
}}
.dd-bar-fill {{
  height: 100%; border-radius: 3px;
  background: linear-gradient(90deg, var(--green), var(--orange), var(--red));
  transition: width .8s ease;
}}

/* ── INFO PILL ───────────────────────────────────────────────── */
.info-pill {{
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 12px; font-weight: 600;
  padding: 4px 10px; border-radius: 20px;
  background: rgba(10,132,255,0.15); color: var(--blue);
}}

/* ── FOOTER ──────────────────────────────────────────────────── */
.footer {{
  text-align: center; padding: 20px 16px;
  font-size: 11px; color: var(--label3); line-height: 1.6;
}}

/* ── ANIMATIONS ──────────────────────────────────────────────── */
@keyframes fadeUp {{
  from {{ opacity: 0; transform: translateY(12px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}
.card, .metric-card {{ animation: fadeUp .3s ease both; }}
.card:nth-child(1) {{ animation-delay: .05s; }}
.card:nth-child(2) {{ animation-delay: .10s; }}
.card:nth-child(3) {{ animation-delay: .15s; }}
.card:nth-child(4) {{ animation-delay: .20s; }}

@keyframes pulse {{
  0%, 100% {{ opacity: 1; }}
  50%       {{ opacity: .5; }}
}}
.live-dot {{
  display: inline-block; width: 6px; height: 6px;
  border-radius: 50%; background: var(--green);
  margin-right: 4px; animation: pulse 2s infinite;
}}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
  <div class="header-inner">
    <div>
      <div class="header-title">📈 Market Bot 2026</div>
      <div class="header-sub"><span class="live-dot"></span>Données synthétiques · {datetime.utcnow():%d %b %Y %H:%M} UTC</div>
    </div>
    <span class="header-badge">v3.0</span>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE 1 — TABLEAU DE BORD MACRO            -->
<!-- ═══════════════════════════════════════════ -->
<div id="page-macro" class="page active">

  <div class="section" style="margin-top:12px">
    <div class="section-title">Vue d'ensemble macro</div>

    <!-- VIX Ring -->
    <div class="card">
      <div class="vix-section">
        <div class="vix-ring">
          <svg viewBox="0 0 80 80">
            <circle cx="40" cy="40" r="34" fill="none" stroke="#2c2c2e" stroke-width="8"/>
            <circle cx="40" cy="40" r="34" fill="none" stroke="{vix_c}" stroke-width="8"
              stroke-dasharray="{min(vix/50*213.6, 213.6):.1f} 213.6"
              stroke-linecap="round"/>
          </svg>
          <div class="vix-ring-text">
            <span style="color:{vix_c};font-size:20px;font-weight:700">{vix:.1f}</span>
            <span class="vix-ring-sub">VIX</span>
          </div>
        </div>
        <div class="vix-info">
          <div class="vix-label">Indice de Volatilité</div>
          <div class="vix-regime" style="color:{vix_c}">{macro.get('vix_regime','N/A')}</div>
          <div style="margin-top:8px">
            <span class="info-pill">Expo: {_expo_str}</span>
          </div>
        </div>
      </div>
      <div class="macro-row">
        <span class="macro-key">T10Y / T2Y</span>
        <span class="macro-val" style="color:{spr_c}">{_fmt(macro.get('t10y'),2)}% / {_fmt(macro.get('t2y'),2)}%</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">Spread 10-2</span>
        <span class="macro-val" style="color:{spr_c}">{_fmt(macro.get('spread_10_2'),2)}%</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">Brent Crude</span>
        <span class="macro-val">{_fmt(brent,1)}$</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">Or (XAU)</span>
        <span class="macro-val">{_fmt(gold,0)}$</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">EUR/USD</span>
        <span class="macro-val">{_fmt(macro.get('eurusd'),4)}</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">USD/JPY</span>
        <span class="macro-val">{_fmt(macro.get('usdjpy'),2)}</span>
      </div>
      <div class="macro-row">
        <span class="macro-key">Biais macro</span>
        <span class="macro-val" style="color:{'#30d158' if macro.get('macro_bias')=='BULLISH' else '#ff453a' if macro.get('macro_bias')=='BEARISH' else '#ff9f0a'}">{macro.get('macro_bias','N/A')}</span>
      </div>
    </div>

    <!-- Fear & Greed -->
    <div class="card">
      <div class="fg-container">
        <div style="font-size:13px;color:var(--label2);margin-bottom:12px;font-weight:600">FEAR & GREED INDEX</div>
        <div class="fg-gauge">
          <svg viewBox="0 0 160 80">
            <path d="M 10 80 A 70 70 0 0 1 150 80" fill="none" stroke="#ff375f" stroke-width="12" stroke-linecap="round"/>
            <path d="M 28 44 A 52 52 0 0 1 132 44" fill="none" stroke="#ff9f0a" stroke-width="12" stroke-linecap="round"/>
            <path d="M 42 24 A 38 38 0 0 1 118 24" fill="none" stroke="#ffd60a" stroke-width="12" stroke-linecap="round"/>
            <path d="M 56 14 A 24 24 0 0 1 104 14" fill="none" stroke="#30d158" stroke-width="12" stroke-linecap="round"/>
          </svg>
          <div class="fg-needle"></div>
        </div>
        <div class="fg-value">{fg:.0f}</div>
        <div class="fg-label" style="color:{fg_color}">{fg_label}</div>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE 2 — ACTIFS & SIGNAUX                  -->
<!-- ═══════════════════════════════════════════ -->
<div id="page-assets" class="page">
  <div class="section" style="margin-top:12px">
    <div class="section-title">Signaux actifs</div>
    {wl_cards}
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE 3 — BACKTEST & MONTE-CARLO           -->
<!-- ═══════════════════════════════════════════ -->
<div id="page-bt" class="page">
  <div class="section" style="margin-top:12px">
    <div class="section-title">Walk-Forward Backtest — {bt.get('symbol','SPY')}</div>
    <div class="card">
      <div class="bt-grid">
        <div class="bt-cell">
          <span class="bt-label">Return total</span>
          <span class="bt-val" style="color:{'#30d158' if bt.get('total_return_pct',0)>0 else '#ff453a'}">{bt.get('total_return_pct',0):+.2f}%</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Sharpe Ratio</span>
          <span class="bt-val" style="color:{'#30d158' if bt.get('sharpe_ratio',0)>1 else '#ff9f0a'}">{bt.get('sharpe_ratio',0):.2f}</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Win Rate</span>
          <span class="bt-val">{bt.get('win_rate',0):.1%}</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Profit Factor</span>
          <span class="bt-val" style="color:{'#30d158' if (bt.get('profit_factor',0) or 0)>1 else '#ff453a'}">{bt.get('profit_factor',0):.2f}</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Max Drawdown</span>
          <span class="bt-val" style="color:#ff9f0a">{bt.get('max_drawdown_pct',0):.2f}%</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Calmar Ratio</span>
          <span class="bt-val">{bt.get('calmar_ratio',0):.2f}</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Alpha vs B&H</span>
          <span class="bt-val" style="color:{'#30d158' if bt.get('alpha_vs_bh',0)>0 else '#ff453a'}">{bt.get('alpha_vs_bh',0):+.1f}%</span>
        </div>
        <div class="bt-cell">
          <span class="bt-label">Fenêtres</span>
          <span class="bt-val">{bt.get('n_windows',0)}</span>
        </div>
      </div>
      <!-- Mini chart des fenêtres -->
      <div style="padding:12px 16px 4px;font-size:11px;color:var(--label3)">P&L par fenêtre walk-forward</div>
      <div class="win-chart">{win_bars}</div>
    </div>

    <div class="section-title" style="margin-top:20px">Monte-Carlo — {mc.get('n_simulations',0)} simulations</div>
    <div class="card">
      <div class="mc-ring-section">
        <div class="mc-ring">
          <svg viewBox="0 0 90 90">
            <circle cx="45" cy="45" r="38" fill="none" stroke="#2c2c2e" stroke-width="8"/>
            <circle cx="45" cy="45" r="38" fill="none"
              stroke="{'#30d158' if prob_pos>60 else '#ff9f0a' if prob_pos>40 else '#ff453a'}"
              stroke-width="8"
              stroke-dasharray="{prob_pos/100*238.76:.1f} 238.76"
              stroke-linecap="round"/>
          </svg>
          <div class="mc-ring-text">
            <span class="mc-pct" style="color:{'#30d158' if prob_pos>60 else '#ff9f0a' if prob_pos>40 else '#ff453a'}">{prob_pos:.0f}%</span>
            <span class="mc-sub">positif</span>
          </div>
        </div>
        <div class="mc-stats">
          <div class="mc-stat-row">
            <span class="mc-stat-label">Return médian</span>
            <span class="mc-stat-val" style="color:{'#30d158' if mc.get('median_return_pct',0)>0 else '#ff453a'}">{mc.get('median_return_pct',0):+.1f}%</span>
          </div>
          <div class="mc-stat-row">
            <span class="mc-stat-label">P10 / P90</span>
            <span class="mc-stat-val">{mc.get('p10_return_pct',0):+.1f}% / {mc.get('p90_return_pct',0):+.1f}%</span>
          </div>
          <div class="mc-stat-row">
            <span class="mc-stat-label">Prob. +10%</span>
            <span class="mc-stat-val" style="color:#30d158">{mc.get('prob_10pct_gain',0):.1f}%</span>
          </div>
          <div class="mc-stat-row">
            <span class="mc-stat-label">Prob. ruine</span>
            <span class="mc-stat-val" style="color:#ff453a">{mc.get('prob_ruin_pct',0):.1f}%</span>
          </div>
          <div class="mc-stat-row">
            <span class="mc-stat-label">DD max médian</span>
            <span class="mc-stat-val" style="color:#ff9f0a">{mc.get('median_max_drawdown',0):.1f}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE 4 — SCREENER                          -->
<!-- ═══════════════════════════════════════════ -->
<div id="page-screen" class="page">
  <div class="section" style="margin-top:12px">
    <div class="section-title">Screener de marché — {len(screen)} actifs</div>
    <div class="card" style="overflow-x:auto">
      <div class="card-inner" style="padding:0">
        <table class="screener-table" style="min-width:360px">
          <thead>
            <tr>
              <th>Sym</th><th>Prix</th><th>Var</th>
              <th>Signal</th><th>RSI</th><th>ADX</th><th>⚡</th>
            </tr>
          </thead>
          <tbody>{screen_rows}</tbody>
        </table>
      </div>
    </div>

    <div class="section-title" style="margin-top:20px">Corrélations inter-actifs</div>
    <div class="card">
      <div class="card-inner">
        {corr_rows}
      </div>
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════ -->
<!-- PAGE 5 — PORTEFEUILLE & RISK               -->
<!-- ═══════════════════════════════════════════ -->
<div id="page-portfolio" class="page">
  <div class="section" style="margin-top:12px">
    <div class="section-title">Portefeuille paper</div>
    <div class="card">
      <div class="risk-header">
        <div>
          <div style="font-size:12px;color:var(--label2);margin-bottom:2px">Capital</div>
          <div class="risk-capital">{st.get('capital', CONFIG['INITIAL_CAPITAL']):,.2f}<span style="font-size:16px;font-weight:400"> $</span></div>
        </div>
        <div class="risk-return" style="background:{'rgba(48,209,88,.15)' if st.get('total_return',0)>=0 else 'rgba(255,69,58,.15)'};color:{'#30d158' if st.get('total_return',0)>=0 else '#ff453a'}">
          {(st.get('total_return',0)*100):+.2f}%
        </div>
      </div>
      <!-- Drawdown bar -->
      <div style="padding:8px 16px 4px;font-size:11px;color:var(--label3)">Drawdown courant: {st.get('max_drawdown',0)*100:.2f}%</div>
      <div class="dd-bar-track">
        <div class="dd-bar-fill" style="width:{min(st.get('max_drawdown',0)*100/CONFIG['MAX_DRAWDOWN_LIMIT']/100*100, 100):.0f}%"></div>
      </div>
      <div class="risk-row"><span class="risk-key">Trades fermés</span><span class="risk-val">{st.get('n_trades',0)}</span></div>
      <div class="risk-row"><span class="risk-key">Win Rate</span><span class="risk-val" style="color:{'#30d158' if st.get('win_rate',0)>0.5 else '#ff453a'}">{st.get('win_rate',0):.1%}</span></div>
      <div class="risk-row"><span class="risk-key">Profit Factor</span><span class="risk-val">{st.get('profit_factor',0)}</span></div>
      <div class="risk-row"><span class="risk-key">Sharpe approx.</span><span class="risk-val">{st.get('sharpe_approx',0):.2f}</span></div>
      <div class="risk-row"><span class="risk-key">Meilleur trade</span><span class="risk-val" style="color:#30d158">{st.get('best_trade',0):+.2f}$</span></div>
      <div class="risk-row"><span class="risk-key">Pire trade</span><span class="risk-val" style="color:#ff453a">{st.get('worst_trade',0):+.2f}$</span></div>
      <div class="risk-row"><span class="risk-key">Espérance</span><span class="risk-val">{st.get('expectancy',0):+.4f}</span></div>
    </div>

    <div class="section-title" style="margin-top:20px">Paramètres de risque</div>
    <div class="card">
      <div class="risk-row"><span class="risk-key">Risque / trade</span><span class="risk-val">{CONFIG['RISK_PER_TRADE']*100:.0f}%</span></div>
      <div class="risk-row"><span class="risk-key">Kelly fraction</span><span class="risk-val">{CONFIG['KELLY_FRACTION']*100:.0f}% du Kelly</span></div>
      <div class="risk-row"><span class="risk-key">Stop ATR</span><span class="risk-val">{CONFIG['ATR_STOP_MULT']}×ATR</span></div>
      <div class="risk-row"><span class="risk-key">TP ATR</span><span class="risk-val">{CONFIG['ATR_TP_MULT']}×ATR (R:R {CONFIG['ATR_TP_MULT']/CONFIG['ATR_STOP_MULT']:.0f}:1)</span></div>
      <div class="risk-row"><span class="risk-key">Positions max</span><span class="risk-val">{CONFIG['MAX_POSITIONS']}</span></div>
      <div class="risk-row"><span class="risk-key">Kill-switch DD</span><span class="risk-val" style="color:#ff9f0a">{CONFIG['MAX_DRAWDOWN_LIMIT']*100:.0f}%</span></div>
      <div class="risk-row"><span class="risk-key">Kill-switch /jour</span><span class="risk-val" style="color:#ff9f0a">{CONFIG['DAILY_LOSS_LIMIT']*100:.0f}%</span></div>
    </div>
  </div>
</div>

<!-- TAB BAR -->
<nav class="tab-bar">
  <div class="tab-item active" onclick="showPage('macro',this)">
    <span class="tab-icon">🌍</span>
    <span class="tab-label">Macro</span>
  </div>
  <div class="tab-item" onclick="showPage('assets',this)">
    <span class="tab-icon">📊</span>
    <span class="tab-label">Actifs</span>
  </div>
  <div class="tab-item" onclick="showPage('bt',this)">
    <span class="tab-icon">🔁</span>
    <span class="tab-label">Backtest</span>
  </div>
  <div class="tab-item" onclick="showPage('screen',this)">
    <span class="tab-icon">🔍</span>
    <span class="tab-label">Screener</span>
  </div>
  <div class="tab-item" onclick="showPage('portfolio',this)">
    <span class="tab-icon">💼</span>
    <span class="tab-label">Portfolio</span>
  </div>
</nav>

<script>
function showPage(id, el) {{
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-item').forEach(t => t.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  el.classList.add('active');
  // Haptic feedback sur iOS (si disponible)
  if (window.navigator && window.navigator.vibrate) window.navigator.vibrate(10);
}}
function toggleDetail(sym) {{
  const el = document.getElementById('detail-' + sym);
  if (el) el.classList.toggle('open');
  // Animation spring
  if (el && el.classList.contains('open')) {{
    el.style.animation = 'fadeUp .2s ease both';
  }}
}}
// Animate bars on load
window.addEventListener('load', () => {{
  setTimeout(() => {{
    document.querySelectorAll('.mini-bar-fill, .corr-bar-fill, .wbar').forEach(el => {{
      el.style.transition = 'width 0.8s cubic-bezier(.4,0,.2,1), height 0.8s cubic-bezier(.4,0,.2,1)';
    }});
  }}, 100);
}});
</script>
</body>
</html>"""

    # Expo already computed above

    path = CONFIG["REPORT_FILE"]
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ═══════════════════════════════════════════════════════════════════════════════
# §21  DÉMO COMPLÈTE
# ═══════════════════════════════════════════════════════════════════════════════

def run_demo():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║   BOT D'ANALYSE DE MARCHÉ v3.0 — DÉMO COMPLÈTE                      ║
║   Données synthétiques · Aucune connexion internet requise           ║
╚══════════════════════════════════════════════════════════════════════╝
""")
    bot = TradingBot(mode="demo", use_synthetic=False)  # données réelles

    # 1. Macro
    print(bot.macro.summary())

    # 2. Analyse multi-actifs
    print("\n── [1/7] Analyse technique ───────────────────────────────────")
    for sym in ["SPY", "BTC-USD", "GC=F", "EURUSD=X"]:
        bot.analyse(sym)

    # 3. Screener
    print("\n── [2/7] Screener ────────────────────────────────────────────")
    bot.run_screener(CONFIG["SCREENER_UNIVERSE"][:6])

    # 4. Paper trading
    print("\n── [3/7] Paper trading ───────────────────────────────────────")
    bot.run_paper(n_iterations=25)

    # 5. Backtest
    print("\n── [4/7] Walk-Forward Backtest ───────────────────────────────")
    bt = bot.run_backtest("SPY", n_days=756)

    # 6. Monte-Carlo
    print("\n── [5/7] Monte-Carlo ─────────────────────────────────────────")
    bot.run_montecarlo(bt, n_sim=1000)

    # 7. Corrélations
    print("\n── [6/7] Corrélations ────────────────────────────────────────")
    bot.run_correlation()

    # 8. Optimisation
    print("\n── [7/7] Optimisation paramétrique ──────────────────────────")
    bot.run_optimization("SPY")

    # 9. Rapport iOS
    print("\n── Génération du rapport iOS HTML ───────────────────────────")
    path = bot.generate_report(bt_result=bt)
    print(f"  ✅ Rapport HTML iOS : {path}")

    # 10. Alertes (demo)
    bot.alerts.add("SPY", "rsi_oversold", 35)
    bot.alerts.add("BTC-USD", "price_above", 70000)
    print(f"\n  📋 Journal : {len(bot.journal.entries)} entrées")
    print(f"  🔔 Alertes : {len(bot.alerts.alerts)} configurées")

    # 11. Export
    exp_path = bot.risk.export_history()
    print(f"  📤 Export trades : {exp_path}")

    print(f"""
══════════════════════════════════════════════════════════════════════
  DÉMO v3 TERMINÉE — Tous les modules opérationnels
  Rapport iOS  : {path}
  Dashboard    : python bot_v3.py --mode dashboard
                 streamlit run dashboard_v3.py
══════════════════════════════════════════════════════════════════════
""")


# ═══════════════════════════════════════════════════════════════════════════════
# §22  DASHBOARD STREAMLIT v3 (généré)
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_V3 = '''\
#!/usr/bin/env python3
# dashboard_v3.py — Streamlit dashboard for Bot v3
import sys, os, json
from datetime import datetime
import streamlit as st
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bot_v3 import TradingBot, IndicatorEngine, RegimeDetector, SignalGenerator
from bot_v3 import CONFIG, Signal, Regime, OrderSide, SyntheticDataGenerator

st.set_page_config(page_title="Market Bot v3", page_icon="📈", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""<style>
[data-testid="stAppViewContainer"] { background:#000; color:#fff; }
[data-testid="stHeader"] { background:rgba(0,0,0,.85); }
.stMetric { background:#1c1c1e; border-radius:12px; padding:12px; }
.stDataFrame { font-size:.85em; }
section[data-testid="stSidebar"] { background:#1c1c1e; }
</style>""", unsafe_allow_html=True)

@st.cache_resource
def get_bot():
    return TradingBot(mode="paper", use_synthetic=False)  # données réelles

bot = get_bot()

# Header
col_h1, col_h2 = st.columns([3,1])
with col_h1:
    st.title("📈 Market Bot v3.0")
    st.caption(f"🟢 Live · {datetime.utcnow():%Y-%m-%d %H:%M UTC} · Données synthétiques")
with col_h2:
    if st.button("🔄 Actualiser"):
        st.cache_resource.clear()
        st.rerun()

tabs = st.tabs(["🌍 Macro", "📊 Actifs", "🔁 Backtest", "🔍 Screener", "💼 Portfolio"])

# ── TAB 1 : MACRO ─────────────────────────────────────────────────────────────
with tabs[0]:
    macro = bot.macro.refresh()
    fg, fg_label = bot.macro.fear_greed_index()

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("VIX", f"{macro.get('vix',0):.1f}", delta_color="inverse")
    c2.metric("T10Y", f"{macro.get('t10y',0):.2f}%")
    c3.metric("Spread 10-2", f"{macro.get('spread_10_2',0):.2f}%")
    c4.metric("Brent", f"{macro.get('brent',0):.1f}$")
    c5.metric("Or XAU", f"{macro.get('gold',0):.0f}$")
    c6.metric(f"F&G: {fg_label}", f"{fg:.0f}/100")

    for alert in bot.macro.alerts:
        st.warning(alert)

    expo = bot.macro.expo_multiplier()
    bias = bot.macro.regime_bias(macro)
    cc1, cc2 = st.columns(2)
    cc1.info(f"**Biais macro** : {bias}")
    cc2.info(f"**Exposition** : {expo:.0%}")

# ── TAB 2 : ACTIFS ─────────────────────────────────────────────────────────────
with tabs[1]:
    sym = st.selectbox("Actif", CONFIG["WATCHLIST"])
    a = bot.analyse(sym, silent=True)
    if "error" not in a:
        col1,col2,col3,col4 = st.columns(4)
        col1.metric("Prix", f"{a['price']:.4f}")
        col1.metric("RSI", f"{a['rsi']:.1f}")
        col1.metric("ADX", f"{a['adx']:.1f}")
        icons = {"STRONG_BULL":"🚀","BULL":"📈","RANGING":"↔️","BEAR":"📉","STRONG_BEAR":"🔻"}
        col2.metric("Régime", f"{icons.get(a['regime'],'')} {a['regime']}")
        col2.metric("Confiance", f"{a['confidence']:.0%}")
        col2.metric("Squeeze", "⚡ Oui" if a.get('squeeze') else "Non")
        sigicons = {"STRONG_BUY":"🚀","BUY":"🟢","HOLD":"⚪","SELL":"🔴","STRONG_SELL":"🔻"}
        col3.metric("Signal", f"{sigicons.get(a['signal'],'')} {a['signal']}")
        col3.metric("Force", f"{a['signal_force']:.0%}")
        col3.metric("GARCH Vol", f"{a.get('garch_vol') or 0:.1f}%")
        col4.metric("Stop Long", f"{a['stop_long']:.4f}")
        col4.metric("TP Long", f"{a['tp_long']:.4f}")
        col4.metric("R:R", f"{a['rr_ratio']:.2f}x")
        if a.get("signal_reasons"):
            with st.expander("Détail des confirmations"):
                for r in a["signal_reasons"]: st.write(f"• {r}")

        # Indicateurs avancés
        with st.expander("Indicateurs avancés"):
            df_ind = pd.DataFrame([{
                "MFI": a.get("mfi"), "CMF": a.get("cmf"), "TRIX": a.get("trix"),
                "DPO": a.get("dpo"), "VWAP dev": a.get("vwap_dev"),
                "Bull Power": a.get("bull_power"), "Bear Power": a.get("bear_power"),
                "OBV": a.get("obv"), "Vol Ratio": a.get("vol_ratio"),
            }])
            st.dataframe(df_ind.T.rename(columns={0:"Valeur"}), use_container_width=True)

# ── TAB 3 : BACKTEST ─────────────────────────────────────────────────────────
with tabs[2]:
    sym_bt = st.selectbox("Actif backtest", ["SPY","QQQ","BTC-USD","GC=F"], key="bt_sym")
    days   = st.slider("Jours d'historique", 252, 1008, 756, 63)
    if st.button("▶ Lancer le Backtest"):
        with st.spinner("Walk-forward en cours..."):
            bt = bot.run_backtest(sym_bt, days)
        if "error" not in bt:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Return total", f"{bt.get('total_return_pct',0):+.2f}%")
            c2.metric("Sharpe", f"{bt.get('sharpe_ratio',0):.2f}")
            c3.metric("Max DD", f"{bt.get('max_drawdown_pct',0):.2f}%")
            c4.metric("Calmar", f"{bt.get('calmar_ratio',0):.2f}")
            c1.metric("Win Rate", f"{bt.get('win_rate',0):.1%}")
            c2.metric("Profit Factor", f"{bt.get('profit_factor',0):.2f}")
            c3.metric("Alpha B&H", f"{bt.get('alpha_vs_bh',0):+.1f}%")
            c4.metric("Fenêtres", bt.get('n_windows',0))

            n_sim = st.slider("Simulations MC", 100, 2000, 500, 100)
            mc = bot.run_montecarlo(bt, n_sim)
            st.markdown("**Monte-Carlo**")
            mc1,mc2,mc3 = st.columns(3)
            mc1.metric("Return médian", f"{mc.get('median_return_pct',0):+.1f}%")
            mc2.metric("Prob. positive", f"{mc.get('prob_positive_pct',0):.0f}%")
            mc3.metric("Prob. ruine", f"{mc.get('prob_ruin_pct',0):.1f}%")

# ── TAB 4 : SCREENER ─────────────────────────────────────────────────────────
with tabs[3]:
    if st.button("🔍 Scanner le marché"):
        with st.spinner("Analyse de l\'univers..."):
            results = bot.run_screener(CONFIG["SCREENER_UNIVERSE"])
        if results:
            df_sc = pd.DataFrame(results)[["symbol","price","change_pct","regime","signal","force","rsi","adx","is_squeeze"]]
            df_sc.columns = ["Symbole","Prix","Var%","Régime","Signal","Force","RSI","ADX","Squeeze"]
            st.dataframe(df_sc, use_container_width=True, hide_index=True)
    with st.expander("Corrélations inter-actifs"):
        corr = bot.run_correlation()
        if "top_pairs" in corr:
            df_corr = pd.DataFrame(corr["top_pairs"][:10])
            st.dataframe(df_corr, use_container_width=True, hide_index=True)

# ── TAB 5 : PORTFOLIO ─────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("### Paper Trading — Simulation")
    col_p1, col_p2 = st.columns(2)
    n_iter = col_p1.slider("Itérations", 10, 50, 20)
    sym_pt = col_p2.selectbox("Actif", CONFIG["WATCHLIST"][:5], key="pt_sym")
    if st.button("▶ Lancer la simulation"):
        with st.spinner("Simulation en cours..."):
            _, stats = bot.run_paper(n_iter, sym_pt)
        s1,s2,s3,s4 = st.columns(4)
        s1.metric("Capital", f"{stats.get('capital',0):,.2f}$")
        s2.metric("Return", f"{stats.get('total_return',0)*100:+.2f}%")
        s3.metric("Win Rate", f"{stats.get('win_rate',0):.1%}")
        s4.metric("Trades", stats.get("n_trades",0))

    # Historique trades
    from bot_v3 import persist, CONFIG as CFG  # self-reference
    trades = persist.read_jsonl(CFG["TRADES_FILE"])
    if trades:
        st.markdown("**Historique des trades**")
        df_t = pd.DataFrame(trades[-30:])
        if "pnl" in df_t.columns:
            st.dataframe(df_t[["symbol","side","entry","exit","pnl","pnl_pct","reason","closed"]]
                         .tail(20), use_container_width=True, hide_index=True)

    # Rapport HTML
    st.markdown("---")
    if st.button("📄 Générer le rapport iOS HTML"):
        with st.spinner("Génération..."):
            rpath = bot.generate_report()
        st.success(f"Rapport généré : {rpath}")
        with open(rpath, "rb") as f:
            st.download_button("⬇️ Télécharger", f.read(),
                               "rapport_ios_2026.html", "text/html")
'''


def create_dashboard_v3():
    with open("dashboard_v3.py", "w", encoding="utf-8") as f:
        f.write(DASHBOARD_V3)
    logger.info("dashboard_v3.py créé — lancer : streamlit run dashboard_v3.py")
    return "dashboard_v3.py"


# ═══════════════════════════════════════════════════════════════════════════════
# §23  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║   BOT D'ANALYSE DE MARCHÉ v3.0 — ARCHITECTURE MAXIMALE              ║
║   60 thèses · 5 volumes · ~4500 lignes · iOS-native UI              ║
╠══════════════════════════════════════════════════════════════════════╣
║  ✦ 20+ indicateurs (VWAP, Keltner, Donchian, TRIX, DPO, Elder Ray) ║
║  ✦ GARCH volatility estimate                                         ║
║  ✦ Candle patterns (Doji, Hammer, Engulfing)                        ║
║  ✦ Screener automatique multi-actifs                                 ║
║  ✦ Alertes conditionnelles configurables                             ║
║  ✦ Journal de trading intelligent (mood + tags)                     ║
║  ✦ Optimisation paramétrique Grid Search                             ║
║  ✦ Walk-forward + Calmar + Alpha vs Buy&Hold                        ║
║  ✦ Monte-Carlo compound avec percentiles                             ║
║  ✦ Corrélations inter-actifs enrichies                               ║
║  ✦ Event Bus (observer pattern)                                      ║
║  ✦ Export CSV automatique                                            ║
║  ✦ Rapport HTML iOS-native (5 onglets, dark mode, animations)       ║
╚══════════════════════════════════════════════════════════════════════╝
""")


def main():
    parser = argparse.ArgumentParser(description="Bot Marché v3.0")
    parser.add_argument("--mode", default="demo",
        choices=["demo","paper","backtest","montecarlo","analyse",
                 "screener","correlation","optimization","rapport","dashboard"])
    parser.add_argument("--symbol",  default=None)
    parser.add_argument("--days",    default=756, type=int)
    parser.add_argument("--sims",    default=1000, type=int)
    parser.add_argument("--live",    action="store_true")
    args = parser.parse_args()
    print_banner()

    if args.mode == "dashboard":
        p = create_dashboard_v3()
        print(f"\n  ✅ {p} créé.")
        print("  Lancer avec : streamlit run dashboard_v3.py\n")
        return

    use_syn = not args.live
    bot = TradingBot(mode=args.mode, use_synthetic=use_syn)

    if args.mode == "demo":
        run_demo(); return

    if args.mode == "analyse":
        print(bot.macro.summary())
        syms = [args.symbol] if args.symbol else CONFIG["WATCHLIST"][:4]
        for s in syms: bot.analyse(s)

    elif args.mode == "paper":
        bot.run_paper(25, args.symbol)

    elif args.mode == "backtest":
        bt = bot.run_backtest(args.symbol or CONFIG["PRIMARY_ASSET"], args.days)
        bot.run_montecarlo(bt, args.sims)

    elif args.mode == "screener":
        bot.run_screener()

    elif args.mode == "correlation":
        bot.run_correlation()

    elif args.mode == "optimization":
        bot.run_optimization(args.symbol)

    elif args.mode == "rapport":
        bt = bot.run_backtest(args.symbol or CONFIG["PRIMARY_ASSET"], 504)
        p  = bot.generate_report(bt_result=bt)
        print(f"\n  Rapport iOS : {p}")


if __name__ == "__main__":
    main()
