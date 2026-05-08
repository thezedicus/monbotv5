#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  orchestrator.py — Orchestrateur principal Market Oracle BCE                ║
║  Intègre : scores techniques + macro + news + décision + dashboard HTML     ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES MAC (Terminal) :                                                  ║
║                                                                              ║
║  python3 orchestrator.py                    # Décision + dashboard HTML     ║
║  python3 orchestrator.py --decision         # Juste le signal              ║
║  python3 orchestrator.py --html             # Génère dashboard_oracle.html ║
║  python3 orchestrator.py --open             # Génère + ouvre dans Safari   ║
║  python3 orchestrator.py --commands         # Affiche toutes les commandes ║
║  python3 orchestrator.py --check            # Vérifie l'état du projet     ║
║  python3 orchestrator.py --cron             # Installe l'auto-refresh cron ║
║                                                                              ║
║  INSTALLATION :                                                              ║
║    pip3 install yfinance requests pandas numpy feedparser streamlit plotly  ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import json
import math
import time
import logging
import warnings
import argparse
import subprocess
from datetime import datetime, date, timedelta
from pathlib  import Path
from typing   import Dict, Tuple, List, Optional

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
        logging.FileHandler("logs/orchestrator.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("Orchestrator")
for n in ("yfinance", "urllib3"): logging.getLogger(n).setLevel(logging.CRITICAL)

try:    import yfinance as yf;    YF_OK = True
except: YF_OK = False;            logger.error("pip3 install yfinance")
try:    import feedparser;        FP_OK = True
except: FP_OK = False

# ── Import des modules locaux (si disponibles) ────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bce_engine import (
        BCEDatabase, BCEAPI, AnalyseurTendancesBCE, RapportBCE
    )
    ENGINE_OK = True
except ImportError:
    ENGINE_OK = False
    logger.warning("bce_engine.py non trouvé — mode autonome activé")


# ══════════════════════════════════════════════════════════════════════════════
# §1  CORRECTIONS AUTOMATIQUES DES ERREURS
#     (intègre et améliore fix_syntax_errors() du code original)
# ══════════════════════════════════════════════════════════════════════════════

def fix_syntax_errors() -> List[str]:
    """
    Corrige automatiquement les erreurs connues dans les fichiers du projet.
    Version corrigée et étendue du code original.
    """
    fixed = []
    project_dir = Path(__file__).parent

    # ── Correctifs connus ─────────────────────────────────────────────────────
    FIXES = {
        "market_oracle.py": [
            # Fichier qui commence sans #
            (lambda c: (not c.startswith("#"), "# -*- coding: utf-8 -*-\n" + c)),
        ],
        "market_ultimate.py": [
            # main()ls → main()
            (lambda c: ("main()ls" in c, c.replace("main()ls", "main()"))),
        ],
        "dashboard_v3.py": [
            # Mauvais import bot_v3_final
            (lambda c: ("bot_v3_final" in c, c.replace("from bot_v3_final import", "from bot_v3 import")
                         .replace("import bot_v3_final", "import bot_v3"))),
            # Données synthétiques → réelles
            (lambda c: ("use_synthetic=True" in c, c.replace("use_synthetic=True", "use_synthetic=False"))),
        ],
        "codesupplementaire.py": [
            # pandas_ta → rien (remplacé par natif)
            (lambda c: ("import pandas_ta as ta" in c, c.replace("import pandas_ta as ta", "")
                         .replace("from pandas_ta", "# from pandas_ta"))),
            # cummax() sur ndarray
            (lambda c: (".cummax()" in c and "pd.Series" not in c,
                         c.replace("paths[s].cummax()", "pd.Series(paths[s]).cummax()"))),
        ],
        "bot_v3.py": [
            # use_synthetic=True → False
            (lambda c: ("use_synthetic: bool = True" in c,
                         c.replace("use_synthetic: bool = True", "use_synthetic: bool = False"))),
        ],
    }

    for filename, corrections in FIXES.items():
        fp = project_dir / filename
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
            original = content
            for check_fn in corrections:
                try:
                    needs_fix, new_content = check_fn(content)
                    if needs_fix:
                        content = new_content
                except Exception:
                    pass
            if content != original:
                # Backup
                backup_dir = project_dir / "backups"
                backup_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                (backup_dir / f"{fp.stem}_{ts}{fp.suffix}").write_text(original, encoding="utf-8")
                fp.write_text(content, encoding="utf-8")
                fixed.append(filename)
                logger.info(f"  ✅ Corrigé : {filename}")
        except Exception as e:
            logger.warning(f"  ⚠️  {filename}: {e}")

    return fixed


# ══════════════════════════════════════════════════════════════════════════════
# §2  SCORES RÉELS — VERSION CORRIGÉE ET ENRICHIE
#     (remplace les placeholders du code original)
# ══════════════════════════════════════════════════════════════════════════════

