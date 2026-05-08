#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  config.py — Configuration centralisée THE ZEDICUS v2                       ║
║  Tous les paramètres · Clés API · Intervalles de cache · Symboles           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  USAGE :                                                                     ║
║    from config import CFG, SYMBOLS, MODULES, RSS_SOURCES, get_env           ║
║                                                                              ║
║  COMMANDES :                                                                 ║
║    python3 config.py              # Affiche la configuration active         ║
║    python3 config.py --check      # Vérifie les clés API                   ║
║    python3 config.py --env        # Génère le fichier .env template         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, argparse
from pathlib  import Path
from datetime import datetime
from typing   import Dict, Any, Optional

# ── Charger .env si disponible ────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════════════════════
# §1  PARAMÈTRES GLOBAUX
# ══════════════════════════════════════════════════════════════════════════════

CFG: Dict[str, Any] = {

    # ── Application ───────────────────────────────────────────────────────────
    "APP_NAME":         "THE ZEDICUS v2",
    "APP_VERSION":      "2.0.0",
    "APP_ICON":         "⚡",
    "DEBUG":            os.getenv("DEBUG", "false").lower() == "true",

    # ── Capital & risque par défaut ───────────────────────────────────────────
    "DEFAULT_CAPITAL":  float(os.getenv("CAPITAL", "1000")),
    "DEFAULT_RISK_PCT": float(os.getenv("RISK_PCT", "2.0")),
    "DEFAULT_SYMBOL":   os.getenv("DEFAULT_SYMBOL", "^STOXX50E"),
    "DEFAULT_PERIOD":   os.getenv("DEFAULT_PERIOD", "6mo"),

    # ── Cache TTL (secondes) ──────────────────────────────────────────────────
    "TTL_PRICES_LIVE":  int(os.getenv("TTL_PRICES",   "20")),    # prix live
    "TTL_OHLCV":        int(os.getenv("TTL_OHLCV",    "300")),   # bougies 5min
    "TTL_RSS":          int(os.getenv("TTL_RSS",       "600")),   # actualités 10min
    "TTL_FRED":         int(os.getenv("TTL_FRED",      "3600")),  # FRED 1h
    "TTL_BCE":          int(os.getenv("TTL_BCE",       "3600")),  # BCE SDMX 1h
    "TTL_CRYPTO":       int(os.getenv("TTL_CRYPTO",    "120")),   # crypto 2min
    "TTL_FEAR_GREED":   int(os.getenv("TTL_FG",        "600")),   # fear&greed 10min
    "TTL_WEATHER":      int(os.getenv("TTL_WEATHER",   "900")),   # météo 15min
    "TTL_GEO":          int(os.getenv("TTL_GEO",       "3600")),  # géoloc 1h
    "TTL_RATES":        int(os.getenv("TTL_RATES",     "1800")),  # taux change 30min
    "TTL_WEIGHTS":      int(os.getenv("TTL_WEIGHTS",   "600")),   # pondérations 10min
    "TTL_SIGNAL":       int(os.getenv("TTL_SIGNAL",    "60")),    # signal composite 1min

    # ── Mise à jour automatique ───────────────────────────────────────────────
    "AUTO_REFRESH_SEC": int(os.getenv("AUTO_REFRESH",  "300")),   # refresh interface 5min
    "UPDATE_INTERVAL":  int(os.getenv("UPDATE_INTERVAL","60")),   # updater boucle 1min
    "MAX_ARTICLES":     int(os.getenv("MAX_ARTICLES",   "60")),   # articles max analysés

    # ── Base de données locale ────────────────────────────────────────────────
    "DB_PATH":          os.getenv("DB_PATH", "data/zedicus_cache.db"),
    "DB_BACKUP_HOURS":  int(os.getenv("DB_BACKUP_HOURS", "24")),  # backup toutes les 24h

    # ── Réseau ────────────────────────────────────────────────────────────────
    "REQUEST_TIMEOUT":  int(os.getenv("REQUEST_TIMEOUT", "10")),
    "MAX_RSS_WORKERS":  int(os.getenv("MAX_RSS_WORKERS",  "8")),
    "MAX_FRED_WORKERS": int(os.getenv("MAX_FRED_WORKERS", "6")),

    # ── Seuils de signal ──────────────────────────────────────────────────────
    "SIGNAL_BUY_THRESHOLD":  float(os.getenv("SIGNAL_BUY",  "0.30")),
    "SIGNAL_SELL_THRESHOLD": float(os.getenv("SIGNAL_SELL", "-0.30")),

    # ── Logging ───────────────────────────────────────────────────────────────
    "LOG_DIR":          os.getenv("LOG_DIR", "logs"),
    "LOG_LEVEL":        os.getenv("LOG_LEVEL", "INFO"),
    "LOG_MAX_BYTES":    int(os.getenv("LOG_MAX_BYTES", str(5*1024*1024))),  # 5MB
    "LOG_BACKUP_COUNT": int(os.getenv("LOG_BACKUP_COUNT", "3")),
}


