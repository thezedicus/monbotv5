#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  THE ZEDICUS — Dashboard BCE Zone Euro                                       ║
║  Version finale · Python 3.9+ · Streamlit · Données réelles                 ║
║                                                                              ║
║  COMMANDE :  python3 -m streamlit run zedicus.py                            ║
║  GITHUB  :   streamlit run zedicus.py                                        ║
║                                                                              ║
║  INSTALLATION :                                                              ║
║    pip install -r requirements.txt                                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── Imports standard ──────────────────────────────────────────────────────────
import sys, os, time, json, math, warnings, re, hashlib
from datetime   import datetime, date, timedelta
from pathlib    import Path
from typing     import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from io         import StringIO

warnings.filterwarnings("ignore")

# ── Dépendances tierces ───────────────────────────────────────────────────────
try:
    import streamlit as st
except ImportError:
    print("pip install streamlit"); sys.exit(1)

try:
    import plotly.graph_objects as go
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

# ── Modules locaux (optionnels — dégradation gracieuse) ──────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from bce_engine import BCEDatabase, BCEAPI, AnalyseurTendancesBCE, RapportBCE
    ENGINE_OK = True
except ImportError:
    ENGINE_OK = False

try:
    from orchestrator import (
        technical_score as _tech_score,
        macro_score     as _macro_score,
        news_score      as _news_score,
        compute_decision, get_indices_data,
        BCE_INDICES_MAP, BULL_WORDS, BEAR_WORDS,
    )
    ORCH_OK = True
except ImportError:
    ORCH_OK = False

# ══════════════════════════════════════════════════════════════════════════════
# §0  NETTOYAGE AUTOMATIQUE AU PREMIER LANCEMENT
# ══════════════════════════════════════════════════════════════════════════════

_OBSOLETE_FILES = [
    "dashboard_temps_reel.py", "market_ultimate.py", "market_ultimate.py.rtf",
    "market_ultimate.py.txt", "streamlit_app.py", "bce_ultimate.py",
    "generate_dashboard.py", "market_oracle.py", "dashboard_v3.py",
    "rapport_ios_v3.html", "dashboard_live.html", "bce_dashboard.py",
    "market_oracle_bce.py", "corrections.py", "api_sources.py",
    "bot.py", "bot_v2.py", "dashboard.py", "market_snapshot.py",
    "codesupplementaire.py",
]

def _cleanup() -> List[str]:
    removed = []
    here = Path(__file__).parent
    for f in _OBSOLETE_FILES:
        p = here / f
        if p.exists() and p.name != Path(__file__).name:
            try:
                p.unlink()
                removed.append(f)
            except Exception:
                pass
    return removed

# ══════════════════════════════════════════════════════════════════════════════
# §1  PAGE CONFIG & DESIGN SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title = "THE ZEDICUS",
    page_icon  = "⚡",
    layout     = "wide",
    initial_sidebar_state = "expanded",
)

# ── Design tokens ─────────────────────────────────────────────────────────────
_GOLD   = "#FFD700"
_ORANGE = "#F28C28"
_PURPLE = "#8B00FF"
_GREEN  = "#00FF87"
_RED    = "#FF3B5C"
_BLUE   = "#00C2FF"
_DARK   = "#0A0A0A"
_CARD   = "#111111"
_CARD2  = "#1A1A1A"
_SEP    = "#2A2A2A"

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=JetBrains+Mono:wght@400;700&display=swap');

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

html, body, .stApp {{
    background: {_DARK} !important;
    font-family: 'Syne', sans-serif;
    color: #E0E0E0;
}}

.stApp > header {{
    background: rgba(10,10,10,.96) !important;
    border-bottom: 1px solid {_ORANGE}33;
    backdrop-filter: blur(20px);
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: {_DARK} !important;
    border-right: 1px solid {_ORANGE}44;
}}
[data-testid="stSidebar"] * {{ color: #ccc !important; }}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {{
    background: {_CARD} !important;
    border-radius: 50px;
    padding: 5px;
    gap: 4px;
    border: 1px solid {_SEP};
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 40px !important;
    color: #666 !important;
    font-weight: 700 !important;
    font-size: 13px !important;
    letter-spacing: .3px;
    padding: 8px 20px !important;
    font-family: 'Syne', sans-serif !important;
}}
.stTabs [aria-selected="true"] {{
    background: linear-gradient(90deg, {_ORANGE}, {_PURPLE}) !important;
    color: white !important;
    box-shadow: 0 0 20px {_ORANGE}55;
}}

/* ── Metrics ── */
[data-testid="stMetric"] {{
    background: {_CARD} !important;
    border: 1px solid {_SEP} !important;
    border-radius: 16px !important;
    padding: 16px !important;
    transition: border-color .2s, transform .2s;
}}
[data-testid="stMetric"]:hover {{
    border-color: {_ORANGE}88 !important;
    transform: translateY(-2px);
}}
[data-testid="stMetricLabel"] {{
    color: #555 !important;
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: .8px;
    font-weight: 700 !important;
}}
[data-testid="stMetricValue"] {{
    color: {_GOLD} !important;
    font-weight: 800 !important;
    font-family: 'JetBrains Mono', monospace !important;
}}
[data-testid="stMetricDelta"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12px !important;
}}

/* ── Buttons ── */
.stButton > button {{
    background: linear-gradient(90deg, {_PURPLE}, {_ORANGE}) !important;
    color: white !important;
    border: none !important;
    border-radius: 50px !important;
    padding: 10px 28px !important;
    font-weight: 800 !important;
    font-family: 'Syne', sans-serif !important;
    letter-spacing: .5px;
    box-shadow: 0 0 15px {_ORANGE}44;
    transition: all .2s !important;
}}
.stButton > button:hover {{
    transform: scale(1.03) !important;
    box-shadow: 0 0 25px {_ORANGE}88 !important;
}}

/* ── Selects / Inputs ── */
.stSelectbox > div > div,
.stMultiSelect > div > div,
.stNumberInput > div > div,
.stTextInput > div > div {{
    background: {_CARD} !important;
    border-color: {_SEP} !important;
    color: #ddd !important;
    border-radius: 12px !important;
    font-family: 'Syne', sans-serif !important;
}}

/* ── Expander ── */
div[data-testid="stExpander"] {{
    background: {_CARD} !important;
    border: 1px solid {_SEP} !important;
    border-left: 3px solid {_ORANGE} !important;
    border-radius: 14px !important;
}}
.streamlit-expanderHeader {{
    color: {_GOLD} !important;
    font-weight: 700 !important;
}}

/* ── DataFrame ── */
.stDataFrame {{ font-size: .83em !important; }}
.stDataFrame th {{
    background: {_CARD2} !important;
    color: {_GOLD} !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    font-size: 10px !important;
    letter-spacing: .6px;
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: {_DARK}; }}
::-webkit-scrollbar-thumb {{ background: {_ORANGE}; border-radius: 4px; }}

