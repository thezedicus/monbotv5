#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  data_cache.py — Gestionnaire de cache persistant SQLite                     ║
║  Stocke toutes les données entre les sessions Streamlit                       ║
║  Compatible GitHub / Streamlit Cloud                                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES :                                                                 ║
║    python3 data_cache.py                  # Affiche l'état du cache          ║
║    python3 data_cache.py --status         # Statistiques détaillées          ║
║    python3 data_cache.py --clear          # Vider le cache                   ║
║    python3 data_cache.py --clear-expired  # Supprimer entrées expirées       ║
║    python3 data_cache.py --export         # Exporter en JSON                 ║
║    python3 data_cache.py --backup         # Créer une sauvegarde             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, gzip, shutil, sqlite3, hashlib, logging, argparse
from datetime   import datetime, timedelta
from pathlib    import Path
from typing     import Any, Dict, List, Optional, Tuple
from contextlib import contextmanager

# ── Import config (si disponible) ────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
try:
    from config import CFG
    DB_PATH = Path(CFG["DB_PATH"])
    LOG_DIR = Path(CFG["LOG_DIR"])
except ImportError:
    DB_PATH = Path("data/zedicus_cache.db")
    LOG_DIR = Path("logs")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
Path("backups").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR/"data_cache.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("DataCache")


# ══════════════════════════════════════════════════════════════════════════════
# §1  GESTIONNAIRE DE CACHE SQLITE
# ══════════════════════════════════════════════════════════════════════════════