# ══════════════════════════════════════════════════════════════════════════════
# §2  CLÉS API
# ══════════════════════════════════════════════════════════════════════════════

API_KEYS: Dict[str, Optional[str]] = {
    # ── Requises pour fonctionnalités avancées (toutes GRATUITES) ─────────────
    "OPENWEATHER":   os.getenv("OPENWEATHER_API_KEY"),    # openweathermap.org — gratuit 60/min
    "NEWSAPI":       os.getenv("NEWSAPI_KEY"),             # newsapi.org — gratuit 100/jour
    "ALPHA_VANTAGE": os.getenv("ALPHA_VANTAGE_KEY"),       # alphavantage.co — gratuit 25/jour
    "FINNHUB":       os.getenv("FINNHUB_KEY"),             # finnhub.io — gratuit 60/min
    "FRED":          os.getenv("FRED_API_KEY"),            # fred.stlouisfed.org — gratuit illimité

    # ── Optionnelles (premium) ────────────────────────────────────────────────
    "BLOOMBERG":     os.getenv("BLOOMBERG_API_KEY"),       # bloomberg.com/professional
    "REFINITIV":     os.getenv("REFINITIV_KEY"),           # refinitiv.com (ex Thomson Reuters)
    "POLYGON":       os.getenv("POLYGON_KEY"),             # polygon.io — 5 requêtes/min gratuit
}

def get_env(key: str, default: Any = None) -> Any:
    """Récupère une variable d'environnement avec fallback."""
    return os.getenv(key, default)

def has_key(service: str) -> bool:
    """Vérifie si une clé API est configurée."""
    return bool(API_KEYS.get(service))


# ══════════════════════════════════════════════════════════════════════════════
# §3  SYMBOLES DE MARCHÉ
# ══════════════════════════════════════════════════════════════════════════════