/* ── General text ── */
p, li, label, span {{ color: #ccc !important; }}
h1, h2, h3, h4 {{ color: {_GOLD} !important; font-weight: 800 !important; }}
hr {{ border: none; height: 1px; background: linear-gradient(90deg,{_ORANGE},{_PURPLE},{_GOLD}); margin: 16px 0; }}

/* ── Custom components ── */
.z-card {{
    background: {_CARD};
    border: 1px solid {_SEP};
    border-radius: 18px;
    padding: 18px 20px;
    margin-bottom: 12px;
}}
.z-signal-buy {{
    background: linear-gradient(135deg, #001A0D, #003520);
    border: 2px solid {_GREEN};
    border-radius: 20px;
    padding: 22px 26px;
    box-shadow: 0 0 30px {_GREEN}22;
}}
.z-signal-sell {{
    background: linear-gradient(135deg, #1A0008, #35001A);
    border: 2px solid {_RED};
    border-radius: 20px;
    padding: 22px 26px;
    box-shadow: 0 0 30px {_RED}22;
}}
.z-signal-wait {{
    background: linear-gradient(135deg, #1A1000, #352500);
    border: 2px solid {_ORANGE};
    border-radius: 20px;
    padding: 22px 26px;
    box-shadow: 0 0 30px {_ORANGE}22;
}}
.z-badge {{
    display: inline-block;
    font-size: 11px;
    font-weight: 800;
    padding: 3px 12px;
    border-radius: 20px;
    letter-spacing: .4px;
    font-family: 'JetBrains Mono', monospace;
}}
.z-mono {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
}}
.z-ticker {{
    background: {_CARD};
    border: 1px solid {_SEP};
    border-radius: 12px;
    padding: 10px 14px;
    text-align: center;
    margin-bottom: 10px;
}}
.z-news-card {{
    background: {_CARD};
    border-radius: 12px;
    padding: 12px 15px;
    margin-bottom: 8px;
    border-left: 3px solid {_ORANGE};
    border: 1px solid {_SEP};
}}
.z-level-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid {_SEP};
}}
.z-glow-title {{
    font-size: 42px;
    font-weight: 800;
    letter-spacing: -1.5px;
    line-height: 1;
    text-shadow: 0 0 40px {_ORANGE}66;
}}
</style>
""", unsafe_allow_html=True)

# ── Plotly theme ──────────────────────────────────────────────────────────────
_PLOTLY = dict(
    template      = "plotly_dark",
    paper_bgcolor = _DARK,
    plot_bgcolor  = _CARD,
    margin        = dict(l=0, r=0, t=32, b=0),
    font          = dict(family="JetBrains Mono, monospace", color="#999", size=11),
    hovermode     = "x unified",
    hoverlabel    = dict(bgcolor=_CARD2, bordercolor=_SEP, font_color="#eee"),
    xaxis_rangeslider_visible = False,
    legend        = dict(orientation="h", y=1.02, font_size=11),
    xaxis         = dict(gridcolor=_SEP, gridwidth=.5),
    yaxis         = dict(gridcolor=_SEP, gridwidth=.5),
)

# ── Color helpers ─────────────────────────────────────────────────────────────
def _cc(v: float, pos=_GREEN, neg=_RED, neu="#888") -> str:
    return pos if v > 0 else neg if v < 0 else neu

def _rgba(hex6: str, a: float) -> str:
    h = hex6.lstrip("#")
    r,g,b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{a})"

def _badge(txt: str, color: str) -> str:
    return (f'<span class="z-badge" style="background:{_rgba(color.lstrip("#"),0.15)};'
            f'color:{color};border:.5px solid {_rgba(color.lstrip("#"),0.4)}">{txt}</span>')


# ══════════════════════════════════════════════════════════════════════════════
# §2  ACQUISITION DES DONNÉES — CACHE AGRESSIF + PARALLÈLE
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_prices(symbols: List[str]) -> Dict[str, Dict]:
    """Prix live — batch Yahoo Finance, cache 20s."""
    if not YF_OK or not symbols:
        return {}
    try:
        raw = yf.download(
            symbols if len(symbols) > 1 else symbols[0],
            period="5d", interval="1d", progress=False,
            auto_adjust=True,
            group_by="ticker" if len(symbols) > 1 else None,
            timeout=10,
        )
        if raw is None or raw.empty:
            return {}
        result = {}
        for sym in symbols:
            try:
                s = (raw[sym]
                     if len(symbols) > 1 and isinstance(raw.columns, pd.MultiIndex)
                     and sym in raw.columns.get_level_values(0)
                     else raw)
                c = float(s["Close"].dropna().iloc[-1])
                p = float(s["Close"].dropna().iloc[-2]) if len(s) > 1 else c
                chg = (c - p) / p * 100 if p else 0
                result[sym] = {
                    "price":   round(c, 4),
                    "chg":     round(chg, 3),
                    "high":    round(float(s["High"].dropna().iloc[-1]), 4),
                    "low":     round(float(s["Low"].dropna().iloc[-1]),  4),
                    "vol":     int(s["Volume"].dropna().iloc[-1]) if "Volume" in s.columns else 0,
                }
            except Exception:
                pass
        return result
    except Exception:
        return {}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_ohlcv(symbol: str, period: str = "6mo") -> pd.DataFrame:
    """OHLCV journalier — cache 5 minutes."""
    if not YF_OK:
        return pd.DataFrame()
    try:
        raw = yf.download(symbol, period=period, interval="1d",
                           progress=False, auto_adjust=True, timeout=12)
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)
        raw.columns = [c.title() for c in raw.columns]
        cols = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
        return raw[cols].dropna(subset=["Close"])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred(series_id: str) -> Optional[pd.Series]:
    """Série FRED — cache 1h."""
    if not REQ_OK:
        return None
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r   = requests.get(url, timeout=10)
        r.raise_for_status()
        df  = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        return df.dropna().set_index("date")["value"].tail(30)
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_macro() -> Dict:
    """Toutes les séries macro en parallèle — cache 1h."""
    SERIES = {
        "FEDFUNDS":     "Fed Funds",
        "DGS10":        "T10Y",
        "DGS2":         "T2Y",
        "UNRATE":       "Chômage US",
        "CPIAUCSL":     "CPI (inflation)",
        "WALCL":        "Bilan Fed",
        "BAMLC0A0CM":   "Spread IG",
        "BAMLH0A0HYM2": "Spread HY",
    }
    result = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {ex.submit(fetch_fred, sid): (sid, label)
                   for sid, label in SERIES.items()}
        for fut in as_completed(futures):
            sid, label = futures[fut]
            try:
                s = fut.result()
                if s is not None and not s.empty:
                    last = float(s.iloc[-1])
                    prev = float(s.iloc[-2]) if len(s) > 1 else last
                    result[label] = {
                        "value":   round(last, 4),
                        "prev":    round(prev, 4),
                        "change":  round(last - prev, 4),
                        "history": s.tolist(),
                    }
            except Exception:
                pass
    # Spread 10-2 dérivé
    t10 = result.get("T10Y", {}).get("value", 0) or 0
    t2  = result.get("T2Y",  {}).get("value", 0) or 0
    result["Spread 10-2"] = {
        "value":   round(t10 - t2, 3),
        "history": [],
        "change":  0,
    }
    return result


@st.cache_data(ttl=600, show_spinner=False)
def fetch_news() -> List[Dict]:
    """Flux RSS BCE — cache 10 minutes."""
    if not FP_OK:
        return []
    BCE_KW  = ["bce","ecb","taux","euribor","zone euro","inflation","lagarde",
                "banque centrale","rate","monetary"]
    sources = {
        "BCE":        "https://www.ecb.europa.eu/rss/press.html",
        "Reuters":    "https://feeds.reuters.com/reuters/businessNews",
        "Les Echos":  "https://www.lesechos.fr/feeds/rss/finance-marches.xml",
        "Le Monde":   "https://www.lemonde.fr/economie/rss_full.xml",
        "Yahoo Finance": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR",
    }
    BULL_W = ["hausse","croissance","record","profit","achat","rally","rise","growth","cut","easing"]
    BEAR_W = ["baisse","récession","inflation","crise","chute","sell","crash","hike","tightening"]
    arts = []
    for src, url in sources.items():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:4]:
                t  = (e.get("title","") or "").strip()
                if not t: continue
                tl = t.lower()
                s  = sum(1 for w in BULL_W if w in tl) - sum(1 for w in BEAR_W if w in tl)
                arts.append({
                    "title":     t[:100],
                    "source":    src,
                    "link":      e.get("link","#"),
                    "date":      e.get("published","")[:16],
                    "score":     s,
                    "sentiment": "🟢" if s>0 else "🔴" if s<0 else "⚪",
                    "bce":       any(w in tl for w in BCE_KW),
                })
            time.sleep(0.15)
        except Exception:
            pass
    arts.sort(key=lambda x: (x["bce"], abs(x["score"])), reverse=True)
    return arts


@st.cache_data(ttl=600, show_spinner=False)
def fetch_fear_greed() -> Dict:
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=7", timeout=6)
        d = r.json()["data"]
        return {"value": int(d[0]["value"]), "label": d[0]["value_classification"],
                "history": [int(x["value"]) for x in d]}
    except Exception:
        return {"value": 50, "label": "Neutral", "history": [50]*7}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_bce_rapport() -> Dict:
    """Rapport BCE complet — cache 5 minutes."""
    if not ENGINE_OK:
        return {}
    try:
        return RapportBCE().generer()
    except Exception as e:
        return {"erreur": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# §3  INDICATEURS TECHNIQUES (NATIFS — sans pandas_ta ni ta-lib)
# ══════════════════════════════════════════════════════════════════════════════

def _safe(v, default=0.0):
    if v is None: return default
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return default

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()

def _rma(s: pd.Series, n: int) -> pd.Series:
    a = 1/n; v = s.values.astype(float); o = np.full(len(v), np.nan)
    i0 = next((i for i,x in enumerate(v) if not np.isnan(x)), None)
    if i0 is None: return pd.Series(o, index=s.index)
    o[i0] = v[i0]
    for i in range(i0+1, len(v)):
        if not np.isnan(v[i]):
            o[i] = (o[i-1] if not np.isnan(o[i-1]) else v[i])*(1-a) + v[i]*a
    return pd.Series(o, index=s.index)

def calc_rsi(df: pd.DataFrame, n=14) -> float:
    d = df["Close"].diff()
    g = _rma(d.clip(lower=0), n)
    l = _rma((-d).clip(lower=0), n)
    r = 100 - 100/(1 + g/l.replace(0, np.nan))
    return _safe(r.dropna().iloc[-1] if not r.dropna().empty else 50, 50)

def calc_atr(df: pd.DataFrame, n=14) -> float:
    H,L,C = df["High"],df["Low"],df["Close"]
    tr = pd.concat([H-L,(H-C.shift()).abs(),(L-C.shift()).abs()],axis=1).max(axis=1)
    return _safe(_rma(tr,n).iloc[-1])

def calc_macd(df: pd.DataFrame) -> Dict:
    ml = _ema(df["Close"],12) - _ema(df["Close"],26)
    sl = _ema(ml,9)
    h  = ml - sl
    return {"line":_safe(ml.iloc[-1]),"signal":_safe(sl.iloc[-1]),"hist":_safe(h.iloc[-1])}

def calc_bbands(df: pd.DataFrame, n=20, mult=2.0) -> Dict:
    C  = df["Close"]
    m  = C.rolling(n).mean()
    s  = C.rolling(n).std(ddof=0)
    return {"upper":_safe((m+mult*s).iloc[-1]),"mid":_safe(m.iloc[-1]),"lower":_safe((m-mult*s).iloc[-1])}

def calc_adx(df: pd.DataFrame, n=14) -> float:
    H,L = df["High"],df["Low"]
    tr  = pd.concat([H-L,(H-df["Close"].shift()).abs(),(L-df["Close"].shift()).abs()],axis=1).max(axis=1)
    up,dn = H.diff(), -L.diff()
    pdm = pd.Series(np.where((up>dn)&(up>0), up, 0.0), index=H.index)
    ndm = pd.Series(np.where((dn>up)&(dn>0), dn, 0.0), index=H.index)
    atr14 = _rma(tr,n)
    pdi = 100*_rma(pdm,n)/atr14.replace(0,np.nan)
    ndi = 100*_rma(ndm,n)/atr14.replace(0,np.nan)
    dx  = 100*(pdi-ndi).abs()/(pdi+ndi).replace(0,np.nan)
    return _safe(_rma(dx,n).iloc[-1])

def calc_supertrend(df: pd.DataFrame, n=10, m=3.0) -> int:
    atr = _rma(pd.concat([df["High"]-df["Low"],(df["High"]-df["Close"].shift()).abs(),(df["Low"]-df["Close"].shift()).abs()],axis=1).max(axis=1),n)
    hl2 = (df["High"]+df["Low"])/2
    ub_r,lb_r = hl2+m*atr, hl2-m*atr
    C = df["Close"]
    ub,lb = ub_r.copy(),lb_r.copy()
    t = pd.Series(1,index=C.index,dtype=int)
    for i in range(1,len(C)):
        ub.iloc[i] = ub_r.iloc[i] if ub_r.iloc[i]<ub.iloc[i-1] or C.iloc[i-1]>ub.iloc[i-1] else ub.iloc[i-1]
        lb.iloc[i] = lb_r.iloc[i] if lb_r.iloc[i]>lb.iloc[i-1] or C.iloc[i-1]<lb.iloc[i-1] else lb.iloc[i-1]
        if t.iloc[i-1]==-1 and C.iloc[i]>ub.iloc[i]:   t.iloc[i]=1
        elif t.iloc[i-1]==1 and C.iloc[i]<lb.iloc[i]:  t.iloc[i]=-1
        else:                                             t.iloc[i]=t.iloc[i-1]
    return int(t.iloc[-1])

def calc_obv(df: pd.DataFrame) -> float:
    return _safe((np.sign(df["Close"].diff().fillna(0))*df["Volume"]).cumsum().iloc[-1])


# ══════════════════════════════════════════════════════════════════════════════
# §4  MOTEUR DE SIGNAL — COMPOSITE MULTI-MODÈLE
# ══════════════════════════════════════════════════════════════════════════════

def generate_signal(df: pd.DataFrame, macro: Dict, capital: float, risk_pct: float) -> Dict:
    """
    Signal composite : technique (50%) + macro (30%) + momentum (20%).
    Retourne décision, niveaux, sizing, raisons.
    """
    if df is None or df.empty or len(df) < 30:
        return {"signal":"ATTENDRE","force":0,"reasons":["Données insuffisantes"],
                "price":0,"stop":0,"tp":0,"rr":0,"units":0,"cost":0,"risk_eur":0,
                "rsi":50,"atr":0,"macd_h":0,"bb_pct":0.5,"adx":0,"supertrend":0}

    C      = df["Close"]
    price  = _safe(C.iloc[-1])
    atr    = calc_atr(df)
    rsi    = calc_rsi(df)
    macd   = calc_macd(df)
    bb     = calc_bbands(df)
    adx    = calc_adx(df)
    st_dir = calc_supertrend(df)
    bb_pct = (price-bb["lower"])/(bb["upper"]-bb["lower"]) if bb["upper"]!=bb["lower"] else .5

    ema20  = _safe(_ema(C,20).iloc[-1])
    ema50  = _safe(_ema(C,50).iloc[-1])
    ema200 = _safe(_ema(C,200).iloc[-1])
    sma200 = _safe(C.rolling(200).mean().iloc[-1])

    bull=0; bear=0; reasons=[]

    # ── Tendance EMA ──────────────────────────────────────────────────────────
    if ema20>ema50>ema200: bull+=2.5; reasons.append("⚡ EMA 20>50>200 — tendance haussière forte")
    elif ema20<ema50<ema200: bear+=2.5; reasons.append("💀 EMA 20<50<200 — tendance baissière forte")
    elif ema20>ema50: bull+=1
    else: bear+=1

    # ── Prix vs EMA200 ────────────────────────────────────────────────────────
    if price>ema200: bull+=1.5; reasons.append("👑 Prix > EMA200 — contexte macro haussier")
    else: bear+=1.5; reasons.append("⚔️ Prix < EMA200 — contexte macro baissier")

    # ── RSI ───────────────────────────────────────────────────────────────────
    if rsi<30:   bull+=2;   reasons.append(f"🔥 RSI {rsi:.0f} — zone survente, opportunité achat")
    elif rsi>70: bear+=2;   reasons.append(f"⚠️ RSI {rsi:.0f} — zone surachat, risque de repli")
    elif rsi<45: bull+=0.5
    elif rsi>55: bear+=0.5

    # ── MACD ─────────────────────────────────────────────────────────────────
    if macd["hist"]>0: bull+=1; reasons.append("🔮 MACD histogramme positif — momentum haussier")
    else:              bear+=1; reasons.append("🌩️ MACD histogramme négatif — momentum baissier")

    # ── Bollinger ─────────────────────────────────────────────────────────────
    if bb_pct<0.1:   bull+=1.5; reasons.append("📉 Prix proche BB basse — zone achat potentiel")
    elif bb_pct>0.9: bear+=1.5; reasons.append("📈 Prix proche BB haute — zone vente potentielle")

    # ── ADX (force tendance) ─────────────────────────────────────────────────
    if adx>25:
        if ema20>ema50: bull+=1
        else:           bear+=1

    # ── SuperTrend ───────────────────────────────────────────────────────────
    if st_dir==1:  bull+=1.5; reasons.append("⚡ SuperTrend haussier — signal de continuation")
    else:          bear+=1.5; reasons.append("🔻 SuperTrend baissier — pression vendeuse")

    # ── Macro ─────────────────────────────────────────────────────────────────
    spread = macro.get("Spread 10-2",{}).get("value",0.3) or 0.3
    fed    = macro.get("Fed Funds",  {}).get("value",4.0) or 4.0
    cpi    = macro.get("CPI (inflation)",{}).get("value",2.5) or 2.5
    hy_sp  = macro.get("Spread HY", {}).get("value",3.5) or 3.5

    if spread<-0.2:  bear+=2; reasons.append("🏛️ Courbe inversée — signal récession")
    elif spread>0.5: bull+=1
    if fed>5:        bear+=1; reasons.append("💰 Taux Fed >5% — environnement restrictif")
    if cpi>3:        bear+=0.5; reasons.append("📈 Inflation >3% — pression baissière")
    if hy_sp>5:      bear+=1; reasons.append("⚠️ Spreads HY élevés — stress crédit")

    # ── Décision ─────────────────────────────────────────────────────────────
    net   = bull - bear
    force = min(abs(net)/12, 1.0)

    if net>=3 and bull>bear:
        signal = "ACHETER"
        stop   = round(price - max(atr*2.0, price*0.015), 4)
        tp     = round(price + max(atr*4.0, price*0.030), 4)
    elif net<=-3 and bear>bull:
        signal = "VENDRE"
        stop   = round(price + max(atr*2.0, price*0.015), 4)
        tp     = round(price - max(atr*4.0, price*0.030), 4)
    else:
        signal = "ATTENDRE"
        stop   = round(price - atr*1.5, 4)
        tp     = round(price + atr*1.5, 4)
        if not reasons: reasons.append("⏸️ Marché neutre — aucune opportunité claire")

    rr   = round(abs(tp-price)/max(abs(stop-price),1e-9), 2)
    risk_amt = capital * risk_pct / 100
    dist     = abs(price-stop)
    units    = round(risk_amt/dist, 4) if dist>0 else 0
    cost     = round(units*price, 2)
    risk_eur = round(units*dist, 2)

    return {
        "signal": signal, "force": round(force,3),
        "reasons": reasons[:5], "price": price,
        "stop": stop, "tp": tp, "rr": rr,
        "units": units, "cost": cost, "risk_eur": risk_eur,
        "rsi": rsi, "atr": round(atr,4), "macd_h": round(macd["hist"],4),
        "bb_pct": round(bb_pct,3), "adx": round(adx,1),
        "supertrend": st_dir, "ema20": round(ema20,4),
        "ema50": round(ema50,4), "ema200": round(ema200,4),
        "bull_score": round(bull,1), "bear_score": round(bear,1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# §5  COMPOSANTS UI RÉUTILISABLES
# ══════════════════════════════════════════════════════════════════════════════

def ui_ticker_bar(prices: Dict[str, Dict], names: Dict[str,str]) -> None:
    symbols = [s for s in prices if prices[s]]
    if not symbols: return
    cols = st.columns(min(len(symbols), 6))
    for i, sym in enumerate(symbols[:6]):
        d  = prices[sym]
        v  = d.get("chg",0)
        cc = _GREEN if v>0 else _RED if v<0 else "#666"
        cols[i].markdown(f"""
        <div class="z-ticker">
          <div style="font-size:10px;color:#555;letter-spacing:.5px;text-transform:uppercase">
            {names.get(sym,sym)[:16]}</div>
          <div style="font-size:15px;font-weight:800;color:{_GOLD};
          font-family:'JetBrains Mono',monospace">{d.get('price',0):,.4f}</div>
          <div style="font-size:11px;font-weight:700;color:{cc}">{v:+.3f}%</div>
        </div>""", unsafe_allow_html=True)


def ui_signal_banner(sig: Dict) -> None:
    s      = sig["signal"]
    force  = sig["force"]
    cls    = {"ACHETER":"z-signal-buy","VENDRE":"z-signal-sell","ATTENDRE":"z-signal-wait"}[s]
    ic     = {"ACHETER":"🚀","VENDRE":"⬇","ATTENDRE":"⏸"}[s]
    col    = {"ACHETER":_GREEN,"VENDRE":_RED,"ATTENDRE":_ORANGE}[s]
    pct    = force*100

    st.markdown(f"""
    <div class="{cls}" style="margin-bottom:20px">
      <div style="font-size:11px;color:#555;text-transform:uppercase;
      letter-spacing:.9px;margin-bottom:8px">Décision algorithmique</div>
      <div style="display:flex;align-items:flex-start;
      justify-content:space-between;flex-wrap:wrap;gap:12px">
        <div>
          <div class="z-glow-title" style="color:{col}">{ic} {s}</div>
          <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
            {_badge(f"Score {sig['bull_score']:.1f}🟢 / {sig['bear_score']:.1f}🔴", col)}
            {_badge(f"RSI {sig['rsi']:.0f}", _BLUE)}
            {_badge(f"ADX {sig['adx']:.0f}", _GOLD)}
            {_badge(f"SuperTrend {'↑' if sig['supertrend']==1 else '↓'}", _GREEN if sig['supertrend']==1 else _RED)}
            {_badge(datetime.utcnow().strftime('%H:%M UTC'), '#444')}
          </div>
        </div>
        <div style="min-width:160px;text-align:right">
          <div style="font-size:11px;color:#444;margin-bottom:6px">CONFIANCE</div>
          <div style="background:#0A0A0A;border-radius:4px;height:8px;
          overflow:hidden;margin-bottom:4px">
            <div style="width:{pct:.0f}%;height:100%;background:{col}"></div>
          </div>
          <div style="font-size:20px;font-weight:800;color:{col};
          font-family:'JetBrains Mono',monospace">{pct:.0f}%</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)


def ui_levels(sig: Dict, capital: float) -> None:
    s   = sig["signal"]
    col = {"ACHETER":_GREEN,"VENDRE":_RED,"ATTENDRE":_ORANGE}[s]
    st.markdown(f"""
    <div class="z-card">
      <div style="font-size:11px;color:#555;text-transform:uppercase;
      letter-spacing:.8px;margin-bottom:14px">Niveaux & Sizing</div>
      <div class="z-level-row">
        <span style="color:#777;font-size:13px">Prix actuel</span>
        <span class="z-mono" style="color:{_GOLD}">{sig['price']:,.4f}</span>
      </div>
      <div class="z-level-row">
        <span style="color:#777;font-size:13px">Stop Loss</span>
        <span class="z-mono" style="color:{_RED}">{sig['stop']:,.4f}</span>
      </div>
      <div class="z-level-row">
        <span style="color:#777;font-size:13px">Take Profit</span>
        <span class="z-mono" style="color:{_GREEN}">{sig['tp']:,.4f}</span>
      </div>
      <div class="z-level-row">
        <span style="color:#777;font-size:13px">R:R Ratio</span>
        <span class="z-mono" style="color:{col}">{sig['rr']:.2f}x</span>
      </div>
      <div class="z-level-row">
        <span style="color:#777;font-size:13px">Taille position</span>
        <span class="z-mono" style="color:{col}">{sig['units']:.4f} unités</span>
      </div>
      <div class="z-level-row" style="border-bottom:none">
        <span style="color:#777;font-size:13px">Risque (€)</span>
        <span class="z-mono" style="color:{_ORANGE}">€{sig['risk_eur']:.2f}
          ({sig['risk_eur']/capital*100:.1f}%)</span>
      </div>
    </div>""", unsafe_allow_html=True)


def ui_score_bar(label: str, val: float, weight: str) -> None:
    pct = (val+1)/2*100
    c   = _GREEN if val>0.15 else _RED if val<-0.15 else _ORANGE
    st.markdown(f"""
    <div style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;margin-bottom:5px">
        <span style="font-size:13px;font-weight:700">{label}
          <span style="font-size:10px;color:#444;font-weight:400;
          margin-left:6px;font-family:'JetBrains Mono'">{weight}</span></span>
        <span style="font-family:'JetBrains Mono';font-size:15px;
        font-weight:800;color:{c}">{"↑" if val>0.15 else "↓" if val<-0.15 else "—"} {val:+.3f}</span>
      </div>
      <div style="background:#1A1A1A;border-radius:4px;height:6px;overflow:hidden">
        <div style="width:{pct:.0f}%;height:100%;background:{c}"></div>
      </div>
    </div>""", unsafe_allow_html=True)


def ui_macro_kpi(macro: Dict) -> None:
    items = [
        ("Fed Funds",       "Fed Funds %",         _ORANGE),
        ("T10Y",            "Taux 10Y US",          _BLUE),
        ("Spread 10-2",     "Spread 10-2Y",         _GREEN if (macro.get("Spread 10-2",{}).get("value",0) or 0)>0 else _RED),
        ("CPI (inflation)", "CPI (inflation)",      _RED if (macro.get("CPI (inflation)",{}).get("value",2) or 2)>3 else _GREEN),
        ("Chômage US",      "Chômage US %",         _ORANGE),
        ("Spread HY",       "Spread HY",            _RED if (macro.get("Spread HY",{}).get("value",3) or 3)>5 else _GOLD),
    ]
    cols = st.columns(3)
    for i, (key, label, color) in enumerate(items):
        d   = macro.get(key, {})
        val = d.get("value")
        chg = d.get("change", 0)
        if val is not None:
            cols[i%3].markdown(f"""
            <div class="z-card" style="border-top:2px solid {color}">
              <div style="font-size:10px;color:#555;text-transform:uppercase;
              letter-spacing:.7px;margin-bottom:6px">{label}</div>
              <div style="font-family:'JetBrains Mono';font-size:22px;
              font-weight:800;color:{color}">{val:.2f}</div>
              <div style="font-size:11px;color:{_cc(chg)};margin-top:4px;
              font-family:'JetBrains Mono'">{chg:+.4f}</div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# §6  GRAPHIQUES PLOTLY
# ══════════════════════════════════════════════════════════════════════════════

def chart_main(df: pd.DataFrame, sym: str, sig: Dict) -> go.Figure:
    C    = df["Close"]
    fig  = make_subplots(rows=3, cols=1, row_heights=[0.60,0.22,0.18],
                          shared_xaxes=True, vertical_spacing=0.02)

    # ── Candlesticks ──────────────────────────────────────────────────────────
    if "Open" in df.columns:
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=C, name=sym,
            increasing_line_color=_GREEN,
            decreasing_line_color=_RED,
            increasing_fillcolor="rgba(0,255,135,0.15)",
            decreasing_fillcolor="rgba(255,59,92,0.15)",
        ), row=1, col=1)

    # ── EMAs ──────────────────────────────────────────────────────────────────
    for n, col, dash in [(20,_GOLD,"solid"),(50,_ORANGE,"dot"),(200,_PURPLE,"dashdot")]:
        if len(C)>n:
            fig.add_trace(go.Scatter(x=df.index, y=_ema(C,n), mode="lines",
                                      name=f"EMA{n}", opacity=.75,
                                      line=dict(color=col,width=1.2,dash=dash)), row=1,col=1)

    # ── Bollinger ─────────────────────────────────────────────────────────────
    bm = C.rolling(20).mean(); bs = C.rolling(20).std(ddof=0)
    bu, bd = bm+2*bs, bm-2*bs
    fig.add_trace(go.Scatter(
        x=list(df.index)+list(df.index[::-1]),
        y=list(bu)+list(bd[::-1]),
        fill="toself", fillcolor="rgba(242,140,40,0.06)",
        line=dict(color="rgba(0,0,0,0)"), name="BB ±2σ",
    ), row=1,col=1)

    # ── Stop / TP ─────────────────────────────────────────────────────────────
    if sig["stop"]:
        fig.add_hline(y=sig["stop"], row=1,col=1, line_color=_RED,
                       line_dash="dash",line_width=1.2,
                       annotation_text=f"Stop {sig['stop']:.2f}",annotation_font_size=10)
    if sig["tp"]:
        fig.add_hline(y=sig["tp"], row=1,col=1, line_color=_GREEN,
                       line_dash="dash",line_width=1.2,
                       annotation_text=f"TP {sig['tp']:.2f}",annotation_font_size=10)

    # ── Volume ────────────────────────────────────────────────────────────────
    if "Volume" in df.columns:
        cv = [_GREEN if float(C.iloc[i])>=float(C.iloc[max(0,i-1)]) else _RED
               for i in range(len(df))]
        fig.add_trace(go.Bar(x=df.index,y=df["Volume"],name="Volume",
                              marker_color=cv,opacity=.4), row=2,col=1)

    # ── RSI ───────────────────────────────────────────────────────────────────
    d = C.diff(); ag=_rma(d.clip(lower=0),14); al=_rma((-d).clip(lower=0),14)
    rsi_s = 100 - 100/(1+ag/al.replace(0,np.nan))
    fig.add_trace(go.Scatter(x=df.index,y=rsi_s,mode="lines",name="RSI 14",
                              line=dict(color=_GOLD,width=1.5)), row=3,col=1)
    fig.add_hrect(y0=70,y1=100,row=3,col=1,fillcolor="rgba(255,59,92,0.08)",line_width=0)
    fig.add_hrect(y0=0,y1=30,row=3,col=1,fillcolor="rgba(0,255,135,0.08)",line_width=0)
    for lvl,lc in [(70,_RED),(30,_GREEN),(50,"#333")]:
        fig.add_hline(y=lvl,row=3,col=1,line_color=lc,line_dash="dash",line_width=.8,opacity=.5)

    kw = _PLOTLY.copy(); kw["height"]=580; kw["showlegend"]=True
    kw["title"]=f"{sym} · {len(df)} barres"
    fig.update_layout(**kw)
    fig.update_yaxes(showgrid=True,gridcolor=_SEP,gridwidth=.5)
    return fig


def chart_bce_history() -> go.Figure:
    if not ENGINE_OK:
        return go.Figure()
    hist  = AnalyseurTendancesBCE.HISTORIQUE_DECISIONS
    dates = [d["date"] for d in hist]
    taux  = [d["taux_depot"] for d in hist]
    bps_  = [d["bps"] for d in hist]
    dcs   = [_GREEN if b<0 else _RED if b>0 else _ORANGE for b in bps_]

    fig = make_subplots(rows=2,cols=1,row_heights=[0.65,0.35],
                         shared_xaxes=True,vertical_spacing=0.04)
    fig.add_trace(go.Scatter(x=dates,y=taux,mode="lines+markers",name="Taux dépôt BCE (%)",
        line=dict(color=_BLUE,width=2.5),
        marker=dict(color=dcs,size=11,line=dict(color=_DARK,width=1.5))), row=1,col=1)
    fig.add_hline(y=2.0,row=1,col=1,line_color=_ORANGE,line_dash="dash",line_width=1.2,
        annotation_text="Taux neutre ~2%",annotation_font_size=10)
    fig.add_hrect(y0=0,y1=2.0,row=1,col=1,fillcolor="rgba(0,255,135,0.04)",line_width=0)
    fig.add_hrect(y0=2.0,y1=5.5,row=1,col=1,fillcolor="rgba(255,59,92,0.04)",line_width=0)
    fig.add_trace(go.Bar(x=dates,y=bps_,name="Variation (bps)",
        marker_color=dcs,opacity=.75), row=2,col=1)

    kw=_PLOTLY.copy(); kw["height"]=420; kw["title"]="Cycle monétaire BCE (2022-2025)"
    fig.update_layout(**kw)
    return fig


def chart_macro_spread(macro: Dict) -> go.Figure:
    h = macro.get("Spread 10-2",{}).get("history",[])
    if not h: return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=h,mode="lines",name="Spread 10-2",
                              line=dict(color=_ORANGE,width=2)))
    fig.add_hline(y=0,line_color=_GOLD,line_dash="dash",
                   annotation_text="Inversion",annotation_font_size=10)
    fig.add_hrect(y0=min(h),y1=0,fillcolor="rgba(255,59,92,0.1)",line_width=0)
    fig.add_hrect(y0=0,y1=max(h) if max(h)>0 else .1,fillcolor="rgba(0,255,135,0.06)",line_width=0)
    kw=_PLOTLY.copy(); kw["height"]=240; kw["title"]="Spread 10-2 ans US"
    fig.update_layout(**kw)
    return fig


def chart_backtest(df: pd.DataFrame, sym: str, capital: float) -> go.Figure:
    if not ENGINE_OK or df is None or df.empty or len(df)<60:
        return go.Figure()
    C    = df["Close"].astype(float)
    decs = AnalyseurTendancesBCE.HISTORIQUE_DECISIONS
    sig_s= pd.Series(0, index=df.index)
    for i,dec in enumerate(decs):
        try:
            dt  = pd.Timestamp(dec["date"])
            nxt = pd.Timestamp(decs[i+1]["date"]) if i+1<len(decs) else df.index[-1]
            val = 1 if dec["decision"]=="BAISSE" else -1 if dec["decision"]=="HAUSSE" else 0
            sig_s[(df.index>=dt)&(df.index<nxt)] = val
        except Exception: pass

    ret   = C.pct_change()
    strat = sig_s.shift(1)*ret
    cum_s = (1+strat.fillna(0)).cumprod()*capital
    cum_bh= (1+ret.fillna(0)).cumprod()*capital

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index,y=cum_s,mode="lines",name="Stratégie BCE",
        line=dict(color=_BLUE,width=2.5),fill="tozeroy",fillcolor="rgba(0,194,255,0.06)"))
    fig.add_trace(go.Scatter(x=df.index,y=cum_bh,mode="lines",name="Buy & Hold",
        line=dict(color="#333",width=1.5,dash="dot")))

    DC = {"BAISSE":_GREEN,"STABLE":_ORANGE,"HAUSSE":_RED}
    for dec in decs:
        try:
            dt = pd.Timestamp(dec["date"])
            if dt>=df.index[0]:
                fig.add_vline(x=dt,line_color=DC.get(dec["decision"],"#333"),
                    line_width=1,line_dash="dash",opacity=.35,
                    annotation_text=dec["decision"][:1],annotation_font_size=9)
        except Exception: pass

    kw=_PLOTLY.copy(); kw["height"]=380
    kw["title"]=f"Stratégie BCE vs Buy&Hold · {sym} · Capital €{capital:,.0f}"
    kw["yaxis_title"]="Capital (€)"
    fig.update_layout(**kw)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# §7  ONGLETS DU DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def tab_signal(cfg: Dict) -> None:
    """Onglet Décision & Signaux."""
    sym = cfg["symbol"]

    with st.spinner("Chargement..."):
        df  = fetch_ohlcv(sym, cfg["period"])
        mac = fetch_all_macro()
        sig = generate_signal(df, mac, cfg["capital"], cfg["risk_pct"])

    # ── Scores orchestrateur (si disponible) ──────────────────────────────────
    orch_scores = {"technique":0,"macro":0,"news":0,"total":0}
    orch_dec    = "ATTENDRE"
    if ORCH_OK:
        try:
            orch_dec, orch_conf, orch_scores = compute_decision()
        except Exception:
            pass

    # ── Bannière décision ─────────────────────────────────────────────────────
    ui_signal_banner(sig)

    # ── KPIs ─────────────────────────────────────────────────────────────────
    k1,k2,k3,k4 = st.columns(4)
    k1.metric("RSI 14",   f"{sig['rsi']:.1f}",
               "Survente" if sig["rsi"]<30 else "Surachat" if sig["rsi"]>70 else "Neutre")
    k2.metric("ATR",      f"{sig['atr']:.4f}", "Volatilité journalière")
    k3.metric("ADX",      f"{sig['adx']:.1f}",
               "Tendance forte" if sig["adx"]>25 else "Pas de tendance")
    k4.metric("MACD Hist",f"{sig['macd_h']:+.4f}",
               "Haussier" if sig["macd_h"]>0 else "Baissier")

    st.markdown("")
    col_chart, col_right = st.columns([3,1])

    with col_chart:
        if not df.empty and PLOTLY_OK:
            st.plotly_chart(chart_main(df, sym, sig), use_container_width=True)
        elif df.empty:
            st.warning("Données Yahoo Finance indisponibles pour ce symbole.")

    with col_right:
        ui_levels(sig, cfg["capital"])

        # Raisons
        st.markdown(f"""
        <div class="z-card">
          <div style="font-size:11px;color:#555;text-transform:uppercase;
          letter-spacing:.8px;margin-bottom:12px">Raisons du signal</div>
          {"".join(f'<div style="font-size:12px;color:#aaa;padding:5px 0;border-bottom:1px solid {_SEP}">{r}</div>' for r in sig["reasons"])}
        </div>""", unsafe_allow_html=True)

        # Scores orchestrateur
        if ORCH_OK:
            st.markdown("""
            <div style="font-size:11px;color:#555;text-transform:uppercase;
            letter-spacing:.8px;margin:14px 0 8px">Scores composites</div>""",
            unsafe_allow_html=True)
            ui_score_bar("Technique",  orch_scores.get("technique",0), "40%")
            ui_score_bar("Macro BCE",  orch_scores.get("macro",0),     "40%")
            ui_score_bar("Actualités", orch_scores.get("news",0),      "20%")


def tab_bce(cfg: Dict) -> None:
    """Onglet Tendances BCE."""
    with st.spinner("Analyse BCE..."):
        rapport = fetch_bce_rapport()

    t  = rapport.get("tendances_bce",{})
    pr = t.get("probabilites",{})
    cal= rapport.get("prochaine_reunion",{})

    if not t:
        st.warning("bce_engine.py requis dans le même dossier pour l'analyse BCE.")
        if ENGINE_OK:
            st.info("Rapport BCE en cours de génération...")
        return

    sc = _GREEN if t.get("stance")=="ACCOMMODANT" else _RED if t.get("stance")=="RESTRICTIF" else _ORANGE

    # Bannière phase
    st.markdown(f"""
    <div class="z-card" style="border-left:4px solid {sc};margin-bottom:18px">
      <div style="font-size:11px;color:#555;text-transform:uppercase;
      letter-spacing:.9px;margin-bottom:8px">Phase du cycle monétaire BCE</div>
      <div style="font-size:28px;font-weight:800;color:{sc};margin-bottom:10px">
        {t.get('phase_cycle','N/A')}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        {_badge("Stance : "+t.get("stance","N/A"), sc)}
        {_badge("Biais : "+t.get("biais_marche","N/A"), _GREEN if t.get("biais_marche","")=="HAUSSIER" else _RED if t.get("biais_marche","")=="BAISSIER" else _ORANGE)}
        {_badge("Confiance : "+str(t.get("confiance_pct",0))+"%", _BLUE)}
      </div>
    </div>""", unsafe_allow_html=True)

    # KPIs BCE
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Taux dépôt BCE",  f"{t.get('taux_actuel',0):.2f}%",
               f"Neutre : {t.get('taux_neutre_estime',2):.2f}%")
    c2.metric("Inflation HICP",  f"{t.get('inflation_hicp',0):.1f}%",
               t.get("inflation_situation",""))
    c3.metric("Taux réel",       f"{t.get('taux_reel',0):.2f}%",
               t.get("taux_reel_situation",""))
    c4.metric("Euribor 3M",      f"{t.get('euribor_3m',0):.3f}%",
               "Taux interbancaire")

    # Probabilités
    st.markdown("##### Prochaine décision BCE")
    b=pr.get("baisse_pct",33); s=pr.get("stable_pct",34); h=pr.get("hausse_pct",33)
    st.markdown(f"""
    <div class="z-card">
      <div style="display:flex;height:12px;border-radius:6px;overflow:hidden;margin-bottom:8px">
        <div style="width:{b:.0f}%;background:{_GREEN}"></div>
        <div style="width:{s:.0f}%;background:{_ORANGE}"></div>
        <div style="width:{h:.0f}%;background:{_RED}"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:12px;font-weight:700;
      font-family:'JetBrains Mono',monospace">
        <span style="color:{_GREEN}">↓ Baisse {b:.0f}%</span>
        <span style="color:{_ORANGE}">— Stable {s:.0f}%</span>
        <span style="color:{_RED}">↑ Hausse {h:.0f}%</span>
      </div>
    </div>""", unsafe_allow_html=True)

    col_mv, col_cal = st.columns([2,1])
    pc = _GREEN if t.get("prochain_mvt_prevu","")=="BAISSE" else _RED if t.get("prochain_mvt_prevu","")=="HAUSSE" else _ORANGE
    with col_mv:
        st.markdown(f"""
        <div class="z-card" style="border-top:2px solid {pc}">
          <div style="font-size:11px;color:#555;margin-bottom:6px">Mouvement attendu</div>
          <div style="font-size:26px;font-weight:800;color:{pc}">
            {t.get("prochain_mvt_prevu","?")} ({t.get("bps_prevu",0):+d}bps)</div>
          <div style="font-size:12px;color:#555;margin-top:6px">{t.get("tendance_recente","")}</div>
        </div>""", unsafe_allow_html=True)
    with col_cal:
        if cal:
            try:
                days=(datetime.strptime(cal.get("date_reunion","2099-01-01"),"%Y-%m-%d").date()-date.today()).days
                jj=f"J-{days}" if days>0 else "Aujourd'hui"
            except Exception: jj=""
            st.markdown(f"""
            <div class="z-card" style="text-align:center;border-top:2px solid {_BLUE}">
              <div style="font-size:10px;color:#555;margin-bottom:6px">Prochaine réunion BCE</div>
              <div style="font-size:18px;font-weight:800;color:{_BLUE}">{cal.get('date_reunion','N/A')}</div>
              <div style="font-size:30px;font-weight:800;margin-top:4px">{jj}</div>
            </div>""", unsafe_allow_html=True)

    # Graphique historique
    if PLOTLY_OK:
        st.plotly_chart(chart_bce_history(), use_container_width=True)

    # Tableau décisions
    rows=[]
    for d in AnalyseurTendancesBCE.HISTORIQUE_DECISIONS[-10:][::-1]:
        rows.append({"Date":d["date"],"Taux (%)":f"{d['taux_depot']:.2f}",
                      "Décision":d["decision"],f"Variation":f"{d['bps']:+d}bps",
                      "Contexte":d.get("contexte","")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def tab_news_impact() -> None:
    """Onglet News & Impact."""
    with st.spinner("Chargement..."):
        news    = fetch_news()
        rapport = fetch_bce_rapport()

    col_n, col_i = st.columns([3,2])

    with col_n:
        st.markdown("##### Veille BCE — Actualités temps réel")
        if not news:
            st.info("pip3 install feedparser — nécessaire pour les actualités RSS")
        else:
            scores    = [a["score"] for a in news]
            avg       = sum(scores)/len(scores) if scores else 0
            norm      = min(max((avg+3)/6*100, 0), 100)
            sc        = _GREEN if norm>60 else _RED if norm<40 else _ORANGE
            sl        = "HAUSSIER" if norm>60 else "BAISSIER" if norm<40 else "NEUTRE"
            bce_n     = sum(1 for a in news if a.get("bce"))
            k1,k2,k3  = st.columns(3)
            k1.metric("Sentiment", f"{norm:.0f}/100", sl)
            k2.metric("Articles",  str(len(news)), "analysés")
            k3.metric("BCE direct",str(bce_n), "mentions")
            st.markdown("")
            for art in news[:10]:
                cc = _GREEN if art["sentiment"]=="🟢" else _RED if art["sentiment"]=="🔴" else "#555"
                st.markdown(f"""
                <a href="{art['link']}" target="_blank" style="text-decoration:none">
                <div class="z-news-card" style="border-left-color:{cc}">
                  <div style="font-size:13px;font-weight:600;color:#ddd;margin-bottom:5px">
                    {art['title']}</div>
                  <div style="font-size:11px;color:#555">
                    {art['source']} · {art['date']}
                    <span style="margin-left:8px;font-size:13px">{art['sentiment']}</span>
                    {"<span style='margin-left:6px;font-size:10px;color:" + _BLUE + "'>📍 BCE</span>" if art.get("bce") else ""}
                  </div>
                </div></a>""", unsafe_allow_html=True)

    with col_i:
        if rapport and "impact_marches" in rapport:
            i   = rapport["impact_marches"]
            pro = i.get("prochain_mouvement","STABLE")
            pc  = _GREEN if pro=="BAISSE" else _RED if pro=="HAUSSE" else _ORANGE
            bps = i.get("bps_attendus",0)
            st.markdown(f"""
            <div class="z-card" style="border-top:2px solid {pc};margin-bottom:14px">
              <div style="font-size:10px;color:#555;margin-bottom:6px">Scénario analysé</div>
              <div style="font-size:22px;font-weight:800;color:{pc}">
                {pro} ({bps:+d}bps)</div>
            </div>""", unsafe_allow_html=True)

            imp  = i.get("impact_j1_attendu",{})
            st.markdown("**Impact indices J+1**")
            for idx,d in imp.get("actions_zone_euro",{}).items():
                v=d.get("impact_pct",0); cc=_GREEN if v>0 else _RED
                st.markdown(f"""<div style="display:flex;justify-content:space-between;
                align-items:center;padding:8px 0;border-bottom:1px solid {_SEP}">
                  <span style="font-size:13px;color:#aaa">{idx}</span>
                  <span style="font-family:'JetBrains Mono';font-size:15px;
                  font-weight:800;color:{cc}">{"▲" if v>0 else "▼"} {abs(v):.1f}%</span>
                </div>""", unsafe_allow_html=True)

            st.markdown("<br>**Secteurs**", unsafe_allow_html=True)
            for sec,d in list(imp.get("secteurs",{}).items())[:4]:
                v=d.get("impact_pct",0); cc=_GREEN if v>0 else _RED
                st.markdown(f"""<div style="display:flex;justify-content:space-between;
                padding:6px 0;border-bottom:1px solid {_SEP}">
                  <span style="font-size:12px;color:#aaa">{sec}</span>
                  <span style="font-family:'JetBrains Mono';font-size:13px;
                  font-weight:700;color:{cc}">{"▲" if v>0 else "▼"} {abs(v):.1f}%</span>
                </div>""", unsafe_allow_html=True)

            mt = i.get("horizon_3_6_mois",{})
            if mt:
                st.markdown("<br>**Horizon 3-6 mois**", unsafe_allow_html=True)
                k1,k2 = st.columns(2)
                k1.metric("Stoxx 50",mt.get("stoxx50_3m","N/A"))
                k2.metric("EUR/USD", mt.get("eur_usd_3m","N/A"))
        else:
            st.info("bce_engine.py requis pour l'analyse d'impact")

        # Fear & Greed
        fg = fetch_fear_greed()
        fv = fg.get("value",50)
        fc = _GREEN if fv>60 else _RED if fv<40 else _ORANGE
        st.markdown(f"""
        <div class="z-card" style="text-align:center;margin-top:14px">
          <div style="font-size:10px;color:#555;text-transform:uppercase;
          letter-spacing:.8px;margin-bottom:8px">Fear & Greed Index</div>
          <div style="font-size:42px;font-weight:800;color:{fc};
          font-family:'JetBrains Mono',monospace">{fv}</div>
          <div style="font-size:14px;color:{fc};margin-top:4px">{fg.get('label','')}</div>
        </div>""", unsafe_allow_html=True)


def tab_macro() -> None:
    """Onglet Macro."""
    with st.spinner("Chargement FRED..."):
        mac = fetch_all_macro()

    ui_macro_kpi(mac)

    # Courbe des taux
    if PLOTLY_OK:
        st.markdown("##### Spread 10-2 ans US (inversion = signal récession)")
        st.plotly_chart(chart_macro_spread(mac), use_container_width=True)

    with st.expander("📖 Comprendre la courbe des taux"):
        st.markdown(f"""
        La **courbe des taux** compare le rendement obligataire US à 10 ans et 2 ans.
        - Spread **positif** → économie saine, contexte favorable aux actions
        - Spread **négatif** (inversé) → signal historique de récession à 12-18 mois
        - Valeur actuelle : **{mac.get('Spread 10-2',{}).get('value','N/A')}%**
        """)


def tab_screener(cfg: Dict) -> None:
    """Onglet Screener multi-actifs."""
    UNIVERSE = {
        "^STOXX50E":"Euro Stoxx 50","^FCHI":"CAC 40","^GDAXI":"DAX 40",
        "^IBEX":"IBEX 35","^AEX":"AEX","EURUSD=X":"EUR/USD",
        "EURGBP=X":"EUR/GBP","BZ=F":"Brent","NG=F":"Gaz","GC=F":"Or",
        "SPY":"S&P 500","QQQ":"Nasdaq 100","BTC-USD":"Bitcoin",
    }
    wl = cfg.get("watchlist", list(UNIVERSE.keys())[:6])

    with st.spinner(f"Analyse de {len(wl)} actifs..."):
        prices = fetch_live_prices(wl)
        mac    = fetch_all_macro()

    rows = []
    for sym in wl:
        d  = prices.get(sym,{})
        if not d: continue
        df = fetch_ohlcv(sym,"3mo")
        si = generate_signal(df, mac, cfg["capital"], cfg["risk_pct"]) if not df.empty else {}
        rows.append({
            "Actif":     UNIVERSE.get(sym,sym),
            "Prix":      f"{d.get('price',0):,.4f}",
            "Var%":      f"{d.get('chg',0):+.3f}%",
            "Signal":    si.get("signal","—"),
            "Confiance": f"{si.get('force',0)*100:.0f}%",
            "RSI":       f"{si.get('rsi',0):.1f}",
            "ADX":       f"{si.get('adx',0):.1f}",
            "R:R":       f"{si.get('rr',0):.2f}x",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Performance comparative
    if PLOTLY_OK and len(wl)>1:
        st.markdown("##### Performance comparative (base 100)")
        fig = go.Figure()
        pal = [_BLUE,_GREEN,_GOLD,_ORANGE,_PURPLE,_RED,"#00FFD0","#FF00AA"]
        for i,sym in enumerate(wl[:6]):
            df = fetch_ohlcv(sym,cfg["period"])
            if df.empty: continue
            norm = df["Close"]/df["Close"].iloc[0]*100-100
            fig.add_trace(go.Scatter(x=df.index,y=norm,mode="lines",
                                      name=UNIVERSE.get(sym,sym)[:16],
                                      line=dict(color=pal[i%len(pal)],width=1.8)))
        fig.add_hline(y=0,line_color="#222",line_dash="dash",opacity=.5)
        kw=_PLOTLY.copy(); kw["height"]=360; kw["yaxis_title"]="Return (%)"
        fig.update_layout(**kw)
        st.plotly_chart(fig, use_container_width=True)


def tab_backtest_tab(cfg: Dict) -> None:
    """Onglet Backtest stratégie BCE."""
    sym = cfg["symbol"]
    cap = cfg["capital"]
    st.info(f"Stratégie : LONG après baisse BCE · SHORT après hausse · Capital €{cap:,}")

    if not ENGINE_OK:
        st.warning("bce_engine.py requis"); return

    df  = fetch_ohlcv(sym, "3y" if cfg["period"] in ["1y","2y","3y"] else "2y")
    if df is None or df.empty or len(df)<60:
        st.warning("Données insuffisantes"); return

    C     = df["Close"].astype(float)
    decs  = AnalyseurTendancesBCE.HISTORIQUE_DECISIONS
    sig_s = pd.Series(0, index=df.index)
    for i,dec in enumerate(decs):
        try:
            dt  = pd.Timestamp(dec["date"])
            nxt = pd.Timestamp(decs[i+1]["date"]) if i+1<len(decs) else df.index[-1]
            val = 1 if dec["decision"]=="BAISSE" else -1 if dec["decision"]=="HAUSSE" else 0
            sig_s[(df.index>=dt)&(df.index<nxt)] = val
        except Exception: pass

    ret   = C.pct_change()
    strat = sig_s.shift(1)*ret
    cum_s = (1+strat.fillna(0)).cumprod()*cap
    cum_bh= (1+ret.fillna(0)).cumprod()*cap
    ret_s = (cum_s.iloc[-1]/cap-1)*100
    ret_bh= (cum_bh.iloc[-1]/cap-1)*100
    alpha = ret_s - ret_bh
    sh    = float(strat.mean()/strat.std()*(252**.5)) if strat.std()>0 else 0
    cm    = cum_s; pk=cm.cummax()
    mdd   = float(((cm-pk)/pk).min()*100)
    wins  = strat[strat>0]; losses=strat[strat<0]
    wr    = len(wins)/(len(wins)+len(losses)) if (len(wins)+len(losses))>0 else 0

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Stratégie BCE", f"{ret_s:+.2f}%",   f"{alpha:+.2f}% alpha")
    c2.metric("Buy & Hold",    f"{ret_bh:+.2f}%")
    c3.metric("Alpha",         f"{alpha:+.2f}%",    "Surperf." if alpha>0 else "Sous-perf.")
    c4.metric("Sharpe",        f"{sh:.2f}")
    c5.metric("Win Rate",      f"{wr:.1%}")
    c6.metric("Max Drawdown",  f"{mdd:.2f}%")

    if PLOTLY_OK:
        st.plotly_chart(chart_backtest(df,sym,cap), use_container_width=True)
        st.caption("🟢 Vert=baisse BCE (long) · 🟡 Orange=stable · 🔴 Rouge=hausse (short)")


# ══════════════════════════════════════════════════════════════════════════════
# §8  RAPPORT MARKDOWN EXPORTABLE
# ══════════════════════════════════════════════════════════════════════════════

def build_report(sym: str, sig: Dict, mac: Dict, capital: float, risk_pct: float) -> str:
    s = sig.get("signal","ATTENDRE"); p = sig.get("price",0)
    spread = mac.get("Spread 10-2",{}).get("value","N/A")
    fed    = mac.get("Fed Funds",  {}).get("value","N/A")
    cpi    = mac.get("CPI (inflation)",{}).get("value","N/A")
    order = (f"`ACHETER  {sig['units']:.4f} unités @ {p:.4f} | Stop {sig['stop']:.4f} | TP {sig['tp']:.4f}`"
             if s=="ACHETER" else
             f"`VENDRE   {sig['units']:.4f} unités @ {p:.4f} | Stop {sig['stop']:.4f} | TP {sig['tp']:.4f}`"
             if s=="VENDRE" else "`ATTENDRE — rester en cash`")
    return f"""# ⚡ THE ZEDICUS — Rapport d'analyse
**Actif** : {sym.upper()}  
**Date** : {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC  
**Prix** : {p:.4f}  

## Signal : {s} ({sig.get('force',0)*100:.0f}% confiance)
{chr(10).join("- " + r for r in sig.get("reasons",[]))}

## Indicateurs techniques
| Indicateur | Valeur | Interprétation |
|---|---|---|
| RSI 14 | {sig.get('rsi',0):.1f} | {"Survente" if sig.get("rsi",50)<30 else "Surachat" if sig.get("rsi",50)>70 else "Neutre"} |
| ATR | {sig.get('atr',0):.4f} | Volatilité journalière |
| ADX | {sig.get('adx',0):.1f} | {"Tendance forte" if sig.get("adx",0)>25 else "Pas de tendance"} |
| MACD Hist | {sig.get('macd_h',0):+.4f} | {"Haussier" if sig.get("macd_h",0)>0 else "Baissier"} |
| EMA 20/50/200 | {sig.get('ema20',0):.4f} / {sig.get('ema50',0):.4f} / {sig.get('ema200',0):.4f} | Tendance |
| SuperTrend | {"Haussier ↑" if sig.get("supertrend",0)==1 else "Baissier ↓"} | Direction |

## Contexte macro
- **Spread 10-2 ans** : {spread} {"⚠️ INVERSÉ" if isinstance(spread,(int,float)) and spread<-0.2 else "✅ Normal"}
- **Fed Funds** : {fed}%
- **Inflation CPI** : {cpi}%

## Ordre recommandé
{order}

**Sizing** :
- Capital : €{capital:.0f} | Risque : {risk_pct}%
- Taille : {sig.get('units',0):.4f} unités  
- Coût : €{sig.get('cost',0):.2f} | Risque : €{sig.get('risk_eur',0):.2f}
- R:R Ratio : {sig.get('rr',0):.2f}x

---
*⚠️ Analyse à titre indicatif. Le trading comporte des risques.*
"""


# ══════════════════════════════════════════════════════════════════════════════
# §9  SIDEBAR & MAIN
# ══════════════════════════════════════════════════════════════════════════════

def build_sidebar() -> Dict:
    SYMBOLS = {
        "^STOXX50E":"Euro Stoxx 50","^FCHI":"CAC 40","^GDAXI":"DAX 40",
        "^IBEX":"IBEX 35","^AEX":"AEX","EURUSD=X":"EUR/USD",
        "EURGBP=X":"EUR/GBP","EURJPY=X":"EUR/JPY","BZ=F":"Brent",
        "NG=F":"Gaz naturel","GC=F":"Or","SPY":"S&P 500",
        "QQQ":"Nasdaq 100","BTC-USD":"Bitcoin","ETH-USD":"Ethereum",
    }

    with st.sidebar:
        st.markdown(f"""
        <div style="text-align:center;padding:16px 0 20px">
          <div style="font-size:36px">⚡</div>
          <div style="font-size:20px;font-weight:800;color:{_GOLD};
          letter-spacing:-1px;margin-top:6px">THE ZEDICUS</div>
          <div style="font-size:11px;color:#444;margin-top:4px">
            BCE · Zone Euro · Temps réel</div>
        </div>
        <hr style="margin:0 0 16px">""", unsafe_allow_html=True)

        st.markdown("##### 📊 Actif principal")
        sym = st.selectbox("", list(SYMBOLS.keys()),
                            format_func=lambda x: SYMBOLS.get(x,x))

        st.markdown("##### 🌐 Watchlist")
        wl = st.multiselect("", list(SYMBOLS.keys()),
                              default=["^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F"],
                              format_func=lambda x: SYMBOLS.get(x,x))

        st.markdown("##### ⏱️ Historique")
        period = st.select_slider("", ["3mo","6mo","1y","2y","3y"], value="6mo")

        st.markdown("##### 💶 Capital & Risque")
        capital  = st.number_input("Capital (€)", min_value=10, max_value=100_000,
                                    value=100, step=10)
        risk_pct = st.slider("Risque par trade (%)", 0.5, 5.0, 2.0, 0.5)

        st.markdown("---")
        if st.button("🔄 Actualiser", use_container_width=True):
            st.cache_data.clear(); st.rerun()

        st.markdown(f"""
        <div style="font-size:10px;color:#333;margin-top:10px;line-height:1.8">
          {"✅" if ENGINE_OK else "❌"} bce_engine<br>
          {"✅" if ORCH_OK else "❌"} orchestrator<br>
          {"✅" if YF_OK else "❌"} yfinance<br>
          {"✅" if FP_OK else "❌"} feedparser<br>
          {datetime.utcnow():%Y-%m-%d %H:%M} UTC
        </div>""", unsafe_allow_html=True)

    return dict(symbol=sym, watchlist=wl or ["^STOXX50E"],
                period=period, capital=capital, risk_pct=risk_pct,
                names=SYMBOLS)


def main() -> None:
    # Nettoyage au premier lancement
    if "cleaned" not in st.session_state:
        removed = _cleanup()
        if removed:
            st.toast(f"🗑️ {len(removed)} ancien(s) fichier(s) supprimé(s)", icon="✅")
        st.session_state.cleaned = True

    cfg = build_sidebar()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
    margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid {_SEP}">
      <div>
        <div style="display:flex;align-items:center;gap:12px">
          <span style="font-size:36px">⚡</span>
          <div>
            <div style="font-size:28px;font-weight:800;color:{_GOLD};
            letter-spacing:-1.5px;line-height:1">THE ZEDICUS</div>
            <div style="font-size:12px;color:#444;margin-top:2px">
              <span style="background:rgba(0,255,135,.12);color:{_GREEN};
              padding:2px 8px;border-radius:10px;font-weight:700;
              font-size:10px;margin-right:8px">● LIVE</span>
              BCE Zone Euro · Données Yahoo Finance · RSS ·
              {datetime.utcnow():%Y-%m-%d %H:%M} UTC
            </div>
          </div>
        </div>
      </div>
      <div style="text-align:right;font-size:10px;color:#333">
        {"✅ Engine" if ENGINE_OK else "❌ Engine"} ·
        {"✅ Orch." if ORCH_OK else "❌ Orch."}<br>
        Python {sys.version.split()[0]}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Ticker bar ────────────────────────────────────────────────────────────
    wl_prices = fetch_live_prices(cfg["watchlist"][:5])
    ui_ticker_bar(wl_prices, cfg["names"])
    st.markdown("")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "⚡ Signal & Décision",
        "🏦 Tendances BCE",
        "📰 News & Impact",
        "🌍 Macro",
        "🔍 Screener",
        "🔁 Backtest BCE",
        "📄 Rapport Export",
    ])

    with tabs[0]: tab_signal(cfg)
    with tabs[1]: tab_bce(cfg)
    with tabs[2]: tab_news_impact()
    with tabs[3]: tab_macro()
    with tabs[4]: tab_screener(cfg)
    with tabs[5]: tab_backtest_tab(cfg)

    with tabs[6]:
        st.markdown("### Exporter le rapport d'analyse")
        df  = fetch_ohlcv(cfg["symbol"], cfg["period"])
        mac = fetch_all_macro()
        sig = generate_signal(df, mac, cfg["capital"], cfg["risk_pct"])
        rpt = build_report(cfg["symbol"], sig, mac, cfg["capital"], cfg["risk_pct"])
        st.markdown(rpt)
        st.download_button(
            "📥 Télécharger (Markdown)",
            rpt,
            file_name=f"zedicus_{cfg['symbol']}_{datetime.utcnow():%Y%m%d_%H%M}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    st.markdown(f"""
    <div style="text-align:center;padding:16px 0 0;margin-top:20px;
    font-size:10px;color:#333;border-top:1px solid {_SEP}">
      THE ZEDICUS · Sources : Yahoo Finance · BCE SDMX · FRED · RSS ·
      ⚠️ Indicatif uniquement — Pas de conseil financier
    </div>""", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