class DataCache:
    """
    Cache persistant SQLite pour toutes les données du dashboard.
    Survit aux redémarrages Streamlit et aux rechargements de page.
    Gère automatiquement l'expiration, la compression et la purge.
    """

    SCHEMA = """
    -- Cache clé-valeur générique
    CREATE TABLE IF NOT EXISTS cache (
        key         TEXT PRIMARY KEY,
        value       BLOB NOT NULL,
        compressed  INTEGER DEFAULT 0,
        ttl_sec     INTEGER DEFAULT 300,
        created_at  REAL NOT NULL,
        expires_at  REAL NOT NULL,
        hits        INTEGER DEFAULT 0,
        category    TEXT DEFAULT 'general',
        size_bytes  INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);
    CREATE INDEX IF NOT EXISTS idx_cache_category ON cache(category);

    -- Historique des prix (time series)
    CREATE TABLE IF NOT EXISTS prices_history (
        symbol      TEXT NOT NULL,
        timestamp   REAL NOT NULL,
        price       REAL,
        chg_pct     REAL,
        volume      INTEGER,
        source      TEXT DEFAULT 'yfinance',
        PRIMARY KEY (symbol, timestamp)
    );
    CREATE INDEX IF NOT EXISTS idx_prices_sym ON prices_history(symbol, timestamp DESC);

    -- Historique des signaux
    CREATE TABLE IF NOT EXISTS signals_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   REAL NOT NULL,
        symbol      TEXT NOT NULL,
        signal      TEXT NOT NULL,
        composite   REAL,
        force       REAL,
        weights     TEXT,
        scores      TEXT,
        price       REAL,
        stop        REAL,
        tp          REAL,
        rr          REAL
    );
    CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals_history(timestamp DESC);

    -- Historique des pondérations dynamiques
    CREATE TABLE IF NOT EXISTS weights_history (
        timestamp   REAL PRIMARY KEY,
        weights     TEXT NOT NULL,
        n_articles  INTEGER DEFAULT 0,
        top_module  TEXT DEFAULT ''
    );

    -- Articles RSS déjà vus (déduplication)
    CREATE TABLE IF NOT EXISTS articles_seen (
        hash        TEXT PRIMARY KEY,
        title       TEXT,
        source      TEXT,
        timestamp   REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_articles_ts ON articles_seen(timestamp DESC);

    -- Statistiques d'utilisation
    CREATE TABLE IF NOT EXISTS stats (
        key         TEXT PRIMARY KEY,
        value       TEXT,
        updated_at  REAL DEFAULT (strftime('%s','now'))
    );
    """

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DB_PATH
        self._init_db()
        logger.info(f"Cache initialisé : {self.db_path.resolve()}")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(
            str(self.db_path), timeout=20,
            check_same_thread=False, isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")    # 64MB cache
        try:
            yield conn
        except Exception as e:
            logger.error(f"DB error: {e}")
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as c:
            c.executescript(self.SCHEMA)

    # ── CACHE GÉNÉRIQUE ────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, ttl: int = 300,
             category: str = "general", compress: bool = False) -> bool:
        """Stocke une valeur dans le cache avec TTL."""
        try:
            serialized = json.dumps(value, default=str).encode("utf-8")
            compressed = 0
            if compress or len(serialized) > 10_000:
                serialized = gzip.compress(serialized, compresslevel=6)
                compressed = 1
            now = time.time()
            with self._conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO cache
                    (key, value, compressed, ttl_sec, created_at, expires_at, category, size_bytes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (key, serialized, compressed, ttl, now, now+ttl, category, len(serialized)))
            return True
        except Exception as e:
            logger.warning(f"Cache.set({key}): {e}")
            return False

    def get(self, key: str) -> Tuple[bool, Any]:
        """Récupère une valeur du cache. Retourne (hit, valeur)."""
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT value, compressed, expires_at FROM cache WHERE key=?", [key]
                ).fetchone()
                if not row:
                    return False, None
                if time.time() > row["expires_at"]:
                    c.execute("DELETE FROM cache WHERE key=?", [key])
                    return False, None
                # Incrémenter hits
                c.execute("UPDATE cache SET hits=hits+1 WHERE key=?", [key])
                data = row["value"]
                if row["compressed"]:
                    data = gzip.decompress(data)
                return True, json.loads(data.decode("utf-8"))
        except Exception as e:
            logger.warning(f"Cache.get({key}): {e}")
            return False, None

    def get_or_fetch(self, key: str, fetch_fn, ttl: int = 300,
                      category: str = "general") -> Any:
        """Retourne depuis le cache ou appelle fetch_fn si expiré."""
        hit, value = self.get(key)
        if hit:
            return value
        try:
            value = fetch_fn()
            if value is not None:
                self.set(key, value, ttl=ttl, category=category)
            return value
        except Exception as e:
            logger.error(f"fetch_fn pour '{key}': {e}")
            return None

    def delete(self, key: str) -> bool:
        try:
            with self._conn() as c:
                c.execute("DELETE FROM cache WHERE key=?", [key])
            return True
        except Exception:
            return False

    def clear_expired(self) -> int:
        """Supprime les entrées expirées. Retourne le nombre supprimé."""
        try:
            with self._conn() as c:
                cur = c.execute("DELETE FROM cache WHERE expires_at < ?", [time.time()])
                n = cur.rowcount
            if n > 0:
                logger.info(f"Cache purge : {n} entrées expirées supprimées")
            return n
        except Exception:
            return 0

    def clear_all(self, category: str = None) -> int:
        try:
            with self._conn() as c:
                if category:
                    cur = c.execute("DELETE FROM cache WHERE category=?", [category])
                else:
                    cur = c.execute("DELETE FROM cache")
                return cur.rowcount
        except Exception:
            return 0

    def size_mb(self) -> float:
        if self.db_path.exists():
            return self.db_path.stat().st_size / 1024 / 1024
        return 0.0

    # ── HISTORIQUE DES PRIX ───────────────────────────────────────────────────

    def save_price(self, symbol: str, price: float, chg_pct: float = 0,
                    volume: int = 0, source: str = "yfinance") -> bool:
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO prices_history
                    (symbol, timestamp, price, chg_pct, volume, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (symbol, time.time(), price, chg_pct, volume, source))
            return True
        except Exception as e:
            logger.warning(f"save_price({symbol}): {e}")
            return False

    def get_price_history(self, symbol: str, hours: int = 24) -> List[Dict]:
        since = time.time() - hours * 3600
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT timestamp, price, chg_pct, volume
                    FROM prices_history
                    WHERE symbol=? AND timestamp>=?
                    ORDER BY timestamp DESC LIMIT 1000
                """, [symbol, since]).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_all_tracked_symbols(self) -> List[str]:
        try:
            with self._conn() as c:
                rows = c.execute("SELECT DISTINCT symbol FROM prices_history").fetchall()
            return [r["symbol"] for r in rows]
        except Exception:
            return []

    # ── HISTORIQUE DES SIGNAUX ────────────────────────────────────────────────

    def save_signal(self, symbol: str, signal: str, composite: float,
                     force: float, weights: Dict, scores: Dict,
                     price: float, stop: float, tp: float, rr: float) -> bool:
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT INTO signals_history
                    (timestamp, symbol, signal, composite, force, weights, scores, price, stop, tp, rr)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (time.time(), symbol, signal, composite, force,
                      json.dumps(weights), json.dumps(scores),
                      price, stop, tp, rr))
            return True
        except Exception as e:
            logger.warning(f"save_signal: {e}")
            return False

    def get_signal_history(self, symbol: str = None, limit: int = 50) -> List[Dict]:
        try:
            with self._conn() as c:
                if symbol:
                    rows = c.execute("""
                        SELECT * FROM signals_history WHERE symbol=?
                        ORDER BY timestamp DESC LIMIT ?
                    """, [symbol, limit]).fetchall()
                else:
                    rows = c.execute("""
                        SELECT * FROM signals_history
                        ORDER BY timestamp DESC LIMIT ?
                    """, [limit]).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["dt"] = datetime.fromtimestamp(d["timestamp"]).strftime("%Y-%m-%d %H:%M")
                try: d["weights"] = json.loads(d["weights"] or "{}")
                except: d["weights"] = {}
                try: d["scores"] = json.loads(d["scores"] or "{}")
                except: d["scores"] = {}
                result.append(d)
            return result
        except Exception:
            return []

    # ── HISTORIQUE DES PONDÉRATIONS ───────────────────────────────────────────

    def save_weights(self, weights: Dict, n_articles: int = 0) -> bool:
        top = max(weights, key=weights.get) if weights else ""
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO weights_history (timestamp, weights, n_articles, top_module)
                    VALUES (?, ?, ?, ?)
                """, (time.time(), json.dumps(weights), n_articles, top))
            return True
        except Exception:
            return False

    def get_weights_history(self, hours: int = 48) -> List[Dict]:
        since = time.time() - hours * 3600
        try:
            with self._conn() as c:
                rows = c.execute("""
                    SELECT timestamp, weights, n_articles, top_module
                    FROM weights_history WHERE timestamp>=?
                    ORDER BY timestamp DESC LIMIT 200
                """, [since]).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                d["dt"] = datetime.fromtimestamp(d["timestamp"]).strftime("%H:%M")
                try: d["weights"] = json.loads(d["weights"])
                except: d["weights"] = {}
                result.append(d)
            return result
        except Exception:
            return []

    # ── ARTICLES VUS (déduplication RSS) ─────────────────────────────────────

    def is_article_seen(self, title: str) -> bool:
        h = hashlib.md5(title[:80].encode()).hexdigest()
        try:
            with self._conn() as c:
                r = c.execute("SELECT 1 FROM articles_seen WHERE hash=?", [h]).fetchone()
            return bool(r)
        except Exception:
            return False

    def mark_article_seen(self, title: str, source: str = "") -> None:
        h = hashlib.md5(title[:80].encode()).hexdigest()
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR IGNORE INTO articles_seen (hash, title, source, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (h, title[:120], source, time.time()))
        except Exception:
            pass

    def purge_old_articles(self, days: int = 7) -> int:
        since = time.time() - days * 86400
        try:
            with self._conn() as c:
                cur = c.execute("DELETE FROM articles_seen WHERE timestamp<?", [since])
                return cur.rowcount
        except Exception:
            return 0

    # ── STATISTIQUES ──────────────────────────────────────────────────────────

    def set_stat(self, key: str, value: Any) -> None:
        try:
            with self._conn() as c:
                c.execute("""
                    INSERT OR REPLACE INTO stats (key, value, updated_at)
                    VALUES (?, ?, ?)
                """, (key, json.dumps(value, default=str), time.time()))
        except Exception:
            pass

    def get_stat(self, key: str, default: Any = None) -> Any:
        try:
            with self._conn() as c:
                r = c.execute("SELECT value FROM stats WHERE key=?", [key]).fetchone()
            return json.loads(r["value"]) if r else default
        except Exception:
            return default

    def get_status(self) -> Dict:
        """Retourne les statistiques complètes du cache."""
        try:
            with self._conn() as c:
                n_cache  = c.execute("SELECT COUNT(*) as n FROM cache").fetchone()["n"]
                n_valid  = c.execute("SELECT COUNT(*) as n FROM cache WHERE expires_at>?", [time.time()]).fetchone()["n"]
                n_prices = c.execute("SELECT COUNT(*) as n FROM prices_history").fetchone()["n"]
                n_sigs   = c.execute("SELECT COUNT(*) as n FROM signals_history").fetchone()["n"]
                n_arts   = c.execute("SELECT COUNT(*) as n FROM articles_seen").fetchone()["n"]
                n_wts    = c.execute("SELECT COUNT(*) as n FROM weights_history").fetchone()["n"]
                top_cats = c.execute("""
                    SELECT category, COUNT(*) as n
                    FROM cache GROUP BY category ORDER BY n DESC LIMIT 5
                """).fetchall()
                last_sig = c.execute("""
                    SELECT dt, symbol, signal, composite
                    FROM (SELECT *, datetime(timestamp,'unixepoch') as dt FROM signals_history ORDER BY timestamp DESC LIMIT 1)
                """).fetchone()

            return {
                "db_path":       str(self.db_path.resolve()),
                "db_size_mb":    round(self.size_mb(), 3),
                "cache_entries": {"total": n_cache, "valid": n_valid, "expired": n_cache-n_valid},
                "prices_rows":   n_prices,
                "signals_rows":  n_sigs,
                "articles_seen": n_arts,
                "weights_rows":  n_wts,
                "categories":    {r["category"]: r["n"] for r in top_cats},
                "last_signal":   dict(last_sig) if last_sig else None,
                "timestamp":     datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}

    # ── BACKUP ────────────────────────────────────────────────────────────────

    def backup(self) -> Path:
        """Crée une sauvegarde compressée de la base de données."""
        ts   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        dest = Path("backups") / f"zedicus_cache_{ts}.db.gz"
        try:
            # Flush WAL avant backup
            with self._conn() as c:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            with open(self.db_path, "rb") as f_in:
                with gzip.open(dest, "wb", compresslevel=9) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logger.info(f"Backup créé : {dest} ({dest.stat().st_size//1024} KB)")
            return dest
        except Exception as e:
            logger.error(f"Backup échoué : {e}")
            return Path()

    def restore(self, backup_path: Path) -> bool:
        """Restaure depuis un backup gzip."""
        try:
            with gzip.open(backup_path, "rb") as f_in:
                with open(self.db_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            logger.info(f"Restauré depuis {backup_path}")
            return True
        except Exception as e:
            logger.error(f"Restauration échouée : {e}")
            return False

    def export_json(self, output_path: Path = None) -> Path:
        """Exporte le cache en JSON lisible."""
        status = self.get_status()
        hist   = self.get_signal_history(limit=100)
        wts    = self.get_weights_history(hours=24)
        data   = {"status": status, "signals": hist, "weights": wts,
                   "exported_at": datetime.utcnow().isoformat()}
        path   = output_path or Path("data") / f"export_{datetime.utcnow():%Y%m%d_%H%M}.json"
        path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        logger.info(f"Export JSON : {path}")
        return path


# ══════════════════════════════════════════════════════════════════════════════
# §2  INSTANCE GLOBALE (Singleton)
# ══════════════════════════════════════════════════════════════════════════════

_cache_instance: Optional[DataCache] = None

def get_cache() -> DataCache:
    """Retourne l'instance singleton du cache."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = DataCache()
    return _cache_instance


# ══════════════════════════════════════════════════════════════════════════════
# §3  INTÉGRATION STREAMLIT (helpers pour st.cache_data)
# ══════════════════════════════════════════════════════════════════════════════

def cached_fetch(key: str, fetch_fn, ttl: int = 300, category: str = "general") -> Any:
    """
    Wrapper double-cache : Streamlit cache_data + SQLite persistant.
    Si Streamlit cache miss → cherche SQLite → cherche réseau.
    """
    cache = get_cache()
    return cache.get_or_fetch(key, fetch_fn, ttl=ttl, category=category)


def invalidate_category(category: str) -> int:
    """Invalide toutes les entrées d'une catégorie."""
    return get_cache().clear_all(category=category)


def invalidate_all() -> int:
    """Vide complètement le cache."""
    return get_cache().clear_all()


# ══════════════════════════════════════════════════════════════════════════════
# §4  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="data_cache.py — Gestionnaire de cache SQLite",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--status",        action="store_true", help="Afficher les statistiques")
    parser.add_argument("--clear",         action="store_true", help="Vider tout le cache")
    parser.add_argument("--clear-expired", action="store_true", help="Supprimer les entrées expirées")
    parser.add_argument("--clear-cat",     type=str, metavar="CATEGORY", help="Vider une catégorie")
    parser.add_argument("--export",        action="store_true", help="Exporter en JSON")
    parser.add_argument("--backup",        action="store_true", help="Créer une sauvegarde")
    parser.add_argument("--history",       action="store_true", help="Historique des signaux")
    parser.add_argument("--weights",       action="store_true", help="Historique des pondérations")
    parser.add_argument("--purge-articles",action="store_true", help="Purger articles vus (>7j)")
    args = parser.parse_args()

    cache = DataCache()

    if args.clear:
        n = cache.clear_all()
        print(f"✅ Cache vidé : {n} entrées supprimées")
        return

    if args.clear_expired:
        n = cache.clear_expired()
        print(f"✅ Expirées supprimées : {n} entrées")
        return

    if args.clear_cat:
        n = cache.clear_all(category=args.clear_cat)
        print(f"✅ Catégorie '{args.clear_cat}' : {n} entrées supprimées")
        return

    if args.backup:
        p = cache.backup()
        print(f"✅ Backup : {p}")
        return

    if args.export:
        p = cache.export_json()
        print(f"✅ Export : {p}")
        return

    if args.purge_articles:
        n = cache.purge_old_articles(days=7)
        print(f"✅ Articles purgés : {n}")
        return

    if args.history:
        sigs = cache.get_signal_history(limit=20)
        if not sigs:
            print("Aucun historique de signal.")
        else:
            print(f"\n{'─'*75}")
            print(f"  {'Date/heure':18s} {'Symbole':12s} {'Signal':10s} {'Composite':12s} {'Prix':10s}")
            print(f"{'─'*75}")
            for s in sigs:
                print(f"  {s.get('dt',''):18s} {s.get('symbol',''):12s} "
                       f"{s.get('signal',''):10s} {s.get('composite',0):+.3f}      "
                       f"{s.get('price',0):,.4f}")
        return

    if args.weights:
        wts = cache.get_weights_history(hours=48)
        if not wts:
            print("Aucun historique de pondérations.")
        else:
            print(f"\n{'─'*65}")
            print(f"  {'Heure':8s} {'Top module':20s} {'Articles':10s}")
            print(f"{'─'*65}")
            for w in wts[:20]:
                print(f"  {w.get('dt',''):8s} {w.get('top_module',''):20s} {w.get('n_articles',0)}")
        return

    # Affichage par défaut
    st = cache.get_status()
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Cache SQLite — THE ZEDICUS v2
╚══════════════════════════════════════════════════════════════╝

  Base de données  : {st.get('db_path','N/A')}
  Taille           : {st.get('db_size_mb',0):.3f} MB

  ENTRÉES CACHE
  ─────────────────────────────────────────────
  Total            : {st.get('cache_entries',{}).get('total',0)}
  Valides          : {st.get('cache_entries',{}).get('valid',0)}
  Expirées         : {st.get('cache_entries',{}).get('expired',0)}

  TABLES
  ─────────────────────────────────────────────
  Prix historique  : {st.get('prices_rows',0)} entrées
  Signaux          : {st.get('signals_rows',0)} entrées
  Articles vus     : {st.get('articles_seen',0)} entrées
  Pondérations     : {st.get('weights_rows',0)} entrées

  CATÉGORIES CACHE
  ─────────────────────────────────────────────""")
    for cat, n in st.get("categories",{}).items():
        print(f"  {cat:20s} : {n} entrées")

    last = st.get("last_signal")
    if last:
        print(f"""
  DERNIER SIGNAL
  ─────────────────────────────────────────────
  {last}""")
    print()


if __name__ == "__main__":
    main()