SYMBOLS: Dict[str, Dict] = {

    # ── Indices zone euro ─────────────────────────────────────────────────────
    "^STOXX50E": {"name":"Euro Stoxx 50",   "type":"index", "region":"EU",  "currency":"EUR"},
    "^FCHI":     {"name":"CAC 40",          "type":"index", "region":"FR",  "currency":"EUR"},
    "^GDAXI":    {"name":"DAX 40",          "type":"index", "region":"DE",  "currency":"EUR"},
    "^IBEX":     {"name":"IBEX 35",         "type":"index", "region":"ES",  "currency":"EUR"},
    "^AEX":      {"name":"AEX (Pays-Bas)",  "type":"index", "region":"NL",  "currency":"EUR"},
    "^FTSEMIB.MI":{"name":"FTSE MIB",       "type":"index", "region":"IT",  "currency":"EUR"},
    "^SSMI":     {"name":"SMI (Suisse)",    "type":"index", "region":"CH",  "currency":"CHF"},

    # ── Indices US ────────────────────────────────────────────────────────────
    "^GSPC":     {"name":"S&P 500",         "type":"index", "region":"US",  "currency":"USD"},
    "^IXIC":     {"name":"Nasdaq 100",      "type":"index", "region":"US",  "currency":"USD"},
    "^DJI":      {"name":"Dow Jones",       "type":"index", "region":"US",  "currency":"USD"},
    "^RUT":      {"name":"Russell 2000",    "type":"index", "region":"US",  "currency":"USD"},

    # ── Forex ─────────────────────────────────────────────────────────────────
    "EURUSD=X":  {"name":"EUR/USD",         "type":"forex", "region":"FX",  "currency":"USD"},
    "EURGBP=X":  {"name":"EUR/GBP",         "type":"forex", "region":"FX",  "currency":"GBP"},
    "EURJPY=X":  {"name":"EUR/JPY",         "type":"forex", "region":"FX",  "currency":"JPY"},
    "EURCHF=X":  {"name":"EUR/CHF",         "type":"forex", "region":"FX",  "currency":"CHF"},
    "EURCNY=X":  {"name":"EUR/CNY",         "type":"forex", "region":"FX",  "currency":"CNY"},
    "DX-Y.NYB":  {"name":"Dollar Index",    "type":"forex", "region":"US",  "currency":"USD"},

    # ── Obligations ───────────────────────────────────────────────────────────
    "ZN=F":      {"name":"T-Note 10Y Fut.", "type":"bond",  "region":"US",  "currency":"USD"},
    "ZB=F":      {"name":"T-Bond 30Y Fut.", "type":"bond",  "region":"US",  "currency":"USD"},
    "^TNX":      {"name":"Taux 10Y US",     "type":"rate",  "region":"US",  "currency":"USD"},
    "^IRX":      {"name":"Taux 3M US",      "type":"rate",  "region":"US",  "currency":"USD"},

    # ── Matières premières ────────────────────────────────────────────────────
    "BZ=F":      {"name":"Brent Crude",     "type":"commodity","region":"GL","currency":"USD"},
    "CL=F":      {"name":"WTI Crude",       "type":"commodity","region":"US","currency":"USD"},
    "NG=F":      {"name":"Gaz naturel",     "type":"commodity","region":"US","currency":"USD"},
    "GC=F":      {"name":"Or",              "type":"commodity","region":"GL","currency":"USD"},
    "SI=F":      {"name":"Argent",          "type":"commodity","region":"GL","currency":"USD"},
    "HG=F":      {"name":"Cuivre",          "type":"commodity","region":"GL","currency":"USD"},
    "ZW=F":      {"name":"Blé",             "type":"commodity","region":"GL","currency":"USD"},
    "ZC=F":      {"name":"Maïs",            "type":"commodity","region":"GL","currency":"USD"},

    # ── Crypto ────────────────────────────────────────────────────────────────
    "BTC-USD":   {"name":"Bitcoin",         "type":"crypto", "region":"GL", "currency":"USD"},
    "ETH-USD":   {"name":"Ethereum",        "type":"crypto", "region":"GL", "currency":"USD"},
    "SOL-USD":   {"name":"Solana",          "type":"crypto", "region":"GL", "currency":"USD"},

    # ── Volatilité / Risque ───────────────────────────────────────────────────
    "^VIX":      {"name":"VIX (peur US)",   "type":"vol",   "region":"US",  "currency":"USD"},
    "^VSTOXX":   {"name":"VSTOXX (peur EU)","type":"vol",   "region":"EU",  "currency":"EUR"},

    # ── ETFs BCE ──────────────────────────────────────────────────────────────
    "SX5EEX.DE": {"name":"iShares Stoxx50", "type":"etf",   "region":"EU",  "currency":"EUR"},
    "EWQ":       {"name":"iShares France",  "type":"etf",   "region":"FR",  "currency":"USD"},
    "EWG":       {"name":"iShares Germany", "type":"etf",   "region":"DE",  "currency":"USD"},
}

# Watchlist par défaut
DEFAULT_WATCHLIST = [
    "^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F","^VIX","GC=F","BTC-USD"
]

# Screener par défaut
DEFAULT_SCREENER = [
    "^STOXX50E","^FCHI","^GDAXI","^GSPC","^IXIC",
    "EURUSD=X","BZ=F","GC=F","BTC-USD","ETH-USD"
]

def get_symbols_by_type(asset_type: str) -> Dict:
    return {k:v for k,v in SYMBOLS.items() if v["type"]==asset_type}

def get_symbol_name(sym: str) -> str:
    return SYMBOLS.get(sym,{}).get("name",sym)


# ══════════════════════════════════════════════════════════════════════════════
# §4  SOURCES RSS
# ══════════════════════════════════════════════════════════════════════════════

