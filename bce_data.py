#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  FICHIER 1/3 — bce_data.py                                                  ║
║  Moteur de données BCE · Indices européens · Veille financière              ║
║  Mission : arbitrage sur indices liés à la Banque Centrale Européenne       ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDE MAC (Terminal) :                                                   ║
║    python3 bce_data.py                  # Affiche toutes les données BCE    ║
║    python3 bce_data.py --indices        # Cours des indices EUR             ║
║    python3 bce_data.py --taux           # Taux BCE + courbe des taux        ║
║    python3 bce_data.py --news           # Veille actualités financières     ║
║    python3 bce_data.py --signal         # Signal d'arbitrage recommandé     ║
║                                                                              ║
║  DÉPENDANCES (installer en premier) :                                        ║
║    pip3 install yfinance requests pandas numpy feedparser                   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, logging, warnings, argparse
from datetime import datetime, timedelta, date
from typing   import Dict, List, Optional, Tuple
from pathlib  import Path

import numpy  as np
import pandas as pd
import requests

warnings.filterwarnings("ignore")
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[logging.FileHandler("logs/bce_data.log"), logging.StreamHandler()]
)
logger = logging.getLogger("BCE")
for n in ("yfinance","urllib3"): logging.getLogger(n).setLevel(logging.CRITICAL)

try:    import yfinance as yf;    YF_OK = True
except: YF_OK = False;            print("pip3 install yfinance")
try:    import feedparser;        FP_OK = True
except: FP_OK = False;            print("pip3 install feedparser")


# ══════════════════════════════════════════════════════════════════════════════
# UNIVERS BCE — Indices et instruments liés à la politique monétaire
# européenne. Périmètre volontairement réduit pour économiser les ressources.
# ══════════════════════════════════════════════════════════════════════════════

BCE_INDICES = {
    # ── Indices actions zone euro ──────────────────────────────────────────
    "^STOXX50E":  {"nom": "Euro Stoxx 50",      "type": "index", "zone": "EUR"},
    "^FCHI":      {"nom": "CAC 40",              "type": "index", "zone": "EUR"},
    "^GDAXI":     {"nom": "DAX 40",              "type": "index", "zone": "EUR"},
    "^IBEX":      {"nom": "IBEX 35 (Espagne)",   "type": "index", "zone": "EUR"},
    "^AEX":       {"nom": "AEX (Pays-Bas)",       "type": "index", "zone": "EUR"},
    "^MIB":       {"nom": "FTSE MIB (Italie)",   "type": "index", "zone": "EUR"},

    # ── Taux et obligations souveraines ───────────────────────────────────
    "EURUSD=X":   {"nom": "EUR/USD",             "type": "forex",  "zone": "EUR"},
    "EURGBP=X":   {"nom": "EUR/GBP",             "type": "forex",  "zone": "EUR"},
    "EURJPY=X":   {"nom": "EUR/JPY",             "type": "forex",  "zone": "EUR"},
    "EURCHF=X":   {"nom": "EUR/CHF",             "type": "forex",  "zone": "EUR"},

    # ── ETFs zone euro (liquidité élevée) ─────────────────────────────────
    "EXW1.DE":    {"nom": "iShares DAX ETF",     "type": "etf",    "zone": "EUR"},
    "CSX5.PA":    {"nom": "Lyxor Euro Stoxx 50", "type": "etf",    "zone": "EUR"},

    # ── Matières premières liées à l'économie europénne ───────────────────
    "BZ=F":       {"nom": "Brent Crude (EUR)",   "type": "commodity","zone":"EUR"},
    "NG=F":       {"nom": "Gaz naturel",          "type": "commodity","zone":"EUR"},
}

# Sources de veille financière (RSS gratuits, pas de clé)
NEWS_SOURCES = {
    "BCE":           "https://www.ecb.europa.eu/rss/press.html",
    "Les Echos":     "https://www.lesechos.fr/feeds/rss/finance-marches.xml",
    "Le Monde Éco":  "https://www.lemonde.fr/economie/rss_full.xml",
    "Reuters EU":    "https://feeds.reuters.com/reuters/businessNews",
    "Boursorama":    "https://www.boursorama.com/bourse/actualites/rss",
    "Yahoo Finance": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR&lang=fr-FR",
}

