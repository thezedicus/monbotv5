#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  FICHIER 1/4 — bce_engine.py                                                ║
║  Moteur d'intelligence BCE — APIs + Base de données + Analyse de tendances  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES MAC :                                                             ║
║    python3 bce_engine.py                   # Rapport complet BCE            ║
║    python3 bce_engine.py --tendances       # Tendances et décisions BCE     ║
║    python3 bce_engine.py --impact          # Impact sur les cours boursiers ║
║    python3 bce_engine.py --calendrier      # Prochaines réunions BCE        ║
║    python3 bce_engine.py --db-init         # Initialiser la base de données ║
║    python3 bce_engine.py --db-update       # Mettre à jour la base          ║
║    python3 bce_engine.py --db-status       # État de la base                ║
║                                                                              ║
║  INSTALLATION :                                                              ║
║    pip3 install yfinance requests pandas numpy scipy feedparser             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, sqlite3, logging, warnings, argparse, hashlib
from datetime    import datetime, timedelta, date
from pathlib     import Path
from typing      import Dict, List, Optional, Tuple, Any
from contextlib  import contextmanager
from io          import StringIO

import numpy  as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")
Path("logs").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bce_engine.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("BCE.Engine")
for n in ("yfinance","urllib3","charset_normalizer"):
    logging.getLogger(n).setLevel(logging.CRITICAL)

try:    import yfinance as yf;      YF_OK = True
except: YF_OK = False;              print("pip3 install yfinance")
try:    import feedparser;          FP_OK = True
except: FP_OK = False;              print("pip3 install feedparser")
try:    from scipy import stats;    SC_OK = True
except: SC_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# §1  BASE DE DONNÉES SQLite — Historique complet BCE
# ══════════════════════════════════════════════════════════════════════════════

DB_PATH = Path("data/bce_intelligence.db")