RSS_SOURCES: Dict[str, Dict] = {
    # ── Banques centrales officielles ─────────────────────────────────────────
    "BCE Officiel":     {"url":"https://www.ecb.europa.eu/rss/press.html",
                          "category":"monetaire", "priority":10, "lang":"en"},
    "Fed Reserve":      {"url":"https://www.federalreserve.gov/feeds/press_all.xml",
                          "category":"monetaire", "priority":10, "lang":"en"},
    "BNS":              {"url":"https://www.snb.ch/en/rss/news",
                          "category":"monetaire", "priority":7,  "lang":"en"},
    "BoE":              {"url":"https://www.bankofengland.co.uk/rss/publications",
                          "category":"monetaire", "priority":7,  "lang":"en"},

    # ── Finance internationale ────────────────────────────────────────────────
    "Reuters Finance":  {"url":"https://feeds.reuters.com/reuters/businessNews",
                          "category":"macro",     "priority":9,  "lang":"en"},
    "FT Markets":       {"url":"https://www.ft.com/rss/home/europe",
                          "category":"macro",     "priority":8,  "lang":"en"},
    "Bloomberg Mkts":   {"url":"https://feeds.bloomberg.com/markets/news.rss",
                          "category":"macro",     "priority":9,  "lang":"en"},

    # ── France ────────────────────────────────────────────────────────────────
    "Les Echos":        {"url":"https://www.lesechos.fr/feeds/rss/finance-marches.xml",
                          "category":"macro",     "priority":8,  "lang":"fr"},
    "Le Monde Eco":     {"url":"https://www.lemonde.fr/economie/rss_full.xml",
                          "category":"macro",     "priority":7,  "lang":"fr"},
    "Boursorama":       {"url":"https://www.boursorama.com/bourse/actualites/rss.phtml",
                          "category":"technique", "priority":6,  "lang":"fr"},

    # ── Investing / Trading ───────────────────────────────────────────────────
    "Investing.com":    {"url":"https://www.investing.com/rss/news_301.rss",
                          "category":"technique", "priority":8,  "lang":"en"},
    "Yahoo Finance":    {"url":"https://feeds.finance.yahoo.com/rss/2.0/headline?s=^STOXX50E&region=FR",
                          "category":"technique", "priority":7,  "lang":"fr"},

    # ── Géopolitique ─────────────────────────────────────────────────────────
    "BBC Business":     {"url":"https://feeds.bbci.co.uk/news/business/rss.xml",
                          "category":"geopolitique","priority":7, "lang":"en"},
    "Google Géopol":    {"url":"https://news.google.com/rss/search?q=geopolitics+finance&hl=fr&gl=FR&ceid=FR:fr",
                          "category":"geopolitique","priority":6, "lang":"fr"},

    # ── Obligations / Crédit ──────────────────────────────────────────────────
    "WSJ Markets":      {"url":"https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
                          "category":"obligations","priority":7,  "lang":"en"},
}

def get_rss_by_category(cat: str) -> Dict:
    return {k:v for k,v in RSS_SOURCES.items() if v.get("category")==cat}

def get_rss_urls() -> Dict[str, str]:
    return {k:v["url"] for k,v in RSS_SOURCES.items()}


# ══════════════════════════════════════════════════════════════════════════════
# §5  MODULES DE SCORING (identiques à zedicus_v2.py)
# ══════════════════════════════════════════════════════════════════════════════