# Mots-clés BCE pour filtrer les actualités pertinentes
BCE_KEYWORDS_BULL = [
    "baisse des taux", "assouplissement", "stimulus", "rachat", "hausse",
    "croissance", "pib", "emploi", "inflation maîtrisée", "relance",
    "rate cut", "easing", "growth", "rally", "momentum", "achat",
]
BCE_KEYWORDS_BEAR = [
    "hausse des taux", "resserrement", "récession", "inflation", "crise",
    "déficit", "chute", "stagflation", "dégradation", "sell-off",
    "rate hike", "tightening", "recession", "selloff", "baisse",
]


# ══════════════════════════════════════════════════════════════════════════════
# §1  DONNÉES BCE OFFICIELLES
# ══════════════════════════════════════════════════════════════════════════════

class BCEDataFetcher:
    """Récupère les données officielles de la Banque Centrale Européenne."""

    BCE_API   = "https://data-api.ecb.europa.eu/service/data"
    BCE_RATES = {
        "EUR/USD": "EXR/D.USD.EUR.SP00.A",
        "EUR/GBP": "EXR/D.GBP.EUR.SP00.A",
        "EUR/JPY": "EXR/D.JPY.EUR.SP00.A",
        "EUR/CHF": "EXR/D.CHF.EUR.SP00.A",
    }
    BCE_INTEREST = "FM/B.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"  # Euribor 3M

    def _get_json(self, series: str) -> Optional[Dict]:
        url = f"{self.BCE_API}/{series}?format=jsondata&detail=dataonly&lastNObservations=5"
        try:
            r = requests.get(url, timeout=10,
                              headers={"Accept": "application/json"})
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            logger.debug(f"BCE API {series}: {e}")
        return None

    def taux_change(self) -> Dict[str, float]:
        """Taux de change officiels BCE (mis à jour quotidiennement)."""
        result = {}
        for paire, series in self.BCE_RATES.items():
            data = self._get_json(series)
            if data:
                try:
                    obs = data["dataSets"][0]["series"]["0:0:0:0:0"]["observations"]
                    last_key = sorted(obs.keys(), key=int)[-1]
                    val = obs[last_key][0]
                    if val is not None:
                        result[paire] = round(float(val), 5)
                except (KeyError, IndexError, TypeError):
                    pass
        return result

    def euribor(self) -> Optional[float]:
        """Taux Euribor 3 mois (référence interbancaire zone euro)."""
        data = self._get_json(self.BCE_INTEREST)
        if not data:
            return None
        try:
            obs = data["dataSets"][0]["series"]["0:0:0:0:0:0:0"]["observations"]
            last_key = sorted(obs.keys(), key=int)[-1]
            val = obs[last_key][0]
            return round(float(val), 4) if val is not None else None
        except Exception:
            return None

    def politique_monetaire(self) -> Dict:
        """
        Résumé de la politique monétaire BCE.
        Données statiques enrichies par la veille RSS.
        """
        return {
            "taux_depot":       4.00,    # % (taux de dépôt BCE – mai 2026)
            "taux_refi":        4.25,    # % (taux de refinancement)
            "taux_pret_marg":   4.50,    # % (taux prêt marginal)
            "bilan_bce_mrd":    6_800,   # Milliards EUR (bilan approximatif)
            "objectif_inflation":2.0,    # % (cible BCE)
            "prochaine_reunion": "2026-06-05",
            "stance":           "NEUTRE",  # RESTRICTIF / NEUTRE / ACCOMMODANT
            "note": "Basé sur les dernières déclarations de la BCE",
        }


# ══════════════════════════════════════════════════════════════════════════════
# §2  DONNÉES DE MARCHÉ EN TEMPS RÉEL
# ══════════════════════════════════════════════════════════════════════════════