class BCEDatabase:
    """
    Base de données SQLite locale — historise toutes les données BCE :
    taux directeurs, indicateurs macro, décisions, actualités, signaux.
    Permet d'analyser les tendances sur plusieurs mois.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info(f"Base BCE : {self.path.resolve()}")

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(str(self.path), timeout=20, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c; c.commit()
        except Exception:
            c.rollback(); raise
        finally:
            c.close()

    def _init_schema(self):
        with self._conn() as c:
            c.executescript("""
            -- Décisions BCE (taux directeurs historiques)
            CREATE TABLE IF NOT EXISTS bce_decisions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL UNIQUE,
                taux_depot   REAL,          -- taux de dépôt BCE (%)
                taux_refi    REAL,          -- taux de refinancement (%)
                taux_pret    REAL,          -- taux prêt marginal (%)
                decision     TEXT,          -- BAISSE / STABLE / HAUSSE
                bps_change   REAL,          -- variation en points de base
                commentaire  TEXT,
                created_at   TEXT DEFAULT (datetime('now','utc'))
            );

            -- Indicateurs macro zone euro
            CREATE TABLE IF NOT EXISTS macro_zone_euro (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL,
                indicateur   TEXT NOT NULL,
                valeur       REAL,
                unite        TEXT,
                source       TEXT,
                created_at   TEXT DEFAULT (datetime('now','utc')),
                UNIQUE(date, indicateur)
            );

            -- Prix des indices BCE (historique)
            CREATE TABLE IF NOT EXISTS indices_eur (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                date         TEXT NOT NULL,
                open         REAL, high REAL, low REAL,
                close        REAL NOT NULL,
                volume       INTEGER,
                UNIQUE(symbol, date)
            );
            CREATE INDEX IF NOT EXISTS idx_indices ON indices_eur(symbol, date DESC);

            -- Ticks (prix live)
            CREATE TABLE IF NOT EXISTS ticks_live (
                symbol       TEXT PRIMARY KEY,
                prix         REAL,
                variation    REAL,
                var_pct      REAL,
                haut_24h     REAL,
                bas_24h      REAL,
                volume       INTEGER,
                source       TEXT,
                updated_at   TEXT DEFAULT (datetime('now','utc'))
            );

            -- Actualités BCE filtrées
            CREATE TABLE IF NOT EXISTS actualites_bce (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                hash_titre   TEXT UNIQUE,
                titre        TEXT NOT NULL,
                source       TEXT,
                lien         TEXT,
                date_pub     TEXT,
                sentiment    TEXT,
                score        INTEGER DEFAULT 0,
                pertinent    INTEGER DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now','utc'))
            );

            -- Signaux d'arbitrage générés
            CREATE TABLE IF NOT EXISTS signaux (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT NOT NULL,
                signal       TEXT NOT NULL,
                score_bull   REAL, score_bear REAL,
                prix         REAL,
                stop_long    REAL, tp_long REAL,
                rr_ratio     REAL,
                regime       TEXT,
                raisons      TEXT,
                created_at   TEXT DEFAULT (datetime('now','utc'))
            );
            CREATE INDEX IF NOT EXISTS idx_signaux ON signaux(symbol, created_at DESC);

            -- Tendances BCE (résumés d'analyse)
            CREATE TABLE IF NOT EXISTS tendances_bce (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL UNIQUE,
                stance       TEXT,          -- RESTRICTIF/NEUTRE/ACCOMMODANT
                biais        TEXT,          -- HAUSSIER/NEUTRE/BAISSIER
                prochain_mvt TEXT,          -- BAISSE/STABLE/HAUSSE attendu
                confiance    REAL,          -- 0-100%
                analyse      TEXT,          -- texte complet
                created_at   TEXT DEFAULT (datetime('now','utc'))
            );

            -- Calendrier BCE
            CREATE TABLE IF NOT EXISTS calendrier_bce (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date_reunion TEXT NOT NULL UNIQUE,
                type_evt     TEXT,          -- REUNIONGOUVERNEURS/PRESSECONF
                description  TEXT,
                created_at   TEXT DEFAULT (datetime('now','utc'))
            );
            """)

    # ── Décisions BCE ─────────────────────────────────────────────────────────
    def save_decision(self, date_str: str, taux_depot: float, taux_refi: float,
                       taux_pret: float, decision: str, bps: float,
                       commentaire: str = "") -> None:
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO bce_decisions
                (date,taux_depot,taux_refi,taux_pret,decision,bps_change,commentaire)
                VALUES(?,?,?,?,?,?,?)""",
                (date_str, taux_depot, taux_refi, taux_pret, decision, bps, commentaire))

    def get_decisions_history(self, limit: int = 20) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM bce_decisions
                ORDER BY date DESC LIMIT ?""", [limit]).fetchall()
        return [dict(r) for r in rows]

    # ── Indicateurs macro ─────────────────────────────────────────────────────
    def save_macro(self, date_str: str, indicateur: str,
                    valeur: float, unite: str = "", source: str = "") -> None:
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO macro_zone_euro
                (date,indicateur,valeur,unite,source) VALUES(?,?,?,?,?)""",
                (date_str, indicateur, valeur, unite, source))

    def get_macro_history(self, indicateur: str, limit: int = 24) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("""SELECT date, valeur, source FROM macro_zone_euro
                WHERE indicateur=? ORDER BY date DESC LIMIT ?""",
                [indicateur, limit]).fetchall()
        return [dict(r) for r in rows]

    def get_latest_macro(self) -> Dict[str, float]:
        with self._conn() as c:
            rows = c.execute("""
                SELECT m.indicateur, m.valeur, m.unite
                FROM macro_zone_euro m
                INNER JOIN (SELECT indicateur, MAX(date) md
                    FROM macro_zone_euro GROUP BY indicateur) x
                ON m.indicateur=x.indicateur AND m.date=x.md""").fetchall()
        return {r["indicateur"]: r["valeur"] for r in rows}

    # ── Indices EUR ───────────────────────────────────────────────────────────
    def save_ohlcv(self, symbol: str, df: pd.DataFrame) -> int:
        if df is None or df.empty: return 0
        rows = []
        for idx, row in df.iterrows():
            dt = idx.strftime("%Y-%m-%d") if hasattr(idx,"strftime") else str(idx)
            rows.append((symbol, dt,
                float(row.get("Open",0) or 0), float(row.get("High",0) or 0),
                float(row.get("Low",0) or 0),  float(row.get("Close",0) or 0),
                int(row.get("Volume",0) or 0)))
        n = 0
        with self._conn() as c:
            for r in rows:
                try:
                    c.execute("""INSERT OR REPLACE INTO indices_eur
                        (symbol,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)""", r)
                    n += 1
                except: pass
        return n

    def get_ohlcv(self, symbol: str, limit: int = 252) -> pd.DataFrame:
        with self._conn() as c:
            rows = c.execute("""SELECT date,open,high,low,close,volume
                FROM indices_eur WHERE symbol=?
                ORDER BY date DESC LIMIT ?""", [symbol, limit]).fetchall()
        if not rows: return pd.DataFrame()
        df = pd.DataFrame([(r["date"],r["open"],r["high"],r["low"],r["close"],r["volume"])
                            for r in rows],
                           columns=["date","Open","High","Low","Close","Volume"])
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date").sort_index()

    # ── Ticks live ────────────────────────────────────────────────────────────
    def save_tick(self, d: Dict) -> None:
        sym = d.get("symbol","")
        if not sym: return
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO ticks_live
                (symbol,prix,variation,var_pct,haut_24h,bas_24h,volume,source,updated_at)
                VALUES(?,?,?,?,?,?,?,?,datetime('now','utc'))""",
                (sym, d.get("prix"), d.get("variation"), d.get("var_pct"),
                 d.get("haut_24h"), d.get("bas_24h"), d.get("volume"), d.get("source","")))

    def get_ticks(self) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM ticks_live ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]

    # ── Actualités ────────────────────────────────────────────────────────────
    def save_actualite(self, art: Dict) -> bool:
        h = hashlib.md5(art.get("titre","").encode()).hexdigest()[:16]
        try:
            with self._conn() as c:
                c.execute("""INSERT OR IGNORE INTO actualites_bce
                    (hash_titre,titre,source,lien,date_pub,sentiment,score,pertinent)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (h, art.get("titre",""), art.get("source",""),
                     art.get("lien",""), art.get("date",""),
                     art.get("sentiment",""), art.get("score",0),
                     int(art.get("pertinent",False))))
            return True
        except: return False

    def get_actualites_recentes(self, limit: int = 20, pertinent_only: bool = False) -> List[Dict]:
        sql = "SELECT * FROM actualites_bce"
        if pertinent_only: sql += " WHERE pertinent=1"
        sql += " ORDER BY created_at DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(sql, [limit]).fetchall()
        return [dict(r) for r in rows]

    # ── Signaux ───────────────────────────────────────────────────────────────
    def save_signal(self, s: Dict) -> None:
        with self._conn() as c:
            c.execute("""INSERT INTO signaux
                (symbol,signal,score_bull,score_bear,prix,stop_long,tp_long,rr_ratio,regime,raisons)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (s.get("symbol",""), s.get("signal",""),
                 s.get("bull_score",0), s.get("bear_score",0),
                 s.get("prix",0), s.get("stop_long",0),
                 s.get("tp_long",0), s.get("rr_ratio",0),
                 s.get("regime",""), json.dumps(s.get("raisons",[]))))

    def get_signal_history(self, symbol: str, limit: int = 30) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM signaux WHERE symbol=?
                ORDER BY created_at DESC LIMIT ?""", [symbol, limit]).fetchall()
        return [dict(r) for r in rows]

    # ── Tendances ─────────────────────────────────────────────────────────────
    def save_tendance(self, t: Dict) -> None:
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO tendances_bce
                (date,stance,biais,prochain_mvt,confiance,analyse)
                VALUES(?,?,?,?,?,?)""",
                (date.today().isoformat(),
                 t.get("stance",""), t.get("biais",""),
                 t.get("prochain_mvt",""), t.get("confiance",50),
                 t.get("analyse","")))

    def get_tendances_history(self, limit: int = 30) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM tendances_bce
                ORDER BY date DESC LIMIT ?""", [limit]).fetchall()
        return [dict(r) for r in rows]

    # ── Calendrier ────────────────────────────────────────────────────────────
    def save_calendrier(self, evenements: List[Dict]) -> None:
        with self._conn() as c:
            for e in evenements:
                try:
                    c.execute("""INSERT OR IGNORE INTO calendrier_bce
                        (date_reunion,type_evt,description) VALUES(?,?,?)""",
                        (e.get("date",""), e.get("type",""), e.get("description","")))
                except: pass

    def get_prochaines_reunions(self, n: int = 5) -> List[Dict]:
        today = date.today().isoformat()
        with self._conn() as c:
            rows = c.execute("""SELECT * FROM calendrier_bce
                WHERE date_reunion >= ? ORDER BY date_reunion ASC LIMIT ?""",
                [today, n]).fetchall()
        return [dict(r) for r in rows]

    # ── Santé ─────────────────────────────────────────────────────────────────
    def status(self) -> Dict:
        sz = self.path.stat().st_size / 1024 / 1024 if self.path.exists() else 0
        with self._conn() as c:
            tables = {}
            for t in ["bce_decisions","macro_zone_euro","indices_eur",
                       "ticks_live","actualites_bce","signaux","tendances_bce"]:
                n = c.execute(f"SELECT COUNT(*) as n FROM {t}").fetchone()["n"]
                tables[t] = n
        return {"taille_mb": round(sz,2), "tables": tables,
                "chemin": str(self.path.resolve())}


# ══════════════════════════════════════════════════════════════════════════════
# §2  APIs BCE — Sources de données officielles et complémentaires
# ══════════════════════════════════════════════════════════════════════════════