MODULES: Dict[str, Dict] = {
    "macro":         {
        "label": "📊 Macro",
        "color": "#00FF87",
        "min_w": 0.05, "max_w": 0.35,
        "description": "PIB, inflation, chômage, dette publique",
        "sources": ["FRED", "Reuters", "Les Echos"],
        "keywords": [
            "pib","gdp","inflation","chômage","unemployment","croissance",
            "recession","cpi","pce","dette","deficit","ipc","hicp",
        ]
    },
    "monetaire":     {
        "label": "🏦 Pol. Monétaire",
        "color": "#00C2FF",
        "min_w": 0.05, "max_w": 0.35,
        "description": "BCE, Fed, BoE — taux, QE/QT, forward guidance",
        "sources": ["BCE Officiel","Fed Reserve","BNS","BoE"],
        "keywords": [
            "bce","ecb","fed","taux","rate","pivot","lagarde","powell","qe","qt",
            "assouplissement","resserrement","banque centrale","monetary","euribor",
            "hiking","cutting","baisse taux","hausse taux","forward guidance",
        ]
    },
    "obligations":   {
        "label": "💵 Obligations",
        "color": "#F28C28",
        "min_w": 0.05, "max_w": 0.25,
        "description": "Spreads, courbe des taux, marchés crédit",
        "sources": ["FRED", "Bloomberg", "WSJ", "FT"],
        "keywords": [
            "bond","obligation","treasury","bund","oat","spread","yield","courbe",
            "inversion","t10y","t2y","dette souveraine","crédit","high yield","btp",
        ]
    },
    "saisonnalite":  {
        "label": "🗓️ Saisonnalité",
        "color": "#FF6B6B",
        "min_w": 0.03, "max_w": 0.15,
        "description": "Patterns calendaires historiques S&P 500",
        "sources": ["Interne"],
        "keywords": [
            "saisonnalité","seasonal","janvier","effet","calendrier","trimestre",
            "q1","q2","q3","q4","dividende","window dressing","reporting",
        ]
    },
    "geopolitique":  {
        "label": "🌍 Géopolitique",
        "color": "#A855F7",
        "min_w": 0.05, "max_w": 0.25,
        "description": "Conflits, sanctions, élections, énergie",
        "sources": ["BBC","Google Géopol","Reuters"],
        "keywords": [
            "guerre","war","conflit","ukraine","russie","chine","china","iran",
            "moyen-orient","sanctions","tariff","election","opep","opec","énergie",
        ]
    },
    "technique":     {
        "label": "📈 Graphiques/TA",
        "color": "#FFD700",
        "min_w": 0.15, "max_w": 0.40,
        "description": "RSI, MACD, EMA, Bollinger, ADX, SuperTrend",
        "sources": ["Yahoo Finance","yfinance"],
        "keywords": [
            "rsi","macd","support","resistance","breakout","tendance","trend",
            "bollinger","ema","momentum","volume","survente","surachat",
        ]
    },
    "volumes":       {
        "label": "📦 Volumes Trades",
        "color": "#06B6D4",
        "min_w": 0.03, "max_w": 0.15,
        "description": "Volume, OBV, flux institutionnels, order flow",
        "sources": ["Yahoo Finance","yfinance"],
        "keywords": [
            "volume","liquidité","flux","flow","institutionnel","retail",
            "open interest","futures","put/call ratio","order flow",
        ]
    },
    "hedge_funds":   {
        "label": "🐋 Hedges Funds",
        "color": "#F97316",
        "min_w": 0.03, "max_w": 0.15,
        "description": "COT, positioning, smart money, dark pools",
        "sources": ["CFTC COT","barchart.com","Alternative.me"],
        "keywords": [
            "hedge fund","cot","commitment of traders","speculative",
            "net long","net short","whale","institutional","smart money","dark pool",
        ]
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# §6  FRED — SÉRIES ÉCONOMIQUES
# ══════════════════════════════════════════════════════════════════════════════

FRED_SERIES: Dict[str, Dict] = {
    "FEDFUNDS":     {"label":"Fed Funds",        "unit":"%",   "module":"monetaire"},
    "DGS10":        {"label":"T10Y US",          "unit":"%",   "module":"obligations"},
    "DGS2":         {"label":"T2Y US",           "unit":"%",   "module":"obligations"},
    "DGS30":        {"label":"T30Y US",          "unit":"%",   "module":"obligations"},
    "T10Y2Y":       {"label":"Spread 10-2 US",   "unit":"%",   "module":"obligations"},
    "CPIAUCSL":     {"label":"CPI US (YoY)",     "unit":"",    "module":"macro"},
    "PCEPI":        {"label":"PCE US",           "unit":"",    "module":"macro"},
    "UNRATE":       {"label":"Chômage US",       "unit":"%",   "module":"macro"},
    "GDP":          {"label":"PIB US",           "unit":"Mds$","module":"macro"},
    "GDPC1":        {"label":"PIB Réel US",      "unit":"%",   "module":"macro"},
    "WALCL":        {"label":"Bilan Fed",        "unit":"Mds$","module":"monetaire"},
    "BAMLC0A0CM":   {"label":"Spread IG",        "unit":"%",   "module":"obligations"},
    "BAMLH0A0HYM2": {"label":"Spread HY",        "unit":"%",   "module":"obligations"},
    "DEXUSEU":      {"label":"USD/EUR",          "unit":"",    "module":"macro"},
    "VIXCLS":       {"label":"VIX (FRED)",       "unit":"",    "module":"geopolitique"},
    "MORTGAGE30US": {"label":"Taux Immobilier US","unit":"%",  "module":"macro"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §7  SAISONNALITÉ — PATTERNS HISTORIQUES
# ══════════════════════════════════════════════════════════════════════════════

SEASONAL_PATTERNS: Dict[int, Dict] = {
    1:  {"biais":+0.50, "label":"Effet Janvier",      "note":"Rally traditionnel, flux institutionnels début d'année"},
    2:  {"biais":+0.20, "label":"Reporting Q4",       "note":"Saison des résultats Q4 — focus sur les surprises"},
    3:  {"biais":-0.10, "label":"Fin Q1",             "note":"Prise de profits institutionnels, window dressing Q1"},
    4:  {"biais":+0.30, "label":"Pré Sell in May",    "note":"Dernier rally de printemps avant la rotation estivale"},
    5:  {"biais":-0.40, "label":"Sell in May",        "note":"'Sell in May and Go Away' — rotation vers cash"},
    6:  {"biais":-0.20, "label":"Début été",          "note":"Volumes faibles, volatilité accrue, prudence"},
    7:  {"biais":-0.10, "label":"Été",                "note":"Marchés calmes, liquidité réduite"},
    8:  {"biais":-0.30, "label":"Creux estival",      "note":"Août : mois de volatilité imprévisible (Black Mondays)"},
    9:  {"biais":-0.50, "label":"Septembre Effect",   "note":"Pire mois statistique S&P 500 historiquement"},
    10: {"biais":+0.10, "label":"Octobre Surprise",   "note":"Retour institutionnels — peut être violent dans les deux sens"},
    11: {"biais":+0.60, "label":"Novembre Rally",     "note":"Meilleur mois historique actions — flux 401k / retraite"},
    12: {"biais":+0.50, "label":"Santa Claus Rally",  "note":"Window dressing fin d'année + effet janvier anticipé"},
}


# ══════════════════════════════════════════════════════════════════════════════
# §8  PONDÉRATIONS STATIQUES (fallback si pas d'articles RSS)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_WEIGHTS: Dict[str, float] = {
    "macro":        0.15,
    "monetaire":    0.20,
    "obligations":  0.15,
    "saisonnalite": 0.05,
    "geopolitique": 0.10,
    "technique":    0.25,
    "volumes":      0.05,
    "hedge_funds":  0.05,
}


# ══════════════════════════════════════════════════════════════════════════════
# §9  ENVIRONNEMENT & VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def check_environment() -> Dict[str, bool]:
    """Vérifie les dépendances Python et les clés API."""
    checks = {}

    # Packages Python
    for pkg in ["streamlit","plotly","pandas","numpy","yfinance",
                 "requests","feedparser","dotenv"]:
        try:
            __import__(pkg.replace("-","_"))
            checks[f"pkg_{pkg}"] = True
        except ImportError:
            checks[f"pkg_{pkg}"] = False

    # Clés API
    for name, key in API_KEYS.items():
        checks[f"api_{name.lower()}"] = bool(key)

    # Dossiers
    for d in ["data","logs","backups"]:
        Path(d).mkdir(exist_ok=True)
        checks[f"dir_{d}"] = True

    # Fichiers locaux
    for f in ["bce_engine.py","orchestrator.py"]:
        checks[f"file_{f}"] = (Path(__file__).parent / f).exists()

    return checks


def generate_env_template() -> str:
    """Génère le contenu du fichier .env template."""
    return f"""# ══════════════════════════════════════════════════════════════════════
# THE ZEDICUS v2 — Configuration (.env)
# Généré le {datetime.utcnow():%Y-%m-%d %H:%M} UTC
# ══════════════════════════════════════════════════════════════════════

# ── Application ─────────────────────────────────────────────────────
DEBUG=false
CAPITAL=1000
RISK_PCT=2.0
DEFAULT_SYMBOL=^STOXX50E
DEFAULT_PERIOD=6mo

# ── Clés API gratuites (toutes optionnelles sauf mention) ────────────

# OpenWeatherMap — météo (gratuit, 60 req/min)
# Créer sur : https://openweathermap.org/api
OPENWEATHER_API_KEY=

# NewsAPI — actualités françaises (gratuit, 100 req/jour)
# Créer sur : https://newsapi.org
NEWSAPI_KEY=

# Alpha Vantage — données intraday haute fréquence (gratuit, 25 req/jour)
# Créer sur : https://alphavantage.co
ALPHA_VANTAGE_KEY=

# Finnhub — news + sentiment + calendrier résultats (gratuit, 60 req/min)
# Créer sur : https://finnhub.io
FINNHUB_KEY=

# FRED — accès JSON avancé (gratuit, illimité avec clé)
# Créer sur : https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=

# ── Cache TTL (secondes) ────────────────────────────────────────────
TTL_PRICES=20
TTL_OHLCV=300
TTL_RSS=600
TTL_FRED=3600
TTL_WEIGHTS=600
TTL_SIGNAL=60

# ── Mise à jour automatique ─────────────────────────────────────────
AUTO_REFRESH=300
UPDATE_INTERVAL=60
MAX_ARTICLES=60

# ── Base de données ─────────────────────────────────────────────────
DB_PATH=data/zedicus_cache.db

# ── Réseau ──────────────────────────────────────────────────────────
REQUEST_TIMEOUT=10
MAX_RSS_WORKERS=8
"""


def print_config() -> None:
    """Affiche la configuration active dans le terminal."""
    checks = check_environment()
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  {CFG['APP_NAME']} v{CFG['APP_VERSION']} — Configuration active
╚══════════════════════════════════════════════════════════════╝

  PARAMÈTRES PRINCIPAUX
  ─────────────────────────────────────────
  Capital défaut      : €{CFG['DEFAULT_CAPITAL']:,.0f}
  Risque/trade        : {CFG['DEFAULT_RISK_PCT']}%
  Actif défaut        : {CFG['DEFAULT_SYMBOL']}
  Signal Achat seuil  : {CFG['SIGNAL_BUY_THRESHOLD']:+.2f}
  Signal Vente seuil  : {CFG['SIGNAL_SELL_THRESHOLD']:+.2f}
  Auto-refresh        : {CFG['AUTO_REFRESH_SEC']}s
  Debug               : {CFG['DEBUG']}

  TTL CACHE (secondes)
  ─────────────────────────────────────────
  Prix live           : {CFG['TTL_PRICES_LIVE']}s
  OHLCV               : {CFG['TTL_OHLCV']}s
  RSS actualités      : {CFG['TTL_RSS']}s
  FRED macro          : {CFG['TTL_FRED']}s
  Pondérations        : {CFG['TTL_WEIGHTS']}s
  Signal composite    : {CFG['TTL_SIGNAL']}s

  CLÉS API
  ─────────────────────────────────────────""")
    for name, key in API_KEYS.items():
        status = "✅ configurée" if key else "⚪ non configurée (optionnelle)"
        print(f"  {name:15s} : {status}")

    print(f"""
  DÉPENDANCES PYTHON
  ─────────────────────────────────────────""")
    for k,v in checks.items():
        if k.startswith("pkg_"):
            icon = "✅" if v else "❌"
            print(f"  {icon} {k[4:]}")

    print(f"""
  FICHIERS LOCAUX
  ─────────────────────────────────────────""")
    for k,v in checks.items():
        if k.startswith("file_"):
            icon = "✅" if v else "⚠️ "
            print(f"  {icon} {k[5:]} {'(présent)' if v else '(optionnel)'}")

    print(f"""
  SOURCES RSS : {len(RSS_SOURCES)} sources configurées
  SYMBOLES    : {len(SYMBOLS)} actifs disponibles
  MODULES     : {len(MODULES)} modules de scoring
  FRED        : {len(FRED_SERIES)} séries économiques
""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="config.py — Configuration THE ZEDICUS v2")
    parser.add_argument("--check",  action="store_true", help="Vérifier l'environnement")
    parser.add_argument("--env",    action="store_true", help="Générer .env template")
    parser.add_argument("--json",   action="store_true", help="Export JSON")
    args = parser.parse_args()

    if args.env:
        env_content = generate_env_template()
        env_path    = Path(".env.example")
        env_path.write_text(env_content)
        print(f"✅ .env.example généré : {env_path.resolve()}")
        print(env_content)
    elif args.json:
        print(json.dumps({"config":CFG,"modules":list(MODULES.keys()),
                           "symbols":len(SYMBOLS),"rss":len(RSS_SOURCES)},
                          indent=2, default=str))
    else:
        print_config()