# Indices BCE à surveiller
BCE_INDICES_MAP = {
    "^STOXX50E": "Euro Stoxx 50",
    "^FCHI":     "CAC 40",
    "^GDAXI":    "DAX 40",
    "^IBEX":     "IBEX 35",
    "^AEX":      "AEX",
    "EURUSD=X":  "EUR/USD",
    "BZ=F":      "Brent",
}

# Mots-clés pour le sentiment news
BULL_WORDS = ["hausse", "croissance", "record", "profit", "relance", "achat",
               "rally", "surge", "gain", "rise", "growth", "beat", "up", "bullish",
               "baisse des taux", "assouplissement", "stimulus"]
BEAR_WORDS = ["baisse", "récession", "inflation", "crise", "déficit", "chute",
               "selloff", "crash", "loss", "decline", "fall", "miss", "down",
               "hausse des taux", "resserrement", "stagflation"]


def technical_score(ticker: str = "^STOXX50E") -> float:
    """
    Score technique basé sur RSI + MACD + tendance EMA.
    Retourne un score entre -1.0 (baissier) et +1.0 (haussier).
    CORRIGÉ : gestion MultiIndex yfinance + fallback robuste.
    """
    if not YF_OK:
        return 0.0
    try:
        raw = yf.download(ticker, period="3mo", interval="1d",
                           progress=False, auto_adjust=True, timeout=12)
        if raw is None or raw.empty:
            return 0.0

        # Correction MultiIndex (bug connu yfinance)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)
        raw.columns = [c.title() for c in raw.columns]

        close = raw["Close"].astype(float).dropna()
        if len(close) < 20:
            return 0.0

        # RSI (14j)
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_g = gain.ewm(alpha=1/14, adjust=False).mean()
        avg_l = loss.ewm(alpha=1/14, adjust=False).mean()
        rsi   = float(100 - 100/(1 + avg_g.iloc[-1]/max(avg_l.iloc[-1], 1e-9)))

        # MACD
        macd     = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        macd_h   = float(macd.iloc[-1] - macd_sig.iloc[-1])

        # EMA tendance
        ema20  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema50  = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        last   = float(close.iloc[-1])

        # Score composite [-1, +1]
        score = 0.0
        # RSI
        if rsi < 30:   score += 0.4
        elif rsi > 70: score -= 0.4
        else:          score += (50 - rsi) / 50 * 0.3
        # MACD
        score += 0.2 if macd_h > 0 else -0.2
        # Tendance EMA
        if last > ema20 > ema50 > ema200: score += 0.4
        elif last < ema20 < ema50 < ema200: score -= 0.4
        elif last > ema200: score += 0.2
        else: score -= 0.2

        return max(-1.0, min(1.0, score))

    except Exception as e:
        logger.debug(f"technical_score {ticker}: {e}")
        return 0.0


def macro_score() -> float:
    """
    Score macro basé sur les données BCE et FRED réelles.
    CORRIGÉ : remplace le placeholder retournant 0.0 avec de vraies données.
    Retourne entre -1.0 (restrictif/baissier) et +1.0 (accommodant/haussier).
    """
    score = 0.0
    n     = 0

    # 1. Euribor 3M via BCE SDMX
    try:
        url = ("https://data-api.ecb.europa.eu/service/data/"
               "FM/B.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"
               "?format=jsondata&lastNObservations=3")
        r = requests.get(url, timeout=10, headers={"Accept": "application/json"})
        if r.status_code == 200:
            data = r.json()
            obs  = (data["dataSets"][0]["series"]
                     [list(data["dataSets"][0]["series"].keys())[0]]["observations"])
            vals = [v[0] for v in sorted(obs.values(), key=lambda x: x) if v[0] is not None]
            if len(vals) >= 2:
                # Baisse euribor = accommodant = haussier pour actions
                diff   = float(vals[-1]) - float(vals[-2])
                score += -1.0 if diff > 0.1 else 1.0 if diff < -0.1 else 0.0
                n += 1
    except Exception as e:
        logger.debug(f"BCE SDMX: {e}")

    # 2. FRED — Spread 10-2 US (proxy risque)
    try:
        r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y",
                          timeout=10)
        if r.status_code == 200:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
            df.columns = ["date","val"]
            df["val"] = pd.to_numeric(df["val"], errors="coerce")
            df = df.dropna().tail(5)
            if not df.empty:
                spread = float(df["val"].iloc[-1])
                # Courbe normale (spread > 0) = haussier
                score += 0.5 if spread > 0.3 else -0.5 if spread < -0.2 else 0.0
                n += 1
    except Exception as e:
        logger.debug(f"FRED spread: {e}")

    # 3. Yahoo Finance — VIX (peur)
    if YF_OK:
        try:
            vix_raw = yf.download("^VIX", period="5d", interval="1d",
                                   progress=False, auto_adjust=True, timeout=10)
            if vix_raw is not None and not vix_raw.empty:
                if isinstance(vix_raw.columns, pd.MultiIndex):
                    vix_raw.columns = vix_raw.columns.droplevel(1)
                vix = float(vix_raw["Close"].dropna().iloc[-1])
                # VIX élevé = baissier pour actions
                score += -0.8 if vix >= 30 else -0.3 if vix >= 20 else 0.5
                n += 1
        except Exception as e:
            logger.debug(f"VIX: {e}")

    # 4. Fear & Greed Index
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=8)
        if r.status_code == 200:
            data = r.json()["data"]
            fg   = int(data[0]["value"])
            # < 25 = peur extrême (opportunité achat), > 75 = avidité (prudence)
            score += 0.5 if fg < 30 else -0.5 if fg > 70 else (fg - 50) / 100
            n += 1
    except Exception as e:
        logger.debug(f"Fear&Greed: {e}")

    return max(-1.0, min(1.0, score / max(n, 1)))