class BCEAPI:
    """
    Agrège toutes les sources de données BCE gratuites :
    - BCE SDMX (officielle) : Euribor, HICP, taux directeurs
    - FRED : corrélation taux US / EU, spreads
    - Yahoo Finance : indices, forex, matières premières
    - RSS BCE : communiqués officiels
    - Investing Calendar : réunions BCE
    """

    # ── BCE SDMX officielle ────────────────────────────────────────────────────
    BCE_SDMX = "https://data-api.ecb.europa.eu/service/data"
    BCE_SERIES = {
        "EURIBOR_3M":   "FM/B.U2.EUR.RT.MM.EURIBOR3MD_.HSTA",
        "EURIBOR_6M":   "FM/B.U2.EUR.RT.MM.EURIBOR6MD_.HSTA",
        "TAUX_DEPOT":   "FM/B.U2.EUR.RT.MM.EDFR.HSTA",
        "HICP_YOY":     "ICP/M.U2.N.000000.4.INX",
        "EUR_USD":      "EXR/D.USD.EUR.SP00.A",
        "EUR_GBP":      "EXR/D.GBP.EUR.SP00.A",
        "EUR_JPY":      "EXR/D.JPY.EUR.SP00.A",
        "M3_YOY":       "BSI/M.U2.N.A.L20.A.1.U2.2300.Z01.E",
    }

    # ── FRED (Réserve Fédérale US) ────────────────────────────────────────────
    FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    FRED_SERIES = {
        "US_T10Y":          "DGS10",
        "US_T2Y":           "DGS2",
        "US_SPREAD_10_2":   "T10Y2Y",
        "US_FED_FUNDS":     "FEDFUNDS",
        "US_CPI_YOY":       "CPIAUCSL",
        "US_UNEMPLOYMENT":  "UNRATE",
        "IG_SPREAD":        "BAMLC0A0CM",
        "HY_SPREAD":        "BAMLH0A0HYM2",
    }

    # ── RSS sources BCE ────────────────────────────────────────────────────────
    RSS_BCE = {
        "BCE Press":    "https://www.ecb.europa.eu/rss/press.html",
        "Reuters EU":   "https://feeds.reuters.com/reuters/businessNews",
        "Les Echos":    "https://www.lesechos.fr/feeds/rss/finance-marches.xml",
        "Le Monde Éco": "https://www.lemonde.fr/economie/rss_full.xml",
        "FT Europe":    "https://www.ft.com/rss/home/europe",
        "Yahoo Finance":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR",
    }

    # ── Calendrier BCE 2025-2026 (officiel) ───────────────────────────────────
    CALENDRIER_BCE = [
        {"date":"2025-01-30","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-03-06","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-04-17","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-06-05","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-07-24","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-09-11","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-10-30","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2025-12-18","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-01-29","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-03-05","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-04-30","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-06-04","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-07-23","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-09-10","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-10-29","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
        {"date":"2026-12-17","type":"DÉCISION","description":"Réunion Conseil des gouverneurs"},
    ]

    def __init__(self, db: BCEDatabase = None):
        self.db = db or BCEDatabase()

    def _get_sdmx(self, series_key: str, n: int = 12) -> Optional[pd.DataFrame]:
        url = f"{self.BCE_SDMX}/{series_key}?format=jsondata&lastNObservations={n}"
        try:
            r = requests.get(url, timeout=12,
                              headers={"Accept":"application/json"})
            if r.status_code != 200:
                return None
            data = r.json()
            series_data = data["dataSets"][0]["series"]
            key = list(series_data.keys())[0]
            obs = series_data[key]["observations"]
            dates_raw = data["structure"]["dimensions"]["observation"][0]["values"]
            rows = []
            for k, v in obs.items():
                idx = int(k)
                if idx < len(dates_raw) and v[0] is not None:
                    rows.append({"date": dates_raw[idx]["id"], "valeur": float(v[0])})
            if not rows: return None
            df = pd.DataFrame(rows).sort_values("date")
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")
        except Exception as e:
            logger.debug(f"BCE SDMX {series_key}: {e}")
            return None

    def _get_fred(self, series_id: str, limit: int = 12) -> Optional[pd.DataFrame]:
        try:
            r = requests.get(f"{self.FRED_BASE}?id={series_id}", timeout=12)
            if r.status_code != 200: return None
            df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
            df.columns = ["date","valeur"]
            df["valeur"] = pd.to_numeric(df["valeur"], errors="coerce")
            df = df.dropna().tail(limit)
            df["date"] = pd.to_datetime(df["date"])
            return df.set_index("date")
        except Exception as e:
            logger.debug(f"FRED {series_id}: {e}")
            return None

    def fetch_all_macro(self) -> Dict[str, Any]:
        """Télécharge tous les indicateurs macro BCE et US."""
        result = {}

        # ── Sources BCE SDMX ──────────────────────────────────────────────────
        logger.info("  Téléchargement indicateurs BCE...")
        for nom, series in self.BCE_SERIES.items():
            df = self._get_sdmx(series, n=6)
            if df is not None and not df.empty:
                val = float(df["valeur"].iloc[-1])
                result[nom] = val
                self.db.save_macro(
                    str(df.index[-1].date()), nom, val,
                    source="BCE SDMX"
                )
            time.sleep(0.3)

        # ── Fallback Yahoo Finance pour taux de change ─────────────────────────
        if "EUR_USD" not in result and YF_OK:
            try:
                h = yf.Ticker("EURUSD=X").history(period="5d", interval="1d")
                if not h.empty:
                    result["EUR_USD"] = float(h["Close"].iloc[-1])
            except: pass

        # ── Sources FRED ──────────────────────────────────────────────────────
        logger.info("  Téléchargement indicateurs FRED...")
        for nom, series in self.FRED_SERIES.items():
            df = self._get_fred(series, limit=6)
            if df is not None and not df.empty:
                val = float(df["valeur"].iloc[-1])
                result[nom] = val
                self.db.save_macro(
                    str(df.index[-1].date()), nom, val,
                    source="FRED"
                )
            time.sleep(0.2)

        # ── Yahoo Finance pour complément ─────────────────────────────────────
        if YF_OK:
            logger.info("  Téléchargement Yahoo Finance...")
            yf_syms = {
                "VIX": "^VIX", "STOXX50": "^STOXX50E",
                "DAX": "^GDAXI", "CAC40": "^FCHI",
                "BRENT": "BZ=F", "EUR_USD_YF": "EURUSD=X",
            }
            for nom, sym in yf_syms.items():
                try:
                    h = yf.Ticker(sym).history(period="5d", interval="1d")
                    if not h.empty:
                        val = float(h["Close"].iloc[-1])
                        result[nom] = val
                        self.db.save_macro(
                            str(h.index[-1].date()), nom, val,
                            source="Yahoo Finance"
                        )
                    time.sleep(0.2)
                except: pass

        result["_timestamp"] = datetime.utcnow().isoformat()
        return result

    def fetch_indices_ohlcv(self, symbols: List[str], jours: int = 252) -> Dict:
        """Télécharge et stocke l'historique OHLCV des indices BCE."""
        if not YF_OK: return {}
        results = {}
        period = f"{max(1, jours//252)}y" if jours >= 252 else f"{jours}d"
        for sym in symbols:
            try:
                raw = yf.download(sym, period=period, interval="1d",
                                   progress=False, auto_adjust=True, timeout=15)
                if raw is None or raw.empty: continue
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.droplevel(1)
                raw.columns = [c.title() for c in raw.columns]
                cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
                df = raw[cols].dropna(subset=["Close"])
                n  = self.db.save_ohlcv(sym, df)
                results[sym] = {"lignes": n, "debut": str(df.index[0].date()),
                                  "fin": str(df.index[-1].date())}
                logger.info(f"  {sym}: {n} lignes sauvegardées")
                time.sleep(0.4)
            except Exception as e:
                logger.warning(f"  {sym}: {e}")
        return results

    def fetch_live_prices(self, symbols: List[str]) -> Dict:
        """Prix en temps réel pour tous les indices BCE."""
        if not YF_OK: return {}
        result = {}
        try:
            raw = yf.download(
                symbols if len(symbols) > 1 else symbols[0],
                period="5d", interval="1d", progress=False,
                auto_adjust=True, group_by="ticker" if len(symbols)>1 else None,
                timeout=15
            )
            if raw is None or raw.empty: return {}
            for sym in symbols:
                try:
                    df_s = raw[sym] if len(symbols)>1 and sym in raw.columns.get_level_values(0) else raw
                    close = float(df_s["Close"].dropna().iloc[-1])
                    prev  = float(df_s["Close"].dropna().iloc[-2]) if len(df_s)>1 else close
                    chg   = close - prev
                    tick  = {
                        "symbol": sym, "prix": round(close,4),
                        "variation": round(chg,4),
                        "var_pct": round(chg/prev*100 if prev else 0, 3),
                        "haut_24h": round(float(df_s["High"].dropna().iloc[-1]),4),
                        "bas_24h":  round(float(df_s["Low"].dropna().iloc[-1]),4),
                        "volume":   int(df_s["Volume"].dropna().iloc[-1]) if "Volume" in df_s.columns else 0,
                        "source": "Yahoo Finance",
                    }
                    result[sym] = tick
                    self.db.save_tick(tick)
                except: pass
        except Exception as e:
            logger.warning(f"fetch_live: {e}")
        return result

    def fetch_actualites(self) -> List[Dict]:
        """Actualités BCE depuis tous les flux RSS."""
        if not FP_OK: return []
        BCE_KW_BULL = ["baisse des taux","assouplissement","stimulus","relance",
                        "rate cut","easing","croissance","emploi","achat"]
        BCE_KW_BEAR = ["hausse des taux","resserrement","récession","inflation",
                        "rate hike","tightening","stagflation","crise"]
        BCE_KW      = ["bce","ecb","banque centrale","taux","euribor","euro",
                        "zone euro","inflation","lagarde","politique monétaire"]
        articles = []
        for source, url in self.RSS_BCE.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    titre = (entry.get("title","") or "").strip()
                    if not titre: continue
                    tl = titre.lower()
                    score = sum(1 for w in BCE_KW_BULL if w in tl) - sum(1 for w in BCE_KW_BEAR if w in tl)
                    pertinent = any(w in tl for w in BCE_KW)
                    sentiment = "🟢 Haussier" if score>0 else "🔴 Baissier" if score<0 else "⚪ Neutre"
                    art = {
                        "titre":    titre,
                        "source":   source,
                        "lien":     entry.get("link","#"),
                        "date":     entry.get("published","")[:25],
                        "sentiment":sentiment,
                        "score":    score,
                        "pertinent":pertinent,
                    }
                    articles.append(art)
                    self.db.save_actualite(art)
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"RSS {source}: {e}")
        articles.sort(key=lambda x: (x["pertinent"], abs(x["score"])), reverse=True)
        return articles

    def get_calendrier(self) -> List[Dict]:
        """Retourne le calendrier BCE (BD + statique officiel)."""
        self.db.save_calendrier(self.CALENDRIER_BCE)
        return self.db.get_prochaines_reunions(n=6)


