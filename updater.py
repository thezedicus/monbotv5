#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  updater.py — Mise à jour automatique des données THE ZEDICUS v2             ║
║  Scheduler · Watchdog · Health Check · Cache warm-up                         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES :                                                                 ║
║    python3 updater.py                     # Lancer le scheduler continu      ║
║    python3 updater.py --once              # Mise à jour unique et quitter    ║
║    python3 updater.py --health            # Vérification santé du système    ║
║    python3 updater.py --warmup            # Préchauffer le cache             ║
║    python3 updater.py --cron              # Installer les tâches cron        ║
║    python3 updater.py --status            # Afficher le statut updater       ║
║    python3 updater.py --clear-cache       # Vider et reconstruire le cache   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, json, signal, logging, argparse, threading, subprocess
import traceback
from datetime   import datetime, timedelta
from pathlib    import Path
from typing     import Dict, List, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

# ── Import modules locaux ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

try:
    from config import CFG, MODULES, DEFAULT_WATCHLIST, FRED_SERIES, get_rss_urls
    UPDATE_INTERVAL  = CFG["UPDATE_INTERVAL"]
    REQUEST_TIMEOUT  = CFG["REQUEST_TIMEOUT"]
    LOG_DIR          = Path(CFG["LOG_DIR"])
    DB_BACKUP_HOURS  = CFG["DB_BACKUP_HOURS"]
except ImportError:
    UPDATE_INTERVAL  = 60
    REQUEST_TIMEOUT  = 10
    LOG_DIR          = Path("logs")
    DB_BACKUP_HOURS  = 24

try:
    from data_cache import DataCache, get_cache
    CACHE_OK = True
except ImportError:
    CACHE_OK = False

LOG_DIR.mkdir(parents=True, exist_ok=True)
Path("data").mkdir(exist_ok=True)
Path("backups").mkdir(exist_ok=True)