def news_score() -> float:
    """
    Score de sentiment basé sur les flux RSS financiers.
    CORRIGÉ : remplace TextBlob (non installé) par analyse de mots-clés.
    Retourne entre -1.0 (négatif) et +1.0 (positif).
    """
    RSS_URLS = [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.lesechos.fr/feeds/rss/finance-marches.xml",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR&lang=fr-FR",
        "https://www.lemonde.fr/economie/rss_full.xml",
    ]
    scores   = []

    if FP_OK:
        for url in RSS_URLS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:4]:
                    titre = (entry.get("title", "") or "").lower()
                    if not titre:
                        continue
                    bull = sum(1 for w in BULL_WORDS if w in titre)
                    bear = sum(1 for w in BEAR_WORDS if w in titre)
                    if bull > bear:     scores.append(min(bull * 0.25, 1.0))
                    elif bear > bull:   scores.append(max(-bear * 0.25, -1.0))
                    else:               scores.append(0.0)
                time.sleep(0.2)
            except Exception as e:
                logger.debug(f"RSS {url[:40]}: {e}")
    else:
        # Fallback sans feedparser — lecture XML brut
        try:
            import xml.etree.ElementTree as ET
            r = requests.get("https://feeds.reuters.com/reuters/businessNews",
                              timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:5]:
                    titre = (item.findtext("title") or "").lower()
                    bull  = sum(1 for w in BULL_WORDS if w in titre)
                    bear  = sum(1 for w in BEAR_WORDS if w in titre)
                    scores.append(max(-1.0, min(1.0, (bull - bear) * 0.25)))
        except Exception as e:
            logger.debug(f"Fallback RSS: {e}")

    if not scores:
        return 0.0
    return max(-1.0, min(1.0, sum(scores) / len(scores)))


def compute_decision() -> Tuple[str, float, Dict]:
    """
    Calcule la décision finale en agrégeant les 3 scores.
    CORRIGÉ : pondération plus rigoureuse, confiance réaliste.
    """
    logger.info("  Calcul des scores...")

    s_tech  = technical_score("^STOXX50E")
    logger.info(f"  Score technique : {s_tech:+.3f}")

    s_macro = macro_score()
    logger.info(f"  Score macro     : {s_macro:+.3f}")

    s_news  = news_score()
    logger.info(f"  Score news      : {s_news:+.3f}")

    # Pondération : technique 40%, macro 40%, news 20%
    total   = s_tech * 0.40 + s_macro * 0.40 + s_news * 0.20

    if total >= 0.35:     decision = "ACHETER"
    elif total <= -0.35:  decision = "VENDRE"
    else:                 decision = "ATTENDRE"

    # Confiance entre 40% et 95%
    confiance = min(95.0, max(40.0, abs(total) * 70 + 40))

    return decision, confiance, {
        "technique": round(s_tech, 3),
        "macro":     round(s_macro, 3),
        "news":      round(s_news, 3),
        "total":     round(total, 3),
    }