# ══════════════════════════════════════════════════════════════════════════════
# §3  MOTEUR D'ANALYSE DES TENDANCES BCE
# ══════════════════════════════════════════════════════════════════════════════

class AnalyseurTendancesBCE:
    """
    Analyse les tendances de la politique monétaire BCE et modélise
    l'impact attendu sur les cours boursiers de la zone euro.

    Basé sur les théories économiques des 60 thèses :
    - Relation taux directeurs / valorisation actions (actualisation DCF)
    - Transmission monétaire : taux → crédit → consommation → bénéfices
    - Corrélation historique BCE/Stoxx50
    - Modèle de réaction de marché (surprise vs anticipation)
    """

    # Historique décisions BCE réelles (référence)
    HISTORIQUE_DECISIONS = [
        {"date":"2022-07-21","taux_depot":0.00, "decision":"HAUSSE", "bps":+50,  "contexte":"Premier relèvement depuis 2011"},
        {"date":"2022-09-08","taux_depot":0.75, "decision":"HAUSSE", "bps":+75,  "contexte":"Inflation record 9.1%"},
        {"date":"2022-10-27","taux_depot":1.50, "decision":"HAUSSE", "bps":+75,  "contexte":"Inflation persistante"},
        {"date":"2022-12-15","taux_depot":2.00, "decision":"HAUSSE", "bps":+50,  "contexte":"Début ralentissement"},
        {"date":"2023-02-02","taux_depot":2.50, "decision":"HAUSSE", "bps":+50,  "contexte":"Core inflation élevée"},
        {"date":"2023-03-16","taux_depot":3.00, "decision":"HAUSSE", "bps":+50,  "contexte":"Crise banques US"},
        {"date":"2023-05-04","taux_depot":3.25, "decision":"HAUSSE", "bps":+25,  "contexte":"Ralentissement hausse"},
        {"date":"2023-06-15","taux_depot":3.50, "decision":"HAUSSE", "bps":+25,  "contexte":"Dernier +25bps"},
        {"date":"2023-07-27","taux_depot":3.75, "decision":"HAUSSE", "bps":+25,  "contexte":"Pause annoncée"},
        {"date":"2023-09-14","taux_depot":4.00, "decision":"HAUSSE", "bps":+25,  "contexte":"Pic du cycle"},
        {"date":"2023-10-26","taux_depot":4.00, "decision":"STABLE", "bps": 0,   "contexte":"Pause confirmée"},
        {"date":"2023-12-14","taux_depot":4.00, "decision":"STABLE", "bps": 0,   "contexte":"Attente données"},
        {"date":"2024-01-25","taux_depot":4.00, "decision":"STABLE", "bps": 0,   "contexte":"Pivot en préparation"},
        {"date":"2024-03-07","taux_depot":4.00, "decision":"STABLE", "bps": 0,   "contexte":"Inflation sur trajectoire"},
        {"date":"2024-04-11","taux_depot":4.00, "decision":"STABLE", "bps": 0,   "contexte":"Juin signalé pour pivot"},
        {"date":"2024-06-06","taux_depot":3.75, "decision":"BAISSE", "bps":-25,  "contexte":"Premier pivot — historique"},
        {"date":"2024-07-18","taux_depot":3.75, "decision":"STABLE", "bps": 0,   "contexte":"Pause post-pivot"},
        {"date":"2024-09-12","taux_depot":3.50, "decision":"BAISSE", "bps":-25,  "contexte":"Désinflation confirmée"},
        {"date":"2024-10-17","taux_depot":3.25, "decision":"BAISSE", "bps":-25,  "contexte":"Accélération baisses"},
        {"date":"2024-12-12","taux_depot":3.00, "decision":"BAISSE", "bps":-25,  "contexte":"Vers taux neutre"},
        {"date":"2025-01-30","taux_depot":2.75, "decision":"BAISSE", "bps":-25,  "contexte":"Poursuite assouplissement"},
        {"date":"2025-03-06","taux_depot":2.50, "decision":"BAISSE", "bps":-25,  "contexte":"Croissance faible"},
        {"date":"2025-04-17","taux_depot":2.25, "decision":"BAISSE", "bps":-25,  "contexte":"Taux neutre approché"},
        {"date":"2025-06-05","taux_depot":2.00, "decision":"BAISSE", "bps":-25,  "contexte":"Taux neutre atteint"},
    ]

    # Impact historique moyen par type de décision sur Stoxx50 (J+1)
    IMPACT_HISTORIQUE = {
        "HAUSSE": {"stoxx50": -1.8, "dax": -1.5, "cac40": -1.7, "eur_usd": +0.3,
                    "banques": +2.1, "utilities": -2.5, "immobilier": -3.2},
        "BAISSE": {"stoxx50": +1.5, "dax": +1.8, "cac40": +1.6, "eur_usd": -0.4,
                    "banques": -1.8, "utilities": +2.2, "immobilier": +2.8},
        "STABLE": {"stoxx50": +0.2, "dax": +0.1, "cac40": +0.2, "eur_usd": +0.0,
                    "banques": +0.0, "utilities": +0.1, "immobilier": +0.0},
    }

    def __init__(self, db: BCEDatabase):
        self.db = db

    def analyser_cycle_monetaire(self, macro: Dict) -> Dict:
        """
        Détermine la phase du cycle monétaire BCE et les tendances probables.
        Retourne une analyse structurée avec prévisions.
        """
        # Taux actuel (depuis macro ou historique)
        taux_depot = macro.get("TAUX_DEPOT") or macro.get("EURIBOR_3M", 2.0)
        euribor_3m = macro.get("EURIBOR_3M", taux_depot)
        hicp       = macro.get("HICP_YOY", 2.5)
        m3         = macro.get("M3_YOY", 3.0)
        vix        = macro.get("VIX", 18)
        eur_usd    = macro.get("EUR_USD") or macro.get("EUR_USD_YF", 1.10)
        us_spread  = macro.get("US_SPREAD_10_2", 0.3)
        ig_spread  = macro.get("IG_SPREAD", 0.9)

        # Dernière décision connue
        dernier     = self.HISTORIQUE_DECISIONS[-1]
        taux_actuel = dernier.get("taux_depot", 2.0)
        tendance_recente = self._tendance_recente()

        # ── Analyse de la situation actuelle ──────────────────────────────────
        # 1. Inflation vs cible
        inflation_gap = (hicp or 2.5) - 2.0  # écart vs cible 2%
        inflation_situation = (
            "AU-DESSUS DE LA CIBLE" if inflation_gap > 0.3 else
            "SUR LA CIBLE" if inflation_gap > -0.3 else
            "EN-DESSOUS DE LA CIBLE"
        )

        # 2. Taux réel (taux depot - inflation)
        taux_reel = taux_actuel - (hicp or 2.5)
        taux_reel_situation = (
            "POSITIF (restrictif)" if taux_reel > 0.5 else
            "NEUTRE" if taux_reel > -0.5 else
            "NÉGATIF (accommodant)"
        )

        # 3. Phase du cycle
        n_baisses = sum(1 for d in self.HISTORIQUE_DECISIONS[-8:]
                         if d["decision"] == "BAISSE")
        n_hausses = sum(1 for d in self.HISTORIQUE_DECISIONS[-8:]
                         if d["decision"] == "HAUSSE")
        n_stables = sum(1 for d in self.HISTORIQUE_DECISIONS[-8:]
                         if d["decision"] == "STABLE")

        if n_baisses > 4:    phase = "ASSOUPLISSEMENT ACTIF"
        elif n_baisses > 2:  phase = "DÉBUT D'ASSOUPLISSEMENT"
        elif n_hausses > 4:  phase = "RESSERREMENT ACTIF"
        elif n_hausses > 2:  phase = "DÉBUT DE RESSERREMENT"
        elif n_stables > 4:  phase = "PAUSE / ATTENTE"
        else:                phase = "TRANSITION"

        # 4. Prochaine décision probable
        if inflation_gap > 0.5 and taux_reel < 0:
            prochain_mvt   = "HAUSSE"
            proba_hausse   = min(70 + inflation_gap * 20, 90)
            proba_baisse   = max(5, 20 - inflation_gap * 10)
            proba_stable   = 100 - proba_hausse - proba_baisse
            bps_prevu      = +25
            confiance      = 65
        elif inflation_gap < -0.2 and taux_reel > 0.5:
            prochain_mvt   = "BAISSE"
            proba_hausse   = max(5, 10 + inflation_gap * 5)
            proba_baisse   = min(75, 60 - inflation_gap * 20)
            proba_stable   = 100 - proba_hausse - proba_baisse
            bps_prevu      = -25
            confiance      = 70
        elif abs(inflation_gap) < 0.3 and n_stables >= 2:
            prochain_mvt   = "STABLE"
            proba_hausse   = 15
            proba_baisse   = 25
            proba_stable   = 60
            bps_prevu      = 0
            confiance      = 60
        else:
            prochain_mvt   = "INCERTAIN"
            proba_hausse   = 25
            proba_baisse   = 35
            proba_stable   = 40
            bps_prevu      = 0
            confiance      = 40

        # 5. Stance global
        if phase in ("ASSOUPLISSEMENT ACTIF","DÉBUT D'ASSOUPLISSEMENT"):
            stance = "ACCOMMODANT"
            biais  = "HAUSSIER"  # Pour les marchés actions
        elif phase in ("RESSERREMENT ACTIF","DÉBUT DE RESSERREMENT"):
            stance = "RESTRICTIF"
            biais  = "BAISSIER"
        else:
            stance = "NEUTRE"
            biais  = "NEUTRE"

        # 6. Taux neutre estimé
        taux_neutre_estime = 2.0  # Estimation BCE "r*"
        ecart_neutre = taux_actuel - taux_neutre_estime

        result = {
            "taux_actuel":          taux_actuel,
            "taux_depot_obs":       taux_depot,
            "euribor_3m":           euribor_3m,
            "inflation_hicp":       hicp,
            "inflation_gap":        round(inflation_gap, 2),
            "inflation_situation":  inflation_situation,
            "taux_reel":            round(taux_reel, 2),
            "taux_reel_situation":  taux_reel_situation,
            "taux_neutre_estime":   taux_neutre_estime,
            "ecart_taux_neutre":    round(ecart_neutre, 2),
            "phase_cycle":          phase,
            "stance":               stance,
            "biais_marche":         biais,
            "tendance_recente":     tendance_recente,
            "prochain_mvt_prevu":   prochain_mvt,
            "bps_prevu":            bps_prevu,
            "probabilites": {
                "hausse_pct":  round(max(0,min(100,proba_hausse)), 1),
                "stable_pct":  round(max(0,min(100,proba_stable)), 1),
                "baisse_pct":  round(max(0,min(100,proba_baisse)), 1),
            },
            "confiance_pct":        confiance,
            "n_baisses_recentes":   n_baisses,
            "n_hausses_recentes":   n_hausses,
            "derniere_decision":    dernier.get("decision","N/A"),
            "dernier_contexte":     dernier.get("contexte",""),
            "ts": datetime.utcnow().isoformat(),
        }

        # Sauvegarder la tendance
        self.db.save_tendance({
            "stance": stance,
            "biais":  biais,
            "prochain_mvt": prochain_mvt,
            "confiance": confiance,
            "analyse": json.dumps(result, default=str),
        })

        return result

    def _tendance_recente(self) -> str:
        decisions = self.HISTORIQUE_DECISIONS[-4:]
        baisses = sum(1 for d in decisions if d["decision"] == "BAISSE")
        hausses = sum(1 for d in decisions if d["decision"] == "HAUSSE")
        if baisses >= 3: return "3+ baisses consécutives — assouplissement soutenu"
        if baisses == 2: return "2 baisses récentes — cycle baissier en cours"
        if hausses >= 3: return "3+ hausses — resserrement fort"
        if hausses == 2: return "2 hausses — cycle haussier en cours"
        return "Politique stable récemment"

    def analyser_impact_marches(self, tendance: Dict, macro: Dict) -> Dict:
        """
        Modélise l'impact des décisions BCE sur les cours boursiers.
        Sections : indices actions, secteurs, forex, obligations.
        """
        prochain = tendance.get("prochain_mvt_prevu","STABLE")
        stance   = tendance.get("stance","NEUTRE")
        bps      = tendance.get("bps_prevu",0)
        confiance= tendance.get("confiance_pct",50) / 100
        vix      = macro.get("VIX",18)

        # Impact de base (historique moyen × confiance)
        impact_base = self.IMPACT_HISTORIQUE.get(prochain, self.IMPACT_HISTORIQUE["STABLE"])

        # Ajustement VIX (marché nerveux → amplification)
        vix_mult = 1.0 + max(0, (vix - 20) / 40)

        # Ajustement magnitude (50bps > 25bps)
        bps_mult = abs(bps) / 25 if bps != 0 else 1.0

        impacts = {}
        for actif, val in impact_base.items():
            impacts[actif] = round(val * confiance * vix_mult * bps_mult, 2)

        # Analyse par classe d'actifs
        actions_zone_euro = {
            "CAC 40":    {"impact_pct": impacts.get("cac40",0),    "logique": ""},
            "DAX 40":    {"impact_pct": impacts.get("dax",0),       "logique": ""},
            "Stoxx 50":  {"impact_pct": impacts.get("stoxx50",0),  "logique": ""},
        }
        secteurs = {
            "Banques":      {"impact_pct": impacts.get("banques",0),
                              "logique": "Marges d'intérêt" + (" ↑" if prochain=="HAUSSE" else " ↓")},
            "Immobilier":   {"impact_pct": impacts.get("immobilier",0),
                              "logique": "Coût du crédit" + (" ↑" if prochain=="HAUSSE" else " ↓")},
            "Utilities":    {"impact_pct": impacts.get("utilities",0),
                              "logique": "Valorisation DCF" + (" ↓" if prochain=="HAUSSE" else " ↑")},
            "Technologie":  {"impact_pct": round(impacts.get("stoxx50",0)*1.2,2),
                              "logique": "Sensible aux taux longs"},
            "Consommation": {"impact_pct": round(impacts.get("stoxx50",0)*0.7,2),
                              "logique": "Pouvoir d'achat ménages"},
        }
        forex = {
            "EUR/USD":    {"impact_pct": impacts.get("eur_usd",0),
                            "direction": "EUR ↑ si hausse taux / EUR ↓ si baisse"},
            "EUR/GBP":    {"impact_pct": round(impacts.get("eur_usd",0)*0.6,3),
                            "direction": "Corrélé mais moins fort"},
        }

        for k in actions_zone_euro:
            v = actions_zone_euro[k]["impact_pct"]
            actions_zone_euro[k]["logique"] = (
                f"Actualisation des flux futurs — taux {'hausse' if prochain=='HAUSSE' else 'baisse'} "
                f"→ valorisation {'réduite' if v<0 else 'augmentée'}"
            )

        # Analyse narrative complète
        narrative = self._construire_narrative(tendance, impacts, macro)

        return {
            "prochain_mouvement":   prochain,
            "bps_attendus":         bps,
            "confiance_pct":        tendance.get("confiance_pct",50),
            "impact_j1_attendu": {
                "actions_zone_euro": actions_zone_euro,
                "secteurs":          secteurs,
                "forex":             forex,
            },
            "horizon_3_6_mois":     self._impact_moyen_terme(tendance, macro),
            "facteurs_risque":      self._facteurs_risque(macro),
            "narrative":            narrative,
            "ts": datetime.utcnow().isoformat(),
        }

    def _construire_narrative(self, tendance: Dict, impacts: Dict, macro: Dict) -> str:
        prochain = tendance.get("prochain_mvt_prevu","STABLE")
        bps      = tendance.get("bps_prevu",0)
        stance   = tendance.get("stance","NEUTRE")
        phase    = tendance.get("phase_cycle","")
        hicp     = macro.get("HICP_YOY", 2.5) or 2.5
        vix      = macro.get("VIX",18) or 18
        taux     = tendance.get("taux_actuel",2.0)

        stoxx_dir = "hausse" if impacts.get("stoxx50",0) > 0 else "baisse"
        narrative = [
            f"📊 ANALYSE BCE — {datetime.utcnow():%d %B %Y}",
            "",
            f"Phase actuelle : {phase}",
            f"Taux de dépôt BCE : {taux:.2f}%",
            f"Inflation HICP zone euro : {hicp:.1f}% (cible 2%)",
            f"VIX (indicateur de risque) : {vix:.1f}",
            "",
            f"🔮 PROCHAINE DÉCISION ATTENDUE : {prochain}" +
            (f" ({bps:+d} bps)" if bps != 0 else ""),
            "",
            "💡 LOGIQUE ÉCONOMIQUE :",
        ]
        if prochain == "BAISSE":
            narrative += [
                f"  La BCE est en cycle d'assouplissement. La baisse de {abs(bps)} bps",
                f"  réduit le coût du crédit pour les entreprises et ménages.",
                f"  → Effet positif attendu sur les actions (+{impacts.get('stoxx50',0):.1f}% Stoxx50).",
                f"  → Les secteurs immobilier et utilities sont les principaux bénéficiaires.",
                f"  → L'EUR/USD pourrait reculer (différentiel de taux réduit vs Fed).",
                f"  → Les banques subissent une compression de leurs marges d'intérêt.",
            ]
        elif prochain == "HAUSSE":
            narrative += [
                f"  La BCE envisage une hausse pour juguler l'inflation ({hicp:.1f}%).",
                f"  → Effet négatif attendu sur les actions ({impacts.get('stoxx50',0):.1f}% Stoxx50).",
                f"  → L'actualisation des flux futurs augmente → valorisations réduites.",
                f"  → Les banques bénéficient de l'élargissement des marges.",
                f"  → L'EUR/USD pourrait progresser (attractivité du rendement EUR).",
            ]
        else:
            narrative += [
                f"  La BCE maintient ses taux. Les marchés ont déjà intégré le statu quo.",
                f"  → Impact limité à court terme ({impacts.get('stoxx50',0):.1f}% Stoxx50).",
                f"  → L'attention se déplace vers la conférence de presse et les projections.",
                f"  → Le 'forward guidance' sera déterminant pour la prochaine réunion.",
            ]
        narrative += [
            "",
            f"⚡ STRATÉGIE D'ARBITRAGE :",
            f"  → Sur indices : position {'longue' if stoxx_dir=='hausse' else 'courte'} "
            f"Stoxx50 / CAC40 / DAX",
            f"  → Sur secteurs : surpondérer {'immobilier + utilities' if prochain=='BAISSE' else 'banques'}",
            f"  → Sur forex : EUR/USD {'en baisse' if prochain=='BAISSE' else 'en hausse'}",
        ]
        return "\n".join(narrative)

    def _impact_moyen_terme(self, tendance: Dict, macro: Dict) -> Dict:
        prochain = tendance.get("prochain_mvt_prevu","STABLE")
        n_baisses = tendance.get("n_baisses_recentes",0)
        taux = tendance.get("taux_actuel",2.0)
        taux_neutre = tendance.get("taux_neutre_estime",2.0)

        if prochain == "BAISSE" and n_baisses >= 2:
            return {
                "stoxx50_3m": "+3% à +8%",
                "dax_3m":     "+4% à +10%",
                "eur_usd_3m": "-0.5% à -2%",
                "secteurs_privilegies": ["Immobilier","Utilities","Technologie"],
                "secteurs_eviter":      ["Banques","Assurances"],
                "logique": f"Cycle d'assouplissement en cours — encore {abs(taux-taux_neutre):.2f}% à baisser vers taux neutre",
            }
        elif prochain == "HAUSSE":
            return {
                "stoxx50_3m": "-2% à -6%",
                "dax_3m":     "-1% à -5%",
                "eur_usd_3m": "+1% à +3%",
                "secteurs_privilegies": ["Banques","Financières","Matières premières"],
                "secteurs_eviter":      ["Immobilier","Utilities","Duration longue"],
                "logique": "Resserrement → compression multiples de valorisation",
            }
        else:
            return {
                "stoxx50_3m": "0% à +3%",
                "dax_3m":     "0% à +4%",
                "eur_usd_3m": "-0.5% à +0.5%",
                "secteurs_privilegies": ["Qualité","Faible levier","Croissance visible"],
                "secteurs_eviter":      ["Secteurs cycliques endettés"],
                "logique": "Pause BCE → sélectivité actions, focus fondamentaux",
            }

    def _facteurs_risque(self, macro: Dict) -> List[str]:
        risques = []
        vix = macro.get("VIX",18) or 18
        ig  = macro.get("IG_SPREAD",0.9) or 0.9
        hy  = macro.get("HY_SPREAD",3.5) or 3.5
        us  = macro.get("US_SPREAD_10_2",0.3) or 0.3

        if vix > 25:  risques.append(f"⚠️  VIX élevé ({vix:.1f}) — volatilité accrue, réduire exposition")
        if ig > 1.5:  risques.append(f"⚠️  Spread IG large ({ig*100:.0f}bps) — stress crédit latent")
        if hy > 5.0:  risques.append(f"⚠️  Spread HY élevé ({hy*100:.0f}bps) — signal récession")
        if us < -0.2: risques.append(f"⚠️  Courbe US inversée ({us:.2f}%) — récession probable US")
        if not risques: risques.append("✅ Aucun signal de risque systémique majeur détecté")
        return risques


