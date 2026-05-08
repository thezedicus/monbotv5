#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  market_db.py  —  Base de données historique + actualisation en direct      ║
║  Bot d'Analyse de Marché v3.0  |  Python 3  |  macOS                        ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES TERMINAL MAC :                                                    ║
║                                                                              ║
║  # Installation (une seule fois)                                             ║
║  pip3 install yfinance requests pandas numpy                                ║
║                                                                              ║
║  # Initialiser la base (actifs principaux — recommandé pour démarrer)       ║
║  python3 market_db.py --init                                                 ║
║                                                                              ║
║  # Initialiser avec actifs complets (~40 symboles)                          ║
║  python3 market_db.py --init --full                                          ║
║                                                                              ║
║  # Télécharger des actifs spécifiques (virgule pour plusieurs)              ║
║  python3 market_db.py --populate SPY                                         ║
║  python3 market_db.py --populate SPY,QQQ,AAPL,BTC-USD,GC=F                 ║
║                                                                              ║
║  # Mettre à jour tous les actifs déjà en base                               ║
║  python3 market_db.py --update                                               ║
║                                                                              ║
║  # Feed temps réel (30s minimum entre actualisations)                       ║
║  python3 market_db.py --watch SPY,QQQ,BTC-USD                               ║
║  python3 market_db.py --watch SPY,BTC-USD --interval-s 15                   ║
║                                                                              ║
║  # Rapport de santé de la base                                               ║
║  python3 market_db.py --health                                               ║
║                                                                              ║
║  # Afficher les dernières données d'un actif                                 ║
║  python3 market_db.py --query SPY                                            ║
║  python3 market_db.py --query SPY --n 20                                     ║
║                                                                              ║
║  # Exporter en CSV                                                           ║
║  python3 market_db.py --export SPY                                           ║
║  python3 market_db.py --export SPY,QQQ,BTC-USD                              ║
║                                                                              ║
║  # Télécharger les fondamentaux                                              ║
║  python3 market_db.py --fundamentals AAPL,MSFT,NVDA                         ║
║                                                                              ║
║  INTÉGRATION dans bot_v3.py :                                                ║
║    from market_db import MarketDatabase, MarketUpdater, MarketDataBridge    ║
║    db     = MarketDatabase()                                                 ║
║    bridge = MarketDataBridge(db)                                             ║
║    df     = bridge.get("SPY", n_days=252)    # Données réelles depuis DB   ║
║    price  = bridge.live_price("SPY")          # Prix actuel                 ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, sqlite3, json, time, logging, threading, warnings
from datetime    import datetime, timedelta, date
from pathlib     import Path
from typing      import Optional, Dict, List, Tuple, Any
from contextlib  import contextmanager
from io          import StringIO

warnings.filterwarnings("ignore")