# ── Logging rotatif ───────────────────────────────────────────────────────────
from logging.handlers import RotatingFileHandler
logger = logging.getLogger("Updater")
logger.setLevel(logging.INFO)
_fh = RotatingFileHandler(LOG_DIR/"updater.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
logger.addHandler(_fh)
logger.addHandler(_sh)


# ══════════════════════════════════════════════════════════════════════════════
# §1  TÂCHES DE MISE À JOUR
# ══════════════════════════════════════════════════════════════════════════════

class UpdateTask:
    """Représente une tâche de mise à jour planifiée."""
    def __init__(self, name: str, fn: Callable, interval_sec: int,
                  priority: int = 5, description: str = ""):
        self.name         = name
        self.fn           = fn
        self.interval_sec = interval_sec
        self.priority     = priority
        self.description  = description
        self.last_run     = 0.0
        self.last_success = 0.0
        self.run_count    = 0
        self.error_count  = 0
        self.last_error   = ""
        self.last_duration= 0.0

    def is_due(self) -> bool:
        return time.time() - self.last_run >= self.interval_sec

    def run(self) -> bool:
        t0 = time.time()
        self.last_run = t0
        self.run_count += 1
        try:
            result = self.fn()
            self.last_success  = time.time()
            self.last_duration = time.time() - t0
            logger.info(f"  ✅ {self.name} ({self.last_duration:.1f}s)")
            return True
        except Exception as e:
            self.error_count += 1
            self.last_error   = str(e)[:200]
            self.last_duration = time.time() - t0
            logger.warning(f"  ❌ {self.name}: {e}")
            return False

    def to_dict(self) -> Dict:
        return {
            "name":          self.name,
            "description":   self.description,
            "interval_sec":  self.interval_sec,
            "last_run":      datetime.fromtimestamp(self.last_run).strftime("%H:%M:%S") if self.last_run else "jamais",
            "last_success":  datetime.fromtimestamp(self.last_success).strftime("%H:%M:%S") if self.last_success else "jamais",
            "run_count":     self.run_count,
            "error_count":   self.error_count,
            "last_error":    self.last_error,
            "last_duration": f"{self.last_duration:.1f}s",
            "next_run_in":   f"{max(0, self.interval_sec-(time.time()-self.last_run)):.0f}s",
        }


# ══════════════════════════════════════════════════════════════════════════════
# §2  FONCTIONS DE MISE À JOUR
# ══════════════════════════════════════════════════════════════════════════════

def _update_prices() -> Dict:
    """Mise à jour des prix live (watchlist complète)."""
    try:
        import yfinance as yf
        symbols = DEFAULT_WATCHLIST
        raw = yf.download(
            symbols, period="5d", interval="1d", progress=False,
            auto_adjust=True, group_by="ticker", timeout=12
        )
        if raw is None or raw.empty:
            return {}
        result = {}
        cache  = get_cache() if CACHE_OK else None
        for sym in symbols:
            try:
                s = (raw[sym] if isinstance(raw.columns, __import__("pandas").MultiIndex)
                       and sym in raw.columns.get_level_values(0) else raw)
                c = float(s["Close"].dropna().iloc[-1])
                p = float(s["Close"].dropna().iloc[-2]) if len(s) > 1 else c
                v = int(s["Volume"].dropna().iloc[-1]) if "Volume" in s.columns else 0
                chg = (c-p)/p*100 if p else 0
                result[sym] = {"price":round(c,4),"chg":round(chg,3),"vol":v}
                if cache:
                    cache.save_price(sym, c, chg, v)
            except Exception:
                pass
        if cache:
            cache.set("prices_live", result, ttl=30, category="prices")
        logger.debug(f"Prix mis à jour : {len(result)} symboles")
        return result
    except Exception as e:
        logger.error(f"_update_prices: {e}")
        return {}


def _update_fred() -> Dict:
    """Mise à jour des séries FRED (macro US)."""
    try:
        import requests
        from io import StringIO
        import pandas as pd
        result = {}
        series_ids = list(FRED_SERIES.keys())[:8] if CACHE_OK else \
            ["FEDFUNDS","DGS10","DGS2","CPIAUCSL","UNRATE","BAMLH0A0HYM2"]

        def fetch_one(sid):
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            r   = requests.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200: return sid, None
            df = pd.read_csv(StringIO(r.text), parse_dates=["DATE"])
            df.columns = ["date","value"]
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.dropna().set_index("date")["value"].tail(30)
            if s.empty: return sid, None
            last=float(s.iloc[-1]); prev=float(s.iloc[-2]) if len(s)>1 else last
            return sid, {"value":round(last,4),"change":round(last-prev,4),"history":s.tolist()}

        with ThreadPoolExecutor(max_workers=5) as ex:
            futs = [ex.submit(fetch_one, sid) for sid in series_ids]
            for fut in as_completed(futs, timeout=30):
                try:
                    sid, data = fut.result()
                    if data:
                        lbl = FRED_SERIES.get(sid, {}).get("label", sid) if CACHE_OK else sid
                        result[lbl] = data
                except Exception:
                    pass

        # Spread 10-2 dérivé
        t10 = result.get("T10Y US",{}).get("value",0) or 0
        t2  = result.get("T2Y US", {}).get("value",0) or 0
        result["Spread 10-2"] = {"value":round(t10-t2,3),"change":0,"history":[]}

        if CACHE_OK:
            get_cache().set("fred_macro", result, ttl=3600, category="macro")
        logger.debug(f"FRED mis à jour : {len(result)} séries")
        return result
    except Exception as e:
        logger.error(f"_update_fred: {e}")
        return {}


def _update_rss() -> List[Dict]:
    """Mise à jour des flux RSS (toutes les sources)."""
    try:
        import feedparser
        try:
            rss_urls = get_rss_urls()
        except Exception:
            rss_urls = {
                "BCE":      "https://www.ecb.europa.eu/rss/press.html",
                "Reuters":  "https://feeds.reuters.com/reuters/businessNews",
                "Les Echos":"https://www.lesechos.fr/feeds/rss/finance-marches.xml",
            }

        cache  = get_cache() if CACHE_OK else None
        articles = []
        seen_hashes = set()

        def fetch_one(src, url):
            try:
                feed = feedparser.parse(url)
                arts = []
                for e in feed.entries[:6]:
                    t = (e.get("title","") or "").strip()
                    if not t: continue
                    if cache and cache.is_article_seen(t):
                        continue
                    arts.append({
                        "title":  t[:120],
                        "source": src,
                        "link":   e.get("link","#"),
                        "date":   e.get("published","")[:16],
                        "text":   (t+" "+(e.get("summary","") or "")).lower(),
                    })
                    if cache:
                        cache.mark_article_seen(t, src)
                return arts
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_one, src, url): src for src,url in rss_urls.items()}
            for fut in as_completed(futs, timeout=25):
                try:
                    arts = fut.result()
                    articles.extend(arts)
                except Exception:
                    pass

        if cache and articles:
            cache.set("rss_articles", articles[:100], ttl=600, category="news")
        logger.debug(f"RSS mis à jour : {len(articles)} nouveaux articles")
        return articles
    except Exception as e:
        logger.error(f"_update_rss: {e}")
        return []