# ══════════════════════════════════════════════════════════════════════════════
# §4  RAPPORT COMPLET
# ══════════════════════════════════════════════════════════════════════════════

class RapportBCE:
    """Génère le rapport complet BCE — utilisé par le dashboard et le terminal."""

    def __init__(self):
        self.db      = BCEDatabase()
        self.api     = BCEAPI(self.db)
        self.analyse = AnalyseurTendancesBCE(self.db)

    def generer(self, symboles_indices: List[str] = None) -> Dict:
        symboles = symboles_indices or ["^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F"]

        logger.info("Génération du rapport BCE complet...")
        ts = datetime.utcnow().isoformat()

        # 1. Données macro
        logger.info("[1/5] Données macro...")
        macro = self.api.fetch_all_macro()

        # 2. Prix live
        logger.info("[2/5] Prix en direct...")
        prix_live = self.api.fetch_live_prices(symboles)

        # 3. Tendances BCE
        logger.info("[3/5] Analyse tendances BCE...")
        tendances = self.analyse.analyser_cycle_monetaire(macro)

        # 4. Impact marchés
        logger.info("[4/5] Impact sur les cours...")
        impact = self.analyse.analyser_impact_marches(tendances, macro)

        # 5. Actualités + Calendrier
        logger.info("[5/5] Actualités et calendrier...")
        actualites  = self.api.fetch_actualites()
        calendrier  = self.api.get_calendrier()

        # Prochaine réunion
        prochaine_reunion = None
        today = date.today().isoformat()
        for evt in calendrier:
            if evt.get("date_reunion","") >= today:
                prochaine_reunion = evt
                break

        rapport = {
            "timestamp":        ts,
            "macro":            macro,
            "prix_live":        prix_live,
            "tendances_bce":    tendances,
            "impact_marches":   impact,
            "actualites":       actualites[:8],
            "calendrier":       calendrier,
            "prochaine_reunion":prochaine_reunion,
            "db_status":        self.db.status(),
        }

        # Sauvegarder le rapport
        Path("logs").mkdir(exist_ok=True)
        with open("logs/rapport_bce_complet.json","w",encoding="utf-8") as f:
            json.dump(rapport, f, indent=2, default=str, ensure_ascii=False)

        return rapport

    def afficher(self, rapport: Dict) -> None:
        """Affichage terminal structuré."""
        t = rapport.get("tendances_bce",{})
        i = rapport.get("impact_marches",{})
        m = rapport.get("macro",{})
        c = rapport.get("calendrier",[])
        pr= rapport.get("prochaine_reunion",{})

        print(f"\n{'═'*72}")
        print(f"  🏦 RAPPORT BCE COMPLET — {datetime.utcnow():%d/%m/%Y %H:%M} UTC")
        print(f"{'═'*72}")

        # Phase et décision
        print(f"\n  PHASE DU CYCLE : {t.get('phase_cycle','N/A')}")
        print(f"  Stance BCE     : {t.get('stance','N/A')} ({t.get('biais_marche','')}) ")
        print(f"  Taux de dépôt  : {t.get('taux_actuel',0):.2f}%  "
              f"(neutre estimé: {t.get('taux_neutre_estime',2.0):.2f}%)")
        print(f"  Inflation HICP : {t.get('inflation_hicp','N/A')}%  ({t.get('inflation_situation','')})")
        print(f"  Taux réel      : {t.get('taux_reel','N/A')}%  ({t.get('taux_reel_situation','')})")

        # Prochaine décision
        prob = t.get("probabilites",{})
        print(f"\n  PROCHAINE DÉCISION PRÉVUE : {t.get('prochain_mvt_prevu','?')}"
              f" ({t.get('bps_prevu',0):+d}bps)  |  Confiance: {t.get('confiance_pct',0)}%")
        print(f"  Probabilités : Baisse {prob.get('baisse_pct',0):.0f}%  "
              f"Stable {prob.get('stable_pct',0):.0f}%  "
              f"Hausse {prob.get('hausse_pct',0):.0f}%")
        print(f"  Tendance récente : {t.get('tendance_recente','')}")

        # Prochaine réunion
        if pr:
            print(f"\n  📅 PROCHAINE RÉUNION BCE : {pr.get('date_reunion','N/A')}")
            print(f"     {pr.get('description','')}")

        # Impact marchés J+1
        imp_act = i.get("impact_j1_attendu",{}).get("actions_zone_euro",{})
        imp_sec = i.get("impact_j1_attendu",{}).get("secteurs",{})
        imp_fx  = i.get("impact_j1_attendu",{}).get("forex",{})

        print(f"\n  IMPACT ATTENDU J+1 (si décision = {i.get('prochain_mouvement','?')}) :")
        print(f"  {'─'*55}")
        for idx, d in imp_act.items():
            v  = d.get("impact_pct",0)
            ic = "▲" if v>0 else "▼" if v<0 else "─"
            print(f"  {idx:15s} {ic} {abs(v):.1f}%   {d.get('logique','')[:40]}")
        print()
        for sec, d in imp_sec.items():
            v  = d.get("impact_pct",0)
            ic = "▲" if v>0 else "▼" if v<0 else "─"
            print(f"  {sec:15s} {ic} {abs(v):.1f}%   {d.get('logique','')[:40]}")
        print()
        for fx, d in imp_fx.items():
            v  = d.get("impact_pct",0)
            ic = "▲" if v>0 else "▼" if v<0 else "─"
            print(f"  {fx:15s} {ic} {abs(v):.2f}%   {d.get('direction','')[:40]}")

        # Moyen terme
        mt = i.get("horizon_3_6_mois",{})
        if mt:
            print(f"\n  HORIZON 3-6 MOIS :")
            print(f"  Stoxx50  : {mt.get('stoxx50_3m','N/A')}")
            print(f"  DAX      : {mt.get('dax_3m','N/A')}")
            print(f"  EUR/USD  : {mt.get('eur_usd_3m','N/A')}")
            if mt.get("secteurs_privilegies"):
                print(f"  ✅ Privilégier : {', '.join(mt['secteurs_privilegies'])}")
            if mt.get("secteurs_eviter"):
                print(f"  ⛔ Éviter     : {', '.join(mt['secteurs_eviter'])}")

        # Facteurs de risque
        risques = i.get("facteurs_risque",[])
        if risques:
            print(f"\n  FACTEURS DE RISQUE :")
            for r in risques: print(f"    {r}")

        # Macro clé
        print(f"\n  MACRO CLÉS :")
        mac_display = [("VIX","VIX"),("EURIBOR_3M","Euribor 3M"),
                        ("HICP_YOY","HICP (infla.)"),("EUR_USD","EUR/USD"),
                        ("US_SPREAD_10_2","Spread US 10-2"),("IG_SPREAD","IG Spread")]
        for key, label in mac_display:
            val = m.get(key)
            if val is not None:
                print(f"    {label:20s}: {val:.4f}")

        # Actualités
        arts = rapport.get("actualites",[])[:4]
        if arts:
            print(f"\n  📰 ACTUALITÉS RÉCENTES :")
            for a in arts:
                print(f"    [{a.get('source','')[:12]}] {a.get('titre','')[:60]}")
                print(f"    {a.get('sentiment','')}  ·  {a.get('date','')[:16]}")

        print(f"\n  Rapport sauvegardé : logs/rapport_bce_complet.json")
        print(f"{'═'*72}\n")