def get_indices_data() -> List[Dict]:
    """
    Récupère les données des indices BCE en temps réel.
    CORRIGÉ : gestion robuste du MultiIndex yfinance.
    """
    result = []
    if not YF_OK:
        return result

    symbols = list(BCE_INDICES_MAP.keys())
    try:
        raw = yf.download(
            symbols if len(symbols) > 1 else symbols[0],
            period="5d", interval="1d",
            progress=False, auto_adjust=True,
            group_by="ticker" if len(symbols) > 1 else None,
            timeout=15
        )
        if raw is None or raw.empty:
            return result

        for sym in symbols:
            try:
                # Gestion MultiIndex
                if len(symbols) > 1 and isinstance(raw.columns, pd.MultiIndex):
                    if sym not in raw.columns.get_level_values(0):
                        continue
                    df_s = raw[sym]
                else:
                    df_s = raw

                close = float(df_s["Close"].dropna().iloc[-1])
                prev  = float(df_s["Close"].dropna().iloc[-2]) if len(df_s) > 1 else close
                chg   = (close - prev) / prev * 100 if prev else 0.0
                hi    = float(df_s["High"].dropna().iloc[-1])
                lo    = float(df_s["Low"].dropna().iloc[-1])
                vol   = int(df_s["Volume"].dropna().iloc[-1]) if "Volume" in df_s.columns else 0

                result.append({
                    "symbol":  sym,
                    "nom":     BCE_INDICES_MAP[sym],
                    "prix":    round(close, 4),
                    "var_pct": round(chg, 3),
                    "haut":    round(hi, 4),
                    "bas":     round(lo, 4),
                    "volume":  vol,
                })
            except Exception:
                result.append({
                    "symbol": sym,
                    "nom":    BCE_INDICES_MAP[sym],
                    "prix":   0, "var_pct": 0,
                    "erreur": "données indisponibles",
                })
    except Exception as e:
        logger.warning(f"get_indices_data: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# §3  GÉNÉRATION DASHBOARD HTML — VERSION CORRIGÉE ET ENRICHIE
#     (remplace la version basique du code original)
# ══════════════════════════════════════════════════════════════════════════════

def generate_dashboard(
    decision: str = None,
    confiance: float = None,
    scores: Dict = None,
    indices: List[Dict] = None,
    rapport_bce: Dict = None,
) -> str:
    """
    Génère un dashboard HTML complet avec design Apple dark mode.
    CORRIGÉ et ENRICHI : design professionnel, données réelles, signaux BCE.
    """
    if decision is None:
        decision, confiance, scores = compute_decision()
    if indices is None:
        indices = get_indices_data()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Couleurs décision
    DEC_COLORS = {"ACHETER": "#30d158", "VENDRE": "#ff453a", "ATTENDRE": "#ff9f0a"}
    dec_color  = DEC_COLORS.get(decision, "#636366")
    dec_icon   = {"ACHETER": "🚀", "VENDRE": "⬇", "ATTENDRE": "⏸️"}.get(decision, "—")

    # Barre de confiance
    conf_w = confiance or 50
    conf_c = "#30d158" if conf_w > 65 else "#ff9f0a" if conf_w > 50 else "#ff453a"

    # Score bars
    def score_bar(val: float, label: str, ponderation: str) -> str:
        pct  = (val + 1) / 2 * 100  # -1..+1 → 0..100
        c    = "#30d158" if val > 0.15 else "#ff453a" if val < -0.15 else "#ff9f0a"
        icon = "↑" if val > 0.15 else "↓" if val < -0.15 else "—"
        return f"""
        <div style="margin-bottom:14px">
          <div style="display:flex;justify-content:space-between;
          align-items:center;margin-bottom:6px">
            <div>
              <span style="font-size:14px;font-weight:600;color:#fff">{label}</span>
              <span style="font-size:11px;color:rgba(235,235,245,.4);
              margin-left:8px">{ponderation}</span>
            </div>
            <span style="font-size:18px;font-weight:700;color:{c}">{icon} {val:+.3f}</span>
          </div>
          <div style="background:#2c2c2e;border-radius:6px;height:8px;overflow:hidden">
            <div style="width:{pct:.0f}%;height:100%;background:{c};border-radius:6px;
            transition:width .8s ease"></div>
          </div>
        </div>"""

    scores_html = (
        score_bar(scores.get("technique", 0), "Score Technique",  "40% — RSI · MACD · EMA")
        + score_bar(scores.get("macro", 0),   "Score Macro",       "40% — BCE · VIX · Euribor")
        + score_bar(scores.get("news", 0),    "Score Actualités",  "20% — RSS · Sentiment")
    ) if scores else ""

    # Tableau des indices
    def ind_row(d: Dict) -> str:
        v  = d.get("var_pct", 0)
        cc = "#30d158" if v > 0 else "#ff453a" if v < 0 else "#636366"
        ic = "▲" if v > 0 else "▼" if v < 0 else "─"
        return f"""
        <tr style="border-bottom:.5px solid #2c2c2e">
          <td style="padding:11px 10px;font-weight:600">{d.get('nom', d.get('symbol',''))}</td>
          <td style="padding:11px 10px;font-variant-numeric:tabular-nums">
            {d.get('prix', 0):,.4f}</td>
          <td style="padding:11px 10px;color:{cc};font-weight:600">
            {ic} {abs(v):.2f}%</td>
          <td style="padding:11px 10px;font-size:12px;color:rgba(235,235,245,.4)">
            H:{d.get('haut',0):,.2f} / B:{d.get('bas',0):,.2f}</td>
        </tr>"""

    indices_html = "".join(ind_row(d) for d in indices) if indices else \
        "<tr><td colspan='4' style='padding:16px;color:#636366;text-align:center'>Données indisponibles</td></tr>"

    # Section BCE (si rapport disponible)
    bce_section = ""
    if rapport_bce and "tendances_bce" in rapport_bce:
        t   = rapport_bce["tendances_bce"]
        pr  = t.get("probabilites", {})
        pc  = "#30d158" if t.get("prochain_mvt_prevu","") == "BAISSE" else \
               "#ff453a" if t.get("prochain_mvt_prevu","") == "HAUSSE" else "#ff9f0a"
        cal = rapport_bce.get("prochaine_reunion", {})

        proba_b = pr.get('baisse_pct', 33)
        proba_s = pr.get('stable_pct', 34)
        proba_h = pr.get('hausse_pct', 33)

        bce_section = f"""
        <div style="background:#1c1c1e;border-radius:16px;padding:20px;
        margin-bottom:16px;border:.5px solid #38383a">
          <div style="font-size:12px;color:rgba(235,235,245,.4);text-transform:uppercase;
          letter-spacing:.8px;margin-bottom:12px">Intelligence BCE</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
            <div>
              <div style="font-size:11px;color:rgba(235,235,245,.4);margin-bottom:3px">
                Phase du cycle</div>
              <div style="font-size:16px;font-weight:700;color:#64d2ff">
                {t.get('phase_cycle','N/A')}</div>
            </div>
            <div>
              <div style="font-size:11px;color:rgba(235,235,245,.4);margin-bottom:3px">
                Prochaine décision</div>
              <div style="font-size:16px;font-weight:700;color:{pc}">
                {t.get('prochain_mvt_prevu','?')} ({t.get('bps_prevu',0):+d}bps)</div>
            </div>
            <div>
              <div style="font-size:11px;color:rgba(235,235,245,.4);margin-bottom:3px">
                Taux de dépôt BCE</div>
              <div style="font-size:16px;font-weight:700">
                {t.get('taux_actuel',0):.2f}%</div>
            </div>
            <div>
              <div style="font-size:11px;color:rgba(235,235,245,.4);margin-bottom:3px">
                Inflation HICP</div>
              <div style="font-size:16px;font-weight:700">
                {t.get('inflation_hicp',0):.1f}%</div>
            </div>
          </div>
          <div style="font-size:11px;color:rgba(235,235,245,.4);margin-bottom:6px">
            Probabilités prochaine décision</div>
          <div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin-bottom:6px">
            <div style="width:{proba_b:.0f}%;background:#30d158"></div>
            <div style="width:{proba_s:.0f}%;background:#ff9f0a"></div>
            <div style="width:{proba_h:.0f}%;background:#ff453a"></div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:11px">
            <span style="color:#30d158">↓ Baisse {proba_b:.0f}%</span>
            <span style="color:#ff9f0a">— Stable {proba_s:.0f}%</span>
            <span style="color:#ff453a">↑ Hausse {proba_h:.0f}%</span>
          </div>
          {"<div style='margin-top:12px;padding-top:12px;border-top:.5px solid #2c2c2e'>" +
           "<span style='font-size:11px;color:rgba(235,235,245,.4)'>Prochaine réunion : </span>" +
           f"<span style='font-size:13px;font-weight:600;color:#0a84ff'>{cal.get('date_reunion','')}</span>" +
           "</div>" if cal else ""}
        </div>"""

    # HTML final
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#000000">
<meta name="description" content="Market Oracle BCE — Dashboard de décision temps réel">
<title>Market Oracle BCE — Dashboard</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent }}
body {{
  font-family: -apple-system, "SF Pro Display", Helvetica, sans-serif;
  background: #000; color: #fff; min-height: 100vh;
  -webkit-font-smoothing: antialiased;
}}
.container {{ max-width: 800px; margin: 0 auto; padding: 20px 16px 40px; }}
.header {{
  padding: 16px 0 24px;
  border-bottom: .5px solid #2c2c2e;
  margin-bottom: 20px;
}}
.header-title {{ font-size: 24px; font-weight: 700; letter-spacing: -.5px }}
.header-sub {{
  font-size: 12px; color: rgba(235,235,245,.4); margin-top: 4px;
  display: flex; align-items: center; gap: 8px;
}}
.live-dot {{
  width: 6px; height: 6px; border-radius: 50%;
  background: #30d158; display: inline-block;
  animation: pulse 2s ease-in-out infinite;
}}
@keyframes pulse {{
  0%,100% {{ opacity:1 }} 50% {{ opacity:.3 }}
}}
.decision-card {{
  background: linear-gradient(135deg, #1c1c1e, #2c2c2e);
  border-radius: 18px; padding: 24px;
  border: .5px solid {dec_color}44;
  border-left: 4px solid {dec_color};
  margin-bottom: 16px;
}}
.decision-label {{
  font-size: 12px; color: rgba(235,235,245,.4);
  text-transform: uppercase; letter-spacing: .8px; margin-bottom: 8px;
}}
.decision-value {{
  font-size: 42px; font-weight: 800;
  color: {dec_color}; letter-spacing: -1px;
}}
.decision-sub {{ font-size: 14px; color: rgba(235,235,245,.6); margin-top: 6px }}
.conf-wrap {{ margin-top: 16px }}
.conf-label {{
  font-size: 11px; color: rgba(235,235,245,.4);
  text-transform: uppercase; letter-spacing: .5px;
  margin-bottom: 6px; display: flex; justify-content: space-between;
}}
.conf-bar-bg {{
  background: #2c2c2e; border-radius: 6px; height: 10px; overflow: hidden;
}}
.conf-bar-fill {{
  width: {conf_w:.0f}%; height: 100%;
  background: {conf_c}; border-radius: 6px;
}}
.card {{
  background: #1c1c1e; border-radius: 16px;
  border: .5px solid #38383a; margin-bottom: 16px; overflow: hidden;
}}
.card-title {{
  font-size: 12px; color: rgba(235,235,245,.4);
  text-transform: uppercase; letter-spacing: .8px;
  padding: 16px 18px 12px; border-bottom: .5px solid #2c2c2e;
}}
.card-body {{ padding: 16px 18px }}
.indices-table {{
  width: 100%; border-collapse: collapse; font-size: 13px;
}}
.indices-table th {{
  text-align: left; padding: 8px 10px; font-size: 10px;
  color: rgba(235,235,245,.4); text-transform: uppercase;
  letter-spacing: .5px; border-bottom: .5px solid #2c2c2e;
}}
.footer {{
  text-align: center; padding: 20px 0 0;
  font-size: 11px; color: rgba(235,235,245,.25);
  border-top: .5px solid #2c2c2e; margin-top: 8px;
}}
@media (max-width: 480px) {{
  .decision-value {{ font-size: 32px }}
  .container {{ padding: 14px 12px 32px }}
}}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <div class="header-title">📈 Market Oracle BCE</div>
    <div class="header-sub">
      <span class="live-dot"></span>
      <span id="ts">{ts}</span>
      &nbsp;·&nbsp; Décision algorithmique temps réel
    </div>
  </div>

  <!-- DÉCISION PRINCIPALE -->
  <div class="decision-card">
    <div class="decision-label">Décision algorithmique</div>
    <div class="decision-value">{dec_icon} {decision}</div>
    <div class="decision-sub">
      Score composite : <strong>{scores.get('total', 0):+.3f}</strong>
      &nbsp;·&nbsp; Confiance : <strong>{confiance:.1f}%</strong>
    </div>
    <div class="conf-wrap">
      <div class="conf-label">
        <span>Niveau de confiance</span>
        <span style="color:{conf_c};font-weight:700">{confiance:.0f}%</span>
      </div>
      <div class="conf-bar-bg">
        <div class="conf-bar-fill"></div>
      </div>
    </div>
  </div>

  <!-- SCORES DÉTAILLÉS -->
  <div class="card">
    <div class="card-title">Scores par composante</div>
    <div class="card-body">{scores_html}</div>
  </div>

  <!-- INTELLIGENCE BCE -->
  {bce_section}

  <!-- INDICES ZONE EURO -->
  <div class="card">
    <div class="card-title">Indices Zone Euro — Temps réel</div>
    <table class="indices-table">
      <thead>
        <tr>
          <th>Indice</th>
          <th>Prix</th>
          <th>Variation</th>
          <th>Haut / Bas</th>
        </tr>
      </thead>
      <tbody>{indices_html}</tbody>
    </table>
  </div>

  <div class="footer">
    Sources : Yahoo Finance · BCE SDMX · FRED · RSS Financiers<br>
    ⚠️ Données à titre indicatif uniquement — Pas de conseil financier<br>
    Généré le {ts}
  </div>

</div>

<script>
// Mise à jour du timestamp en local
const el = document.getElementById('ts');
if (el) el.textContent = new Date().toLocaleString('fr-FR');
</script>
</body>
</html>"""

    path = Path("dashboard_oracle.html")
    path.write_text(html, encoding="utf-8")
    logger.info(f"Dashboard HTML généré : {path.resolve()} ({path.stat().st_size//1024} KB)")
    return html


# ══════════════════════════════════════════════════════════════════════════════
# §4  COMMANDES DU PROJET
# ══════════════════════════════════════════════════════════════════════════════

def show_commands() -> None:
    """
    Affiche toutes les commandes pour utiliser le projet.
    Version complète du code original.
    """
    print("""
╔══════════════════════════════════════════════════════════════════════════╗
║  COMMANDES COMPLÈTES — Market Oracle BCE · monbotv3                    ║
╚══════════════════════════════════════════════════════════════════════════╝

  ── INSTALLATION (une seule fois) ───────────────────────────────────────
  pip3 install yfinance requests pandas numpy feedparser streamlit plotly

  ── ORCHESTRATEUR (ce fichier) ──────────────────────────────────────────
  python3 orchestrator.py                   # Rapport + dashboard HTML
  python3 orchestrator.py --decision        # Signal d'arbitrage seul
  python3 orchestrator.py --html --open     # Dashboard + ouvrir Safari
  python3 orchestrator.py --check           # Vérifier l'état du projet
  python3 orchestrator.py --commands        # Cette aide

  ── MOTEUR BCE ──────────────────────────────────────────────────────────
  python3 bce_engine.py                     # Rapport BCE complet
  python3 bce_engine.py --tendances         # Tendances + probabilités
  python3 bce_engine.py --impact            # Impact sur les cours
  python3 bce_engine.py --calendrier        # Prochaines réunions BCE
  python3 bce_engine.py --db-init          # Initialiser la base SQLite
  python3 bce_engine.py --db-status        # État de la base de données

  ── DASHBOARD STREAMLIT (interface web locale) ──────────────────────────
  python3 -m streamlit run bce_dashboard.py          # Dashboard BCE
  python3 -m streamlit run streamlit_app.py          # Dashboard général

  ── BOT V3 (analyse complète) ───────────────────────────────────────────
  python3 bot_v3.py --mode demo             # Démo complète
  python3 bot_v3.py --mode analyse          # Analyse watchlist
  python3 bot_v3.py --mode screener         # Scanner le marché
  python3 bot_v3.py --mode backtest         # Backtest historique
  python3 bot_v3.py --mode rapport          # Rapport HTML iOS

  ── APIs DE DONNÉES ─────────────────────────────────────────────────────
  python3 api_manager.py --check            # Tester les APIs
  python3 api_manager.py --price SPY,QQQ,BTC-USD,GC=F
  python3 api_manager.py --macro            # Données macro
  python3 api_manager.py --crypto           # Marché crypto
  python3 api_manager.py --snap > snapshot.json

  ── BASE DE DONNÉES ─────────────────────────────────────────────────────
  python3 market_db.py --init               # Initialiser
  python3 market_db.py --populate SPY,QQQ,BTC-USD
  python3 market_db.py --watch SPY,BTC-USD  # Feed temps réel
  python3 market_db.py --export SPY         # Export CSV

  ── CORRECTIONS AUTOMATIQUES ────────────────────────────────────────────
  python3 corrections.py --fix all          # Corriger tous les bugs
  python3 corrections.py --check           # Vérifier sans modifier

  ── GÉNÉRATION DASHBOARDS ───────────────────────────────────────────────
  python3 generate_dashboard.py --open      # Dashboard HTML live
  python3 generate_dashboard.py --watch     # Auto-refresh 60s

  ── ANALYSE QUANTITATIVE ────────────────────────────────────────────────
  python3 market_oracle_extension.py --symbol SPY
  python3 market_oracle_extension.py --watchlist SPY,QQQ,AAPL,BTC-USD

  ── SAUVEGARDE ──────────────────────────────────────────────────────────
  python3 api_manager.py --snap > snapshot_$(date +%Y%m%d).json
  tar -czf backup_$(date +%Y%m%d).tar.gz *.py *.json data/ logs/

  ── CRON (auto-refresh toutes les heures) ───────────────────────────────
  python3 orchestrator.py --cron
  crontab -l  # Vérifier
""")


def check_project() -> None:
    """Vérifie l'état complet du projet."""
    print("\n🩺  ÉTAT DU PROJET\n" + "═"*55)
    project_dir = Path(__file__).parent

    # Fichiers attendus
    FICHIERS = {
        "orchestrator.py":           "Orchestrateur principal",
        "bce_engine.py":             "Moteur BCE (tendances + impact)",
        "bce_dashboard.py":          "Dashboard Streamlit BCE",
        "install_bce.py":            "Script d'installation",
        "bot_v3.py":                 "Bot trading v3",
        "api_manager.py":            "APIs de données",
        "market_db.py":              "Base de données marché",
        "streamlit_app.py":          "Dashboard Streamlit général",
        "market_oracle_extension.py":"Module analyse quant",
        "corrections.py":            "Correcteur automatique",
        "generate_dashboard.py":     "Générateur HTML",
        "features_engine.py":        "Moteur de features ML",
    }

    print(f"\n  {'Fichier':35s} {'État':12s} {'Rôle'}")
    print(f"  {'─'*70}")
    for nom, role in FICHIERS.items():
        fp = project_dir / nom
        if fp.exists():
            ok, _ = __import__("subprocess").run(
                [sys.executable, "-m", "py_compile", str(fp)],
                capture_output=True
            ).returncode == 0, None
            status = "✅ OK" if ok else "❌ Erreur"
        else:
            status = "⚠️  absent"
        print(f"  {nom:35s} {status:12s} {role}")

    # Dépendances
    print(f"\n  DÉPENDANCES PYTHON")
    print(f"  {'─'*40}")
    DEPS = {
        "yfinance":   "Yahoo Finance",
        "requests":   "Appels API",
        "pandas":     "Données",
        "numpy":      "Calculs",
        "streamlit":  "Dashboard web",
        "plotly":     "Graphiques",
        "feedparser": "RSS Actualités",
        "scipy":      "Statistiques",
    }
    for dep, desc in DEPS.items():
        try:
            __import__(dep)
            print(f"  ✅ {dep:15s} {desc}")
        except ImportError:
            print(f"  ❌ {dep:15s} MANQUANT → pip3 install {dep}")

    # Base de données
    db_path = project_dir / "data" / "bce_intelligence.db"
    print(f"\n  BASE DE DONNÉES BCE")
    if db_path.exists():
        sz = db_path.stat().st_size / 1024
        print(f"  ✅ bce_intelligence.db ({sz:.1f} KB)")
    else:
        print("  ⚠️  Base non initialisée → python3 bce_engine.py --db-init")
    print()


def install_cron() -> None:
    """Installe l'auto-refresh via cron (toutes les heures)."""
    script = str(Path(__file__).resolve())
    log    = str(Path("logs/orchestrator.log").resolve())
    cmd    = f"0 * * * * cd {Path(__file__).parent} && /usr/bin/python3 {script} --html >> {log} 2>&1"
    result = subprocess.run(
        f'(crontab -l 2>/dev/null | grep -v orchestrator; echo "{cmd}") | crontab -',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✅ Cron installé : {cmd}")
        print("  Vérifier avec : crontab -l")
    else:
        print(f"  ❌ Erreur cron : {result.stderr}")


# ══════════════════════════════════════════════════════════════════════════════
# §5  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="orchestrator.py — Market Oracle BCE Ultimate",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--decision", action="store_true",
                         help="Afficher seulement le signal de décision")
    parser.add_argument("--html",     action="store_true",
                         help="Générer le dashboard HTML")
    parser.add_argument("--open",     action="store_true",
                         help="Ouvrir le dashboard dans Safari après génération")
    parser.add_argument("--commands", action="store_true",
                         help="Afficher toutes les commandes du projet")
    parser.add_argument("--check",    action="store_true",
                         help="Vérifier l'état du projet")
    parser.add_argument("--fix",      action="store_true",
                         help="Corriger automatiquement les erreurs connues")
    parser.add_argument("--cron",     action="store_true",
                         help="Installer le cron auto-refresh (toutes les heures)")
    args = parser.parse_args()

    print("""
╔════════════════════════════════════════════════════════╗
║  Market Oracle BCE — Orchestrateur                    ║
║  Décision · Dashboard · Indices Zone Euro             ║
╚════════════════════════════════════════════════════════╝
""")

    if args.commands:
        show_commands(); return
    if args.check:
        check_project(); return
    if args.cron:
        install_cron(); return
    if args.fix:
        fixed = fix_syntax_errors()
        print(f"  Fichiers corrigés : {fixed if fixed else 'aucun (déjà OK)'}\n")
        return

    # Appliquer corrections silencieusement
    fix_syntax_errors()

    # Générer le rapport BCE (si moteur disponible)
    rapport_bce = None
    if ENGINE_OK:
        try:
            logger.info("Génération rapport BCE...")
            rapport_bce = RapportBCE().generer()
        except Exception as e:
            logger.warning(f"Rapport BCE: {e}")

    # Calculer la décision
    logger.info("Calcul de la décision...")
    dec, conf, scores = compute_decision()

    print(f"\n  ┌─────────────────────────────────────────┐")
    print(f"  │  DÉCISION : {dec:8s}  Confiance : {conf:5.1f}%  │")
    print(f"  └─────────────────────────────────────────┘")
    print(f"\n  Score technique  : {scores.get('technique',0):+.3f}  (40%)")
    print(f"  Score macro      : {scores.get('macro',0):+.3f}  (40%)")
    print(f"  Score actualités : {scores.get('news',0):+.3f}  (20%)")
    print(f"  ─────────────────────────────────────")
    print(f"  Score total      : {scores.get('total',0):+.3f}")

    if args.decision:
        return

    # Données indices
    logger.info("Récupération des indices...")
    indices = get_indices_data()
    if indices:
        print(f"\n  INDICES ZONE EURO :")
        for d in indices:
            v  = d.get("var_pct", 0)
            ic = "▲" if v > 0 else "▼" if v < 0 else "─"
            cc = "+" if v > 0 else ""
            print(f"  {d.get('nom',''):18s} {d.get('prix',0):10.4f}  {ic} {cc}{v:.2f}%")

    # Dashboard HTML
    if args.html or not args.decision:
        logger.info("Génération du dashboard HTML...")
        generate_dashboard(dec, conf, scores, indices, rapport_bce)
        print(f"\n  ✅  Dashboard : {Path('dashboard_oracle.html').resolve()}")
        if args.open:
            subprocess.run(["open", "dashboard_oracle.html"], check=False)
            print("  🌐  Ouvert dans Safari")

    # Sauvegarder le rapport JSON
    rapport_final = {
        "timestamp":  datetime.now().isoformat(),
        "decision":   dec,
        "confiance":  conf,
        "scores":     scores,
        "indices":    indices,
        "bce":        rapport_bce.get("tendances_bce") if rapport_bce else None,
    }
    Path("logs/rapport_latest.json").write_text(
        json.dumps(rapport_final, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"  📄  Rapport JSON : logs/rapport_latest.json")
    print()


if __name__ == "__main__":
    main()