class MarketDataEUR:
    """Données de marché en temps réel pour les indices BCE."""

    def __init__(self):
        self._cache: Dict[str, Tuple] = {}
        self._ttl = 30  # secondes

    def _cached(self, key: str, fn, ttl: int = None):
        now = time.time()
        ttl = ttl or self._ttl
        if key in self._cache:
            val, ts = self._cache[key]
            if now - ts < ttl:
                return val
        val = fn()
        self._cache[key] = (val, now)
        return val

    def prix_live(self, symbol: str) -> Optional[Dict]:
        """Prix en temps réel depuis Yahoo Finance."""
        def _fetch():
            if not YF_OK: return None
            try:
                t    = yf.Ticker(symbol)
                hist = t.history(period="2d", interval="1m", auto_adjust=True)
                if hist is None or hist.empty:
                    hist = t.history(period="5d", interval="1d", auto_adjust=True)
                if hist is None or hist.empty: return None
                last  = float(hist["Close"].iloc[-1])
                prev  = float(hist["Close"].iloc[-2]) if len(hist) > 1 else last
                chg   = last - prev
                chgp  = chg / prev * 100 if prev else 0
                vol   = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
                return {
                    "symbol":    symbol,
                    "prix":      round(last, 4),
                    "variation": round(chg, 4),
                    "var_pct":   round(chgp, 3),
                    "volume":    vol,
                    "haut_24h":  round(float(hist["High"].max()), 4),
                    "bas_24h":   round(float(hist["Low"].min()), 4),
                    "ts":        datetime.utcnow().isoformat(),
                }
            except Exception as e:
                logger.debug(f"Prix {symbol}: {e}")
                return None
        return self._cached(f"prix_{symbol}", _fetch, ttl=30)

    def tous_les_prix(self) -> Dict[str, Dict]:
        """Prix de tous les indices BCE en batch."""
        result = {}
        symbols = list(BCE_INDICES.keys())
        if not YF_OK:
            return result
        try:
            raw = yf.download(symbols, period="5d", interval="1d",
                               progress=False, auto_adjust=True,
                               group_by="ticker", timeout=20)
            for sym in symbols:
                try:
                    if len(symbols) == 1:
                        df_s = raw
                    else:
                        if sym not in raw.columns.get_level_values(0):
                            continue
                        df_s = raw[sym]
                    close = float(df_s["Close"].dropna().iloc[-1])
                    prev  = float(df_s["Close"].dropna().iloc[-2]) if len(df_s) > 1 else close
                    chg   = close - prev
                    result[sym] = {
                        "symbol":  sym,
                        "nom":     BCE_INDICES[sym]["nom"],
                        "type":    BCE_INDICES[sym]["type"],
                        "prix":    round(close, 4),
                        "var_pct": round(chg / prev * 100 if prev else 0, 3),
                    }
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Batch download: {e}")
            # Fallback individuel
            for sym in symbols[:5]:  # Limiter pour économiser les ressources
                p = self.prix_live(sym)
                if p:
                    result[sym] = {**p, "nom": BCE_INDICES[sym]["nom"],
                                    "type": BCE_INDICES[sym]["type"]}
                time.sleep(0.3)
        return result

    def historique(self, symbol: str, jours: int = 252) -> pd.DataFrame:
        """OHLCV historique pour les calculs techniques."""
        if not YF_OK:
            return pd.DataFrame()
        try:
            period = f"{max(1, jours // 252)}y" if jours >= 252 else f"{jours}d"
            raw    = yf.download(symbol, period=period, interval="1d",
                                  progress=False, auto_adjust=True, timeout=15)
            if raw is None or raw.empty:
                return pd.DataFrame()
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.droplevel(1)
            raw.columns = [c.title() for c in raw.columns]
            cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
            return raw[cols].dropna(subset=["Close"])
        except Exception as e:
            logger.warning(f"Historique {symbol}: {e}")
            return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# §3  VEILLE D'ACTUALITÉS FINANCIÈRES
# ══════════════════════════════════════════════════════════════════════════════