# ══════════════════════════════════════════════════════════════════════════════
# §5  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="bce_engine.py — Intelligence BCE complète",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--tendances",   action="store_true",
                         help="Analyser les tendances BCE uniquement")
    parser.add_argument("--impact",      action="store_true",
                         help="Analyser l'impact sur les cours")
    parser.add_argument("--calendrier",  action="store_true",
                         help="Prochaines réunions BCE")
    parser.add_argument("--db-init",     action="store_true",
                         help="Initialiser la base de données")
    parser.add_argument("--db-update",   action="store_true",
                         help="Mettre à jour la base de données")
    parser.add_argument("--db-status",   action="store_true",
                         help="État de la base de données")
    parser.add_argument("--json",        action="store_true",
                         help="Sortie JSON brute")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════╗
║  bce_engine.py — Intelligence BCE / Zone Euro           ║
║  APIs : BCE SDMX · FRED · Yahoo Finance · RSS           ║
║  Base : SQLite locale                                    ║
╚══════════════════════════════════════════════════════════╝
""")

    db  = BCEDatabase()
    api = BCEAPI(db)
    ana = AnalyseurTendancesBCE(db)
    rpt = RapportBCE()

    if args.db_status:
        st = db.status()
        print(f"  Base : {st['chemin']}")
        print(f"  Taille : {st['taille_mb']:.2f} MB")
        for t, n in st["tables"].items():
            print(f"  {t:30s}: {n} enregistrements")
        return

    if args.db_init or args.db_update:
        print("  Initialisation/Mise à jour de la base...")
        SYMBOLES_BCE = ["^STOXX50E","^FCHI","^GDAXI","^IBEX","EURUSD=X","BZ=F"]
        res = api.fetch_indices_ohlcv(SYMBOLES_BCE, jours=252)
        for sym, info in res.items():
            print(f"  {sym}: {info.get('lignes',0)} lignes")
        db.save_calendrier(api.CALENDRIER_BCE)
        print("  ✅ Base mise à jour")
        db.status()
        return

    if args.calendrier:
        print("  📅 PROCHAINES RÉUNIONS BCE\n" + "─"*45)
        evts = api.get_calendrier()
        for e in evts:
            print(f"  {e.get('date_reunion','N/A'):12s}  {e.get('description','')}")
        return

    if args.tendances:
        print("  Analyse des tendances BCE...")
        macro = api.fetch_all_macro()
        t     = ana.analyser_cycle_monetaire(macro)
        if args.json:
            print(json.dumps(t, indent=2, default=str))
        else:
            print(f"\n  Phase      : {t['phase_cycle']}")
            print(f"  Stance     : {t['stance']}")
            print(f"  Décision   : {t['prochain_mvt_prevu']} ({t['bps_prevu']:+d}bps)")
            print(f"  Confiance  : {t['confiance_pct']}%")
            print(f"  Probabilités :")
            for k,v in t["probabilites"].items():
                print(f"    {k}: {v:.0f}%")
        return

    if args.impact:
        print("  Analyse de l'impact sur les marchés...")
        macro = api.fetch_all_macro()
        t     = ana.analyser_cycle_monetaire(macro)
        i     = ana.analyser_impact_marches(t, macro)
        if args.json:
            print(json.dumps(i, indent=2, default=str))
        else:
            print(f"\n  {i.get('narrative','')}")
        return

    # Rapport complet par défaut
    rapport = rpt.generer()
    if args.json:
        print(json.dumps({k:v for k,v in rapport.items()
                           if k not in ("actualites","db_status")},
                          indent=2, default=str))
    else:
        rpt.afficher(rapport)


if __name__ == "__main__":
    main()

# FIN bce_engine.py — voir market_oracle_bce.py pour le dashboard Streamlit
