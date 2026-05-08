#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  THE ZEDICUS v2 — Dashboard BCE · 8 Modules · Pondération Dynamique         ║
║                                                                              ║
║  Architecture :                                                              ║
║    8 modules de scoring indépendants                                         ║
║    Pondération dynamique basée sur la fréquence des sujets dans la presse    ║
║    → le module le plus cité = poids le plus élevé                           ║
║                                                                              ║
║  COMMANDE : python3 -m streamlit run zedicus_v2.py                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import sys, os, time, math, re, warnings
from datetime   import datetime, date, timedelta
from pathlib    import Path
from typing     import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from io         import StringIO
from collections import Counter

warnings.filterwarnings("ignore")

try:
    import streamlit as st
except ImportError:
    print("pip install streamlit"); sys.exit(1)

try:
    import plotly.graph_objects as go
    import plotly.express       as px
    from   plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

try:
    import pandas as pd
    import numpy  as np
except ImportError:
    st.error("pip install pandas numpy"); st.stop()

try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False

try:
    import requests
    REQ_OK = True
except ImportError:
    REQ_OK = False

try:
    import feedparser
    FP_OK = True
except ImportError:
    FP_OK = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
try:
    from bce_engine import AnalyseurTendancesBCE, RapportBCE
    ENGINE_OK = True
except ImportError:
    ENGINE_OK = False

try:
    from orchestrator import compute_decision
    ORCH_OK = True
except ImportError:
    ORCH_OK = False


# ══════════════════════════════════════════════════════════════════════════════
# §1  DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="THE ZEDICUS v2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

G  = "#FFD700"; O  = "#F28C28"; P  = "#8B00FF"
GR = "#00FF87"; RD = "#FF3B5C"; BL = "#00C2FF"
DK = "#080808"; C1 = "#101010"; C2 = "#181818"; SP = "#252525"