class VeilleBCE:
    """Agrège les actualités financières liées à la BCE depuis des sources RSS."""

    def __init__(self):
        self._cache_news: List[Dict] = []
        self._cache_ts   = 0

    def actualites(self, limite: int = 20) -> List[Dict]:
        """Récupère et filtre les actualités BCE depuis les flux RSS."""
        if time.time() - self._cache_ts < 600:  # Cache 10 minutes
            return self._cache_news[:limite]

        if not FP_OK:
            logger.warning("feedparser non installé : pip3 install feedparser")
            return []

        articles = []
        for source, url in NEWS_SOURCES.items():
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    titre = (entry.get("title","") or "").strip()
                    if not titre:
                        continue
                    titre_lower = titre.lower()
                    resume = (entry.get("summary","") or
                               entry.get("description","") or "")[:300]

                    # Score de sentiment basé sur les mots-clés BCE
                    score = 0
                    for mot in BCE_KEYWORDS_BULL:
                        if mot in titre_lower or mot in resume.lower():
                            score += 1
                    for mot in BCE_KEYWORDS_BEAR:
                        if mot in titre_lower or mot in resume.lower():
                            score -= 1

                    # Pertinence BCE
                    bce_mots = ["bce","banque centrale","taux","euribor","euro",
                                 "zone euro","écb","ecb","fed","inflation"]
                    pertinent = any(m in titre_lower for m in bce_mots)

                    sentiment = ("🟢 Haussier" if score > 0 else
                                  "🔴 Baissier" if score < 0 else "⚪ Neutre")
                    articles.append({
                        "source":    source,
                        "titre":     titre,
                        "resume":    resume,
                        "lien":      entry.get("link","#"),
                        "date":      entry.get("published","")[:25],
                        "sentiment": sentiment,
                        "score":     score,
                        "pertinent": pertinent,
                    })
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"RSS {source}: {e}")

        # Trier : articles pertinents BCE en premier, puis par score
        articles.sort(key=lambda x: (x["pertinent"], abs(x["score"])), reverse=True)
        self._cache_news = articles
        self._cache_ts   = time.time()
        return articles[:limite]

    def score_sentiment_global(self, articles: List[Dict]) -> Tuple[float, str]:
        """Calcule un score de sentiment global sur les dernières actualités."""
        if not articles:
            return 50.0, "NEUTRE"
        scores = [a["score"] for a in articles]
        total  = sum(scores)
        n      = len(scores)
        # Normaliser entre 0 et 100
        avg    = total / n
        norm   = min(max((avg + 3) / 6 * 100, 0), 100)  # [-3,+3] → [0,100]
        if norm > 65:   label = "HAUSSIER"
        elif norm > 55: label = "LÉGÈREMENT HAUSSIER"
        elif norm > 45: label = "NEUTRE"
        elif norm > 35: label = "LÉGÈREMENT BAISSIER"
        else:           label = "BAISSIER"
        return round(norm, 1), label


# ══════════════════════════════════════════════════════════════════════════════
# §4  MOTEUR D'ANALYSE TECHNIQUE (simplifié, pour les indices EUR)
# ══════════════════════════════════════════════════════════════════════════════