def _update_weights(articles: List[Dict] = None) -> Dict:
    """Recalcule les pondérations dynamiques."""
    try:
        cache = get_cache() if CACHE_OK else None
        if articles is None and cache:
            _, articles = cache.get("rss_articles") if hasattr(cache,"get") else (False, [])
            if not articles: articles = []

        from collections import Counter
        import math as _math

        articles = articles or []
        corpus   = " ".join(a.get("text","") for a in articles[:60])
        raw = {}
        for mod_id, mod in MODULES.items():
            count = sum(corpus.count(k) for k in mod["keywords"])
            raw[mod_id] = max(count, 1)

        total = sum(raw.values())
        clipped = {}
        for mod_id, mod in MODULES.items():
            w = raw[mod_id] / total
            clipped[mod_id] = max(mod["min_w"], min(mod["max_w"], w))
        tc = sum(clipped.values())
        weights = {k: round(v/tc, 4) for k,v in clipped.items()}

        if cache:
            cache.save_weights(weights, n_articles=len(articles))
            cache.set("dynamic_weights", weights, ttl=600, category="analysis")

        top = max(weights, key=weights.get) if weights else "technique"
        logger.debug(f"Pondérations : top={top} ({weights.get(top,0)*100:.0f}%) sur {len(articles)} articles")
        return weights
    except Exception as e:
        logger.error(f"_update_weights: {e}")
        return {}


def _update_bce() -> Dict:
    """Mise à jour du rapport BCE."""
    try:
        from bce_engine import RapportBCE
        rapport = RapportBCE().generer()
        if CACHE_OK and rapport:
            get_cache().set("bce_rapport", rapport, ttl=3600, category="bce")
        logger.debug("Rapport BCE mis à jour")
        return rapport
    except Exception as e:
        logger.debug(f"BCE non disponible: {e}")
        return {}


def _update_crypto() -> Dict:
    """Mise à jour des prix crypto (CoinGecko)."""
    try:
        import requests
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin,ethereum,solana&vs_currencies=eur,usd&include_24hr_change=true",
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            if CACHE_OK:
                get_cache().set("crypto_prices", data, ttl=120, category="crypto")
            return data
    except Exception as e:
        logger.debug(f"Crypto: {e}")
    return {}


def _update_fear_greed() -> Dict:
    """Mise à jour Fear & Greed Index."""
    try:
        import requests
        r = requests.get("https://api.alternative.me/fng/?limit=7", timeout=6)
        if r.status_code == 200:
            d = r.json()["data"]
            data = {"value":int(d[0]["value"]),"label":d[0]["value_classification"],
                    "history":[int(x["value"]) for x in d]}
            if CACHE_OK:
                get_cache().set("fear_greed", data, ttl=600, category="sentiment")
            return data
    except Exception as e:
        logger.debug(f"Fear&Greed: {e}")
    return {}