# ── Dossiers ──────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    handlers= [
        logging.FileHandler("logs/market_db.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("MarketBot.DB")
for _n in ("yfinance","urllib3","peewee","charset_normalizer"):
    logging.getLogger(_n).setLevel(logging.CRITICAL)

import pandas as pd
import numpy  as np

try:    import yfinance as yf;  YF_OK = True
except: YF_OK = False; print("⚠️  pip3 install yfinance")
try:    import requests;        REQ_OK = True
except: REQ_OK = False; print("⚠️  pip3 install requests")


# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH   = Path("data/market.db")
EXPORT_DIR = Path("data/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Univers d'actifs couverts
UNIVERSE: Dict[str, List[str]] = {
    "us_equities": [
        "SPY","QQQ","IWM","DIA","XLK","XLF","XLE","XLV","XLI","XLP",
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
        "MA","NFLX","ORCL","ADBE","AMD","INTC","CRM","IBM",
    ],
    "indices": [
        "^GSPC","^IXIC","^DJI","^RUT","^VIX","^TNX","^IRX",
        "^GDAXI","^FCHI","^N225","^HSI",
    ],
    "commodities": ["GC=F","SI=F","CL=F","BZ=F","NG=F","HG=F","ZC=F","ZW=F"],
    "forex":       [
        "EURUSD=X","USDJPY=X","GBPUSD=X","AUDUSD=X",
        "USDCHF=X","USDCAD=X","DX-Y.NYB",
    ],
    "crypto":      ["BTC-USD","ETH-USD","SOL-USD","BNB-USD","XRP-USD"],
}

QUICK_LIST = [
    "SPY","QQQ","AAPL","MSFT","NVDA","BTC-USD","ETH-USD",
    "GC=F","CL=F","EURUSD=X","USDJPY=X","^VIX","^TNX",
]

# Séries FRED à stocker
FRED_SERIES: Dict[str, str] = {
    "DGS10":       "T10Y",
    "DGS2":        "T2Y",
    "DTB3":        "T3M",
    "DGS5":        "T5Y",
    "DGS30":       "T30Y",
    "VIXCLS":      "VIX_FRED",
    "BAMLC0A0CM":  "IG_SPREAD",
    "BAMLH0A0HYM2":"HY_SPREAD",
    "FEDFUNDS":    "FED_FUNDS",
    "CPIAUCSL":    "CPI",
    "UNRATE":      "UNEMPLOYMENT",
}


# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DONNÉES SQLITE
# ══════════════════════════════════════════════════════════════════════════════

class MarketDatabase:
    """Base de données SQLite locale pour toutes les données de marché."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock   = threading.RLock()
        self._init_schema()
        logger.info(f"Base de données : {self.db_path.resolve()}")

    @contextmanager
    def _conn(self):
        """Connexion thread-safe avec commit/rollback automatique."""
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Crée les tables si elles n'existent pas encore."""
        with self._lock, self._conn() as c:
            c.executescript("""
                -- OHLCV : données de prix historiques
                CREATE TABLE IF NOT EXISTS ohlcv (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol    TEXT    NOT NULL,
                    date      TEXT    NOT NULL,
                    interval  TEXT    NOT NULL DEFAULT '1d',
                    open      REAL,
                    high      REAL,
                    low       REAL,
                    close     REAL    NOT NULL,
                    volume    INTEGER,
                    UNIQUE(symbol, date, interval)
                );
                CREATE INDEX IF NOT EXISTS idx_ohlcv_sym
                    ON ohlcv(symbol, interval, date DESC);

                -- Ticks : prix temps réel
                CREATE TABLE IF NOT EXISTS ticks (
                    symbol      TEXT PRIMARY KEY,
                    price       REAL,
                    change      REAL,
                    change_pct  REAL,
                    volume      INTEGER,
                    high_24h    REAL,
                    low_24h     REAL,
                    source      TEXT,
                    updated_at  TEXT DEFAULT (datetime('now','utc'))
                );

                -- Macro : séries économiques FRED
                CREATE TABLE IF NOT EXISTS macro (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT    NOT NULL,
                    name      TEXT,
                    value     REAL    NOT NULL,
                    date      TEXT    NOT NULL,
                    source    TEXT    DEFAULT 'FRED',
                    UNIQUE(series_id, date)
                );
                CREATE INDEX IF NOT EXISTS idx_macro_sid
                    ON macro(series_id, date DESC);

                -- Fondamentaux : données fondamentales par action
                CREATE TABLE IF NOT EXISTS fundamentals (
                    symbol          TEXT PRIMARY KEY,
                    company_name    TEXT,
                    sector          TEXT,
                    industry        TEXT,
                    country         TEXT,
                    market_cap      REAL,
                    pe_ratio        REAL,
                    forward_pe      REAL,
                    eps_ttm         REAL,
                    profit_margin   REAL,
                    roe             REAL,
                    debt_equity     REAL,
                    beta            REAL,
                    dividend_yield  REAL,
                    high_52w        REAL,
                    low_52w         REAL,
                    recommendation  TEXT,
                    raw_json        TEXT,
                    updated_at      TEXT DEFAULT (datetime('now','utc'))
                );

                -- Signaux : historique des signaux générés par le bot
                CREATE TABLE IF NOT EXISTS signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT NOT NULL,
                    signal      TEXT,
                    regime      TEXT,
                    bull_score  REAL,
                    bear_score  REAL,
                    confidence  REAL,
                    price       REAL,
                    reasons     TEXT,
                    created_at  TEXT DEFAULT (datetime('now','utc'))
                );
                CREATE INDEX IF NOT EXISTS idx_sig_sym
                    ON signals(symbol, created_at DESC);

                -- Métadonnées : timestamps et config
                CREATE TABLE IF NOT EXISTS meta (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TEXT DEFAULT (datetime('now','utc'))
                );
            """)

    # ── OHLCV ─────────────────────────────────────────────────────────────────

    def upsert_ohlcv(self, symbol: str, df: "pd.DataFrame",
                      interval: str = "1d") -> int:
        """Insère ou met à jour des barres OHLCV. Retourne le nombre de lignes insérées."""
        if df is None or df.empty:
            return 0
        rows = []
        for idx, row in df.iterrows():
            dt = idx.strftime("%Y-%m-%d %H:%M:%S") if hasattr(idx, "strftime") else str(idx)
            rows.append((
                symbol, dt, interval,
                float(row.get("Open",  0) or 0),
                float(row.get("High",  0) or 0),
                float(row.get("Low",   0) or 0),
                float(row.get("Close", 0) or 0),
                int(row.get("Volume", 0) or 0),
            ))
        inserted = 0
        with self._lock, self._conn() as c:
            for r in rows:
                try:
                    c.execute(
                        "INSERT OR REPLACE INTO ohlcv"
                        "(symbol,date,interval,open,high,low,close,volume) "
                        "VALUES(?,?,?,?,?,?,?,?)", r
                    )
                    inserted += 1
                except Exception:
                    pass
        self._set_meta(f"ohlcv_last_{symbol}_{interval}", datetime.utcnow().isoformat())
        return inserted

    def get_ohlcv(self, symbol: str, interval: str = "1d",
                   n_last: int = 504,
                   start_date: str = None) -> "pd.DataFrame":
        """Lit les données OHLCV depuis la base. Retourne DataFrame trié par date ASC."""
        sql    = ("SELECT date,open,high,low,close,volume FROM ohlcv "
                   "WHERE symbol=? AND interval=?")
        params: List = [symbol, interval]
        if start_date:
            sql    += " AND date >= ?"; params.append(start_date)
        sql    += " ORDER BY date DESC LIMIT ?"
        params.append(n_last)

        with self._lock, self._conn() as c:
            rows = c.execute(sql, params).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            [(r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"])
             for r in rows],
            columns=["date","Open","High","Low","Close","Volume"]
        )
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()

    def symbols_in_db(self, interval: str = "1d") -> List[str]:
        """Liste des symboles présents en base pour un intervalle donné."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT symbol FROM ohlcv WHERE interval=? ORDER BY symbol",
                [interval]
            ).fetchall()
        return [r["symbol"] for r in rows]

    def coverage(self) -> List[Dict]:
        """Résumé de la couverture des données (symboles, nombre de lignes, dates)."""
        with self._lock, self._conn() as c:
            rows = c.execute("""
                SELECT symbol, interval,
                       COUNT(*)    AS n,
                       MIN(date)   AS first_date,
                       MAX(date)   AS last_date
                FROM ohlcv
                GROUP BY symbol, interval
                ORDER BY symbol, interval
            """).fetchall()
        return [dict(r) for r in rows]

    def needs_update(self, symbol: str, interval: str = "1d",
                      max_age_h: float = 8.0) -> bool:
        """Retourne True si les données ont plus de max_age_h heures."""
        last = self._get_meta(f"ohlcv_last_{symbol}_{interval}")
        if not last:
            return True
        try:
            dt  = datetime.fromisoformat(last)
            age = (datetime.utcnow() - dt).total_seconds()
            return age > max_age_h * 3600
        except Exception:
            return True

    # ── Ticks (prix temps réel) ────────────────────────────────────────────────

    def upsert_tick(self, data: Dict) -> None:
        """Met à jour le dernier prix connu d'un symbole."""
        sym = data.get("symbol", "")
        if not sym:
            return
        with self._lock, self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO ticks
                (symbol,price,change,change_pct,volume,high_24h,low_24h,source,updated_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now','utc'))
            """, (
                sym,
                data.get("price"),
                data.get("change"),
                data.get("change_pct"),
                data.get("volume"),
                data.get("high_24h"),
                data.get("low_24h"),
                data.get("source", ""),
            ))

    def get_tick(self, symbol: str) -> Optional[Dict]:
        """Retourne le dernier tick connu d'un symbole."""
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM ticks WHERE symbol=?", [symbol]).fetchone()
        return dict(r) if r else None

    def get_all_ticks(self) -> List[Dict]:
        """Retourne tous les ticks disponibles."""
        with self._lock, self._conn() as c:
            rows = c.execute("SELECT * FROM ticks ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    # ── Macro (FRED) ───────────────────────────────────────────────────────────

    def upsert_macro(self, series_id: str, name: str,
                      value: float, date_str: str,
                      source: str = "FRED") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO macro(series_id,name,value,date,source) "
                "VALUES(?,?,?,?,?)",
                (series_id, name, value, date_str, source)
            )

    def get_macro_latest(self) -> Dict:
        """Snapshot des dernières valeurs de chaque série macro."""
        with self._lock, self._conn() as c:
            rows = c.execute("""
                SELECT m.series_id, m.name, m.value, m.date, m.source
                FROM macro m
                INNER JOIN (
                    SELECT series_id, MAX(date) AS md
                    FROM macro GROUP BY series_id
                ) x ON m.series_id=x.series_id AND m.date=x.md
                ORDER BY m.series_id
            """).fetchall()
        return {
            r["series_id"]: {
                "name":   r["name"],
                "value":  r["value"],
                "date":   r["date"],
                "source": r["source"],
            }
            for r in rows
        }

    def get_macro_series(self, series_id: str, limit: int = 252) -> "pd.DataFrame":
        """Historique d'une série macro."""
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT date, value FROM macro WHERE series_id=? "
                "ORDER BY date DESC LIMIT ?",
                [series_id, limit]
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([(r["date"], r["value"]) for r in rows],
                           columns=["date","value"])
        df["date"]  = pd.to_datetime(df["date"])
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.sort_values("date").set_index("date")

    # ── Fondamentaux ──────────────────────────────────────────────────────────

    def upsert_fundamentals(self, data: Dict) -> None:
        sym = data.get("symbol","")
        if not sym:
            return
        with self._lock, self._conn() as c:
            c.execute("""
                INSERT OR REPLACE INTO fundamentals
                (symbol,company_name,sector,industry,country,market_cap,pe_ratio,
                 forward_pe,eps_ttm,profit_margin,roe,debt_equity,beta,
                 dividend_yield,high_52w,low_52w,recommendation,raw_json,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','utc'))
            """, (
                sym,
                data.get("company_name"),  data.get("sector"),
                data.get("industry"),      data.get("country"),
                data.get("market_cap"),    data.get("pe_ratio"),
                data.get("forward_pe"),    data.get("eps_ttm"),
                data.get("profit_margin"), data.get("roe"),
                data.get("debt_equity"),   data.get("beta"),
                data.get("dividend_yield"),data.get("52w_high"),
                data.get("52w_low"),       data.get("recommendation"),
                json.dumps(data),
            ))

    def get_fundamentals(self, symbol: str) -> Optional[Dict]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM fundamentals WHERE symbol=?", [symbol]).fetchone()
        if not r:
            return None
        d = dict(r)
        if d.get("raw_json"):
            try:
                d.update(json.loads(d["raw_json"]))
            except Exception:
                pass
        return d

    # ── Signaux ───────────────────────────────────────────────────────────────

    def save_signal(self, analysis: Dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("""
                INSERT INTO signals
                (symbol,signal,regime,bull_score,bear_score,confidence,price,reasons)
                VALUES(?,?,?,?,?,?,?,?)
            """, (
                analysis.get("symbol",""),
                analysis.get("signal","HOLD"),
                analysis.get("regime",""),
                analysis.get("bull_score", 0),
                analysis.get("bear_score", 0),
                analysis.get("confidence", 0),
                analysis.get("price", 0),
                json.dumps(analysis.get("reasons", [])),
            ))

    def get_signal_history(self, symbol: str, limit: int = 30) -> List[Dict]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM signals WHERE symbol=? "
                "ORDER BY created_at DESC LIMIT ?",
                [symbol, limit]
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Méta ──────────────────────────────────────────────────────────────────

    def _set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO meta(key,value,updated_at) "
                "VALUES(?,?,datetime('now','utc'))",
                [key, str(value)]
            )

    def _get_meta(self, key: str) -> Optional[str]:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT value FROM meta WHERE key=?", [key]).fetchone()
        return r["value"] if r else None

    # ── Export ────────────────────────────────────────────────────────────────

    def export_csv(self, symbol: str, interval: str = "1d") -> str:
        """Exporte les données OHLCV d'un symbole en CSV. Retourne le chemin du fichier."""
        df = self.get_ohlcv(symbol, interval)
        if df.empty:
            raise ValueError(f"Aucune donnée pour {symbol} ({interval})")
        safe = symbol.replace("/","_").replace("^","").replace("=","_").replace("-","_")
        path = str(EXPORT_DIR / f"{safe}_{interval}_{date.today()}.csv")
        df.to_csv(path)
        return path

    # ── Rapport de santé ──────────────────────────────────────────────────────

    def health_report(self) -> None:
        cov   = self.coverage()
        ticks = self.get_all_ticks()
        macro = self.get_macro_latest()
        sz    = self.db_path.stat().st_size / 1024 / 1024 if self.db_path.exists() else 0

        print(f"\n{'═'*70}")
        print(f"  BASE DE DONNÉES — {self.db_path.resolve()}")
        print(f"  Taille : {sz:.2f} MB  |  {datetime.utcnow():%Y-%m-%d %H:%M} UTC")
        print(f"{'═'*70}")

        with self._lock, self._conn() as c:
            n_sig = c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"]

        print(f"\n  OHLCV — {len(cov)} séries de données")
        if cov:
            print(f"  {'Symbole':14s} {'Int':5s} {'Lignes':8s} "
                  f"{'Début':12s} {'Fin':12s} {'Màj':6s}")
            print(f"  {'─'*62}")
            for r in sorted(cov, key=lambda x: x["symbol"])[:20]:
                age_h = ""
                last_meta = self._get_meta(f"ohlcv_last_{r['symbol']}_{r['interval']}")
                if last_meta:
                    try:
                        age = (datetime.utcnow() - datetime.fromisoformat(last_meta)).total_seconds()
                        h   = age / 3600
                        age_h = f"{h:.0f}h"
                    except Exception:
                        pass
                print(f"  {r['symbol']:14s} {r['interval']:5s} {r['n']:8d} "
                      f"{str(r['first_date'])[:10]:12s} {str(r['last_date'])[:10]:12s} "
                      f"{age_h:6s}")
            if len(cov) > 20:
                print(f"  ... et {len(cov)-20} autres")
        else:
            print("  (vide — lancer : python3 market_db.py --init)")

        if ticks:
            print(f"\n  PRIX TEMPS RÉEL — {len(ticks)} actifs")
            print(f"  {'Symbole':14s} {'Prix':14s} {'Var%':10s} {'Màj':20s}")
            print(f"  {'─'*60}")
            for t in sorted(ticks, key=lambda x: x.get("symbol",""))[:12]:
                chg  = t.get("change_pct") or 0
                icon = "▲" if chg > 0 else "▼" if chg < 0 else "─"
                upd  = (t.get("updated_at") or "")[:16]
                print(f"  {t.get('symbol',''):14s} {t.get('price') or 0:14.4f} "
                      f"{icon}{abs(chg):9.3f}% {upd:20s}")

        if macro:
            print(f"\n  MACRO (FRED) — {len(macro)} séries")
            for sid, d in list(macro.items())[:10]:
                print(f"  {sid:18s}: {d['value']:.3f}   ({d['date'][:10]})")

        print(f"\n  Signaux enregistrés : {n_sig}")
        print(f"{'═'*70}\n")


# ══════════════════════════════════════════════════════════════════════════════
# MARKET UPDATER — Téléchargement + Feed temps réel
# ══════════════════════════════════════════════════════════════════════════════

class MarketUpdater:
    """
    Télécharge les données historiques depuis Yahoo Finance et FRED.
    Lance un thread de fond pour actualiser les prix en temps réel.
    """

    def __init__(self, db: MarketDatabase) -> None:
        self.db       = db
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stats   = {"updates": 0, "errors": 0, "start": None}

    # ── Téléchargement OHLCV ──────────────────────────────────────────────────

    def download_ohlcv(self, symbol: str, years: int = 3,
                        interval: str = "1d", force: bool = False) -> bool:
        """Télécharge l'historique OHLCV. Retourne True si succès."""
        if not YF_OK:
            logger.error("yfinance non installé : pip3 install yfinance")
            return False
        if not force and not self.db.needs_update(symbol, interval, max_age_h=8):
            logger.info(f"  {symbol:14s} {interval}  à jour, skip")
            return True

        period = f"{min(years,10)}y"
        for attempt in range(3):
            try:
                raw = yf.download(
                    symbol, period=period, interval=interval,
                    progress=False, auto_adjust=True, timeout=20
                )
                if raw is None or raw.empty:
                    time.sleep(3 * (attempt + 1))
                    continue

                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.droplevel(1)
                raw.columns = [str(c).strip().title() for c in raw.columns]
                cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
                df   = raw[cols].dropna(subset=["Close"])

                n = self.db.upsert_ohlcv(symbol, df, interval)
                logger.info(
                    f"  ✅ {symbol:14s} {interval}  {n:5d} lignes  "
                    f"{df.index[0].date()} → {df.index[-1].date()}"
                )
                return True

            except Exception as e:
                logger.warning(f"  ⚠️  {symbol} tentative {attempt+1}: {e}")
                time.sleep(5 * (attempt + 1))

        logger.error(f"  ❌ {symbol} : échec après 3 tentatives")
        return False

    def download_many(self, symbols: List[str], years: int = 3,
                       interval: str = "1d", force: bool = False) -> Dict[str, bool]:
        """Télécharge plusieurs actifs avec rapport de progression."""
        results: Dict[str, bool] = {}
        total = len(symbols)
        print(f"\n📥  Téléchargement — {total} actifs  ({interval}, {years} an(s))")
        print("─" * 60)
        for i, sym in enumerate(symbols, 1):
            print(f"  [{i:3d}/{total}] {sym:16s}", end=" ", flush=True)
            ok = self.download_ohlcv(sym, years=years, interval=interval, force=force)
            results[sym] = ok
            print("✅" if ok else "❌")
            time.sleep(0.6)   # Respecter le rate limit Yahoo Finance
        success = sum(1 for v in results.values() if v)
        print(f"─  {success}/{total} succès\n")
        return results

    def download_fundamentals(self, symbols: List[str]) -> None:
        """Télécharge et stocke les fondamentaux depuis Yahoo Finance."""
        if not YF_OK:
            return
        print(f"\n📋  Fondamentaux — {len(symbols)} actifs")
        for sym in symbols:
            try:
                info = yf.Ticker(sym).info or {}
                self.db.upsert_fundamentals({
                    "symbol":         sym,
                    "company_name":   info.get("longName",""),
                    "sector":         info.get("sector",""),
                    "industry":       info.get("industry",""),
                    "country":        info.get("country",""),
                    "market_cap":     info.get("marketCap"),
                    "pe_ratio":       info.get("trailingPE"),
                    "forward_pe":     info.get("forwardPE"),
                    "eps_ttm":        info.get("trailingEps"),
                    "profit_margin":  info.get("profitMargins"),
                    "roe":            info.get("returnOnEquity"),
                    "debt_equity":    info.get("debtToEquity"),
                    "beta":           info.get("beta"),
                    "dividend_yield": info.get("dividendYield"),
                    "52w_high":       info.get("fiftyTwoWeekHigh"),
                    "52w_low":        info.get("fiftyTwoWeekLow"),
                    "recommendation": info.get("recommendationKey",""),
                })
                print(f"  ✅ {sym}")
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  {sym}: {e}")

    # ── Actualisation prix temps réel ────────────────────────────────────────

    def refresh_prices(self, symbols: List[str]) -> None:
        """Actualise les prix depuis Yahoo Finance (batch)."""
        if not YF_OK or not symbols:
            return
        try:
            raw = yf.download(
                symbols if len(symbols) > 1 else symbols[0],
                period="5d", interval="1d",
                progress=False, auto_adjust=True,
                group_by="ticker" if len(symbols) > 1 else None,
                timeout=20
            )
            if raw is None or raw.empty:
                return

            for sym in symbols:
                try:
                    if len(symbols) == 1:
                        s_df = raw
                    else:
                        lvl0 = raw.columns.get_level_values(0)
                        if sym not in lvl0:
                            continue
                        s_df = raw[sym]

                    close = float(s_df["Close"].dropna().iloc[-1])
                    prev  = float(s_df["Close"].dropna().iloc[-2]) if len(s_df) > 1 else close
                    vol   = int(s_df["Volume"].dropna().iloc[-1]) if "Volume" in s_df.columns else 0
                    hi    = float(s_df["High"].dropna().iloc[-1])
                    lo    = float(s_df["Low"].dropna().iloc[-1])
                    chg   = close - prev

                    self.db.upsert_tick({
                        "symbol":     sym,
                        "price":      round(close, 6),
                        "change":     round(chg, 6),
                        "change_pct": round(chg / prev * 100 if prev else 0, 3),
                        "volume":     vol,
                        "high_24h":   round(hi, 6),
                        "low_24h":    round(lo, 6),
                        "source":     "Yahoo Finance",
                    })
                except Exception:
                    pass

        except Exception as e:
            logger.debug(f"refresh_prices: {e}")

    # ── Actualisation macro FRED ──────────────────────────────────────────────

    def refresh_macro_fred(self) -> None:
        """Télécharge les dernières valeurs des séries macro FRED."""
        if not REQ_OK:
            return
        for sid, name in FRED_SERIES.items():
            try:
                r = requests.get(
                    f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}",
                    timeout=12
                )
                r.raise_for_status()
                df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
                df.columns = ["date","value"]
                df["value"] = pd.to_numeric(df["value"], errors="coerce")
                df = df.dropna()
                if not df.empty:
                    last = df.iloc[-1]
                    self.db.upsert_macro(
                        sid, name, float(last["value"]),
                        str(last["date"].date()), "FRED"
                    )
                time.sleep(0.4)
            except Exception as e:
                logger.debug(f"FRED refresh {sid}: {e}")

    # ── Feed temps réel ───────────────────────────────────────────────────────

    def start(self, symbols: List[str], interval_s: int = 60,
               callbacks: List = None) -> None:
        """
        Démarre le feed temps réel en arrière-plan.
        interval_s : secondes entre actualisations (minimum 15s)
        callbacks  : fonctions appelées à chaque mise à jour (reçoivent le tick dict)
        """
        self._running  = True
        self._callbacks = callbacks or []
        self._stats["start"] = datetime.utcnow().isoformat()

        def _loop():
            while self._running:
                try:
                    self.refresh_prices(symbols)
                    self.refresh_macro_fred()
                    self._stats["updates"] += 1

                    # Appeler les callbacks
                    for tick in self.db.get_all_ticks():
                        for fn in self._callbacks:
                            try: fn(tick)
                            except Exception: pass

                    logger.debug(f"Feed update #{self._stats['updates']}")
                except Exception as e:
                    self._stats["errors"] += 1
                    logger.error(f"Feed error: {e}")

                # Attente interruptible
                iv = max(15, interval_s)
                for _ in range(iv):
                    if not self._running:
                        return
                    time.sleep(1)

        self._thread = threading.Thread(target=_loop, name="MarketFeed", daemon=True)
        self._thread.start()
        logger.info(
            f"Feed démarré — {len(symbols)} actifs "
            f"toutes les {max(15,interval_s)}s"
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Feed arrêté")

    @property
    def is_running(self) -> bool:
        return (self._running and
                self._thread is not None and
                self._thread.is_alive())

    def status(self) -> Dict:
        return {
            "running":   self.is_running,
            "updates":   self._stats["updates"],
            "errors":    self._stats["errors"],
            "start":     self._stats.get("start"),
        }


# ══════════════════════════════════════════════════════════════════════════════
# BRIDGE — Remplace DataProvider dans bot_v3.py
# ══════════════════════════════════════════════════════════════════════════════

class MarketDataBridge:
    """
    Pont entre la base de données locale et bot_v3.py.
    Remplace le DataProvider synthétique par des données réelles.

    Usage dans bot_v3.py :
        from market_db import MarketDataBridge
        bridge = MarketDataBridge()
        df     = bridge.get("SPY", n_days=252)
        price  = bridge.live_price("BTC-USD")
    """

    def __init__(self, db: Optional[MarketDatabase] = None) -> None:
        self.db = db or MarketDatabase()

    def get(self, symbol: str, n_days: int = 504,
             interval: str = "1d") -> "pd.DataFrame":
        """Lit depuis la DB locale ; fallback Yahoo Finance si absent ou vide."""
        df = self.db.get_ohlcv(symbol, interval=interval, n_last=n_days)
        if not df.empty and len(df) >= 30:
            return df

        # Fallback direct Yahoo Finance
        if YF_OK:
            try:
                logger.info(f"Bridge fallback YF pour {symbol}")
                raw = yf.download(
                    symbol,
                    period=f"{max(1, n_days // 252)}y",
                    interval=interval,
                    progress=False, auto_adjust=True, timeout=20
                )
                if raw is not None and not raw.empty:
                    if isinstance(raw.columns, pd.MultiIndex):
                        raw.columns = raw.columns.droplevel(1)
                    raw.columns = [str(c).strip().title() for c in raw.columns]
                    cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
                    df2  = raw[cols].dropna(subset=["Close"])
                    self.db.upsert_ohlcv(symbol, df2, interval)
                    return df2.tail(n_days)
            except Exception as e:
                logger.warning(f"Bridge YF fallback {symbol}: {e}")

        return pd.DataFrame()

    def live_price(self, symbol: str) -> Optional[float]:
        """Prix actuel depuis la DB ticks ou Yahoo Finance."""
        tick = self.db.get_tick(symbol)
        if tick and tick.get("price"):
            # Vérifier que le tick n'est pas trop vieux (>5 min)
            try:
                upd = datetime.fromisoformat(tick["updated_at"])
                if (datetime.utcnow() - upd).total_seconds() < 300:
                    return float(tick["price"])
            except Exception:
                return float(tick["price"])

        # Fallback Yahoo Finance
        if YF_OK:
            try:
                raw = yf.download(symbol, period="2d", interval="1d",
                                   progress=False, auto_adjust=True, timeout=15)
                if raw is not None and not raw.empty:
                    return float(raw["Close"].dropna().iloc[-1])
            except Exception:
                pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    import argparse

    print("""
╔══════════════════════════════════════════════════════════╗
║  market_db.py  —  Base de données de marché             ║
║  Python 3 · macOS · SQLite                              ║
╚══════════════════════════════════════════════════════════╝
""")

    parser = argparse.ArgumentParser(
        description="Gestion de la base de données de marché",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--init",           action="store_true",
                         help="Initialiser la base (actifs principaux)")
    parser.add_argument("--full",           action="store_true",
                         help="Avec --init : télécharger l'univers complet")
    parser.add_argument("--populate",       type=str, default="",
                         help="Télécharger des actifs  ex: SPY,QQQ,BTC-USD")
    parser.add_argument("--update",         action="store_true",
                         help="Mettre à jour tous les actifs connus en base")
    parser.add_argument("--fundamentals",   type=str, default="",
                         help="Télécharger les fondamentaux  ex: AAPL,MSFT")
    parser.add_argument("--watch",          type=str, default="",
                         help="Feed temps réel  ex: SPY,BTC-USD")
    parser.add_argument("--interval-s",     type=int, default=60,
                         help="Intervalle du feed en secondes (défaut: 60, min: 15)")
    parser.add_argument("--health",         action="store_true",
                         help="Rapport de santé de la base")
    parser.add_argument("--query",          type=str, default="",
                         help="Afficher les dernières données  ex: SPY")
    parser.add_argument("--n",              type=int, default=10,
                         help="Nombre de lignes pour --query (défaut: 10)")
    parser.add_argument("--export",         type=str, default="",
                         help="Exporter en CSV  ex: SPY  ou  SPY,QQQ")
    parser.add_argument("--years",          type=int, default=3,
                         help="Années d'historique (défaut: 3)")
    parser.add_argument("--force",          action="store_true",
                         help="Forcer le re-téléchargement même si données récentes")
    parser.add_argument("--macro",          action="store_true",
                         help="Télécharger les séries macro FRED")
    args = parser.parse_args()

    db  = MarketDatabase()
    upd = MarketUpdater(db)

    # Par défaut : rapport de santé
    if not any([args.init, args.populate, args.update, args.fundamentals,
                args.watch, args.health, args.query, args.export, args.macro]):
        db.health_report()
        return

    # ── Init ─────────────────────────────────────────────────────────────────
    if args.init:
        syms = (
            list({s for cat in UNIVERSE.values() for s in cat})
            if args.full else QUICK_LIST
        )
        print(f"  Initialisation — {len(syms)} actifs "
              f"({'univers complet' if args.full else 'liste rapide'})")
        upd.download_many(syms, years=args.years, force=args.force)
        upd.refresh_macro_fred()
        db.health_report()

    # ── Populate ─────────────────────────────────────────────────────────────
    elif args.populate:
        syms = [s.strip() for s in args.populate.split(",") if s.strip()]
        upd.download_many(syms, years=args.years, force=args.force)

    # ── Update ────────────────────────────────────────────────────────────────
    elif args.update:
        known = db.symbols_in_db()
        if not known:
            print("  Base vide. Lancer d'abord : python3 market_db.py --init")
        else:
            print(f"  Mise à jour de {len(known)} actifs connus")
            upd.download_many(known, years=1, force=True)
            upd.refresh_macro_fred()

    # ── Macro ─────────────────────────────────────────────────────────────────
    if args.macro:
        print("\n  📡  Téléchargement des séries macro FRED...")
        upd.refresh_macro_fred()
        mac = db.get_macro_latest()
        print(f"  {len(mac)} séries téléchargées")
        for sid, d in mac.items():
            print(f"    {sid:18s}: {d['value']:.3f}   ({d['date'][:10]})")

    # ── Fondamentaux ──────────────────────────────────────────────────────────
    if args.fundamentals:
        syms = [s.strip() for s in args.fundamentals.split(",") if s.strip()]
        upd.download_fundamentals(syms)

    # ── Query ─────────────────────────────────────────────────────────────────
    if args.query:
        sym = args.query.strip().upper()
        df  = db.get_ohlcv(sym, n_last=args.n)
        if df.empty:
            print(f"\n  ❌  Aucune donnée pour {sym}")
            print(f"      Télécharger d'abord : python3 market_db.py --populate {sym}")
        else:
            print(f"\n📊  {sym} — {args.n} dernières barres")
            print(df.to_string())
            tick = db.get_tick(sym)
            if tick:
                chg = tick.get("change_pct", 0) or 0
                upd_at = (tick.get("updated_at") or "")[:16]
                icon   = "▲" if chg > 0 else "▼"
                print(f"\n  Prix actuel : {tick.get('price')} "
                      f"({icon}{abs(chg):.2f}%) — màj {upd_at}")

    # ── Export ────────────────────────────────────────────────────────────────
    if args.export:
        syms = [s.strip() for s in args.export.split(",") if s.strip()]
        for sym in syms:
            try:
                path = db.export_csv(sym)
                print(f"  ✅  {sym} → {path}")
            except ValueError as e:
                print(f"  ❌  {e}")

    # ── Watch (feed temps réel) ────────────────────────────────────────────────
    if args.watch:
        syms = [s.strip() for s in args.watch.split(",") if s.strip()]
        iv   = max(15, args.interval_s)

        print(f"\n  🟢  Feed temps réel — {syms} — intervalle {iv}s")
        print(f"  Ctrl+C pour arrêter\n")
        print(f"  {'Symbole':14s} {'Prix':14s} {'Var%':10s} {'Mis à jour':20s}")
        print(f"  {'─'*60}")

        def on_tick(tick):
            chg  = tick.get("change_pct", 0) or 0
            icon = "▲" if chg > 0 else "▼" if chg < 0 else "─"
            print(
                f"\r  {tick.get('symbol',''):14s} "
                f"{tick.get('price',0):14.4f} "
                f"{icon}{abs(chg):9.3f}% "
                f"{(tick.get('updated_at',''))[:16]:20s}",
                end="", flush=True
            )

        upd.start(syms, interval_s=iv, callbacks=[on_tick])
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            print(f"\n\n  Arrêt...")
            upd.stop()
            print(f"  Updates réalisés : {upd.status()['updates']}")

    # ── Rapport final ─────────────────────────────────────────────────────────
    if args.health or args.init or args.update:
        db.health_report()


if __name__ == "__main__":
    main()