class AnalyseTechniqueEUR:
    """Calcule les indicateurs techniques sur les indices BCE."""

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False, min_periods=n).mean()

    @staticmethod
    def _rma(s: pd.Series, n: int) -> pd.Series:
        a = 1/n; arr = s.values.astype(float); out = np.full(len(arr), np.nan)
        i0 = next((i for i,v in enumerate(arr) if not np.isnan(v)), None)
        if i0 is None: return pd.Series(out, index=s.index)
        out[i0] = arr[i0]
        for i in range(i0+1, len(arr)):
            if not np.isnan(arr[i]):
                out[i] = (out[i-1] if not np.isnan(out[i-1]) else arr[i])*(1-a)+arr[i]*a
        return pd.Series(out, index=s.index)

    def analyser(self, df: pd.DataFrame, symbol: str) -> Dict:
        """Analyse complète d'un indice BCE. Retourne signaux et niveaux."""
        if df is None or df.empty or len(df) < 30:
            return {"symbol": symbol, "erreur": "Données insuffisantes"}

        C, H, L, V = (df[c].astype(float) for c in ["Close","High","Low","Volume"])
        pc = C.shift(1)
        tr = pd.concat([H-L,(H-pc).abs(),(L-pc).abs()], axis=1).max(axis=1)

        # EMAs
        ema20  = self._ema(C, 20)
        ema50  = self._ema(C, 50)
        ema200 = self._ema(C, 200)

        # RSI
        Δ  = C.diff()
        ag = self._rma(Δ.clip(lower=0), 14)
        al = self._rma((-Δ).clip(lower=0), 14)
        rsi = 100 - 100 / (1 + ag / al.replace(0, np.nan))

        # MACD
        macd  = self._ema(C, 12) - self._ema(C, 26)
        sig_m = self._ema(macd, 9)
        hist  = macd - sig_m

        # ATR
        atr = self._rma(tr, 14)

        # Bollinger
        bm  = C.rolling(20).mean()
        bs  = C.rolling(20).std(ddof=0)
        bb_up = bm + 2*bs; bb_dn = bm - 2*bs
        bb_pct = (C - bb_dn) / (bb_up - bb_dn).replace(0, np.nan)

        # ADX
        up, dn = H.diff(), -L.diff()
        pdm = pd.Series(np.where((up>dn)&(up>0), up, 0.0), index=C.index)
        ndm = pd.Series(np.where((dn>up)&(dn>0), dn, 0.0), index=C.index)
        atr14 = self._rma(tr, 14)
        pdi   = 100 * self._rma(pdm, 14) / atr14.replace(0, np.nan)
        ndi   = 100 * self._rma(ndm, 14) / atr14.replace(0, np.nan)
        dx    = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        adx   = self._rma(dx, 14)

        # Volume ratio
        vol_ratio = V / V.rolling(20).mean().replace(0, np.nan)

        # Valeurs actuelles
        def v(s): return float(s.dropna().iloc[-1]) if not s.dropna().empty else 0.0

        prix       = v(C)
        rsi_v      = v(rsi)
        adx_v      = v(adx)
        pdi_v      = v(pdi)
        ndi_v      = v(ndi)
        macd_h     = v(hist)
        ema20_v    = v(ema20)
        ema50_v    = v(ema50)
        ema200_v   = v(ema200)
        bb_pct_v   = v(bb_pct)
        atr_v      = v(atr)
        vol_r      = v(vol_ratio)

        # Retours
        ret_1s  = (prix / float(C.iloc[-2]) - 1) * 100 if len(C) > 1  else 0
        ret_1m  = (prix / float(C.iloc[-22]) - 1) * 100 if len(C) > 22 else 0
        ret_3m  = (prix / float(C.iloc[-65]) - 1) * 100 if len(C) > 65 else 0
        ret_ytd = 0.0
        ytd = C[C.index.year == datetime.utcnow().year]
        if len(ytd) > 1:
            ret_ytd = (float(ytd.iloc[-1]) / float(ytd.iloc[0]) - 1) * 100

        # Score signal
        bull = 0; bear = 0; raisons_b = []; raisons_s = []

        if ema20_v > ema50_v > ema200_v:
            bull += 3; raisons_b.append("Alignement EMA 20>50>200 ✓")
        elif ema20_v < ema50_v < ema200_v:
            bear += 3; raisons_s.append("Alignement EMA 20<50<200 ✗")
        elif ema20_v > ema50_v:
            bull += 1
        else:
            bear += 1

        if prix > ema200_v * 1.005:
            bull += 2; raisons_b.append("Prix > EMA200 ✓")
        elif prix < ema200_v * 0.995:
            bear += 2; raisons_s.append("Prix < EMA200 ✗")

        if rsi_v < 30:    bull += 2; raisons_b.append(f"RSI {rsi_v:.0f} — survente ✓")
        elif rsi_v > 70:  bear += 2; raisons_s.append(f"RSI {rsi_v:.0f} — surachat ✗")

        if macd_h > 0: bull += 1
        else:          bear += 1

        if adx_v > 25:
            if pdi_v > ndi_v: bull += 1; raisons_b.append(f"ADX {adx_v:.0f} haussier ✓")
            else:             bear += 1; raisons_s.append(f"ADX {adx_v:.0f} baissier ✗")

        if bb_pct_v < 0.15: bull += 1; raisons_b.append("Proche BB lower ✓")
        elif bb_pct_v > 0.85: bear += 1; raisons_s.append("Proche BB upper ✗")

        if vol_r > 1.4:
            if bull > bear: bull += 1; raisons_b.append(f"Volume fort ({vol_r:.1f}x) ✓")
            else:           bear += 1; raisons_s.append(f"Volume fort ({vol_r:.1f}x) ✗")

        # Régime
        net = bull - bear
        if   net >= 5:    regime = "FORTE HAUSSE"
        elif net >= 2:    regime = "HAUSSE"
        elif net <= -5:   regime = "FORTE BAISSE"
        elif net <= -2:   regime = "BAISSE"
        else:             regime = "NEUTRE"

        # Signal
        if bull >= 5 and bull > bear + 1:
            signal = "ACHETER" if bull < 8 else "ACHETER FORT"
            force  = min(bull / 10, 1.0)
        elif bear >= 5 and bear > bull + 1:
            signal = "VENDRE" if bear < 8 else "VENDRE FORT"
            force  = min(bear / 10, 1.0)
        else:
            signal = "ATTENDRE"
            force  = 0.3

        raisons = (raisons_b if bull > bear else raisons_s)[:4]

        # Niveaux
        stop_long  = round(prix - atr_v * 2.0, 4)
        tp_long    = round(prix + atr_v * 4.0, 4)
        stop_short = round(prix + atr_v * 2.0, 4)
        tp_short   = round(prix - atr_v * 4.0, 4)
        rr_ratio   = round(abs(tp_long - prix) / max(abs(prix - stop_long), 1e-9), 2)

        # VaR paramétrique (approximation simple)
        lr   = np.log(C / C.shift(1)).dropna()
        mu_r = float(lr.mean())
        sg_r = float(lr.std())
        var95 = abs(mu_r - 1.645 * sg_r) * 100
        sharpe= float(lr.mean() / lr.std() * np.sqrt(252)) if sg_r > 0 else 0

        return {
            "symbol":     symbol,
            "nom":        BCE_INDICES.get(symbol, {}).get("nom", symbol),
            "prix":       round(prix, 4),
            "ret_1j":     round(ret_1s, 3),
            "ret_1m":     round(ret_1m, 2),
            "ret_3m":     round(ret_3m, 2),
            "ret_ytd":    round(ret_ytd, 2),
            "signal":     signal,
            "regime":     regime,
            "force":      round(force, 3),
            "bull_score": bull,
            "bear_score": bear,
            "raisons":    raisons,
            "rsi":        round(rsi_v, 1),
            "adx":        round(adx_v, 1),
            "macd_h":     round(macd_h, 6),
            "bb_pct":     round(bb_pct_v, 3),
            "atr":        round(atr_v, 4),
            "atr_pct":    round(atr_v / prix * 100, 2) if prix > 0 else 0,
            "vol_ratio":  round(vol_r, 2),
            "ema20":      round(ema20_v, 4),
            "ema50":      round(ema50_v, 4),
            "ema200":     round(ema200_v, 4),
            "stop_long":  stop_long,
            "tp_long":    tp_long,
            "stop_short": stop_short,
            "tp_short":   tp_short,
            "rr_ratio":   rr_ratio,
            "var95_pct":  round(var95, 3),
            "sharpe_1y":  round(sharpe, 2),
            "ts":         datetime.utcnow().isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# §5  SIGNAL D'ARBITRAGE BCE
# ══════════════════════════════════════════════════════════════════════════════

class SignalArbitrageBCE:
    """
    Génère des signaux d'arbitrage en croisant :
    - Analyse technique des indices BCE
    - Politique monétaire BCE
    - Sentiment des actualités
    """

    def __init__(self):
        self.bce    = BCEDataFetcher()
        self.market = MarketDataEUR()
        self.veille = VeilleBCE()
        self.tech   = AnalyseTechniqueEUR()

    def generer(self, symboles: List[str] = None) -> Dict:
        """Génère le rapport d'arbitrage complet."""
        symboles  = symboles or ["^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F"]
        timestamp = datetime.utcnow().isoformat()

        # 1. Politique monétaire BCE
        politique = self.bce.politique_monetaire()
        taux_bce  = self.bce.taux_change()
        euribor   = self.bce.euribor()

        # 2. Actualités et sentiment
        articles      = self.veille.actualites(limite=15)
        score_sent, label_sent = self.veille.score_sentiment_global(articles)

        # 3. Analyse technique
        analyses = {}
        for sym in symboles:
            df = self.market.historique(sym, jours=252)
            if not df.empty:
                analyses[sym] = self.tech.analyser(df, sym)
                time.sleep(0.2)  # Rate limit Yahoo Finance

        # 4. Score global d'opportunité
        if analyses:
            signals     = [a.get("signal","ATTENDRE") for a in analyses.values()]
            bull_signals= sum(1 for s in signals if "ACHETER" in s)
            bear_signals= sum(1 for s in signals if "VENDRE" in s)
            n           = len(signals)
            opp_score   = (bull_signals - bear_signals) / n * 10 if n > 0 else 0

            # Ajustement par sentiment
            sent_adj = (score_sent - 50) / 50  # -1 à +1
            opp_score = opp_score * 0.7 + sent_adj * 3 * 0.3

            # Ajustement par politique BCE
            if politique["stance"] == "ACCOMMODANT":   opp_score += 1
            elif politique["stance"] == "RESTRICTIF":  opp_score -= 1

            if   opp_score >= 4:  opportunite = "FORTE OPPORTUNITÉ ACHAT"
            elif opp_score >= 2:  opportunite = "OPPORTUNITÉ ACHAT"
            elif opp_score <= -4: opportunite = "FORTE OPPORTUNITÉ VENTE"
            elif opp_score <= -2: opportunite = "OPPORTUNITÉ VENTE"
            else:                 opportunite = "PAS D'OPPORTUNITÉ CLAIRE"
        else:
            opp_score   = 0
            opportunite = "DONNÉES INSUFFISANTES"
            bull_signals= bear_signals = 0

        # 5. Meilleure opportunité du moment
        meilleure = None
        if analyses:
            candidats = [
                a for a in analyses.values()
                if "ACHETER" in a.get("signal","") or "VENDRE" in a.get("signal","")
            ]
            if candidats:
                meilleure = max(candidats, key=lambda x: x.get("force",0))

        return {
            "timestamp":       timestamp,
            "politique_bce":   politique,
            "euribor_3m":      euribor,
            "taux_bce":        taux_bce,
            "sentiment": {
                "score":       score_sent,
                "label":       label_sent,
                "n_articles":  len(articles),
            },
            "analyses":        analyses,
            "score_opportunite": round(opp_score, 2),
            "opportunite":     opportunite,
            "signaux": {
                "achat":  bull_signals,
                "vente":  bear_signals,
                "neutre": len(signals) - bull_signals - bear_signals if analyses else 0,
            },
            "meilleure_opportunite": meilleure,
            "articles_top5":   articles[:5],
        }


# ══════════════════════════════════════════════════════════════════════════════
# §6  AFFICHAGE TERMINAL
# ══════════════════════════════════════════════════════════════════════════════

def afficher_rapport(rapport: Dict) -> None:
    """Affichage structuré du rapport d'arbitrage BCE dans le terminal."""
    ts  = rapport.get("timestamp","")[:16].replace("T"," ")
    opp = rapport.get("opportunite","N/A")
    sc  = rapport.get("score_opportunite", 0)
    sigs= rapport.get("signaux", {})
    pol = rapport.get("politique_bce", {})
    sent= rapport.get("sentiment", {})

    OPP_ICONS = {
        "FORTE OPPORTUNITÉ ACHAT":  "🚀",
        "OPPORTUNITÉ ACHAT":         "📈",
        "FORTE OPPORTUNITÉ VENTE":  "🔻",
        "OPPORTUNITÉ VENTE":         "📉",
        "PAS D'OPPORTUNITÉ CLAIRE": "⏸️",
        "DONNÉES INSUFFISANTES":    "⚠️",
    }

    print(f"\n{'═'*70}")
    print(f"  📊 RAPPORT BCE — {ts} UTC")
    print(f"{'═'*70}")
    print(f"\n  {OPP_ICONS.get(opp,'•')} OPPORTUNITÉ : {opp}")
    print(f"  Score composite : {sc:+.2f}/10")
    print(f"  Signaux → Achat : {sigs.get('achat',0)}  "
          f"Vente : {sigs.get('vente',0)}  Neutre : {sigs.get('neutre',0)}")

    print(f"\n  POLITIQUE MONÉTAIRE BCE")
    print(f"  {'─'*40}")
    print(f"  Taux de dépôt    : {pol.get('taux_depot', 'N/A')}%")
    print(f"  Taux refi        : {pol.get('taux_refi', 'N/A')}%")
    print(f"  Stance           : {pol.get('stance', 'N/A')}")
    print(f"  Prochaine réunion: {pol.get('prochaine_reunion', 'N/A')}")
    if rapport.get("euribor_3m"):
        print(f"  Euribor 3M       : {rapport['euribor_3m']:.3f}%")

    print(f"\n  SENTIMENT ACTUALITÉS")
    print(f"  {'─'*40}")
    print(f"  Score : {sent.get('score',50):.0f}/100 — {sent.get('label','N/A')}")
    print(f"  Articles analysés : {sent.get('n_articles',0)}")

    print(f"\n  ANALYSES TECHNIQUES — INDICES BCE")
    print(f"  {'─'*65}")
    print(f"  {'Indice':14s} {'Prix':10s} {'1j%':7s} {'Signal':20s} {'RSI':6s} {'ADX':6s}")
    print(f"  {'─'*65}")

    SIG_ICONS = {
        "ACHETER FORT": "🚀", "ACHETER": "↑",
        "ATTENDRE": "—",
        "VENDRE": "↓",     "VENDRE FORT": "🔻",
    }

    for sym, a in rapport.get("analyses", {}).items():
        if "erreur" in a: continue
        sig_i = SIG_ICONS.get(a.get("signal",""), "—")
        chg   = a.get("ret_1j", 0)
        chg_s = f"{chg:+.2f}%"
        print(f"  {sym:14s} {a.get('prix',0):10.2f} {chg_s:7s} "
              f"{sig_i}{a.get('signal',''):18s} "
              f"{a.get('rsi',0):6.1f} {a.get('adx',0):6.1f}")

    m = rapport.get("meilleure_opportunite")
    if m:
        print(f"\n  ⭐ MEILLEURE OPPORTUNITÉ : {m.get('nom', m.get('symbol',''))} "
              f"({m.get('signal','')})")
        print(f"  Prix : {m.get('prix',0):.4f}")
        print(f"  Stop : {m.get('stop_long',0):.4f}  "
              f"TP : {m.get('tp_long',0):.4f}  R:R : {m.get('rr_ratio',0):.1f}x")
        for r in m.get("raisons",[])[:3]:
            print(f"    • {r}")

    if rapport.get("articles_top5"):
        print(f"\n  📰 ACTUALITÉS PERTINENTES")
        print(f"  {'─'*60}")
        for art in rapport["articles_top5"]:
            print(f"  [{art['source']}] {art['titre'][:60]}")
            print(f"    {art['sentiment']} · {art['date'][:16]}")

    print(f"\n{'═'*70}\n")


# ══════════════════════════════════════════════════════════════════════════════
# §7  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="bce_data.py — Données et signaux BCE pour arbitrage",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--indices",  action="store_true", help="Prix des indices BCE")
    parser.add_argument("--taux",     action="store_true", help="Taux BCE + Euribor")
    parser.add_argument("--news",     action="store_true", help="Actualités financières")
    parser.add_argument("--signal",   action="store_true", help="Signal d'arbitrage complet")
    parser.add_argument("--symboles", type=str, default="",
                         help="Symboles à analyser (ex: ^FCHI,^GDAXI,EURUSD=X)")
    parser.add_argument("--json",     action="store_true", help="Sortie JSON brute")
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════╗
║  BCE Data Engine · Arbitrage Zone Euro      ║
║  Sources : Yahoo Finance · BCE · RSS        ║
╚══════════════════════════════════════════════╝
""")

    if not any([args.indices, args.taux, args.news, args.signal]):
        # Par défaut : rapport complet
        args.signal = True

    market = MarketDataEUR()
    bce    = BCEDataFetcher()
    veille = VeilleBCE()
    engine = SignalArbitrageBCE()

    if args.indices:
        print("📊 PRIX DES INDICES BCE EN DIRECT\n" + "─"*50)
        prix = market.tous_les_prix()
        for sym, d in prix.items():
            chg = d.get("var_pct", 0)
            icon = "▲" if chg > 0 else "▼" if chg < 0 else "─"
            print(f"  {sym:14s} {d.get('nom',''):28s} "
                  f"{d.get('prix',0):12.4f}  {icon}{abs(chg):.2f}%")
        return

    if args.taux:
        print("🏦 TAUX BCE\n" + "─"*40)
        pol = bce.politique_monetaire()
        print(f"  Taux dépôt  : {pol['taux_depot']}%")
        print(f"  Taux refi   : {pol['taux_refi']}%")
        print(f"  Stance      : {pol['stance']}")
        euribor = bce.euribor()
        if euribor:
            print(f"  Euribor 3M  : {euribor:.3f}%")
        taux_fx = bce.taux_change()
        print(f"\n  TAUX DE CHANGE BCE OFFICIELS")
        for paire, val in taux_fx.items():
            print(f"  {paire:10s}: {val:.5f}")
        return

    if args.news:
        print("📰 VEILLE BCE\n" + "─"*60)
        articles = veille.actualites(limite=10)
        score, label = veille.score_sentiment_global(articles)
        print(f"  Sentiment global : {score:.0f}/100 — {label}")
        print(f"  Articles analysés : {len(articles)}\n")
        for art in articles:
            print(f"  [{art['source'][:15]}] {art['titre'][:65]}")
            print(f"    {art['sentiment']}  ·  {art['date'][:16]}")
            print()
        return

    if args.signal:
        syms = ([s.strip() for s in args.symboles.split(",") if s.strip()]
                if args.symboles else None)
        print("  Génération du rapport d'arbitrage BCE...")
        rapport = engine.generer(symboles=syms)
        if args.json:
            print(json.dumps({k:v for k,v in rapport.items()
                               if k not in ("articles_top5",)},
                              indent=2, default=str))
        else:
            afficher_rapport(rapport)

        # Sauvegarder
        Path("logs").mkdir(exist_ok=True)
        with open("logs/rapport_bce_latest.json","w") as f:
            json.dump(rapport, f, indent=2, default=str)
        print(f"  Rapport sauvegardé : logs/rapport_bce_latest.json")


if __name__ == "__main__":
    main()