def _cleanup_cache() -> None:
    """Nettoyage périodique du cache."""
    if not CACHE_OK: return
    cache = get_cache()
    n_exp = cache.clear_expired()
    n_art = cache.purge_old_articles(days=7)
    if n_exp or n_art:
        logger.info(f"Cleanup: {n_exp} expirées · {n_art} anciens articles purgés")


def _backup_db() -> None:
    """Sauvegarde périodique de la base de données."""
    if not CACHE_OK: return
    cache = get_cache()
    p = cache.backup()
    if p.exists():
        # Garder seulement les 5 derniers backups
        backups = sorted(Path("backups").glob("zedicus_cache_*.db.gz"))
        for old in backups[:-5]:
            old.unlink()
        logger.info(f"Backup DB : {p.name}")


# ══════════════════════════════════════════════════════════════════════════════
# §3  SCHEDULER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

class Scheduler:
    """Scheduler de tâches avec gestion des priorités et signal d'arrêt."""

    def __init__(self):
        self.tasks: List[UpdateTask] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._cycle_count = 0

        self._register_tasks()

    def _register_tasks(self):
        """Enregistre toutes les tâches par ordre de priorité."""
        self.tasks = [
            UpdateTask("Prix live",         _update_prices,    interval_sec=20,   priority=1,
                        description="Cours Yahoo Finance — watchlist complète"),
            UpdateTask("Fear & Greed",       _update_fear_greed,interval_sec=600,  priority=2,
                        description="Alternative.me Fear & Greed Index crypto"),
            UpdateTask("Crypto CoinGecko",   _update_crypto,    interval_sec=120,  priority=2,
                        description="BTC, ETH, SOL depuis CoinGecko (sans clé)"),
            UpdateTask("RSS Actualités",     _update_rss,       interval_sec=600,  priority=3,
                        description=f"15 sources RSS — BCE, Reuters, Bloomberg, Investing.com..."),
            UpdateTask("Pondérations",       _update_weights,   interval_sec=600,  priority=3,
                        description="Recalcul pondérations dynamiques (algo Franck)"),
            UpdateTask("Macro FRED",         _update_fred,      interval_sec=3600, priority=4,
                        description="Séries macro FRED — Fed Funds, CPI, chômage, spreads"),
            UpdateTask("Rapport BCE",        _update_bce,       interval_sec=3600, priority=4,
                        description="Tendances BCE, probabilités, calendrier réunions"),
            UpdateTask("Cleanup cache",      _cleanup_cache,    interval_sec=1800, priority=9,
                        description="Suppression entrées expirées et anciens articles"),
            UpdateTask("Backup DB",          _backup_db,        interval_sec=DB_BACKUP_HOURS*3600,
                        priority=10, description="Sauvegarde compressée de la base SQLite"),
        ]
        # Trier par priorité
        self.tasks.sort(key=lambda t: t.priority)

    def run_once(self, task_names: List[str] = None) -> Dict[str, bool]:
        """Exécute une passe unique de toutes les tâches (ou celles spécifiées)."""
        results = {}
        for task in self.tasks:
            if task_names and task.name not in task_names:
                continue
            logger.info(f"→ {task.name}")
            results[task.name] = task.run()
        return results

    def run_due(self) -> int:
        """Exécute les tâches qui sont dues. Retourne le nombre exécuté."""
        due   = [t for t in self.tasks if t.is_due()]
        count = 0
        # Exécuter les tâches prioritaires séquentiellement,
        # les basses priorités en parallèle
        high_priority = [t for t in due if t.priority <= 3]
        low_priority  = [t for t in due if t.priority > 3]

        for task in high_priority:
            task.run(); count += 1

        if low_priority:
            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {ex.submit(t.run): t for t in low_priority}
                for fut in as_completed(futs, timeout=60):
                    count += 1

        return count

    def start(self, interval: int = None) -> None:
        """Démarre la boucle infinie."""
        interval = interval or UPDATE_INTERVAL
        logger.info(f"Scheduler démarré · Interval : {interval}s · {len(self.tasks)} tâches")
        logger.info(f"Tâches : {', '.join(t.name for t in self.tasks)}")

        # Préchauffage initial
        logger.info("Préchauffage initial du cache...")
        self.run_once()

        # Sauvegarder le statut
        if CACHE_OK:
            get_cache().set_stat("updater_start", datetime.utcnow().isoformat())
            get_cache().set_stat("updater_pid", os.getpid())

        while not self._stop.is_set():
            try:
                self._cycle_count += 1
                t0 = time.time()
                n  = self.run_due()
                dt = time.time() - t0

                if n > 0:
                    logger.info(f"Cycle #{self._cycle_count} : {n} tâches exécutées en {dt:.1f}s")

                # Sauvegarder le statut toutes les 5 cycles
                if CACHE_OK and self._cycle_count % 5 == 0:
                    self._save_status()

                # Attendre jusqu'au prochain intervalle
                sleep_time = max(1, interval - (time.time() - t0))
                self._stop.wait(timeout=sleep_time)

            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Erreur cycle #{self._cycle_count}: {e}")
                logger.debug(traceback.format_exc())
                time.sleep(5)

        logger.info("Scheduler arrêté.")

    def stop(self) -> None:
        self._stop.set()

    def _save_status(self) -> None:
        if not CACHE_OK: return
        status = {
            "pid":          os.getpid(),
            "uptime_min":   round((time.time()-self._start_time)/60, 1),
            "cycles":       self._cycle_count,
            "tasks":        [t.to_dict() for t in self.tasks],
            "updated_at":   datetime.utcnow().isoformat(),
        }
        get_cache().set("updater_status", status, ttl=UPDATE_INTERVAL*5, category="system")

    def get_status(self) -> Dict:
        return {
            "pid":         os.getpid(),
            "uptime_min":  round((time.time()-self._start_time)/60, 1),
            "cycles":      self._cycle_count,
            "tasks":       [t.to_dict() for t in self.tasks],
            "updated_at":  datetime.utcnow().isoformat(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# §4  HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════════════

class HealthChecker:
    """Vérifie la santé de tous les composants du système."""

    CHECKS = {
        "Yahoo Finance":     lambda: __import__("yfinance").download("SPY",period="1d",progress=False) is not None,
        "FRED":              lambda: __import__("requests").get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=FEDFUNDS",timeout=8).status_code==200,
        "BCE SDMX":          lambda: __import__("requests").get("https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.RT.MM.EURIBOR3MD_.HSTA?format=jsondata&lastNObservations=1",timeout=8,headers={"Accept":"application/json"}).status_code==200,
        "Fear & Greed":      lambda: __import__("requests").get("https://api.alternative.me/fng/?limit=1",timeout=6).status_code==200,
        "CoinGecko":         lambda: __import__("requests").get("https://api.coingecko.com/api/v3/ping",timeout=6).status_code==200,
        "Reuters RSS":       lambda: len(__import__("feedparser").parse("https://feeds.reuters.com/reuters/businessNews").entries)>0,
        "Les Echos RSS":     lambda: len(__import__("feedparser").parse("https://www.lesechos.fr/feeds/rss/finance-marches.xml").entries)>0,
        "BCE RSS":           lambda: len(__import__("feedparser").parse("https://www.ecb.europa.eu/rss/press.html").entries)>0,
    }

    @classmethod
    def run(cls, verbose: bool = True) -> Dict[str, bool]:
        results = {}
        print("\n🩺  HEALTH CHECK — THE ZEDICUS v2\n" + "═"*55)

        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(cls._check, name, fn): name
                    for name, fn in cls.CHECKS.items()}
            for fut in as_completed(futs, timeout=30):
                name = futs[fut]
                try:
                    ok = fut.result()
                except Exception:
                    ok = False
                results[name] = ok
                if verbose:
                    icon = "✅" if ok else "❌"
                    print(f"  {icon}  {name}")

        # Modules Python
        print(f"\n  DÉPENDANCES PYTHON")
        for pkg in ["streamlit","plotly","pandas","numpy","yfinance","requests","feedparser"]:
            try:
                __import__(pkg)
                print(f"  ✅  {pkg}")
                results[f"pkg_{pkg}"] = True
            except ImportError:
                print(f"  ❌  {pkg}  →  pip install {pkg}")
                results[f"pkg_{pkg}"] = False

        # Cache SQLite
        print(f"\n  BASE DE DONNÉES")
        if CACHE_OK:
            try:
                cache = get_cache()
                st    = cache.get_status()
                print(f"  ✅  SQLite ({st.get('db_size_mb',0):.2f} MB) · {st.get('cache_entries',{}).get('valid',0)} entrées valides")
                results["sqlite"] = True
            except Exception as e:
                print(f"  ❌  SQLite : {e}")
                results["sqlite"] = False
        else:
            print("  ⚠️   data_cache.py non importé")
            results["sqlite"] = False

        # Modules locaux
        print(f"\n  MODULES LOCAUX")
        for mod in ["config.py","data_cache.py","updater.py","zedicus_v2.py","bce_engine.py","orchestrator.py"]:
            exists = (Path(__file__).parent / mod).exists()
            icon   = "✅" if exists else ("⚠️ " if mod in ["bce_engine.py","orchestrator.py"] else "❌")
            note   = " (optionnel)" if mod in ["bce_engine.py","orchestrator.py"] else ""
            print(f"  {icon}  {mod}{note}")
            results[f"file_{mod}"] = exists

        # Score global
        n_ok  = sum(1 for k,v in results.items() if v and not k.startswith("file_"))
        n_tot = sum(1 for k in results if not k.startswith("file_"))
        score = n_ok/n_tot*100 if n_tot else 0
        print(f"\n  SCORE : {n_ok}/{n_tot} ({score:.0f}%)")
        print(f"  {'✅ Système opérationnel' if score>=70 else '⚠️  Certains services indisponibles'}\n")

        return results

    @staticmethod
    def _check(name: str, fn: Callable) -> bool:
        try:
            return bool(fn())
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# §5  WARMUP — PRÉCHAUFFAGE DU CACHE
# ══════════════════════════════════════════════════════════════════════════════

def warmup_cache() -> None:
    """Précouffe le cache avec toutes les données critiques."""
    print("\n🔥  PRÉCHAUFFAGE DU CACHE\n" + "═"*50)
    tasks_warmup = [
        ("Prix live",         _update_prices,    "20 symboles watchlist"),
        ("Macro FRED",        _update_fred,       "10 séries économiques"),
        ("RSS Actualités",    _update_rss,        "15 sources RSS"),
        ("Fear & Greed",      _update_fear_greed, "Alternative.me"),
        ("Crypto",            _update_crypto,     "BTC, ETH, SOL"),
        ("Rapport BCE",       _update_bce,        "Tendances + calendrier"),
        ("Pondérations",      _update_weights,    "Calcul poids dynamiques"),
    ]
    total_t = 0
    for name, fn, desc in tasks_warmup:
        print(f"  → {name:20s} {desc}", end=" ... ", flush=True)
        t0 = time.time()
        try:
            fn()
            dt = time.time()-t0
            total_t += dt
            print(f"✅ ({dt:.1f}s)")
        except Exception as e:
            dt = time.time()-t0
            print(f"⚠️  {e} ({dt:.1f}s)")
    print(f"\n  ✅ Préchauffage terminé en {total_t:.1f}s")
    if CACHE_OK:
        st = get_cache().get_status()
        print(f"  Cache : {st.get('cache_entries',{}).get('valid',0)} entrées · {st.get('db_size_mb',0):.2f} MB\n")


# ══════════════════════════════════════════════════════════════════════════════
# §6  CRON
# ══════════════════════════════════════════════════════════════════════════════

def install_cron() -> None:
    """Installe les tâches cron pour l'auto-refresh."""
    script   = str(Path(__file__).resolve())
    log_file = str(LOG_DIR / "cron_updater.log")
    py       = sys.executable

    cron_jobs = [
        f"*/1  * * * * cd {Path(__file__).parent} && {py} {script} --once >> {log_file} 2>&1",
        f"0    */6 * * * cd {Path(__file__).parent} && {py} {script} --warmup >> {log_file} 2>&1",
        f"0    2   * * * cd {Path(__file__).parent} && {py} {script} --clear-cache >> {log_file} 2>&1",
    ]

    print("\n📅  INSTALLATION CRON\n" + "─"*55)
    for job in cron_jobs:
        print(f"  → {job}")

    cmd = f'(crontab -l 2>/dev/null | grep -v "updater.py"; ' + \
          "; ".join(f'echo "{j}"' for j in cron_jobs) + \
          ') | crontab -'

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"\n  ✅ {len(cron_jobs)} tâches cron installées")
        print(f"  Vérifier avec : crontab -l")
        print(f"  Logs : {log_file}\n")
    else:
        print(f"  ❌ Erreur : {result.stderr}")
        print(f"\n  Ajouter manuellement dans crontab (crontab -e) :")
        for j in cron_jobs:
            print(f"  {j}")


