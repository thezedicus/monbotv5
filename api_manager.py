#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  api_manager.py  —  Données de marché temps réel                            ║
║  Bot d'Analyse de Marché v3.0  |  Python 3  |  macOS                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES TERMINAL MAC :                                                    ║
║                                                                              ║
║  # Installation (une seule fois)                                             ║
║  pip3 install yfinance requests pandas numpy python-dotenv                  ║
║                                                                              ║
║  # Tester toutes les APIs                                                    ║
║  python3 api_manager.py --check                                              ║
║                                                                              ║
║  # Prix temps réel (un ou plusieurs)                                         ║
║  python3 api_manager.py --price AAPL                                         ║
║  python3 api_manager.py --price SPY,QQQ,BTC-USD,GC=F,EURUSD=X              ║
║                                                                              ║
║  # Historique OHLCV                                                          ║
║  python3 api_manager.py --ohlcv SPY --period 1y --interval 1d               ║
║  python3 api_manager.py --ohlcv BTC-USD --period 3mo --interval 1h          ║
║                                                                              ║
║  # Tableau de bord macro (taux, VIX, spreads...)                            ║
║  python3 api_manager.py --macro                                              ║
║                                                                              ║
║  # Courbe des taux US complète                                               ║
║  python3 api_manager.py --curve                                              ║
║                                                                              ║
║  # Marché crypto + Fear & Greed                                              ║
║  python3 api_manager.py --crypto                                             ║
║                                                                              ║
║  # Actualités financières                                                    ║
║  python3 api_manager.py --news AAPL                                          ║
║                                                                              ║
║  # Fondamentaux d'une action                                                 ║
║  python3 api_manager.py --fund AAPL                                          ║
║                                                                              ║
║  # Snapshot complet du marché (JSON)                                         ║
║  python3 api_manager.py --snap                                               ║
║  python3 api_manager.py --snap > snapshot.json                               ║
║                                                                              ║
║  CLÉS API GRATUITES (optionnel — améliore la qualité des données) :         ║
║  Créer un fichier .env dans votre dossier monbotv3/ :                       ║
║    echo "ALPHA_VANTAGE_KEY=votre_cle" >> .env                                ║
║    echo "FINNHUB_KEY=votre_cle"       >> .env                                ║
║    echo "NEWS_API_KEY=votre_cle"      >> .env                                ║
║    echo "FRED_API_KEY=votre_cle"      >> .env                                ║
║  Sources : alphavantage.co  |  finnhub.io  |  newsapi.org  |  fred.stl...  ║
║                                                                              ║
║  INTÉGRATION dans bot_v3.py :                                                ║
║    from api_manager import MarketAPI                                         ║
║    api  = MarketAPI()                                                        ║
║    prix = api.price("AAPL")           # → dict avec price, change_pct...   ║
║    df   = api.ohlcv("SPY", "1y")      # → DataFrame OHLCV                  ║
║    mac  = api.macro_summary()         # → dict VIX, taux, spreads...       ║
║    c    = api.crypto()                # → dict BTC, ETH + Fear&Greed        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, logging, warnings, threading
from datetime    import datetime, timedelta, date
from pathlib     import Path
from typing      import Optional, Dict, List, Tuple, Any
from io          import StringIO

warnings.filterwarnings("ignore")