# Module color palette (8 modules)
MOD_COLORS = [GR, BL, O, "#FF6B6B", "#A855F7", G, "#06B6D4", "#F97316"]

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
*{{box-sizing:border-box}}
html,body,.stApp{{background:{DK}!important;font-family:'Space Grotesk',sans-serif;color:#E8E8E8}}
.stApp>header{{background:rgba(8,8,8,.98)!important;border-bottom:1px solid #1a1a1a;backdrop-filter:blur(24px)}}
[data-testid="stSidebar"]{{background:{C1}!important;border-right:1px solid {SP}}}
[data-testid="stSidebar"] *{{color:#bbb!important}}
.stTabs [data-baseweb="tab-list"]{{background:{C1}!important;border-radius:12px;padding:4px;gap:2px;border:1px solid {SP}}}
.stTabs [data-baseweb="tab"]{{border-radius:8px!important;color:#555!important;font-weight:600!important;font-size:12px!important;padding:6px 14px!important;font-family:'Space Grotesk',sans-serif!important;transition:all .2s}}
.stTabs [aria-selected="true"]{{background:{C2}!important;color:#fff!important;border:.5px solid {SP}!important}}
[data-testid="stMetric"]{{background:{C1}!important;border:1px solid {SP}!important;border-radius:12px!important;padding:14px!important}}
[data-testid="stMetricLabel"]{{color:#444!important;font-size:10px!important;text-transform:uppercase;letter-spacing:.8px;font-weight:600!important}}
[data-testid="stMetricValue"]{{color:{G}!important;font-weight:700!important;font-family:'JetBrains Mono',monospace!important}}
[data-testid="stMetricDelta"]{{font-family:'JetBrains Mono',monospace!important;font-size:11px!important}}
.stButton>button{{background:{C2}!important;color:#ddd!important;border:1px solid {SP}!important;border-radius:8px!important;padding:8px 20px!important;font-weight:600!important;font-family:'Space Grotesk',sans-serif!important;transition:all .2s!important}}
.stButton>button:hover{{background:{SP}!important;color:#fff!important;border-color:{G}66!important}}
.stSelectbox>div>div,.stMultiSelect>div>div,.stNumberInput>div>div,.stTextInput>div>div{{background:{C1}!important;border-color:{SP}!important;color:#ddd!important;border-radius:8px!important}}
div[data-testid="stExpander"]{{background:{C1}!important;border:1px solid {SP}!important;border-radius:12px!important}}
.streamlit-expanderHeader{{color:#bbb!important;font-weight:600!important}}
::-webkit-scrollbar{{width:4px}} ::-webkit-scrollbar-thumb{{background:{SP};border-radius:3px}}
p,li,label,span{{color:#bbb!important}}
h1,h2,h3,h4{{color:#eee!important;font-weight:700!important}}
hr{{border:none;height:1px;background:{SP};margin:16px 0}}

/* Custom components */
.z-card{{background:{C1};border:1px solid {SP};border-radius:12px;padding:16px 18px;margin-bottom:10px}}
.z-module{{background:{C1};border:1px solid {SP};border-radius:12px;padding:14px;margin-bottom:8px}}
.z-ticker{{background:{C1};border:1px solid {SP};border-radius:10px;padding:10px 12px;text-align:center;margin-bottom:8px}}
.z-news{{background:{C1};border-radius:10px;padding:11px 14px;margin-bottom:7px;border-left:2px solid {O};border:.5px solid {SP}}}
.z-mono{{font-family:'JetBrains Mono',monospace}}
.z-source-tag{{display:inline-block;font-size:10px;font-weight:600;padding:2px 8px;border-radius:6px;background:{C2};color:#666;border:.5px solid {SP};margin-right:4px}}
.z-badge{{display:inline-block;font-size:11px;font-weight:700;padding:3px 10px;border-radius:20px;letter-spacing:.2px;font-family:'JetBrains Mono',monospace}}
.stDataFrame{{font-size:.82em!important}}
.z-weight-bar{{border-radius:4px;height:6px;overflow:hidden;margin:4px 0}}
</style>
""", unsafe_allow_html=True)

_PL = dict(
    template="plotly_dark", paper_bgcolor=DK, plot_bgcolor=C1,
    margin=dict(l=0,r=0,t=38,b=0),
    font=dict(family="JetBrains Mono,monospace", color="#555", size=11),
    hovermode="x unified",
    hoverlabel=dict(bgcolor=C2, bordercolor=SP, font_color="#ddd"),
    xaxis_rangeslider_visible=False,
    legend=dict(orientation="h", y=1.02, font_size=11),
    xaxis=dict(gridcolor=SP, gridwidth=.5),
    yaxis=dict(gridcolor=SP, gridwidth=.5),
)

def _cc(v): return GR if v>0 else RD if v<0 else "#555"
def _safe(v, d=0.0):
    try:
        f=float(v); return d if math.isnan(f) or math.isinf(f) else f
    except: return d
def _rgba(h, a):
    h=h.lstrip("#"); r,g,b=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
    return f"rgba({r},{g},{b},{a})"
def _badge(txt, color):
    return (f'<span class="z-badge" style="background:{_rgba(color.lstrip("#"),0.15)};'
            f'color:{color};border:.5px solid {_rgba(color.lstrip("#"),0.3)}">{txt}</span>')


# ══════════════════════════════════════════════════════════════════════════════
# §2  DÉFINITION DES 8 MODULES
# ══════════════════════════════════════════════════════════════════════════════

MODULES = {
    "macro":         {"label":"📊 Macro",          "color":MOD_COLORS[0], "min_w":0.05, "max_w":0.35,
                       "keywords":["pib","gdp","inflation","chômage","unemployment","croissance","recession",
                                    "cpi","pce","dette","deficit","ipc","hicp","croissance","bilan"]},
    "monetaire":     {"label":"🏦 Pol. Monétaire",  "color":MOD_COLORS[1], "min_w":0.05, "max_w":0.35,
                       "keywords":["bce","ecb","fed","taux","rate","pivot","lagarde","powell","qe","qt",
                                    "assouplissement","resserrement","banque centrale","monetary","euribor",
                                    "hiking","cutting","baisse taux","hausse taux","forward guidance"]},
    "obligations":   {"label":"💵 Obligations",     "color":MOD_COLORS[2], "min_w":0.05, "max_w":0.25,
                       "keywords":["bond","obligation","treasury","bund","oat","spread","yield","courbe",
                                    "inversion","t10y","t2y","taux 10","taux 2","dette souveraine","crédit",
                                    "investment grade","high yield","btp","gilt"]},
    "saisonnalite":  {"label":"🗓️ Saisonnalité",    "color":MOD_COLORS[3], "min_w":0.03, "max_w":0.15,
                       "keywords":["saisonnalité","seasonal","janvier","effet","calendrier","trimestre",
                                    "q1","q2","q3","q4","fin d'année","début d'année","dividende",
                                    "reporting","résultats trimestriels","window dressing"]},
    "geopolitique":  {"label":"🌍 Géopolitique",    "color":MOD_COLORS[4], "min_w":0.05, "max_w":0.25,
                       "keywords":["guerre","war","conflit","ukraine","russie","chine","china","iran",
                                    "moyen-orient","middle east","sanctions","tariff","tarif","trade war",
                                    "election","geopolitical","opep","opec","énergie","energy","pétrole oil"]},
    "technique":     {"label":"📈 Graphiques/TA",   "color":MOD_COLORS[5], "min_w":0.15, "max_w":0.40,
                       "keywords":["rsi","macd","support","resistance","breakout","tendance","trend",
                                    "bollinger","ema","sma","retracement","fibonacci","chartisme",
                                    "momentum","volume","survente","surachat","signal technique"]},
    "volumes":       {"label":"📦 Volumes Trades",  "color":MOD_COLORS[6], "min_w":0.03, "max_w":0.15,
                       "keywords":["volume","liquidité","liquidity","flux","flow","institutionnel",
                                    "retail","achat","vente","order flow","carnet d'ordres",
                                    "open interest","contrats","futures","put/call ratio"]},
    "hedge_funds":   {"label":"🐋 Hedges Funds",    "color":MOD_COLORS[7], "min_w":0.03, "max_w":0.15,
                       "keywords":["hedge fund","cot","commitment of traders","speculative","non commercial",
                                    "positioning","short squeeze","gamma squeeze","dark pool","smart money",
                                    "net long","net short","whale","institutional","gros porteurs"]},
}


# ══════════════════════════════════════════════════════════════════════════════
# §3  SOURCES DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

RSS_SOURCES = {
    # Banques centrales officielles
    "BCE Officiel":        "https://www.ecb.europa.eu/rss/press.html",
    "Fed Reserve":         "https://www.federalreserve.gov/feeds/press_all.xml",
    "BNS":                 "https://www.snb.ch/en/rss/news",
    # Finance internationale
    "Reuters Finance":     "https://feeds.reuters.com/reuters/businessNews",
    "Bloomberg (proxy)":   "https://feeds.bloomberg.com/markets/news.rss",
    "FT Markets":          "https://www.ft.com/rss/home/europe",
    "Les Echos":           "https://www.lesechos.fr/feeds/rss/finance-marches.xml",
    "Le Monde Eco":        "https://www.lemonde.fr/economie/rss_full.xml",
    # Investissement / trading
    "Investing.com":       "https://www.investing.com/rss/news_301.rss",
    "Yahoo Finance":       "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR",
    # Géopolitique
    "Google News Géopol":  "https://news.google.com/rss/search?q=geopolitics+finance&hl=fr&gl=FR&ceid=FR:fr",
    "BBC Business":        "https://feeds.bbci.co.uk/news/business/rss.xml",
}

FRED_SERIES = {
    "FEDFUNDS":     "Fed Funds",
    "DGS10":        "T10Y US",
    "DGS2":         "T2Y US",
    "CPIAUCSL":     "CPI US",
    "UNRATE":       "Chômage US",
    "GDP":          "PIB US",
    "WALCL":        "Bilan Fed",
    "BAMLC0A0CM":   "Spread IG",
    "BAMLH0A0HYM2": "Spread HY",
    "DEXUSEU":      "USD/EUR",
}

UNIVERSE = {
    "^STOXX50E":"Euro Stoxx 50","^FCHI":"CAC 40","^GDAXI":"DAX 40",
    "^IBEX":"IBEX 35","^AEX":"AEX","^GSPC":"S&P 500","^IXIC":"Nasdaq",
    "EURUSD=X":"EUR/USD","EURGBP=X":"EUR/GBP","EURJPY=X":"EUR/JPY",
    "BZ=F":"Brent","NG=F":"Gaz","GC=F":"Or","SI=F":"Argent",
    "^VIX":"VIX","ZN=F":"T-Note 10Y Future","BTC-USD":"Bitcoin",
}

CFTC_PROXIES = {
    "EUR/USD (EURUSD=X)": {"sym":"EURUSD=X","desc":"Proxy via volume OI yfinance"},
    "S&P 500 (ES=F)":     {"sym":"ES=F",    "desc":"E-mini S&P positions"},
    "Or (GC=F)":          {"sym":"GC=F",    "desc":"Gold futures OI"},
    "VIX (^VIX)":         {"sym":"^VIX",    "desc":"Vol options positioning"},
}

SEASONAL_PATTERNS = {
    1:  {"biais":+0.5,  "note":"Effet janvier — rally traditionnel actions"},
    2:  {"biais":+0.2,  "note":"Reporting Q4 — saison des résultats"},
    3:  {"biais":-0.1,  "note":"Fin Q1 — prise de profits institutionnels"},
    4:  {"biais":+0.3,  "note":"Sell in May approche — dernier rally printemps"},
    5:  {"biais":-0.4,  "note":"Sell in May and Go Away — prudence"},
    6:  {"biais":-0.2,  "note":"Été — faibles volumes, volatilité"},
    7:  {"biais":-0.1,  "note":"Été — marchés calmes"},
    8:  {"biais":-0.3,  "note":"Août — mois de la volatilité estivale"},
    9:  {"biais":-0.5,  "note":"Septembre — pire mois historique S&P 500"},
    10: {"biais":+0.1,  "note":"Octobre — retour institutionnels, parfois crash"},
    11: {"biais":+0.6,  "note":"Novembre — meilleur mois historique actions"},
    12: {"biais":+0.5,  "note":"Décembre — Santa Claus Rally + window dressing"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §4  ACQUISITION — PARALLÈLE + CACHE AGRESSIF
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def fetch_all_articles() -> List[Dict]:
    """Charge tous les articles RSS depuis les 12 sources."""
    if not FP_OK:
        return []
    articles = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_fetch_rss, src, url): src
                for src, url in RSS_SOURCES.items()}
        for fut in as_completed(futs):
            try:
                arts = fut.result()
                articles.extend(arts)
            except Exception:
                pass
    # Déduplique par hash du titre
    seen, unique = set(), []
    for a in articles:
        h = hash(a["title"][:40])
        if h not in seen:
            seen.add(h); unique.append(a)
    # Trier par date descendant
    unique.sort(key=lambda x: x.get("date",""), reverse=True)
    return unique

def _fetch_rss(source: str, url: str) -> List[Dict]:
    try:
        feed = feedparser.parse(url)
        arts = []
        for e in feed.entries[:6]:
            t = (e.get("title","") or "").strip()
            if not t: continue
            arts.append({
                "title":  t[:120],
                "source": source,
                "link":   e.get("link","#"),
                "date":   e.get("published","")[:16],
                "text":   (t + " " + (e.get("summary","") or "")).lower(),
            })
        return arts
    except Exception:
        return []


@st.cache_data(ttl=600, show_spinner=False)
def compute_module_weights(articles: List[Dict]) -> Dict[str, float]:
    """
    ALGORITHME DE PONDÉRATION DYNAMIQUE DE FRANCK :
    - Compte la fréquence des mots-clés de chaque module dans la presse
    - Les sujets qui reviennent le plus = poids augmenté
    - Normalisation : somme des poids = 1.0
    - Chaque module reste dans son intervalle [min_w, max_w]
    """
    if not articles:
        return {k: 1/len(MODULES) for k in MODULES}

    full_corpus = " ".join(a["text"] for a in articles[:60])
    raw_counts  = {}

    for mod_id, mod in MODULES.items():
        count = sum(full_corpus.count(kw) for kw in mod["keywords"])
        raw_counts[mod_id] = max(count, 1)

    total = sum(raw_counts.values())

    # Distribution brute proportionnelle
    raw_weights = {k: v/total for k,v in raw_counts.items()}

    # Clip dans [min_w, max_w]
    clipped = {}
    for mod_id, mod in MODULES.items():
        clipped[mod_id] = max(mod["min_w"], min(mod["max_w"], raw_weights[mod_id]))

    # Renormalise pour que sum = 1.0
    total_c = sum(clipped.values())
    return {k: round(v/total_c, 4) for k,v in clipped.items()}


@st.cache_data(ttl=600, show_spinner=False)
def module_news_score(articles: List[Dict], mod_id: str) -> Tuple[float, List[Dict]]:
    """Score sentiment [-1,+1] + articles pertinents pour un module."""
    kws  = MODULES[mod_id]["keywords"]
    BULL = ["hausse","croissance","positif","rally","record","achat","better","rise","up",
             "growth","optimism","beat","baisse taux","assouplissement","stimulus","strong"]
    BEAR = ["baisse","récession","crise","chute","déficit","selloff","crash","miss","down",
             "worse","recession","crisis","hawkish","resserrement","tension","conflict","weak"]

    pertinent = [a for a in articles if any(k in a["text"] for k in kws)]
    if not pertinent:
        return 0.0, []

    scores = []
    for a in pertinent[:15]:
        tl = a["text"]
        b  = sum(1 for w in BULL if w in tl)
        br = sum(1 for w in BEAR if w in tl)
        if b > br:   scores.append(min(1.0,  (b-br)*0.3))
        elif br > b: scores.append(max(-1.0, -(br-b)*0.3))
        else:        scores.append(0.0)

    avg = sum(scores)/len(scores) if scores else 0.0
    return round(max(-1.0, min(1.0, avg)), 3), pertinent[:6]


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred_all() -> Dict:
    if not REQ_OK:
        return {}
    result = {}
    def _get(sid, lbl):
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=10)
            if r.status_code == 200:
                df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
                df.columns = ["date","value"]
                df["value"] = pd.to_numeric(df["value"], errors="coerce")
                s = df.dropna().set_index("date")["value"].tail(30)
                if not s.empty:
                    last=float(s.iloc[-1]); prev=float(s.iloc[-2]) if len(s)>1 else last
                    return lbl, {"value":round(last,4),"change":round(last-prev,4),"history":s.tolist()}
        except Exception:
            pass
        return lbl, None

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_get, sid, lbl) for sid,lbl in FRED_SERIES.items()]
        for fut in as_completed(futs):
            try:
                lbl, d = fut.result()
                if d: result[lbl] = d
            except Exception:
                pass

    # Spread 10-2
    t10 = result.get("T10Y US",{}).get("value",0) or 0
    t2  = result.get("T2Y US", {}).get("value",0) or 0
    result["Spread 10-2"] = {"value":round(t10-t2,3),"change":0,"history":[]}
    return result


@st.cache_data(ttl=20, show_spinner=False)
def fetch_prices(symbols: List[str]) -> Dict:
    if not YF_OK or not symbols: return {}
    try:
        raw = yf.download(symbols if len(symbols)>1 else symbols[0],
                           period="5d",interval="1d",progress=False,auto_adjust=True,
                           group_by="ticker" if len(symbols)>1 else None,timeout=12)
        if raw is None or raw.empty: return {}
        result = {}
        for sym in symbols:
            try:
                s = (raw[sym] if len(symbols)>1 and isinstance(raw.columns,pd.MultiIndex)
                       and sym in raw.columns.get_level_values(0) else raw)
                c=float(s["Close"].dropna().iloc[-1]); p=float(s["Close"].dropna().iloc[-2]) if len(s)>1 else c
                vol=int(s["Volume"].dropna().iloc[-1]) if "Volume" in s.columns else 0
                vol_prev=int(s["Volume"].dropna().iloc[-2]) if "Volume" in s.columns and len(s)>1 else vol
                result[sym]={"price":round(c,4),"chg":round((c-p)/p*100 if p else 0,3),
                             "vol":vol,"vol_chg":round((vol-vol_prev)/max(vol_prev,1)*100,1)}
            except Exception: pass
        return result
    except Exception: return {}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_ohlcv(symbol: str, period: str="6mo") -> pd.DataFrame:
    if not YF_OK: return pd.DataFrame()
    try:
        raw = yf.download(symbol,period=period,interval="1d",progress=False,auto_adjust=True,timeout=12)
        if raw is None or raw.empty: return pd.DataFrame()
        if isinstance(raw.columns,pd.MultiIndex): raw.columns=raw.columns.droplevel(1)
        raw.columns=[c.title() for c in raw.columns]
        return raw[[c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]].dropna(subset=["Close"])
    except Exception: return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_fear_greed() -> Dict:
    try:
        r=requests.get("https://api.alternative.me/fng/?limit=7",timeout=6)
        if r.status_code==200:
            d=r.json()["data"]
            return {"value":int(d[0]["value"]),"label":d[0]["value_classification"],
                    "history":[int(x["value"]) for x in d]}
    except: pass
    return {"value":50,"label":"Neutral","history":[50]*7}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_bce_rapport() -> Dict:
    if not ENGINE_OK: return {}
    try: return RapportBCE().generer()
    except: return {}


# ══════════════════════════════════════════════════════════════════════════════
# §5  SCORING PAR MODULE
# ══════════════════════════════════════════════════════════════════════════════

def _ema(s,n): return s.ewm(span=n,adjust=False,min_periods=n).mean()
def _rma(s,n):
    a=1/n; v=s.values.astype(float); o=np.full(len(v),np.nan)
    i0=next((i for i,x in enumerate(v) if not np.isnan(x)),None)
    if i0 is None: return pd.Series(o,index=s.index)
    o[i0]=v[i0]
    for i in range(i0+1,len(v)):
        if not np.isnan(v[i]): o[i]=(o[i-1] if not np.isnan(o[i-1]) else v[i])*(1-a)+v[i]*a
    return pd.Series(o,index=s.index)

def score_macro(fred: Dict, articles: List[Dict]) -> Tuple[float, str, List]:
    """Module 1 — Macroéconomie."""
    score=0.0; details=[]
    # PIB
    pib=fred.get("PIB US",{}).get("change",0) or 0
    if pib>0.5: score+=1; details.append(f"✅ PIB US en croissance (+{pib:.2f}%)")
    elif pib<-0.5: score-=1; details.append(f"⚠️ PIB US en contraction ({pib:.2f}%)")
    # Inflation
    cpi=fred.get("CPI US",{}).get("value",2.5) or 2.5
    cpi_chg=fred.get("CPI US",{}).get("change",0) or 0
    if cpi<2.5: score+=0.5; details.append(f"✅ CPI US bas ({cpi:.2f}) → accommodant")
    elif cpi>4: score-=1.5; details.append(f"🔴 CPI US élevé ({cpi:.2f}) → restrictif")
    else: score-=0.3; details.append(f"⚠️ CPI US modéré ({cpi:.2f})")
    if cpi_chg<0: score+=0.5; details.append("✅ Inflation en baisse")
    # Chômage
    unemp=fred.get("Chômage US",{}).get("value",4.0) or 4.0
    if unemp<4.5: score+=0.5; details.append(f"✅ Chômage US sain ({unemp:.1f}%)")
    elif unemp>6: score-=0.5; details.append(f"⚠️ Chômage US élevé ({unemp:.1f}%)")
    # Score news
    news_sc, _ = module_news_score(articles, "macro")
    score += news_sc*0.5
    return max(-1.0,min(1.0,score/3)), f"CPI {cpi:.2f} · Chômage {unemp:.1f}% · PIB {pib:+.2f}%", details

def score_monetaire(fred: Dict, rapport_bce: Dict, articles: List[Dict]) -> Tuple[float, str, List]:
    """Module 2 — Politique monétaire BCE + Fed."""
    score=0.0; details=[]
    t=rapport_bce.get("tendances_bce",{})
    # BCE
    if t:
        stance=t.get("stance","NEUTRE")
        if stance=="ACCOMMODANT":   score+=1.5; details.append("✅ BCE accommodante — baisses en cours")
        elif stance=="RESTRICTIF":  score-=1.5; details.append("🔴 BCE restrictive — taux élevés")
        else:                       score+=0.2; details.append("⚠️ BCE neutre")
        prochain=t.get("prochain_mvt_prevu","STABLE")
        if prochain=="BAISSE":  score+=1; details.append("✅ Prochaine décision BCE : BAISSE attendue")
        elif prochain=="HAUSSE":score-=1; details.append("🔴 Prochaine décision BCE : HAUSSE attendue")
    # Fed
    fed=fred.get("Fed Funds",{}).get("value",4.0) or 4.0
    fed_chg=fred.get("Fed Funds",{}).get("change",0) or 0
    if fed_chg<0:  score+=0.5; details.append(f"✅ Fed en baisse ({fed:.2f}%)")
    elif fed_chg>0:score-=0.5; details.append(f"⚠️ Fed en hausse ({fed:.2f}%)")
    if fed>5: score-=0.5; details.append(f"🔴 Taux Fed restrictifs ({fed:.2f}%)")
    # News
    ns, _ = module_news_score(articles, "monetaire")
    score += ns
    return max(-1.0,min(1.0,score/3)), f"BCE {t.get('stance','N/A')} · Fed {fed:.2f}%", details

def score_obligations(fred: Dict, articles: List[Dict]) -> Tuple[float, str, List]:
    """Module 3 — Marché obligataire."""
    score=0.0; details=[]
    spread=fred.get("Spread 10-2",{}).get("value",0.3) or 0.3
    t10=fred.get("T10Y US",{}).get("value",4.0) or 4.0
    ig=fred.get("Spread IG",{}).get("value",0.9) or 0.9
    hy=fred.get("Spread HY",{}).get("value",3.5) or 3.5
    if spread<-0.2:   score-=2; details.append(f"🔴 Courbe inversée ({spread:.2f}%) — signal récession")
    elif spread<0:    score-=0.5; details.append(f"⚠️ Courbe plate ({spread:.2f}%)")
    elif spread>0.5:  score+=1; details.append(f"✅ Courbe normale ({spread:.2f}%)")
    if t10>4.5:       score-=0.5; details.append(f"⚠️ T10Y élevé ({t10:.2f}%) → pression actions")
    elif t10<3:       score+=0.5; details.append(f"✅ T10Y accommodant ({t10:.2f}%)")
    if ig>1.5:        score-=0.5; details.append(f"⚠️ Spread IG large ({ig:.2f}%) — stress crédit")
    if hy>5:          score-=1; details.append(f"🔴 Spread HY élevé ({hy:.2f}%) — risque crédit")
    elif hy<3.5:      score+=0.5; details.append(f"✅ Spread HY sain ({hy:.2f}%)")
    ns, _ = module_news_score(articles, "obligations")
    score += ns*0.5
    return max(-1.0,min(1.0,score/3)), f"Spread 10-2: {spread:.2f}% · HY: {hy:.2f}%", details

def score_saisonnalite() -> Tuple[float, str, List]:
    """Module 4 — Saisonnalité."""
    month = date.today().month
    day   = date.today().day
    pattern = SEASONAL_PATTERNS.get(month, {"biais":0, "note":"Mois neutre"})
    biais   = pattern["biais"]
    note    = pattern["note"]
    # Ajustement fin de mois (window dressing)
    if day >= 25:
        biais = min(biais+0.2, 1.0)
        extra = "· Fin de mois : window dressing possible"
    elif day <= 5:
        biais = min(biais+0.1, 1.0)
        extra = "· Début de mois : flux institutionnels"
    else:
        extra = ""
    details = [
        f"Mois : {date.today().strftime('%B %Y')}",
        f"Biais historique : {biais:+.1f}",
        note + " " + extra,
    ]
    return max(-1.0,min(1.0,biais)), f"Mois {month} · Biais {biais:+.1f}", details

def score_geopolitique(articles: List[Dict], fred: Dict) -> Tuple[float, str, List]:
    """Module 5 — Géopolitique."""
    score=0.0; details=[]
    GEO_RISK = ["guerre","war","conflit","sanctions","invasion","terror","attaque","crise",
                 "escalation","missile","coup","geopolitical risk","nuclear","tension"]
    geo_arts = [a for a in articles if any(k in a["text"] for k in MODULES["geopolitique"]["keywords"])]
    risk_count = sum(1 for a in geo_arts if any(k in a["text"] for k in GEO_RISK))
    total_geo  = len(geo_arts)
    if total_geo > 0:
        risk_ratio = risk_count / total_geo
        score -= risk_ratio * 2
        details.append(f"📰 {total_geo} articles géopolitiques · {risk_count} à risque élevé")
    # VIX comme proxy géopolitique
    vix_p=fetch_prices(["^VIX"])
    vix=vix_p.get("^VIX",{}).get("price",18) or 18
    if vix>30:   score-=1;   details.append(f"🔴 VIX élevé ({vix:.1f}) — peur extrême")
    elif vix>20: score-=0.5; details.append(f"⚠️ VIX modéré ({vix:.1f}) — nervosité")
    elif vix<15: score+=0.5; details.append(f"✅ VIX bas ({vix:.1f}) — calme des marchés")
    ns, _ = module_news_score(articles, "geopolitique")
    score += ns*0.5
    return max(-1.0,min(1.0,score/2)), f"VIX {vix:.1f} · {total_geo} articles géopol.", details

def score_technique(df: pd.DataFrame) -> Tuple[float, str, List]:
    """Module 6 — Analyse graphique / TA."""
    if df is None or df.empty or len(df)<30:
        return 0.0, "Données insuffisantes", ["Charger un actif avec données suffisantes"]
    C=df["Close"]; price=_safe(C.iloc[-1]); details=[]
    # RSI
    d=C.diff(); g=_rma(d.clip(lower=0),14); l=_rma((-d).clip(lower=0),14)
    rsi_s=100-100/(1+g/l.replace(0,np.nan)); rsi=_safe(rsi_s.dropna().iloc[-1] if not rsi_s.dropna().empty else 50,50)
    # MACD
    ml=_ema(C,12)-_ema(C,26); sl=_ema(ml,9); macd_h=_safe((ml-sl).iloc[-1])
    # EMA
    e20=_safe(_ema(C,20).iloc[-1]); e50=_safe(_ema(C,50).iloc[-1]); e200=_safe(_ema(C,200).iloc[-1])
    # ADX
    H,L=df["High"],df["Low"]
    tr=pd.concat([H-L,(H-C.shift()).abs(),(L-C.shift()).abs()],axis=1).max(axis=1)
    up,dn=H.diff(),-L.diff()
    pdm=pd.Series(np.where((up>dn)&(up>0),up,0.0),index=H.index)
    ndm=pd.Series(np.where((dn>up)&(dn>0),dn,0.0),index=H.index)
    atr14=_rma(tr,14); pdi=100*_rma(pdm,14)/atr14.replace(0,np.nan)
    ndi=100*_rma(ndm,14)/atr14.replace(0,np.nan)
    adx=_safe(_rma(100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan),14).iloc[-1])
    # SuperTrend
    atr10=_rma(tr,10); hl2=(H+L)/2; ub_r=hl2+3*atr10; lb_r=hl2-3*atr10
    ub,lb=ub_r.copy(),lb_r.copy(); t=pd.Series(1,index=C.index,dtype=int)
    for i in range(1,len(C)):
        ub.iloc[i]=ub_r.iloc[i] if ub_r.iloc[i]<ub.iloc[i-1] or C.iloc[i-1]>ub.iloc[i-1] else ub.iloc[i-1]
        lb.iloc[i]=lb_r.iloc[i] if lb_r.iloc[i]>lb.iloc[i-1] or C.iloc[i-1]<lb.iloc[i-1] else lb.iloc[i-1]
        if t.iloc[i-1]==-1 and C.iloc[i]>ub.iloc[i]: t.iloc[i]=1
        elif t.iloc[i-1]==1 and C.iloc[i]<lb.iloc[i]: t.iloc[i]=-1
        else: t.iloc[i]=t.iloc[i-1]
    st_dir=int(t.iloc[-1])
    # BB %B
    bm=C.rolling(20).mean(); bs=C.rolling(20).std(ddof=0)
    bb_pct=(price-_safe((bm-2*bs).iloc[-1]))/max(_safe((4*bs).iloc[-1]),1e-9)
    score=0.0
    if e20>e50>e200: score+=2; details.append("✅ EMA 20>50>200 — tendance forte")
    elif e20<e50<e200: score-=2; details.append("🔴 EMA 20<50<200 — tendance baissière")
    elif e20>e50: score+=0.5
    else: score-=0.5
    if price>e200: score+=1; details.append("✅ Prix > EMA200 — haussier LT")
    else: score-=1; details.append("🔴 Prix < EMA200 — baissier LT")
    if rsi<30: score+=2; details.append(f"✅ RSI {rsi:.0f} — survente")
    elif rsi>70: score-=2; details.append(f"🔴 RSI {rsi:.0f} — surachat")
    else: score+=(50-rsi)/100
    if macd_h>0: score+=1; details.append("✅ MACD haussier")
    else: score-=1; details.append("🔴 MACD baissier")
    if st_dir==1: score+=1.5; details.append("✅ SuperTrend haussier")
    else: score-=1.5; details.append("🔴 SuperTrend baissier")
    if adx>25: details.append(f"✅ ADX {adx:.0f} — tendance confirmée")
    else: details.append(f"⚠️ ADX {adx:.0f} — pas de tendance claire")
    if bb_pct<0.1: score+=1; details.append("✅ Prix proche BB basse")
    elif bb_pct>0.9: score-=1; details.append("⚠️ Prix proche BB haute")
    return max(-1.0,min(1.0,score/8)), f"RSI {rsi:.0f} · MACD {'↑' if macd_h>0 else '↓'} · ST {'↑' if st_dir==1 else '↓'} · ADX {adx:.0f}", details

def score_volumes(df: pd.DataFrame, prices_data: Dict, sym: str) -> Tuple[float, str, List]:
    """Module 7 — Volumes de trades."""
    if df is None or df.empty or "Volume" not in df.columns:
        return 0.0, "Volume indisponible", []
    score=0.0; details=[]
    V=df["Volume"].astype(float); C=df["Close"].astype(float)
    vol_last=_safe(V.iloc[-1]); vol_avg=_safe(V.rolling(20).mean().iloc[-1])
    vol_ratio=vol_last/max(vol_avg,1)
    vol_chg=prices_data.get(sym,{}).get("vol_chg",0) or 0
    if vol_ratio>1.5:
        score+=1 if C.diff().iloc[-1]>0 else -1
        details.append(f"⚡ Volume {vol_ratio:.1f}x la moyenne — fort intérêt {'acheteur' if C.diff().iloc[-1]>0 else 'vendeur'}")
    elif vol_ratio<0.5:
        score-=0.3; details.append(f"⚠️ Volume faible ({vol_ratio:.1f}x) — conviction limitée")
    else:
        details.append(f"Volume normal ({vol_ratio:.1f}x la moyenne)")
    # OBV simplifié
    obv_change = (np.sign(C.diff().fillna(0))*V).tail(5).sum()
    if obv_change>0: score+=0.5; details.append("✅ OBV en hausse — pression acheteuse")
    else: score-=0.5; details.append("⚠️ OBV en baisse — pression vendeuse")
    # Volume relatif 5j vs 20j
    vol5=V.tail(5).mean(); vol20=V.tail(20).mean()
    v_rel=(vol5/max(vol20,1)-1)*100
    details.append(f"Volume 5j vs 20j : {v_rel:+.0f}%")
    return max(-1.0,min(1.0,score)), f"Ratio vol {vol_ratio:.1f}x · OBV {'↑' if obv_change>0 else '↓'}", details

def score_hedge_funds(articles: List[Dict], df: pd.DataFrame) -> Tuple[float, str, List]:
    """Module 8 — Positions Hedges Funds (proxy COT + news)."""
    score=0.0; details=[]
    # Score news HF/COT
    ns, hf_arts = module_news_score(articles, "hedge_funds")
    score += ns
    # Proxy : ratio Put/Call via VIX
    vix_prices=fetch_prices(["^VIX"])
    vix=vix_prices.get("^VIX",{}).get("price",18) or 18
    vix_chg=vix_prices.get("^VIX",{}).get("chg",0) or 0
    if vix>25: score-=0.5; details.append(f"⚠️ VIX {vix:.1f} — HF couverts (hedgés)")
    elif vix<15: score+=0.5; details.append(f"✅ VIX {vix:.1f} — HF peu couverts (bullish)")
    if vix_chg>5: score-=0.5; details.append(f"🔴 VIX +{vix_chg:.1f}% — achat protection accéléré")
    elif vix_chg<-5: score+=0.3; details.append(f"✅ VIX {vix_chg:.1f}% — débouclement protection")
    # Proxy momentum HF (short-term momentum factor)
    if df is not None and not df.empty and len(df)>=20:
        C=df["Close"]; mom10=_safe(C.iloc[-1])/_safe(C.iloc[-10])-1 if len(C)>=10 else 0
        if mom10>0.03: score+=0.5; details.append(f"✅ Momentum 10j {mom10*100:+.1f}% — HF trend-following long")
        elif mom10<-0.03: score-=0.5; details.append(f"🔴 Momentum 10j {mom10*100:+.1f}% — HF short/flat")
    details.append(f"{len(hf_arts)} articles HF/COT/positions détectés")
    details.append("📌 Source COT complète : barchart.com/commitment-of-traders")
    return max(-1.0,min(1.0,score)), f"VIX {vix:.1f} ({vix_chg:+.1f}%) · Score news HF {ns:+.2f}", details


def compute_composite_signal(
    scores: Dict[str, float],
    weights: Dict[str, float],
    capital: float,
    risk_pct: float,
    df: pd.DataFrame,
) -> Dict:
    """Signal final pondéré."""
    composite = sum(scores[mod] * weights[mod] for mod in scores)
    composite  = max(-1.0, min(1.0, composite))
    force      = abs(composite)

    if composite >= 0.30:   signal = "ACHETER"
    elif composite <= -0.30:signal = "VENDRE"
    else:                    signal = "ATTENDRE"

    # Niveaux
    price = _safe(df["Close"].iloc[-1]) if df is not None and not df.empty else 0
    atr   = 0.0
    if df is not None and not df.empty and "High" in df.columns:
        H,L,C=df["High"],df["Low"],df["Close"]
        tr=pd.concat([H-L,(H-C.shift()).abs(),(L-C.shift()).abs()],axis=1).max(axis=1)
        atr=_safe(_rma(tr,14).iloc[-1])

    if signal=="ACHETER":
        stop=round(price-max(atr*2,price*.015),4); tp=round(price+max(atr*4,price*.03),4)
    elif signal=="VENDRE":
        stop=round(price+max(atr*2,price*.015),4); tp=round(price-max(atr*4,price*.03),4)
    else:
        stop=round(price-atr*1.5,4); tp=round(price+atr*1.5,4)

    rr   = round(abs(tp-price)/max(abs(stop-price),1e-9),2)
    dist = abs(price-stop)
    units= round((capital*risk_pct/100)/dist,4) if dist>0 else 0

    return {
        "signal":composite, "label":signal, "force":round(force,3),
        "price":price, "stop":stop, "tp":tp, "rr":rr,
        "units":units, "risk_eur":round(units*dist,2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §6  GRAPHIQUES
# ══════════════════════════════════════════════════════════════════════════════

def chart_spider(scores: Dict[str, float], weights: Dict[str, float]) -> go.Figure:
    """Graphique radar des 8 modules."""
    labels=[MODULES[m]["label"] for m in scores]
    vals_s=[((scores[m]+1)/2)*100 for m in scores]
    vals_w=[weights[m]*100 for m in scores]
    fig=go.Figure()
    fig.add_trace(go.Scatterpolar(r=vals_s+[vals_s[0]], theta=labels+[labels[0]],
        fill="toself", name="Score modules",
        line=dict(color=BL,width=2), fillcolor=_rgba(BL.lstrip("#"),0.15)))
    fig.add_trace(go.Scatterpolar(r=vals_w+[vals_w[0]], theta=labels+[labels[0]],
        fill="toself", name="Poids dynamiques (%)",
        line=dict(color=O,width=1.5,dash="dot"), fillcolor=_rgba(O.lstrip("#"),0.08)))
    kw=_PL.copy(); kw.pop("hovermode",None); kw.pop("xaxis",None); kw.pop("yaxis",None)
    kw["polar"]=dict(radialaxis=dict(visible=True,range=[0,100],gridcolor=SP,linecolor=SP),
                      angularaxis=dict(gridcolor=SP,linecolor=SP))
    kw["height"]=360; kw["title"]="Radar — Scores & Pondérations"
    fig.update_layout(**kw)
    return fig

def chart_weights_bar(weights: Dict[str, float], counts: Dict[str, int]) -> go.Figure:
    labels=[MODULES[m]["label"] for m in weights]
    w_vals=[weights[m]*100 for m in weights]
    colors=[MODULES[m]["color"] for m in weights]
    fig=go.Figure(go.Bar(x=labels, y=w_vals, marker_color=colors, opacity=.85,
        text=[f"{v:.1f}%" for v in w_vals], textposition="outside",
        customdata=[counts.get(m,0) for m in weights],
        hovertemplate="%{x}<br>Poids : %{y:.1f}%<br>Mentions presse : %{customdata}<extra></extra>"))
    kw=_PL.copy(); kw["height"]=280; kw["title"]="Pondérations dynamiques (basées fréquence presse)"
    kw["yaxis_title"]="Poids (%)"
    fig.update_layout(**kw)
    fig.add_hline(y=100/len(weights),line_color="#333",line_dash="dash",opacity=.5,annotation_text="Poids égaux",annotation_font_size=9)
    return fig

def chart_ohlcv(df: pd.DataFrame, sym: str, sig: Dict) -> go.Figure:
    C_=df["Close"]; fig=make_subplots(rows=3,cols=1,row_heights=[0.60,0.22,0.18],shared_xaxes=True,vertical_spacing=0.02)
    if "Open" in df.columns:
        fig.add_trace(go.Candlestick(x=df.index,open=df["Open"],high=df["High"],low=df["Low"],close=C_,name=sym,
            increasing_line_color=GR,decreasing_line_color=RD,
            increasing_fillcolor="rgba(0,255,135,0.12)",decreasing_fillcolor="rgba(255,59,92,0.12)"),row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=df.index,y=C_,mode="lines",name=sym,line=dict(color=BL,width=2)),row=1,col=1)
    for n,col,dash in [(20,G,"solid"),(50,O,"dot"),(200,P,"dashdot")]:
        if len(C_)>n:
            fig.add_trace(go.Scatter(x=df.index,y=_ema(C_,n),mode="lines",name=f"EMA{n}",
                opacity=.7,line=dict(color=col,width=1.2,dash=dash)),row=1,col=1)
    bm=C_.rolling(20).mean(); bs=C_.rolling(20).std(ddof=0)
    fig.add_trace(go.Scatter(x=list(df.index)+list(df.index[::-1]),
        y=list(bm+2*bs)+list((bm-2*bs)[::-1]),fill="toself",
        fillcolor="rgba(242,140,40,0.05)",line=dict(color="rgba(0,0,0,0)"),name="BB"),row=1,col=1)
    if sig["stop"]:
        fig.add_hline(y=sig["stop"],row=1,col=1,line_color=RD,line_dash="dash",line_width=1,
            annotation_text=f"Stop {sig['stop']:.2f}",annotation_font_size=9)
    if sig["tp"]:
        fig.add_hline(y=sig["tp"],row=1,col=1,line_color=GR,line_dash="dash",line_width=1,
            annotation_text=f"TP {sig['tp']:.2f}",annotation_font_size=9)
    if "Volume" in df.columns:
        cv=[GR if float(C_.iloc[i])>=float(C_.iloc[max(0,i-1)]) else RD for i in range(len(df))]
        fig.add_trace(go.Bar(x=df.index,y=df["Volume"],name="Volume",marker_color=cv,opacity=.4),row=2,col=1)
    d=C_.diff(); ag=_rma(d.clip(lower=0),14); al=_rma((-d).clip(lower=0),14)
    rsi_s=100-100/(1+ag/al.replace(0,np.nan))
    fig.add_trace(go.Scatter(x=df.index,y=rsi_s,mode="lines",name="RSI 14",
        line=dict(color=G,width=1.5)),row=3,col=1)
    fig.add_hrect(y0=70,y1=100,row=3,col=1,fillcolor="rgba(255,59,92,0.07)",line_width=0)
    fig.add_hrect(y0=0,y1=30,row=3,col=1,fillcolor="rgba(0,255,135,0.07)",line_width=0)
    for lvl,lc in [(70,RD),(30,GR),(50,"#222")]:
        fig.add_hline(y=lvl,row=3,col=1,line_color=lc,line_dash="dash",line_width=.8,opacity=.4)
    kw=_PL.copy(); kw["height"]=560; kw["title"]=f"{sym} — EMA 20/50/200 · Bollinger · RSI"
    fig.update_layout(**kw); return fig

def chart_signal_gauge(composite: float) -> go.Figure:
    val=(composite+1)/2*100
    col=GR if composite>0.3 else RD if composite<-0.3 else O
    fig=go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(composite*100,1),
        title={"text":"Signal composite","font":{"size":14,"color":"#888"}},
        delta={"reference":0,"increasing":{"color":GR},"decreasing":{"color":RD}},
        gauge={
            "axis":{"range":[-100,100],"tickcolor":"#333","tickfont":{"color":"#555"}},
            "bar":{"color":col,"thickness":0.3},
            "bgcolor":C1,
            "bordercolor":SP,
            "steps":[{"range":[-100,-30],"color":"rgba(255,59,92,0.08)"},
                      {"range":[-30,30],  "color":"rgba(255,159,10,0.06)"},
                      {"range":[30,100],  "color":"rgba(0,255,135,0.08)"}],
            "threshold":{"line":{"color":col,"width":2},"value":round(composite*100,1)},
        },
        number={"suffix":"","font":{"size":28,"color":col,"family":"JetBrains Mono"}}
    ))
    kw=_PL.copy(); kw["height"]=240; kw["paper_bgcolor"]=C1
    fig.update_layout(**kw); return fig


# ══════════════════════════════════════════════════════════════════════════════
# §7  SIDEBAR & MAIN
# ══════════════════════════════════════════════════════════════════════════════

def sidebar() -> Dict:
    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center;padding:16px 0 18px">
          <div style="font-size:30px">⚡</div>
          <div style="font-size:18px;font-weight:700;color:{G};letter-spacing:-.5px;margin-top:5px">THE ZEDICUS v2</div>
          <div style="font-size:10px;color:#333;margin-top:3px">8 Modules · Pondération Dynamique</div>
        </div><hr style="border:none;height:1px;background:{SP};margin:0 0 14px">""",
        unsafe_allow_html=True)

        sym = st.selectbox("📊 Actif principal", list(UNIVERSE.keys()),
                            format_func=lambda x: UNIVERSE.get(x,x))
        period = st.select_slider("⏱️ Historique",["3mo","6mo","1y","2y"],value="6mo")
        wl = st.multiselect("🌐 Watchlist",list(UNIVERSE.keys()),
                              default=["^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F","^VIX"],
                              format_func=lambda x: UNIVERSE.get(x,x))
        capital = st.number_input("💶 Capital (€)",min_value=10,max_value=1_000_000,value=1000,step=100)
        risk_pct= st.slider("🛡️ Risque/trade (%)",0.5,5.0,2.0,0.5)

        st.markdown("---")
        st.markdown(f"<div style='font-size:11px;color:#444;margin-bottom:8px'>🔄 Sources actives</div>",
                     unsafe_allow_html=True)
        for src in list(RSS_SOURCES.keys())[:6]:
            st.markdown(f"<div style='font-size:10px;color:#333'>· {src}</div>",unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:10px;color:#333'>... +{len(RSS_SOURCES)-6} autres</div>",
                     unsafe_allow_html=True)

        st.markdown("---")
        if st.button("🔄 Actualiser tout",use_container_width=True):
            st.cache_data.clear(); st.rerun()
        st.markdown(f"""
        <div style="font-size:10px;color:#333;margin-top:10px;line-height:1.9">
          {"✅" if ENGINE_OK else "❌"} bce_engine · {"✅" if ORCH_OK else "❌"} orchestrator<br>
          {"✅" if YF_OK else "❌"} yfinance · {"✅" if FP_OK else "❌"} feedparser<br>
          {datetime.utcnow():%Y-%m-%d %H:%M} UTC
        </div>""",unsafe_allow_html=True)

    return dict(symbol=sym, period=period, watchlist=wl or ["^STOXX50E"],
                capital=capital, risk_pct=risk_pct)


def main():
    cfg = sidebar()
    sym = cfg["symbol"]

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
    margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid {SP}">
      <div style="display:flex;align-items:center;gap:14px">
        <span style="font-size:32px">⚡</span>
        <div>
          <div style="font-size:26px;font-weight:700;color:{G};letter-spacing:-1px;line-height:1">THE ZEDICUS v2</div>
          <div style="font-size:12px;color:#333;margin-top:3px">
            <span style="background:rgba(0,255,135,.1);color:{GR};padding:2px 8px;border-radius:6px;font-weight:700;font-size:10px;margin-right:8px">● LIVE</span>
            8 modules · Pondération presse dynamique · {datetime.utcnow():%Y-%m-%d %H:%M} UTC
          </div>
        </div>
      </div>
      <div style="font-size:10px;color:#333;text-align:right">
        {len(RSS_SOURCES)} sources RSS<br>
        FRED · BCE · COT proxy
      </div>
    </div>""", unsafe_allow_html=True)

    # ── Chargement données ────────────────────────────────────────────────────
    with st.spinner("Chargement des 12 sources RSS + FRED..."):
        articles    = fetch_all_articles()
        fred        = fetch_fred_all()
        rapport_bce = fetch_bce_rapport()
        df          = fetch_ohlcv(sym, cfg["period"])
        prices      = fetch_prices(cfg["watchlist"])
        weights     = compute_module_weights(articles)
        fg          = fetch_fear_greed()

    # ── Compter occurrences par module ────────────────────────────────────────
    corpus = " ".join(a["text"] for a in articles[:60])
    mod_counts = {m: sum(corpus.count(k) for k in MODULES[m]["keywords"]) for m in MODULES}

    # ── Calcul des 8 scores ───────────────────────────────────────────────────
    sc_macro, macro_summary, macro_det   = score_macro(fred, articles)
    sc_mon,   mon_summary,   mon_det     = score_monetaire(fred, rapport_bce, articles)
    sc_obl,   obl_summary,   obl_det     = score_obligations(fred, articles)
    sc_sai,   sai_summary,   sai_det     = score_saisonnalite()
    sc_geo,   geo_summary,   geo_det     = score_geopolitique(articles, fred)
    sc_tech,  tech_summary,  tech_det    = score_technique(df)
    sc_vol,   vol_summary,   vol_det     = score_volumes(df, prices, sym)
    sc_hf,    hf_summary,    hf_det      = score_hedge_funds(articles, df)

    module_scores = {
        "macro":       sc_macro,
        "monetaire":   sc_mon,
        "obligations": sc_obl,
        "saisonnalite":sc_sai,
        "geopolitique":sc_geo,
        "technique":   sc_tech,
        "volumes":     sc_vol,
        "hedge_funds": sc_hf,
    }

    sig = compute_composite_signal(module_scores, weights, cfg["capital"], cfg["risk_pct"], df)

    # ── Ticker bar ────────────────────────────────────────────────────────────
    wl_syms = cfg["watchlist"][:6]
    if prices:
        cols = st.columns(len([s for s in wl_syms if s in prices]))
        ci   = 0
        for sym_ in wl_syms:
            if sym_ not in prices: continue
            d=prices[sym_]; v=d.get("chg",0); cc=_cc(v)
            cols[ci].markdown(f"""<div class="z-ticker">
              <div style="font-size:9px;color:#333;letter-spacing:.5px">{UNIVERSE.get(sym_,sym_)[:14]}</div>
              <div style="font-size:13px;font-weight:700;color:{G};font-family:'JetBrains Mono'">{d.get('price',0):,.4f}</div>
              <div style="font-size:10px;color:{cc};font-weight:600">{v:+.3f}%</div>
            </div>""",unsafe_allow_html=True); ci+=1

    st.markdown("")

    # ══════════════════════════════════════════════════════════════════════════
    # ONGLET PRINCIPAL — SIGNAL COMPOSITE
    # ══════════════════════════════════════════════════════════════════════════
    tabs = st.tabs([
        "⚡ Signal Global", "📊 8 Modules", "📈 Graphiques",
        "📰 Presse & Pondération", "🌍 Macro & Obligations",
        "🏦 BCE", "🔍 Screener", "📄 Export"
    ])

    # ── TAB 0 : Signal global ─────────────────────────────────────────────────
    with tabs[0]:
        label=sig["label"]; comp=sig["signal"]
        cls={"ACHETER":GR,"VENDRE":RD,"ATTENDRE":O}[label]
        ic={"ACHETER":"🚀","VENDRE":"⬇","ATTENDRE":"⏸"}[label]

        col_gauge, col_banner = st.columns([1,2])
        with col_gauge:
            if PLOTLY_OK:
                st.plotly_chart(chart_signal_gauge(comp),use_container_width=True)
        with col_banner:
            st.markdown(f"""
            <div style="background:{C1};border-radius:16px;padding:22px 24px;
            border:.5px solid {SP};border-left:5px solid {cls};height:100%">
              <div style="font-size:11px;color:#444;text-transform:uppercase;letter-spacing:.9px;margin-bottom:10px">Décision algorithmique — 8 modules pondérés</div>
              <div style="font-size:46px;font-weight:700;color:{cls};letter-spacing:-2px;line-height:1">{ic} {label}</div>
              <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
                {_badge(f"Composite {comp:+.3f}", cls)}
                {_badge(f"Force {sig['force']*100:.0f}%", BL)}
                {_badge(f"{len(articles)} articles analysés", "#444")}
                {_badge(f"FG {fg['value']}/100 {fg['label']}", GR if fg['value']>60 else RD if fg['value']<40 else O)}
              </div>
              <div style="margin-top:14px;background:{DK};border-radius:4px;height:6px;overflow:hidden">
                <div style="width:{sig['force']*100:.0f}%;height:100%;background:{cls}"></div>
              </div>
            </div>""",unsafe_allow_html=True)

        st.markdown("")

        # Niveaux de trading
        if sig["price"]:
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric("Prix",    f"{sig['price']:,.4f}")
            c2.metric("Stop",    f"{sig['stop']:,.4f}", "SL")
            c3.metric("TP",      f"{sig['tp']:,.4f}",   "TP")
            c4.metric("R:R",     f"{sig['rr']:.2f}x")
            c5.metric("Taille",  f"{sig['units']:.4f} u.")
            c6.metric("Risque",  f"€{sig['risk_eur']:.2f}")

        st.markdown("")

        # Résumé modules (tableau synthèse)
        st.markdown("##### Contribution de chaque module au signal")
        rows=[]
        for mod_id in MODULES:
            sc=module_scores[mod_id]; w=weights[mod_id]
            contrib=sc*w
            rows.append({
                "Module":      MODULES[mod_id]["label"],
                "Score":       f"{sc:+.3f}",
                "Poids":       f"{w*100:.1f}%",
                "Contribution":f"{contrib:+.4f}",
                "Mentions":    f"{mod_counts.get(mod_id,0)} articles",
                "Biais":       "🟢 Haussier" if sc>0.15 else "🔴 Baissier" if sc<-0.15 else "⚪ Neutre",
            })
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

    # ── TAB 1 : 8 modules détail ──────────────────────────────────────────────
    with tabs[1]:
        if PLOTLY_OK:
            c1,c2=st.columns([1,1])
            with c1: st.plotly_chart(chart_spider(module_scores,weights),use_container_width=True)
            with c2: st.plotly_chart(chart_weights_bar(weights,mod_counts),use_container_width=True)

        st.markdown("##### Détail de chaque module")
        mod_data = [
            ("macro",       sc_macro, macro_summary, macro_det),
            ("monetaire",   sc_mon,   mon_summary,   mon_det),
            ("obligations", sc_obl,   obl_summary,   obl_det),
            ("saisonnalite",sc_sai,   sai_summary,   sai_det),
            ("geopolitique",sc_geo,   geo_summary,   geo_det),
            ("technique",   sc_tech,  tech_summary,  tech_det),
            ("volumes",     sc_vol,   vol_summary,   vol_det),
            ("hedge_funds", sc_hf,    hf_summary,    hf_det),
        ]
        cols=st.columns(2)
        for i,(mod_id,sc,summary,details) in enumerate(mod_data):
            mod=MODULES[mod_id]; color=mod["color"]; w=weights[mod_id]
            pct=(sc+1)/2*100
            with cols[i%2]:
                st.markdown(f"""
                <div class="z-module" style="border-top:2px solid {color}">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <span style="font-size:13px;font-weight:700;color:{color}">{mod['label']}</span>
                    <div style="display:flex;gap:6px;align-items:center">
                      {_badge(f"Score {sc:+.2f}",color)}
                      {_badge(f"Poids {w*100:.0f}%","#444")}
                      {_badge(f"{mod_counts.get(mod_id,0)} art.","#333")}
                    </div>
                  </div>
                  <div style="font-size:11px;color:#444;margin-bottom:6px;font-family:'JetBrains Mono'">{summary}</div>
                  <div class="z-weight-bar" style="background:{SP}">
                    <div style="width:{pct:.0f}%;height:6px;background:{color};border-radius:4px"></div>
                  </div>
                  {"".join(f'<div style="font-size:11px;color:#555;padding:3px 0;border-bottom:.5px solid {SP}">{d}</div>' for d in details[:3])}
                </div>""",unsafe_allow_html=True)

    # ── TAB 2 : Graphiques ────────────────────────────────────────────────────
    with tabs[2]:
        if not df.empty and PLOTLY_OK:
            st.plotly_chart(chart_ohlcv(df,sym,sig),use_container_width=True)
            # Volume chart dédié
            if "Volume" in df.columns:
                V=df["Volume"]; avg20=V.rolling(20).mean()
                fig_v=go.Figure()
                cv=[GR if float(df["Close"].iloc[i])>=float(df["Close"].iloc[max(0,i-1)]) else RD for i in range(len(df))]
                fig_v.add_trace(go.Bar(x=df.index,y=V,name="Volume",marker_color=cv,opacity=.5))
                fig_v.add_trace(go.Scatter(x=df.index,y=avg20,mode="lines",name="Moy. 20j",
                    line=dict(color=O,width=1.5)))
                kw=_PL.copy(); kw["height"]=200; kw["title"]="Volumes de trades"
                fig_v.update_layout(**kw)
                st.plotly_chart(fig_v,use_container_width=True)
        else:
            st.warning(f"Données OHLCV indisponibles pour {sym}")

    # ── TAB 3 : Presse & Pondération ──────────────────────────────────────────
    with tabs[3]:
        st.markdown(f"##### 📰 {len(articles)} articles analysés · Pondération dynamique")
        st.info(f"""
        **Algorithme de franck_arauld** : la fréquence des mots-clés de chaque module dans les {len(articles)} articles
        récents détermine son poids dans le signal final. Si la presse parle surtout de **politique monétaire**,
        ce module reçoit un poids plus élevé. Si c'est la **géopolitique** qui domine, c'est elle qui pèse plus.
        """)

        # Top mots-clés
        all_words=[w for a in articles for w in a["text"].split() if len(w)>5]
        word_freq=Counter(all_words).most_common(20)
        col_wf,col_news=st.columns([1,2])
        with col_wf:
            st.markdown("**Top 20 termes dans la presse**")
            df_wf=pd.DataFrame(word_freq,columns=["Terme","Occurrences"])
            st.dataframe(df_wf,use_container_width=True,hide_index=True)
        with col_news:
            st.markdown("**Articles BCE / Finance récents**")
            bce_arts=[a for a in articles if any(k in a["text"] for k in MODULES["monetaire"]["keywords"])][:8]
            for art in bce_arts:
                cc=BL if "bce" in art["text"] or "ecb" in art["text"] else O
                st.markdown(f"""
                <a href="{art['link']}" target="_blank" style="text-decoration:none">
                <div class="z-news" style="border-left-color:{cc}">
                  <div style="font-size:13px;font-weight:500;color:#ccc;margin-bottom:4px">{art['title']}</div>
                  <div style="font-size:10px;color:#444">{art['source']} · {art['date']}</div>
                </div></a>""",unsafe_allow_html=True)

    # ── TAB 4 : Macro & Obligations ───────────────────────────────────────────
    with tabs[4]:
        st.markdown("##### 🌍 Indicateurs FRED")
        items=[("Fed Funds","%",O),("T10Y US","%",BL),("T2Y US","%",GR),
                ("Spread 10-2","%",RD if (fred.get("Spread 10-2",{}).get("value",0) or 0)<0 else GR),
                ("CPI US","",RD if (fred.get("CPI US",{}).get("value",2) or 2)>3 else GR),
                ("Chômage US","%",O),("Spread IG","%",O),("Spread HY","%",RD)]
        cols=st.columns(4)
        for i,(lbl,unit,color) in enumerate(items):
            d=fred.get(lbl,{}); v=d.get("value"); chg=d.get("change",0)
            if v is not None:
                cols[i%4].markdown(f"""<div class="z-card" style="border-top:2px solid {color}">
                  <div style="font-size:10px;color:#444;text-transform:uppercase;letter-spacing:.6px;margin-bottom:5px">{lbl}</div>
                  <div style="font-family:'JetBrains Mono';font-size:22px;font-weight:700;color:{color}">{v:.2f}{unit}</div>
                  <div style="font-size:11px;color:{_cc(chg)};margin-top:3px;font-family:'JetBrains Mono'">{chg:+.4f}</div>
                </div>""",unsafe_allow_html=True)

        # Spread chart
        h=fred.get("Spread 10-2",{}).get("history",[])
        if h and PLOTLY_OK:
            fig=go.Figure()
            fig.add_trace(go.Scatter(y=h,mode="lines",name="Spread 10-2 ans",line=dict(color=O,width=2)))
            fig.add_hline(y=0,line_color=RD,line_dash="dash",annotation_text="Inversion courbe = signal récession",annotation_font_size=9)
            fig.add_hrect(y0=min(h) if h else -1,y1=0,fillcolor="rgba(255,59,92,0.08)",line_width=0)
            fig.add_hrect(y0=0,y1=max(h) if max(h)>0 else 1,fillcolor="rgba(0,255,135,0.05)",line_width=0)
            kw=_PL.copy(); kw["height"]=220; kw["title"]="Spread 10-2 ans US (courbe des taux)"
            fig.update_layout(**kw); st.plotly_chart(fig,use_container_width=True)

        with st.expander("📖 Lire la courbe des taux"):
            st.markdown(f"""
            Le spread 10-2 ans est la différence entre le taux US à 10 ans et à 2 ans.
            - **Spread positif** : courbe normale, économie saine
            - **Spread négatif (inversé)** : signal historique de récession à 12-18 mois
            - Valeur actuelle : **{fred.get("Spread 10-2",{}).get("value","N/A")}%**
            - Sources : Investing.com, Bloomberg, **sites banques centrales** (BCE/Fed/BNS)
            """)

    # ── TAB 5 : BCE ───────────────────────────────────────────────────────────
    with tabs[5]:
        t=rapport_bce.get("tendances_bce",{})
        pr=t.get("probabilites",{})
        if t:
            sc_c=GR if t.get("stance")=="ACCOMMODANT" else RD if t.get("stance")=="RESTRICTIF" else O
            st.markdown(f"""
            <div class="z-card" style="border-left:4px solid {sc_c}">
              <div style="font-size:11px;color:#444;text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px">Phase du cycle monétaire BCE</div>
              <div style="font-size:24px;font-weight:700;color:{sc_c};margin-bottom:8px">{t.get('phase_cycle','N/A')}</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                {_badge("Stance : "+t.get("stance","N/A"),sc_c)}
                {_badge("Prochain : "+t.get("prochain_mvt_prevu","?"),(GR if t.get("prochain_mvt_prevu","")=="BAISSE" else RD))}
                {_badge("Confiance : "+str(t.get("confiance_pct",0))+"%",BL)}
              </div>
            </div>""",unsafe_allow_html=True)
            c1,c2,c3,c4=st.columns(4)
            c1.metric("Taux BCE",f"{t.get('taux_actuel',0):.2f}%")
            c2.metric("Inflation HICP",f"{t.get('inflation_hicp',0):.1f}%")
            c3.metric("Taux réel",f"{t.get('taux_reel',0):.2f}%")
            c4.metric("Euribor 3M",f"{t.get('euribor_3m',0):.3f}%")
            b=pr.get("baisse_pct",33); s_=pr.get("stable_pct",34); h=pr.get("hausse_pct",33)
            st.markdown(f"""<div class="z-card">
              <div style="font-size:11px;color:#444;margin-bottom:8px">Probabilités prochaine décision BCE</div>
              <div style="display:flex;height:10px;border-radius:5px;overflow:hidden;margin-bottom:7px">
                <div style="width:{b:.0f}%;background:{GR}"></div>
                <div style="width:{s_:.0f}%;background:{O}"></div>
                <div style="width:{h:.0f}%;background:{RD}"></div>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:600;font-family:'JetBrains Mono'">
                <span style="color:{GR}">↓ Baisse {b:.0f}%</span>
                <span style="color:{O}">— Stable {s_:.0f}%</span>
                <span style="color:{RD}">↑ Hausse {h:.0f}%</span>
              </div>
            </div>""",unsafe_allow_html=True)
            if ENGINE_OK and PLOTLY_OK:
                hist=AnalyseurTendancesBCE.HISTORIQUE_DECISIONS
                dates=[d["date"] for d in hist]; taux=[d["taux_depot"] for d in hist]; bps_=[d["bps"] for d in hist]
                dcs=[GR if b<0 else RD if b>0 else O for b in bps_]
                fig=make_subplots(rows=2,cols=1,row_heights=[0.65,0.35],shared_xaxes=True,vertical_spacing=0.05)
                fig.add_trace(go.Scatter(x=dates,y=taux,mode="lines+markers",name="Taux dépôt BCE (%)",
                    line=dict(color=BL,width=2.5),marker=dict(color=dcs,size=11,line=dict(color=DK,width=1.5))),row=1,col=1)
                fig.add_hline(y=2.0,row=1,col=1,line_color=O,line_dash="dash",line_width=1,annotation_text="Taux neutre ~2%",annotation_font_size=9)
                fig.add_trace(go.Bar(x=dates,y=bps_,name="Variation (bps)",marker_color=dcs,opacity=.75),row=2,col=1)
                kw=_PL.copy(); kw["height"]=380; kw["title"]="Cycle monétaire BCE (2022-2025)"
                fig.update_layout(**kw); st.plotly_chart(fig,use_container_width=True)
        else:
            st.warning("Ajouter bce_engine.py dans le même dossier pour l'analyse BCE complète")

    # ── TAB 6 : Screener ─────────────────────────────────────────────────────
    with tabs[6]:
        sc_syms=st.multiselect("Actifs à screener",list(UNIVERSE.keys()),
            default=list(UNIVERSE.keys())[:8],format_func=lambda x:UNIVERSE.get(x,x))
        if sc_syms:
            rows=[]
            for s_ in sc_syms:
                d_=prices.get(s_,{})
                if not d_: continue
                df_=fetch_ohlcv(s_,"3mo")
                rsi_=50; adx_=0
                if not df_.empty and len(df_)>=14:
                    C=df_["Close"]; dd=C.diff(); gg=_rma(dd.clip(lower=0),14); ll=_rma((-dd).clip(lower=0),14)
                    rsi_s=100-100/(1+gg/ll.replace(0,np.nan)); v=rsi_s.dropna()
                    rsi_=_safe(v.iloc[-1] if not v.empty else 50,50)
                rows.append({"Actif":UNIVERSE.get(s_,s_),"Prix":f"{d_.get('price',0):,.4f}",
                              "Var%":f"{d_.get('chg',0):+.3f}%","RSI 14":f"{rsi_:.0f}",
                              "Vol Chg%":f"{d_.get('vol_chg',0):+.0f}%",
                              "Biais":"🟢" if rsi_<40 else "🔴" if rsi_>65 else "⚪"})
            if rows: st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

            # Perf comparative
            if PLOTLY_OK:
                fig=go.Figure()
                pal=[BL,GR,G,O,P,RD,"#06B6D4","#F97316","#A855F7","#EC4899"]
                for i,s_ in enumerate(sc_syms[:8]):
                    df_=fetch_ohlcv(s_,cfg["period"])
                    if df_.empty: continue
                    norm=df_["Close"]/df_["Close"].iloc[0]*100-100
                    fig.add_trace(go.Scatter(x=df_.index,y=norm,mode="lines",name=UNIVERSE.get(s_,s_)[:14],line=dict(color=pal[i%len(pal)],width=1.8)))
                fig.add_hline(y=0,line_color="#222",line_dash="dash",opacity=.5)
                kw=_PL.copy(); kw["height"]=340; kw["yaxis_title"]="Return (%)"
                fig.update_layout(**kw); st.plotly_chart(fig,use_container_width=True)

    # ── TAB 7 : Export ────────────────────────────────────────────────────────
    with tabs[7]:
        t_=rapport_bce.get("tendances_bce",{})
        rpt=f"""# ⚡ THE ZEDICUS v2 — Rapport 8 Modules
**Date** : {datetime.utcnow():%d/%m/%Y %H:%M} UTC | **Actif** : {sym}

## Signal composite : {sig['label']} ({sig['signal']:+.3f})

## Scores & Pondérations
| Module | Score | Poids | Contrib. | Mentions presse |
|---|---|---|---|---|
{"".join(f"| {MODULES[m]['label']} | {module_scores[m]:+.3f} | {weights[m]*100:.1f}% | {module_scores[m]*weights[m]:+.4f} | {mod_counts.get(m,0)} |" + chr(10) for m in MODULES)}

## Niveaux
- Prix : {sig['price']:.4f} | Stop : {sig['stop']:.4f} | TP : {sig['tp']:.4f}
- R:R : {sig['rr']:.2f}x | Taille : {sig['units']:.4f} u. | Risque : €{sig['risk_eur']:.2f}

## Macro FRED
- Fed Funds : {fred.get('Fed Funds',{}).get('value','N/A')}% | T10Y : {fred.get('T10Y US',{}).get('value','N/A')}%
- Spread 10-2 : {fred.get('Spread 10-2',{}).get('value','N/A')}% | CPI : {fred.get('CPI US',{}).get('value','N/A')}

## BCE
- Stance : {t_.get('stance','N/A')} | Prochain : {t_.get('prochain_mvt_prevu','N/A')} ({t_.get('bps_prevu',0):+d}bps)

## Sources utilisées
{chr(10).join('- ' + s for s in RSS_SOURCES.keys())}
- FRED (Federal Reserve Economic Data)
- BCE SDMX (données officielles BCE)

---
*⚠️ Indicatif uniquement. Trading = risque de perte en capital.*
"""
        st.markdown(rpt)
        st.download_button("📥 Télécharger rapport (Markdown)", rpt,
            file_name=f"zedicus_v2_{sym}_{datetime.utcnow():%Y%m%d_%H%M}.md",
            mime="text/markdown", use_container_width=True)

    # Footer
    st.markdown(f"""
    <div style="text-align:center;padding:14px 0 0;margin-top:16px;font-size:10px;color:#333;border-top:1px solid {SP}">
      THE ZEDICUS v2 · 8 Modules · {len(RSS_SOURCES)} sources RSS · FRED · BCE SDMX · CoinGecko · Alternative.me<br>
      Investing.com · Bloomberg · BCE · Fed Reserve · BNS · Reuters · FT Markets · Les Echos · BBC · Google News<br>
      ⚠️ À titre indicatif uniquement — Pas de conseil financier
    </div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