# ══════════════════════════════════════════════════════════════════════════════
# §7  SIGNAL HANDLER — Arrêt propre
# ══════════════════════════════════════════════════════════════════════════════

_scheduler: Optional[Scheduler] = None

def _signal_handler(sig, frame):
    logger.info(f"Signal {sig} reçu — arrêt propre...")
    if _scheduler:
        _scheduler.stop()

signal.signal(signal.SIGINT,  _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ══════════════════════════════════════════════════════════════════════════════
# §8  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global _scheduler

    parser = argparse.ArgumentParser(
        description="updater.py — Mise à jour automatique THE ZEDICUS v2",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--once",        action="store_true", help="Mise à jour unique et quitter")
    parser.add_argument("--warmup",      action="store_true", help="Préchauffer le cache")
    parser.add_argument("--health",      action="store_true", help="Health check complet")
    parser.add_argument("--cron",        action="store_true", help="Installer tâches cron")
    parser.add_argument("--status",      action="store_true", help="Afficher statut updater")
    parser.add_argument("--clear-cache", action="store_true", help="Vider et reconstruire le cache")
    parser.add_argument("--interval",    type=int, default=UPDATE_INTERVAL, help=f"Intervalle boucle (défaut: {UPDATE_INTERVAL}s)")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  THE ZEDICUS v2 — Updater                               ║
║  Scheduler · Health Check · Cache warm-up               ║
╚══════════════════════════════════════════════════════════╝
""")

    if args.health:
        HealthChecker.run()
        return

    if args.cron:
        install_cron()
        return

    if args.warmup:
        warmup_cache()
        return

    if args.clear_cache:
        if CACHE_OK:
            n = get_cache().clear_all()
            print(f"  ✅ Cache vidé : {n} entrées supprimées")
        warmup_cache()
        return

    if args.status:
        if CACHE_OK:
            data = get_cache().get("updater_status")
            if data and data[0]:
                st = data[1]
                print(f"  PID      : {st.get('pid','N/A')}")
                print(f"  Uptime   : {st.get('uptime_min',0):.1f} min")
                print(f"  Cycles   : {st.get('cycles',0)}")
                print(f"  Mis à jour : {st.get('updated_at','N/A')}")
                print(f"\n  TÂCHES :")
                for t in st.get("tasks",[]):
                    print(f"  {t.get('name',''):20s} | last: {t.get('last_run','jamais'):10s} | "
                           f"runs: {t.get('run_count',0):4d} | errors: {t.get('error_count',0):3d} | "
                           f"next: {t.get('next_run_in','?')}")
            else:
                print("  Aucun updater en cours.")
        return

    if args.once:
        print("  Mode : exécution unique\n")
        sched   = Scheduler()
        results = sched.run_once()
        n_ok    = sum(1 for v in results.values() if v)
        print(f"\n  ✅ {n_ok}/{len(results)} tâches réussies")
        return

    # Mode continu (par défaut)
    print(f"  Mode : scheduler continu | Intervalle : {args.interval}s")
    print(f"  Arrêt : Ctrl+C\n")
    _scheduler = Scheduler()
    _scheduler.start(interval=args.interval)


if __name__ == "__main__":
    main()