# ── Dossiers ──────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    handlers= [
        logging.FileHandler("logs/api_manager.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("MarketBot.API")

# Silencer les loggers parasites
for _n in ("yfinance", "urllib3", "requests", "peewee", "charset_normalizer"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

# ── Dépendances ───────────────────────────────────────────────────────────────
try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    print("⚠️  pip3 install requests")

try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False
    print("⚠️  pip3 install yfinance")

try:
    import pandas as pd
    import numpy  as np
    PANDAS_OK = True
except ImportError:
    PANDAS_OK = False
    print("⚠️  pip3 install pandas numpy")

# ── Charger .env ──────────────────────────────────────────────────────────────
def _load_env() -> None:
    for p in [Path(".env"), Path.home() / ".bot_market.env"]:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_load_env()

API_KEYS: Dict[str, str] = {
    "ALPHA_VANTAGE": os.getenv("ALPHA_VANTAGE_KEY", "demo"),
    "FINNHUB":       os.getenv("FINNHUB_KEY",       ""),
    "NEWS_API":      os.getenv("NEWS_API_KEY",       ""),
    "FRED":          os.getenv("FRED_API_KEY",       ""),
    "TWELVE_DATA":   os.getenv("TWELVE_DATA_KEY",    ""),
}


# ══════════════════════════════════════════════════════════════════════════════
# §1  CACHE EN MÉMOIRE — TTL différencié par type de donnée
# ══════════════════════════════════════════════════════════════════════════════

class _Cache:
    """Cache thread-safe avec TTL configurable par type de donnée."""

    TTL: Dict[str, int] = {
        "price":        15,      # Prix : 15 secondes
        "ohlcv_1m":     60,
        "ohlcv_5m":     300,
        "ohlcv_15m":    900,
        "ohlcv_1h":     3_600,
        "ohlcv_1d":     43_200,  # 12 heures
        "macro":        300,     # FRED : 5 minutes
        "fundamentals": 7_200,   # Fondamentaux : 2 heures
        "news":         600,     # News : 10 minutes
        "crypto":       30,      # Crypto : 30 secondes
        "forex":        30,
        "options":      300,
        "default":      60,
    }

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[Any, float]] = {}
        self._lock  = threading.RLock()
        self._hits  = 0
        self._miss  = 0

    def get(self, key: str, dtype: str = "default") -> Optional[Any]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._miss += 1
                return None
            val, ts = entry
            if time.time() - ts > self.TTL.get(dtype, 60):
                del self._store[key]
                self._miss += 1
                return None
            self._hits += 1
            return val

    def set(self, key: str, val: Any) -> None:
        with self._lock:
            self._store[key] = (val, time.time())

    def invalidate(self, prefix: str = "") -> int:
        with self._lock:
            if not prefix:
                n = len(self._store)
                self._store.clear()
                return n
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    @property
    def stats(self) -> Dict:
        total = self._hits + self._miss
        return {
            "entries": len(self._store),
            "hits":    self._hits,
            "misses":  self._miss,
            "ratio":   f"{self._hits / total:.1%}" if total else "N/A",
        }


CACHE = _Cache()


# ══════════════════════════════════════════════════════════════════════════════
# §2  YAHOO FINANCE  (gratuit, sans clé, très fiable)
# ══════════════════════════════════════════════════════════════════════════════

class YahooFinanceAPI:
    """
    Interface complète Yahoo Finance.
    Actions, ETFs, indices, matières premières, forex, crypto.
    Fallback automatique sur plusieurs périodes en cas d'échec.
    """

    # Alias pratiques → ticker Yahoo Finance officiel
    ALIASES: Dict[str, str] = {
        "BTC":     "BTC-USD",   "ETH":     "ETH-USD",   "SOL":   "SOL-USD",
        "BNB":     "BNB-USD",   "XRP":     "XRP-USD",
        "OR":      "GC=F",      "GOLD":    "GC=F",       "BRENT": "BZ=F",
        "PETROLE": "CL=F",      "OIL":     "CL=F",       "SILVER":"SI=F",
        "EUR":     "EURUSD=X",  "GBP":     "GBPUSD=X",   "JPY":   "USDJPY=X",
        "CHF":     "USDCHF=X",  "AUD":     "AUDUSD=X",   "CAD":   "USDCAD=X",
        "VIX":     "^VIX",      "SP500":   "^GSPC",      "NASDAQ":"^IXIC",
        "DOW":     "^DJI",      "DAX":     "^GDAXI",     "CAC40": "^FCHI",
        "NIKKEI":  "^N225",     "HANG":    "^HSI",
        "T10Y":    "^TNX",      "T2Y":     "^IRX",       "DXY":   "DX-Y.NYB",
    }

    def _t(self, symbol: str) -> str:
        return self.ALIASES.get(symbol.upper(), symbol)

    # ── Prix temps réel ───────────────────────────────────────────────────────
    def price(self, symbol: str) -> Optional[Dict]:
        sym = self._t(symbol)
        ck  = f"yf_p_{sym}"
        if (c := CACHE.get(ck, "price")):
            return c

        for period, interval in [("2d", "1m"), ("5d", "5m"), ("5d", "1d")]:
            try:
                hist = yf.Ticker(sym).history(
                    period=period, interval=interval,
                    auto_adjust=True, prepost=False
                )
                if hist is None or hist.empty:
                    continue
                last  = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                chg   = last - prev
                chgp  = chg / prev * 100 if prev else 0.0
                vol   = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
                res   = {
                    "symbol":      symbol.upper(),
                    "yahoo_ticker":sym,
                    "price":       round(last, 6),
                    "prev_close":  round(prev, 6),
                    "change":      round(chg, 6),
                    "change_pct":  round(chgp, 3),
                    "volume":      vol,
                    "high_24h":    round(float(hist["High"].max()), 6),
                    "low_24h":     round(float(hist["Low"].min()), 6),
                    "timestamp":   datetime.utcnow().isoformat(),
                    "source":      "Yahoo Finance",
                }
                CACHE.set(ck, res)
                return res
            except Exception:
                continue

        logger.warning(f"YF price: données indisponibles pour {symbol}")
        return None

    # ── OHLCV historique ─────────────────────────────────────────────────────
    def ohlcv(self, symbol: str, period: str = "1y",
               interval: str = "1d") -> Optional["pd.DataFrame"]:
        """
        period   : 1d 5d 1mo 3mo 6mo 1y 2y 5y ytd max
        interval : 1m 2m 5m 15m 30m 60m 1h 1d 5d 1wk 1mo
        """
        sym   = self._t(symbol)
        dtype = f"ohlcv_{interval}"
        ck    = f"yf_ohlcv_{sym}_{period}_{interval}"
        if (c := CACHE.get(ck, dtype)) is not None:
            return c
        try:
            raw = yf.download(
                sym, period=period, interval=interval,
                progress=False, auto_adjust=True, timeout=20
            )
            if raw is None or raw.empty:
                return None
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            raw.columns = [str(c).strip().title() for c in raw.columns]
            cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
            df   = raw[cols].dropna(subset=["Close"])
            CACHE.set(ck, df)
            return df
        except Exception as e:
            logger.warning(f"YF ohlcv {symbol} ({period}/{interval}): {e}")
            return None

    # ── Multi-prix ────────────────────────────────────────────────────────────
    def multi_price(self, symbols: List[str]) -> Dict[str, Dict]:
        if not symbols:
            return {}
        tickers = [self._t(s) for s in symbols]
        try:
            raw = yf.download(
                tickers if len(tickers) > 1 else tickers[0],
                period="5d", interval="1d",
                progress=False, auto_adjust=True,
                group_by="ticker" if len(tickers) > 1 else None,
                timeout=20
            )
            if raw is None or raw.empty:
                return {}
            result = {}
            for sym, orig in zip(tickers, symbols):
                try:
                    if len(tickers) == 1:
                        s_df = raw
                    else:
                        lvl0 = raw.columns.get_level_values(0)
                        if sym not in lvl0:
                            continue
                        s_df = raw[sym]
                    close = float(s_df["Close"].dropna().iloc[-1])
                    prev  = float(s_df["Close"].dropna().iloc[-2]) if len(s_df) > 1 else close
                    vol   = int(s_df["Volume"].dropna().iloc[-1]) if "Volume" in s_df.columns else 0
                    chg   = close - prev
                    result[orig] = {
                        "symbol":     orig.upper(),
                        "price":      round(close, 6),
                        "change":     round(chg, 6),
                        "change_pct": round(chg / prev * 100 if prev else 0, 3),
                        "volume":     vol,
                        "source":     "Yahoo Finance",
                    }
                except Exception:
                    pass
            return result
        except Exception as e:
            logger.warning(f"YF multi_price: {e}")
            return {}

    # ── Fondamentaux ─────────────────────────────────────────────────────────
    def fundamentals(self, symbol: str) -> Optional[Dict]:
        ck = f"yf_fund_{symbol}"
        if (c := CACHE.get(ck, "fundamentals")):
            return c
        try:
            info = yf.Ticker(self._t(symbol)).info or {}

            def _f(k, default=None):
                v = info.get(k, default)
                if v is None:
                    return default
                try:
                    return float(v) if isinstance(default, float) or default is None else v
                except Exception:
                    return default

            res = {
                "symbol":            symbol.upper(),
                "company_name":      info.get("longName", "N/A"),
                "sector":            info.get("sector", "N/A"),
                "industry":          info.get("industry", "N/A"),
                "country":           info.get("country", "N/A"),
                "currency":          info.get("currency", "USD"),
                "market_cap":        _f("marketCap"),
                "enterprise_value":  _f("enterpriseValue"),
                "pe_ratio":          _f("trailingPE"),
                "forward_pe":        _f("forwardPE"),
                "peg_ratio":         _f("pegRatio"),
                "price_to_book":     _f("priceToBook"),
                "price_to_sales":    _f("priceToSalesTrailing12Months"),
                "ev_ebitda":         _f("enterpriseToEbitda"),
                "eps_ttm":           _f("trailingEps"),
                "eps_forward":       _f("forwardEps"),
                "revenue_ttm":       _f("totalRevenue"),
                "gross_margin":      _f("grossMargins"),
                "profit_margin":     _f("profitMargins"),
                "operating_margin":  _f("operatingMargins"),
                "roe":               _f("returnOnEquity"),
                "roa":               _f("returnOnAssets"),
                "debt_equity":       _f("debtToEquity"),
                "current_ratio":     _f("currentRatio"),
                "quick_ratio":       _f("quickRatio"),
                "free_cashflow":     _f("freeCashflow"),
                "dividend_yield":    _f("dividendYield"),
                "payout_ratio":      _f("payoutRatio"),
                "beta":              _f("beta"),
                "52w_high":          _f("fiftyTwoWeekHigh"),
                "52w_low":           _f("fiftyTwoWeekLow"),
                "avg_volume_10d":    _f("averageVolume10days"),
                "short_ratio":       _f("shortRatio"),
                "short_percent":     _f("shortPercentOfFloat"),
                "analyst_target":    _f("targetMeanPrice"),
                "analyst_count":     _f("numberOfAnalystOpinions"),
                "recommendation":    info.get("recommendationKey", "N/A"),
                "source":            "Yahoo Finance",
                "timestamp":         datetime.utcnow().isoformat(),
            }
            CACHE.set(ck, res)
            return res
        except Exception as e:
            logger.warning(f"YF fundamentals {symbol}: {e}")
            return None

    # ── Chaîne d'options ─────────────────────────────────────────────────────
    def options_chain(self, symbol: str) -> Optional[Dict]:
        try:
            t    = yf.Ticker(self._t(symbol))
            exps = t.options
            if not exps:
                return None
            chain = t.option_chain(exps[0])
            cols  = ["strike","lastPrice","bid","ask","volume",
                      "openInterest","impliedVolatility"]

            def _clean(df):
                df = df[[c for c in cols if c in df.columns]].copy()
                if "impliedVolatility" in df.columns:
                    df["impliedVolatility"] = df["impliedVolatility"].round(4)
                return df.head(12).to_dict("records")

            return {
                "symbol":          symbol,
                "expiration":      exps[0],
                "all_expirations": list(exps[:6]),
                "calls":           _clean(chain.calls),
                "puts":            _clean(chain.puts),
                "source":          "Yahoo Finance",
                "timestamp":       datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.debug(f"YF options {symbol}: {e}")
            return None

    # ── Résultats trimestriels ────────────────────────────────────────────────
    def earnings(self, symbol: str) -> Optional[Dict]:
        try:
            t   = yf.Ticker(self._t(symbol))
            cal = t.earnings_dates
            if cal is None or cal.empty:
                return None
            records = []
            for idx, row in cal.head(8).iterrows():
                records.append({
                    "date":         str(idx.date()) if hasattr(idx, "date") else str(idx),
                    "eps_estimated":float(row.get("EPS Estimate") or 0),
                    "eps_reported": float(row.get("Reported EPS") or 0),
                    "surprise_pct": float(row.get("Surprise(%)") or 0),
                })
            return {"symbol": symbol, "earnings": records, "source": "Yahoo Finance"}
        except Exception as e:
            logger.debug(f"YF earnings {symbol}: {e}")
            return None


# ══════════════════════════════════════════════════════════════════════════════
# §3  FRED  (Réserve Fédérale — données macro gratuites)
# ══════════════════════════════════════════════════════════════════════════════

class FREDAPI:
    """
    FRED — Federal Reserve Economic Data (St. Louis Fed).
    Accès CSV public sans clé, ou JSON avec clé optionnelle.
    """

    BASE_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    BASE_API = "https://api.stlouisfed.org/fred/series/observations"

    KEY_SERIES: Dict[str, Tuple[str, str]] = {
        "T10Y":          ("DGS10",        "Taux 10 ans US (%)"),
        "T2Y":           ("DGS2",         "Taux 2 ans US (%)"),
        "T3M":           ("DTB3",         "T-Bills 3 mois (%)"),
        "T5Y":           ("DGS5",         "Taux 5 ans US (%)"),
        "T30Y":          ("DGS30",        "Taux 30 ans US (%)"),
        "SPREAD_10_2":   ("T10Y2Y",       "Spread 10 ans - 2 ans (%)"),
        "FEDFUNDS":      ("FEDFUNDS",     "Taux Fed Funds effectif (%)"),
        "CPI":           ("CPIAUCSL",     "CPI (inflation, nsa)"),
        "PCE":           ("PCEPI",        "PCE (objectif Fed)"),
        "UNEMPLOYMENT":  ("UNRATE",       "Taux chômage US (%)"),
        "IG_SPREAD":     ("BAMLC0A0CM",   "Spread Investment Grade OAS"),
        "HY_SPREAD":     ("BAMLH0A0HYM2", "Spread High Yield OAS"),
        "TIPS_10Y":      ("DFII10",       "TIPS 10 ans — rendement réel"),
        "M2":            ("M2SL",         "Masse monétaire M2 ($Mrd)"),
        "VIX_FRED":      ("VIXCLS",       "VIX (clôture FRED)"),
    }

    def __init__(self) -> None:
        self.api_key = API_KEYS.get("FRED", "")

    def get_series(self, series_id: str, limit: int = 60) -> Optional["pd.DataFrame"]:
        """Télécharge une série FRED. Retourne DataFrame date/value."""
        ck = f"fred_{series_id}_{limit}"
        if (c := CACHE.get(ck, "macro")) is not None:
            return c

        # Méthode 1 : CSV public (sans clé, toujours disponible)
        try:
            r = requests.get(f"{self.BASE_CSV}?id={series_id}", timeout=12)
            r.raise_for_status()
            df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
            df.columns = ["date", "value"]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna().tail(limit).reset_index(drop=True)
            CACHE.set(ck, df)
            return df
        except Exception as e:
            logger.debug(f"FRED CSV {series_id}: {e}")

        # Méthode 2 : API JSON avec clé (si disponible)
        if self.api_key:
            try:
                r = requests.get(self.BASE_API, params={
                    "series_id":  series_id,
                    "api_key":    self.api_key,
                    "file_type":  "json",
                    "sort_order": "desc",
                    "limit":      limit,
                }, timeout=12)
                r.raise_for_status()
                obs = r.json().get("observations", [])
                rows = [(o["date"], pd.to_numeric(o["value"], errors="coerce"))
                        for o in obs if o.get("value") != "."]
                df = pd.DataFrame(rows, columns=["date", "value"])
                df["date"]  = pd.to_datetime(df["date"])
                df = df.dropna().sort_values("date").reset_index(drop=True)
                CACHE.set(ck, df)
                return df
            except Exception as e:
                logger.debug(f"FRED API {series_id}: {e}")

        return None

    def macro_dashboard(self) -> Dict:
        """Tableau de bord macro complet — toutes séries clés."""
        ck = "fred_dashboard"
        if (c := CACHE.get(ck, "macro")):
            return c

        result: Dict[str, Any] = {}
        for name, (sid, label) in self.KEY_SERIES.items():
            df = self.get_series(sid, limit=10)
            if df is None or df.empty:
                continue
            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last
            val  = float(last["value"])
            chg  = val - float(prev["value"])
            result[name] = {
                "value":    round(val, 4),
                "prev":     round(float(prev["value"]), 4),
                "change":   round(chg, 4),
                "date":     str(last["date"].date()) if hasattr(last["date"], "date") else str(last["date"]),
                "label":    label,
                "series_id":sid,
            }

        # Spread calculé localement
        if "T10Y" in result and "T2Y" in result:
            s = result["T10Y"]["value"] - result["T2Y"]["value"]
            result["SPREAD_CALC"] = {
                "value":  round(s, 3),
                "label":  "Spread 10-2 calculé",
                "signal": ("⚠️  INVERSÉE — Récession probable" if s < -0.20 else
                            "⚡ Très plate"                   if s < 0.10  else
                            "✓ Normale"                        if s > 0.50  else "Plate"),
            }

        # Spreads crédit en bps (FRED donne en %)
        for key in ("IG_SPREAD", "HY_SPREAD"):
            if key in result:
                bps = result[key]["value"] * 100
                result[key]["bps"]   = round(bps, 1)
                result[key]["alert"] = (
                    "⚠️  STRESS CRÉDIT"
                    if (key == "IG_SPREAD" and bps > 150) or (key == "HY_SPREAD" and bps > 600)
                    else "Normal"
                )

        result["_timestamp"] = datetime.utcnow().isoformat()
        CACHE.set(ck, result)
        return result

    def yield_curve(self) -> Dict[str, float]:
        """Courbe des taux complète (3M → 30Y)."""
        mats = {
            "3M":"DTB3", "6M":"DTB6", "1Y":"DGS1",
            "2Y":"DGS2", "3Y":"DGS3", "5Y":"DGS5",
            "7Y":"DGS7", "10Y":"DGS10","20Y":"DGS20","30Y":"DGS30",
        }
        curve: Dict[str, float] = {}
        for mat, sid in mats.items():
            df = self.get_series(sid, limit=3)
            if df is not None and not df.empty:
                v = float(df.iloc[-1]["value"])
                if not pd.isna(v):
                    curve[mat] = round(v, 3)
        return curve


# ══════════════════════════════════════════════════════════════════════════════
# §4  COINGECKO  (crypto temps réel, sans clé)
# ══════════════════════════════════════════════════════════════════════════════

class CoinGeckoAPI:
    """CoinGecko — données crypto gratuites sans clé API."""

    BASE = "https://api.coingecko.com/api/v3"

    COIN_IDS: Dict[str, str] = {
        "BTC":   "bitcoin",      "ETH":  "ethereum",    "SOL":  "solana",
        "BNB":   "binancecoin",  "XRP":  "ripple",      "ADA":  "cardano",
        "AVAX":  "avalanche-2",  "DOT":  "polkadot",    "LINK": "chainlink",
        "MATIC": "matic-network","UNI":  "uniswap",     "ATOM": "cosmos",
        "DOGE":  "dogecoin",     "SHIB": "shiba-inu",   "LTC":  "litecoin",
        "TON":   "the-open-network",
    }

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Any]:
        try:
            r = requests.get(f"{self.BASE}/{endpoint}", params=params or {}, timeout=12)
            if r.status_code == 429:
                logger.warning("CoinGecko: rate limit — réessayer dans 60s")
                return None
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"CoinGecko {endpoint}: {e}")
            return None

    def prices(self, *symbols: str) -> Dict[str, Dict]:
        """Prix temps réel de plusieurs cryptos en un seul appel."""
        coin_ids = [self.COIN_IDS.get(s.upper(), s.lower()) for s in symbols]
        ck = f"cg_prices_{'_'.join(coin_ids)}"
        if (c := CACHE.get(ck, "crypto")):
            return c

        data = self._get("simple/price", {
            "ids":                   ",".join(coin_ids),
            "vs_currencies":         "usd",
            "include_24hr_change":   "true",
            "include_24hr_vol":      "true",
            "include_market_cap":    "true",
            "include_last_updated_at":"true",
        })
        if not data:
            return {}

        result: Dict[str, Dict] = {}
        for sym, cid in zip(symbols, coin_ids):
            d = data.get(cid, {})
            if not d:
                continue
            ts = d.get("last_updated_at")
            result[sym.upper()] = {
                "symbol":     sym.upper(),
                "price":      d.get("usd"),
                "change_24h": round(d.get("usd_24h_change") or 0, 3),
                "volume_24h": d.get("usd_24h_vol"),
                "market_cap": d.get("usd_market_cap"),
                "updated_at": datetime.fromtimestamp(ts).isoformat() if ts else None,
                "source":     "CoinGecko",
            }
        CACHE.set(ck, result)
        return result

    def ohlcv(self, symbol: str, days: int = 30) -> Optional["pd.DataFrame"]:
        """OHLCV historique (gratuit jusqu'à 90 jours)."""
        cid = self.COIN_IDS.get(symbol.upper(), symbol.lower())
        ck  = f"cg_ohlcv_{cid}_{days}"
        if (c := CACHE.get(ck, "ohlcv_1d")) is not None:
            return c

        data = self._get(f"coins/{cid}/ohlc", {"vs_currency": "usd", "days": str(days)})
        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data, columns=["ts","Open","High","Low","Close"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("ts").sort_index()
        CACHE.set(ck, df)
        return df

    def global_market(self) -> Dict:
        """Données globales du marché crypto."""
        ck = "cg_global"
        if (c := CACHE.get(ck, "crypto")):
            return c
        data = self._get("global")
        if not data:
            return {}
        d  = data.get("data", {})
        mc = d.get("total_market_cap", {})
        res = {
            "total_mcap_usd":        mc.get("usd"),
            "total_volume_24h_usd":  d.get("total_volume", {}).get("usd"),
            "btc_dominance":         round(d.get("market_cap_percentage", {}).get("btc", 0), 2),
            "eth_dominance":         round(d.get("market_cap_percentage", {}).get("eth", 0), 2),
            "active_cryptos":        d.get("active_cryptocurrencies"),
            "mcap_change_24h":       round(d.get("market_cap_change_percentage_24h_usd", 0), 3),
            "source":                "CoinGecko",
        }
        CACHE.set(ck, res)
        return res

    def fear_greed(self) -> Dict:
        """Indice Fear & Greed (Alternative.me)."""
        ck = "fg_index"
        if (c := CACHE.get(ck, "macro")):
            return c
        try:
            r = requests.get("https://api.alternative.me/fng/?limit=7", timeout=10)
            r.raise_for_status()
            data = r.json()["data"]
            hist = [
                {
                    "value": int(d["value"]),
                    "label": d["value_classification"],
                    "date":  datetime.fromtimestamp(int(d["timestamp"])).strftime("%Y-%m-%d"),
                }
                for d in data
            ]
            res = {
                "value":      int(data[0]["value"]),
                "label":      data[0]["value_classification"],
                "history_7d": hist,
                "source":     "Alternative.me",
                "timestamp":  datetime.utcnow().isoformat(),
            }
            CACHE.set(ck, res)
            return res
        except Exception as e:
            logger.debug(f"Fear&Greed: {e}")
            return {"value": 50, "label": "Neutral", "source": "unavailable"}


# ══════════════════════════════════════════════════════════════════════════════
# §5  ALPHA VANTAGE  (clé gratuite — 25 req/jour)
# ══════════════════════════════════════════════════════════════════════════════

class AlphaVantageAPI:
    """Alpha Vantage — intraday haute qualité, forex, indicateurs."""

    BASE = "https://www.alphavantage.co/query"

    def __init__(self) -> None:
        self.key      = API_KEYS["ALPHA_VANTAGE"]
        self._req_n   = 0
        self._reset   = time.time()

    def _rate_limit(self) -> None:
        if time.time() - self._reset > 60:
            self._req_n = 0
            self._reset = time.time()
        if self._req_n >= 5:
            wait = 60 - (time.time() - self._reset)
            if wait > 0:
                logger.info(f"AlphaVantage rate limit — pause {wait:.0f}s")
                time.sleep(wait)
            self._req_n = 0
            self._reset = time.time()
        self._req_n += 1

    def _call(self, params: Dict) -> Optional[Dict]:
        if not REQUESTS_OK:
            return None
        params["apikey"] = self.key
        try:
            self._rate_limit()
            r = requests.get(self.BASE, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            if "Note" in data or "Information" in data:
                logger.warning(f"AV: {data.get('Note') or data.get('Information')}")
                return None
            return data
        except Exception as e:
            logger.warning(f"AlphaVantage: {e}")
            return None

    def intraday(self, symbol: str, interval: str = "5min") -> Optional["pd.DataFrame"]:
        """Données intraday (1min, 5min, 15min, 30min, 60min)."""
        if self.key == "demo":
            return None
        ck = f"av_intra_{symbol}_{interval}"
        if (c := CACHE.get(ck, "ohlcv_5m")) is not None:
            return c

        data = self._call({
            "function":   "TIME_SERIES_INTRADAY",
            "symbol":     symbol,
            "interval":   interval,
            "outputsize": "compact",
            "adjusted":   "true",
        })
        if not data:
            return None

        ts_key = f"Time Series ({interval})"
        ts = data.get(ts_key, {})
        if not ts:
            return None

        rows = []
        for dt_str, vals in sorted(ts.items()):
            rows.append({
                "Open":   float(vals.get("1. open", 0)),
                "High":   float(vals.get("2. high", 0)),
                "Low":    float(vals.get("3. low",  0)),
                "Close":  float(vals.get("4. close",0)),
                "Volume": int(vals.get("5. volume", 0)),
            })
        df = pd.DataFrame(rows, index=pd.to_datetime(sorted(ts.keys())))
        CACHE.set(ck, df)
        return df

    def forex_rate(self, from_sym: str, to_sym: str = "USD") -> Optional[Dict]:
        """Taux de change en temps réel."""
        if self.key == "demo":
            return None
        ck = f"av_fx_{from_sym}_{to_sym}"
        if (c := CACHE.get(ck, "forex")):
            return c

        data = self._call({
            "function":     "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_sym,
            "to_currency":   to_sym,
        })
        if not data:
            return None

        info = data.get("Realtime Currency Exchange Rate", {})
        if not info:
            return None

        res = {
            "from":      from_sym,
            "to":        to_sym,
            "rate":      float(info.get("5. Exchange Rate", 0)),
            "bid":       float(info.get("8. Bid Price", 0)),
            "ask":       float(info.get("9. Ask Price", 0)),
            "timestamp": info.get("6. Last Refreshed", ""),
            "source":    "Alpha Vantage",
        }
        CACHE.set(ck, res)
        return res


# ══════════════════════════════════════════════════════════════════════════════
# §6  FINNHUB  (news, sentiment, calendrier — clé gratuite)
# ══════════════════════════════════════════════════════════════════════════════

class FinnhubAPI:
    """Finnhub — actualités, sentiment, calendrier résultats, recommandations."""

    BASE = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        self.key = API_KEYS["FINNHUB"]

    def _get(self, endpoint: str, params: Dict = None) -> Optional[Any]:
        if not self.key or not REQUESTS_OK:
            return None
        try:
            p = dict(params or {})
            p["token"] = self.key
            r = requests.get(f"{self.BASE}/{endpoint}", params=p, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"Finnhub {endpoint}: {e}")
            return None

    def news_sentiment(self, symbol: str) -> Optional[Dict]:
        """Score de sentiment des actualités."""
        ck = f"fh_sent_{symbol}"
        if (c := CACHE.get(ck, "news")):
            return c
        data = self._get("news-sentiment", {"symbol": symbol})
        if not data:
            return None
        res = {
            "symbol":         symbol,
            "bull_pct":       round(data.get("sentiment", {}).get("bullishPercent", 0), 3),
            "bear_pct":       round(data.get("sentiment", {}).get("bearishPercent", 0), 3),
            "articles_count": data.get("articleCount", 0),
            "buzz_weekly":    data.get("buzz", {}).get("articlesInLastWeek", 0),
            "source":         "Finnhub",
            "timestamp":      datetime.utcnow().isoformat(),
        }
        CACHE.set(ck, res)
        return res

    def company_news(self, symbol: str, days: int = 5) -> List[Dict]:
        """Actualités récentes d'une entreprise."""
        ck = f"fh_news_{symbol}_{days}"
        if (c := CACHE.get(ck, "news")):
            return c
        fd = (date.today() - timedelta(days=days)).isoformat()
        td = date.today().isoformat()
        data = self._get("company-news", {"symbol": symbol, "from": fd, "to": td})
        if not data or not isinstance(data, list):
            return []
        news = [
            {
                "headline": item.get("headline", ""),
                "summary":  (item.get("summary") or "")[:250],
                "source":   item.get("source", ""),
                "url":      item.get("url", ""),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
            }
            for item in data[:12]
        ]
        CACHE.set(ck, news)
        return news

    def analyst_recommendation(self, symbol: str) -> Optional[Dict]:
        """Consensus des analystes."""
        ck = f"fh_rec_{symbol}"
        if (c := CACHE.get(ck, "fundamentals")):
            return c
        data = self._get("stock/recommendation", {"symbol": symbol})
        if not data or not isinstance(data, list) or not data:
            return None
        latest = data[0]
        total  = sum(latest.get(k, 0) for k in ["strongBuy","buy","hold","sell","strongSell"])
        res = {
            "symbol":         symbol,
            "period":         latest.get("period"),
            "strong_buy":     latest.get("strongBuy", 0),
            "buy":            latest.get("buy", 0),
            "hold":           latest.get("hold", 0),
            "sell":           latest.get("sell", 0),
            "strong_sell":    latest.get("strongSell", 0),
            "total_analysts": total,
            "source":         "Finnhub",
        }
        CACHE.set(ck, res)
        return res

    def earnings_calendar(self, days_ahead: int = 7) -> List[Dict]:
        """Calendrier des publications de résultats."""
        fd = date.today().isoformat()
        td = (date.today() + timedelta(days=days_ahead)).isoformat()
        data = self._get("calendar/earnings", {"from": fd, "to": td})
        if not data:
            return []
        return data.get("earningsCalendar", [])[:20]


# ══════════════════════════════════════════════════════════════════════════════
# §7  YAHOO RSS NEWS  (actualités sans aucune clé)
# ══════════════════════════════════════════════════════════════════════════════

class YahooRSSNews:
    """Actualités Yahoo Finance via RSS — 100% gratuit, sans clé."""

    RSS_SYMBOL  = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={}&region=US&lang=en-US"
    RSS_MARKET  = "https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US"

    def get_news(self, symbol: str = None, limit: int = 10) -> List[Dict]:
        url = self.RSS_SYMBOL.format(symbol) if symbol else self.RSS_MARKET
        ck  = f"rss_{symbol or 'mkt'}_{limit}"
        if (c := CACHE.get(ck, "news")):
            return c
        try:
            import xml.etree.ElementTree as ET
            r = requests.get(url, timeout=10,
                              headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X)"})
            r.raise_for_status()
            root  = ET.fromstring(r.content)
            items = root.findall(".//item")
            news  = [
                {
                    "headline": (item.findtext("title") or "").strip(),
                    "url":       item.findtext("link") or "",
                    "datetime":  item.findtext("pubDate") or "",
                    "source":    "Yahoo Finance RSS",
                    "summary":   (item.findtext("description") or "")[:200],
                }
                for item in items[:limit]
                if item.findtext("title")
            ]
            CACHE.set(ck, news)
            return news
        except Exception as e:
            logger.debug(f"Yahoo RSS {symbol}: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
# §8  MARKET API — FAÇADE UNIFIÉE (point d'entrée unique)
# ══════════════════════════════════════════════════════════════════════════════

class MarketAPI:
    """
    Façade unifiée vers toutes les sources de données réelles.

    Priorités et fallbacks automatiques :
      Prix actions/ETFs   → Yahoo Finance (gratuit)
      Prix crypto         → Yahoo Finance → CoinGecko (gratuit)
      Macro US            → FRED CSV public (gratuit)
      Intraday détaillé   → Alpha Vantage (clé gratuite)
      News                → Finnhub (clé gratuite) → Yahoo RSS (gratuit)
      Fear & Greed        → Alternative.me (gratuit)
    """

    def __init__(self) -> None:
        self.yf   = YahooFinanceAPI()
        self.fred = FREDAPI()
        self.cg   = CoinGeckoAPI()
        self.av   = AlphaVantageAPI()
        self.fh   = FinnhubAPI()
        self.rss  = YahooRSSNews()
        logger.info("MarketAPI initialisé — YF + FRED + CoinGecko + AV + Finnhub + RSS")

    # ── Prix ─────────────────────────────────────────────────────────────────

    def price(self, symbol: str) -> Optional[Dict]:
        """Prix temps réel avec fallback automatique."""
        p = self.yf.price(symbol)
        if p:
            return p
        # Fallback CoinGecko pour crypto
        clean = symbol.upper().replace("-USD", "")
        if clean in CoinGeckoAPI.COIN_IDS:
            cg = self.cg.prices(clean)
            d  = cg.get(clean, {})
            if d:
                return {
                    "symbol":     symbol.upper(),
                    "price":      d.get("price"),
                    "change_pct": d.get("change_24h"),
                    "volume":     d.get("volume_24h"),
                    "source":     "CoinGecko",
                }
        return None

    def prices(self, *symbols: str) -> Dict[str, Optional[Dict]]:
        """Prix de plusieurs actifs en un seul appel (batch optimisé)."""
        CRYPTO   = set(CoinGeckoAPI.COIN_IDS.keys())
        crypto_s = [s for s in symbols if s.upper().replace("-USD","") in CRYPTO]
        stock_s  = [s for s in symbols if s not in crypto_s]
        result: Dict[str, Optional[Dict]] = {}

        if stock_s:
            multi = self.yf.multi_price(list(stock_s))
            result.update(multi)
            for s in stock_s:
                if s not in result:
                    result[s] = self.yf.price(s)

        if crypto_s:
            clean_ids = [s.upper().replace("-USD","") for s in crypto_s]
            cg = self.cg.prices(*clean_ids)
            for orig, cid in zip(crypto_s, clean_ids):
                d = cg.get(cid, {})
                if d:
                    result[orig] = {
                        "symbol":     orig.upper(),
                        "price":      d.get("price"),
                        "change_pct": d.get("change_24h"),
                        "volume":     d.get("volume_24h"),
                        "source":     "CoinGecko",
                    }

        return result

    # ── OHLCV ────────────────────────────────────────────────────────────────

    def ohlcv(self, symbol: str, period: str = "1y",
               interval: str = "1d") -> Optional["pd.DataFrame"]:
        """OHLCV avec fallback YF → CoinGecko (crypto) → AV (intraday)."""
        df = self.yf.ohlcv(symbol, period=period, interval=interval)
        if df is not None and not df.empty and len(df) >= 5:
            return df

        clean = symbol.upper().replace("-USD","")
        if clean in CoinGeckoAPI.COIN_IDS:
            days = {"1mo":30,"3mo":90,"6mo":90,"1y":90}.get(period, 30)
            return self.cg.ohlcv(clean, days=days)

        if interval in ("1m","2m","5m","15m","30m","60m","1h"):
            av_int = {"1h":"60min","60m":"60min"}.get(interval, interval.replace("m","min"))
            return self.av.intraday(symbol, av_int)

        return None

    def ohlcv_multi_tf(self, symbol: str) -> Dict[str, Optional["pd.DataFrame"]]:
        """OHLCV sur 3 timeframes simultanément."""
        return {
            "1d": self.ohlcv(symbol, "2y",  "1d"),
            "1h": self.ohlcv(symbol, "60d", "1h"),
            "5m": self.ohlcv(symbol, "5d",  "5m"),
        }

    # ── Macro ────────────────────────────────────────────────────────────────

    def macro(self) -> Dict:
        """Données macro complètes (FRED + enrichissement Yahoo Finance)."""
        result = self.fred.macro_dashboard()

        # Enrichir avec Yahoo Finance pour VIX, Or, Brent, Forex
        for sym, key in [
            ("^VIX","VIX_YF"), ("GC=F","GOLD"), ("BZ=F","BRENT"),
            ("DX-Y.NYB","DXY"), ("EURUSD=X","EURUSD"), ("USDJPY=X","USDJPY"),
            ("GBPUSD=X","GBPUSD"),
        ]:
            p = self.yf.price(sym)
            if p:
                result[key] = {
                    "value":      p["price"],
                    "change":     p["change"],
                    "change_pct": p["change_pct"],
                    "source":     "Yahoo Finance",
                }

        result["yield_curve"] = self.fred.yield_curve()
        return result

    def macro_summary(self) -> Dict:
        """Résumé macro concis pour l'affichage rapide."""
        m = self.macro()
        return {
            "t10y":          m.get("T10Y", {}).get("value"),
            "t2y":           m.get("T2Y", {}).get("value"),
            "spread_10_2":   (m.get("SPREAD_CALC", {}).get("value") or
                               m.get("SPREAD_10_2", {}).get("value")),
            "vix":           (m.get("VIX_YF", {}).get("value") or
                               m.get("VIX_FRED", {}).get("value")),
            "gold":          m.get("GOLD", {}).get("value"),
            "brent":         m.get("BRENT", {}).get("value"),
            "dxy":           m.get("DXY", {}).get("value"),
            "eurusd":        m.get("EURUSD", {}).get("value"),
            "usdjpy":        m.get("USDJPY", {}).get("value"),
            "gbpusd":        m.get("GBPUSD", {}).get("value"),
            "ig_spread_bps": m.get("IG_SPREAD", {}).get("bps"),
            "hy_spread_bps": m.get("HY_SPREAD", {}).get("bps"),
            "fed_funds":     m.get("FEDFUNDS", {}).get("value"),
            "cpi":           m.get("CPI", {}).get("value"),
            "unemployment":  m.get("UNEMPLOYMENT", {}).get("value"),
            "yield_curve":   m.get("yield_curve", {}),
            "timestamp":     datetime.utcnow().isoformat(),
        }

    # ── Crypto ───────────────────────────────────────────────────────────────

    def crypto(self) -> Dict:
        """Données crypto complètes : prix + marché global + Fear&Greed."""
        syms = ["BTC","ETH","SOL","BNB","XRP","ADA"]
        return {
            "prices":     self.cg.prices(*syms),
            "global":     self.cg.global_market(),
            "fear_greed": self.cg.fear_greed(),
            "timestamp":  datetime.utcnow().isoformat(),
        }

    # ── News & Sentiment ─────────────────────────────────────────────────────

    def news(self, symbol: str = None, limit: int = 10) -> List[Dict]:
        """Actualités : Finnhub (si clé) → Yahoo RSS (gratuit)."""
        if symbol and self.fh.key:
            result = self.fh.company_news(symbol, days=3)
            if result:
                return result[:limit]
        return self.rss.get_news(symbol, limit=limit)

    def sentiment(self, symbol: str) -> Optional[Dict]:
        return self.fh.news_sentiment(symbol)

    def analyst_consensus(self, symbol: str) -> Optional[Dict]:
        return self.fh.analyst_recommendation(symbol)

    # ── Fondamentaux ─────────────────────────────────────────────────────────

    def fundamentals(self, symbol: str) -> Optional[Dict]:
        return self.yf.fundamentals(symbol)

    def earnings(self, symbol: str) -> Optional[Dict]:
        return self.yf.earnings(symbol)

    def options(self, symbol: str) -> Optional[Dict]:
        return self.yf.options_chain(symbol)

    # ── Snapshot complet ─────────────────────────────────────────────────────

    def snapshot(self, watchlist: List[str] = None) -> Dict:
        """Snapshot complet du marché — tout en un appel pour le dashboard."""
        wl = watchlist or ["SPY","QQQ","AAPL","MSFT","NVDA",
                            "BTC-USD","GC=F","EURUSD=X","^VIX"]
        return {
            "timestamp":   datetime.utcnow().isoformat(),
            "prices":      self.prices(*wl),
            "macro":       self.macro_summary(),
            "crypto":      self.crypto(),
            "market_news": self.rss.get_news(limit=8),
            "cache_stats": CACHE.stats,
        }

    # ── Health check ─────────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, str]:
        """Vérifie chaque source et retourne son statut."""
        status: Dict[str, str] = {}

        # Yahoo Finance
        try:
            p = self.yf.price("SPY")
            status["yahoo_finance"] = (
                f"✅  SPY = ${p['price']:>10,.2f}   ({p['change_pct']:+.2f}%)"
                if p else "⚠️  Données vides"
            )
        except Exception as e:
            status["yahoo_finance"] = f"❌  {e}"

        # FRED
        try:
            df = self.fred.get_series("DGS10", limit=2)
            status["fred"] = (
                f"✅  T10Y = {df.iloc[-1]['value']:.2f}%   ({df.iloc[-1]['date'].date()})"
                if df is not None and not df.empty else "⚠️  Données vides"
            )
        except Exception as e:
            status["fred"] = f"❌  {e}"

        # CoinGecko
        try:
            cg = self.cg.prices("BTC")
            d  = cg.get("BTC", {})
            status["coingecko"] = (
                f"✅  BTC = ${d.get('price', 0):>12,.0f}   ({d.get('change_24h', 0):+.2f}%)"
                if d else "⚠️  Données vides"
            )
        except Exception as e:
            status["coingecko"] = f"❌  {e}"

        # Fear & Greed
        try:
            fg = self.cg.fear_greed()
            status["fear_greed"] = f"✅  {fg['value']}/100 — {fg['label']}"
        except Exception as e:
            status["fear_greed"] = f"⚠️  {e}"

        # Alpha Vantage
        status["alpha_vantage"] = (
            f"✅  Clé configurée ({self.av.key[:6]}...)"
            if self.av.key != "demo"
            else "ℹ️   Clé demo (limitée) — Obtenir gratuitement : alphavantage.co"
        )

        # Finnhub
        status["finnhub"] = (
            "✅  Clé configurée — news + sentiment + calendrier résultats"
            if self.fh.key
            else "ℹ️   Non configuré (optionnel) — Obtenir gratuitement : finnhub.io"
        )

        # Yahoo RSS
        try:
            n = self.rss.get_news(limit=2)
            status["yahoo_rss"] = (
                f"✅  {len(n)} articles récupérés (gratuit, sans clé)"
                if n else "⚠️  RSS vide"
            )
        except Exception as e:
            status["yahoo_rss"] = f"⚠️  {e}"

        # FRED API key
        status["fred_api_key"] = (
            "✅  Clé FRED configurée (accès JSON + séries avancées)"
            if self.fred.api_key
            else "ℹ️   Pas de clé FRED (CSV public fonctionnel) — Optionnel : fred.stlouisfed.org"
        )

        status["_cache"] = (
            f"📦  Cache : {CACHE.stats['entries']} entrées | "
            f"hits={CACHE.stats['hits']} | ratio={CACHE.stats['ratio']}"
        )
        return status


# ══════════════════════════════════════════════════════════════════════════════
# §9  CLI — EXÉCUTION DIRECTE  python3 api_manager.py [--option]
# ══════════════════════════════════════════════════════════════════════════════

def _banner() -> None:
    print("""
╔══════════════════════════════════════════════════════════╗
║  api_manager.py  —  Données de marché temps réel        ║
║  Sources : Yahoo Finance · FRED · CoinGecko             ║
║            Alpha Vantage · Finnhub · Yahoo RSS          ║
╚══════════════════════════════════════════════════════════╝
""")


def main() -> None:
    import argparse
    _banner()

    p = argparse.ArgumentParser(
        description=(
            "Test et démonstration des APIs de données de marché\n"
            "Toutes les commandes sont compatibles Python 3 sur macOS (Terminal)."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("--check",    action="store_true",
                    help="Health check de toutes les sources")
    p.add_argument("--price",    type=str, default="",
                    help="Prix temps réel  ex: AAPL  ou  SPY,QQQ,BTC-USD")
    p.add_argument("--ohlcv",   type=str, default="",
                    help="OHLCV historique  ex: SPY")
    p.add_argument("--period",  type=str, default="1y",
                    help="Période OHLCV  ex: 1y  3mo  ytd  (défaut: 1y)")
    p.add_argument("--interval",type=str, default="1d",
                    help="Intervalle OHLCV  ex: 1d  1h  5m  (défaut: 1d)")
    p.add_argument("--macro",   action="store_true",
                    help="Tableau de bord macro complet")
    p.add_argument("--curve",   action="store_true",
                    help="Courbe des taux US (3M → 30Y)")
    p.add_argument("--crypto",  action="store_true",
                    help="Marché crypto + Fear & Greed")
    p.add_argument("--news",    type=str, default="",
                    help="Actualités  ex: AAPL  (vide = marché général)")
    p.add_argument("--fund",    type=str, default="",
                    help="Fondamentaux  ex: AAPL")
    p.add_argument("--options", type=str, default="",
                    help="Chaîne d'options  ex: AAPL")
    p.add_argument("--snap",    action="store_true",
                    help="Snapshot complet du marché (JSON)")
    args = p.parse_args()

    api = MarketAPI()

    # Par défaut : health check si aucun argument
    if not any([args.price, args.ohlcv, args.macro, args.curve,
                args.crypto, args.news, args.fund, args.options, args.snap]):
        args.check = True

    # ── Health check ──────────────────────────────────────────────────────────
    if args.check:
        print("📡  SOURCES DE DONNÉES — ÉTAT\n" + "═"*60)
        for src, st in api.health_check().items():
            if src.startswith("_"):
                print(f"\n  {st}")
            else:
                print(f"  {src:20s}: {st}")
        print()

    # ── Prix ─────────────────────────────────────────────────────────────────
    if args.price:
        syms = [s.strip() for s in args.price.split(",") if s.strip()]
        print(f"💹  PRIX EN TEMPS RÉEL\n" + "─"*60)
        data = api.prices(*syms)
        for sym in syms:
            d = data.get(sym)
            if not d:
                print(f"  {sym:14s}  N/A")
                continue
            chg  = d.get("change_pct", 0) or 0
            icon = "▲" if chg > 0 else "▼" if chg < 0 else "─"
            vol  = d.get("volume", 0) or 0
            src  = d.get("source", "")
            print(f"  {sym:14s}  {d.get('price', 0):>14.4f}  {icon} {chg:+.3f}%  "
                  f"vol:{vol:>15,}  [{src}]")
        print()

    # ── OHLCV ────────────────────────────────────────────────────────────────
    if args.ohlcv:
        sym = args.ohlcv.strip()
        print(f"📊  OHLCV — {sym.upper()}  ({args.period} / {args.interval})\n" + "─"*60)
        df = api.ohlcv(sym, period=args.period, interval=args.interval)
        if df is not None and not df.empty:
            print(df.tail(10).to_string())
            n   = len(df)
            ret = (float(df["Close"].iloc[-1]) / float(df["Close"].iloc[0]) - 1) * 100
            print(f"\n  {n} barres | {df.index[0].date()} → {df.index[-1].date()}")
            print(f"  Clôture : {df['Close'].iloc[-1]:.4f} | Return période : {ret:+.2f}%")
        else:
            print("  ❌  Aucune donnée disponible")
        print()

    # ── Macro ────────────────────────────────────────────────────────────────
    if args.macro:
        print("🌍  TABLEAU DE BORD MACRO\n" + "─"*60)
        m = api.macro_summary()
        fields = [
            ("Taux 10 ans US",   "t10y",          "%.3f %%"),
            ("Taux 2 ans US",    "t2y",            "%.3f %%"),
            ("Spread 10-2",      "spread_10_2",    "%.3f %%"),
            ("Fed Funds",        "fed_funds",      "%.2f %%"),
            ("Inflation CPI",    "cpi",            "%.1f (index)"),
            ("Chômage US",       "unemployment",   "%.1f %%"),
            ("VIX",              "vix",            "%.2f"),
            ("Or (XAU/USD)",     "gold",           "$ %.2f"),
            ("Brent Crude",      "brent",          "$ %.2f"),
            ("Dollar Index",     "dxy",            "%.2f"),
            ("EUR/USD",          "eurusd",         "%.4f"),
            ("USD/JPY",          "usdjpy",         "%.2f"),
            ("GBP/USD",          "gbpusd",         "%.4f"),
            ("Spread IG (bps)",  "ig_spread_bps",  "%.1f bps"),
            ("Spread HY (bps)",  "hy_spread_bps",  "%.1f bps"),
        ]
        for label, key, fmt in fields:
            v = m.get(key)
            if v is None:
                continue
            try:    display = fmt % float(v)
            except: display = str(v)
            print(f"  {label:22s}: {display}")

        full = api.macro()
        if "SPREAD_CALC" in full:
            print(f"\n  Courbe : {full['SPREAD_CALC'].get('signal','N/A')}")
        if "IG_SPREAD" in full and full["IG_SPREAD"].get("alert"):
            print(f"  Crédit : {full['IG_SPREAD']['alert']}")
        print()

    # ── Courbe des taux ───────────────────────────────────────────────────────
    if args.curve:
        print("📈  COURBE DES TAUX US\n" + "─"*40)
        curve = api.fred.yield_curve()
        if curve:
            prev = list(curve.values())[0]
            for mat, val in curve.items():
                bar  = "█" * max(1, int(val * 5))
                inv  = " ← inversée" if val < prev else ""
                print(f"  {mat:5s}  {val:.3f}%  {bar}{inv}")
                prev = val
        else:
            print("  Données FRED temporairement indisponibles")
        print()

    # ── Crypto ───────────────────────────────────────────────────────────────
    if args.crypto:
        print("₿   MARCHÉ CRYPTO\n" + "─"*60)
        c  = api.crypto()
        fg = c.get("fear_greed", {})
        gl = c.get("global", {})
        print(f"  Fear & Greed : {fg.get('value','N/A')}/100 — {fg.get('label','N/A')}")
        if gl.get("btc_dominance"):
            print(f"  BTC Dominance: {gl['btc_dominance']:.1f}%")
        if gl.get("total_mcap_usd"):
            print(f"  Market Cap   : ${gl['total_mcap_usd']/1e12:.2f}T")
        if gl.get("mcap_change_24h") is not None:
            print(f"  Var 24h      : {gl['mcap_change_24h']:+.2f}%")
        print()
        for sym, d in c.get("prices", {}).items():
            chg  = d.get("change_24h", 0) or 0
            icon = "▲" if chg > 0 else "▼"
            mcap = d.get("market_cap")
            ms   = f"  mcap:${mcap/1e9:.1f}B" if mcap else ""
            print(f"  {sym:6s}  ${d.get('price',0):>12,.2f}  {icon} {chg:+.2f}%{ms}")
        print()

    # ── News ─────────────────────────────────────────────────────────────────
    if args.news is not None and args.news != "":
        sym = args.news.strip() or None
        print(f"📰  ACTUALITÉS — {sym.upper() if sym else 'MARCHÉ GÉNÉRAL'}\n" + "─"*60)
        news = api.news(sym, limit=8)
        if news:
            for i, n in enumerate(news, 1):
                dt = (n.get("datetime","")[:16] or "").replace("T"," ")
                print(f"\n  [{i}] {n.get('headline','')}")
                print(f"      {dt}  •  {n.get('source','')}")
                if n.get("summary"):
                    print(f"      {n['summary'][:100]}")
                if n.get("url") and n["url"] != "#":
                    print(f"      → {n['url']}")
        else:
            print("  Aucune actualité disponible")
        print()

    # ── Fondamentaux ─────────────────────────────────────────────────────────
    if args.fund:
        sym = args.fund.strip().upper()
        print(f"📋  FONDAMENTAUX — {sym}\n" + "─"*60)
        f = api.fundamentals(sym)
        if f:
            fields_f = [
                ("Société",        "company_name",    "%s"),
                ("Secteur",        "sector",          "%s / {industry}"),
                ("Pays / Devise",  "country",         "%s / {currency}"),
                ("Market Cap",     "market_cap",      "$ {:,.0f}"),
                ("Entr. Value",    "enterprise_value","$ {:,.0f}"),
                ("P/E Trailing",   "pe_ratio",        "%.2f"),
                ("P/E Forward",    "forward_pe",      "%.2f"),
                ("PEG Ratio",      "peg_ratio",       "%.2f"),
                ("Prix/Valeur lv", "price_to_book",   "%.2f"),
                ("EPS TTM",        "eps_ttm",         "$ %.2f"),
                ("EPS Forward",    "eps_forward",     "$ %.2f"),
                ("Marge nette",    "profit_margin",   "%.1f %%"),
                ("Marge opérat.",  "operating_margin","%.1f %%"),
                ("ROE",            "roe",             "%.1f %%"),
                ("ROA",            "roa",             "%.1f %%"),
                ("Dette/CP",       "debt_equity",     "%.2f"),
                ("Ratio courant",  "current_ratio",   "%.2f"),
                ("Free Cash Flow", "free_cashflow",   "$ {:,.0f}"),
                ("Dividende",      "dividend_yield",  "%.2f %%"),
                ("Beta",           "beta",            "%.2f"),
                ("52W High",       "52w_high",        "$ %.2f"),
                ("52W Low",        "52w_low",         "$ %.2f"),
                ("Nb analystes",   "analyst_count",   "%.0f"),
                ("Prix cible",     "analyst_target",  "$ %.2f"),
                ("Recommandation", "recommendation",  "%s"),
            ]
            for label, key, fmt in fields_f:
                v = f.get(key)
                if v is None:
                    continue
                try:
                    if "{" in fmt:
                        pass  # skip complex format
                    elif "%" in fmt:
                        mult = 100 if key in ("profit_margin","operating_margin","roe","roa","dividend_yield") else 1
                        display = fmt % (float(v) * mult)
                    else:
                        display = fmt % float(v) if isinstance(v, (int, float)) else fmt % v
                    print(f"  {label:22s}: {display}")
                except Exception:
                    if v:
                        print(f"  {label:22s}: {v}")
        else:
            print("  ❌  Données fondamentales indisponibles")
        print()

    # ── Options ──────────────────────────────────────────────────────────────
    if args.options:
        sym = args.options.strip().upper()
        print(f"📑  CHAÎNE D'OPTIONS — {sym}\n" + "─"*60)
        opt = api.options(sym)
        if opt:
            print(f"  Expiration : {opt['expiration']}")
            print(f"  Expirations dispo : {', '.join(opt.get('all_expirations',[])[:4])}")
            print(f"\n  CALLS (top 5) :")
            for c in opt.get("calls", [])[:5]:
                print(f"    Strike {c.get('strike'):>8.2f} | Bid {c.get('bid',0):.2f} "
                      f"Ask {c.get('ask',0):.2f} | Vol {c.get('volume',0)} "
                      f"| IV {c.get('impliedVolatility',0):.1%}")
            print(f"\n  PUTS (top 5) :")
            for c in opt.get("puts", [])[:5]:
                print(f"    Strike {c.get('strike'):>8.2f} | Bid {c.get('bid',0):.2f} "
                      f"Ask {c.get('ask',0):.2f} | Vol {c.get('volume',0)} "
                      f"| IV {c.get('impliedVolatility',0):.1%}")
        else:
            print("  ❌  Options indisponibles pour ce symbole")
        print()

    # ── Snapshot ─────────────────────────────────────────────────────────────
    if args.snap:
        print("🔭  SNAPSHOT COMPLET DU MARCHÉ\n" + "─"*60)
        snap = api.snapshot()
        # Affichage JSON structuré
        # On filtre les champs trop lourds pour l'affichage terminal
        display = {
            "timestamp": snap["timestamp"],
            "prices":    snap["prices"],
            "macro": {k: v for k, v in snap["macro"].items()
                      if k not in ("yield_curve","timestamp") and v is not None},
            "crypto_fg":  snap.get("crypto",{}).get("fear_greed",{}),
            "cache":      snap["cache_stats"],
        }
        print(json.dumps(display, indent=2, ensure_ascii=False, default=str))
        print()

    print(f"  Cache final : {CACHE.stats}")
    print()


if __name__ == "__main__":
    main()
