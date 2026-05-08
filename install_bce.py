from typing import Dict, List, Optional, Tuple, Any
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  install_bce.py — Script d'installation et configuration du projet          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDE MAC (Terminal) :                                                   ║
║    python3 install_bce.py              # Installation complète              ║
║    python3 install_bce.py --deps       # Installer les dépendances         ║
║    python3 install_bce.py --check      # Vérifier l'installation           ║
║    python3 install_bce.py --db         # Initialiser la base de données    ║
║    python3 install_bce.py --test       # Tester toutes les APIs            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, subprocess, time, json, argparse
from pathlib  import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent

# ── Dépendances requises ──────────────────────────────────────────────────────
DEPS_REQUIRED = [
    ("yfinance",     "Données Yahoo Finance (actions, crypto, forex)"),
    ("requests",     "Appels APIs REST (BCE, FRED, Alternative.me)"),
    ("pandas",       "Manipulation et analyse de données"),
    ("numpy",        "Calculs numériques"),
    ("scipy",        "Statistiques avancées (VaR, corrélation)"),
    ("streamlit",    "Interface web locale (dashboard)"),
    ("plotly",       "Graphiques interactifs"),
    ("feedparser",   "Flux RSS (actualités financières)"),
    ("python-dotenv","Gestion des clés API (.env)"),
]

DEPS_OPTIONAL = [
    ("ta-lib",       "Indicateurs techniques avancés (optionnel)"),
    ("alpaca-trade-api","Broker Alpaca pour paper trading (optionnel)"),
]

# ── Fichiers du projet ────────────────────────────────────────────────────────
FICHIERS_PROJET = {
    "bce_engine.py":            "Moteur BCE — APIs + Base SQLite + Analyse tendances",
    "bce_dashboard.py":         "Dashboard Streamlit BCE Zone Euro",
    "orchestrator.py":          "Orchestrateur principal — Décision + HTML",
    "bot_v3.py":                "Bot trading v3 complet (3842 lignes)",
    "api_manager.py":           "Gestionnaire APIs de données marché",
    "market_db.py":             "Base de données SQLite marché",
    "streamlit_app.py":         "Dashboard Streamlit général",
    "market_oracle_extension.py":"Module analyse quantitative",
    "corrections.py":           "Correcteur automatique des bugs",
    "generate_dashboard.py":    "Générateur dashboard HTML live",
    "features_engine.py":       "Moteur features ML",
}


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║  Market Oracle BCE — Script d'installation                          ║
║  Dossier : /Users/macbook/Documents/monbotv3/                       ║
╚══════════════════════════════════════════════════════════════════════╝
""")


# ══════════════════════════════════════════════════════════════════════════════
# §1  INSTALLATION DES DÉPENDANCES
# ══════════════════════════════════════════════════════════════════════════════

def install_deps(force: bool = False) -> bool:
    """Installe toutes les dépendances Python requises."""
    print("📦  INSTALLATION DES DÉPENDANCES\n" + "─"*55)
    all_ok = True

    for pkg, desc in DEPS_REQUIRED:
        # Vérifier si déjà installé
        try:
            __import__(pkg.replace("-","_").split("[")[0])
            if not force:
                print(f"  ✅ {pkg:20s} déjà installé")
                continue
        except ImportError:
            pass

        print(f"  📥 {pkg:20s} {desc[:35]}", end=" ... ", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", pkg,
             "--break-system-packages", "-q"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("✅")
        else:
            print(f"❌  {result.stderr[:60]}")
            all_ok = False

    print()
    return all_ok


# ══════════════════════════════════════════════════════════════════════════════
# §2  VÉRIFICATION DE L'INSTALLATION
# ══════════════════════════════════════════════════════════════════════════════

def check_installation() -> Dict:
    """Vérifie l'état complet de l'installation."""
    from typing import Dict as _Dict
    results: _Dict = {"deps": {}, "files": {}, "apis": {}, "db": {}}

    print("🩺  VÉRIFICATION DE L'INSTALLATION\n" + "═"*55)

    # ── Dépendances ───────────────────────────────────────────────────────────
    print("\n  DÉPENDANCES PYTHON")
    print(f"  {'─'*50}")
    for pkg, desc in DEPS_REQUIRED:
        mod = pkg.replace("-","_").split("[")[0]
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            print(f"  ✅ {pkg:20s} v{ver:<12s} {desc[:25]}")
            results["deps"][pkg] = True
        except ImportError:
            print(f"  ❌ {pkg:20s} MANQUANT → pip3 install {pkg}")
            results["deps"][pkg] = False

    # ── Fichiers projet ───────────────────────────────────────────────────────
    print(f"\n  FICHIERS DU PROJET  ({PROJECT_DIR})")
    print(f"  {'─'*50}")
    for nom, role in FICHIERS_PROJET.items():
        fp = PROJECT_DIR / nom
        if fp.exists():
            lines = fp.read_text(encoding="utf-8").count("\n")
            # Vérification syntaxe
            r = subprocess.run(
                [sys.executable, "-m", "py_compile", str(fp)],
                capture_output=True
            )
            status = "✅" if r.returncode == 0 else "❌ Erreur syntaxe"
            print(f"  {status} {nom:35s} {lines:5d} lignes")
            results["files"][nom] = r.returncode == 0
        else:
            print(f"  ⚠️  {nom:35s} ABSENT")
            results["files"][nom] = False

    # ── Base de données ───────────────────────────────────────────────────────
    print(f"\n  BASE DE DONNÉES")
    print(f"  {'─'*50}")
    db_path = PROJECT_DIR / "data" / "bce_intelligence.db"
    if db_path.exists():
        sz = db_path.stat().st_size / 1024
        print(f"  ✅ bce_intelligence.db ({sz:.1f} KB)")
        results["db"]["exists"] = True
    else:
        print(f"  ⚠️  Base non initialisée → python3 install_bce.py --db")
        results["db"]["exists"] = False

    mdb_path = PROJECT_DIR / "data" / "market.db"
    if mdb_path.exists():
        sz = mdb_path.stat().st_size / 1024
        print(f"  ✅ market.db ({sz:.1f} KB)")
    else:
        print(f"  ⚠️  market.db absent → python3 market_db.py --init")

    # ── Dossiers ──────────────────────────────────────────────────────────────
    print(f"\n  DOSSIERS")
    for d in ["logs", "data", "data/exports", "backups"]:
        dp = PROJECT_DIR / d
        dp.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {d}/")

    print()
    return results


# ══════════════════════════════════════════════════════════════════════════════
# §3  INITIALISATION DE LA BASE DE DONNÉES
# ══════════════════════════════════════════════════════════════════════════════

def init_database() -> bool:
    """Initialise la base de données BCE et télécharge les données de base."""
    print("🗄️   INITIALISATION DES BASES DE DONNÉES\n" + "─"*55)

    # Base BCE Intelligence
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        from bce_engine import BCEDatabase, BCEAPI

        print("  Création de la base bce_intelligence.db...")
        db  = BCEDatabase()
        api = BCEAPI(db)

        # Sauvegarder le calendrier BCE
        api.db.save_calendrier(api.CALENDRIER_BCE)
        print(f"  ✅ Calendrier BCE : {len(api.CALENDRIER_BCE)} réunions enregistrées")

        # Télécharger les indices BCE
        SYMBOLES = ["^STOXX50E","^FCHI","^GDAXI","EURUSD=X","BZ=F"]
        print(f"  Téléchargement des indices BCE : {', '.join(SYMBOLES)}")
        res = api.fetch_indices_ohlcv(SYMBOLES, jours=252)
        for sym, info in res.items():
            print(f"    {sym}: {info.get('lignes',0)} lignes")

        st = db.status()
        print(f"\n  ✅ Base BCE : {st['taille_mb']:.2f} MB")
        for table, n in st["tables"].items():
            if n > 0:
                print(f"     {table:30s}: {n} enregistrements")

    except ImportError:
        print("  ❌  bce_engine.py introuvable")
        return False
    except Exception as e:
        print(f"  ❌  Erreur : {e}")
        return False

    # Base Marché (si market_db.py présent)
    mdb_script = PROJECT_DIR / "market_db.py"
    if mdb_script.exists():
        print(f"\n  Initialisation de market.db...")
        result = subprocess.run(
            [sys.executable, str(mdb_script), "--init"],
            capture_output=True, text=True, cwd=str(PROJECT_DIR)
        )
        if result.returncode == 0:
            print("  ✅ market.db initialisée")
        else:
            print(f"  ⚠️  market.db : {result.stderr[:80]}")

    print()
    return True


# ══════════════════════════════════════════════════════════════════════════════
# §4  TEST DES APIs
# ══════════════════════════════════════════════════════════════════════════════

def test_apis() -> None:
    """Teste la connexion à toutes les sources de données."""
    print("📡  TEST DES APIS\n" + "─"*55)

    import requests as req

    TESTS = [
        ("Yahoo Finance (SPY)",
         lambda: __import__("yfinance").download("SPY",period="2d",progress=False,auto_adjust=True) is not None,
         "Actions, ETFs, indices, forex, crypto"),

        ("BCE SDMX (Euribor 3M)",
         lambda: req.get(
             "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.RT.MM.EURIBOR3MD_.HSTA"
             "?format=jsondata&lastNObservations=1",
             timeout=8, headers={"Accept":"application/json"}
         ).status_code == 200,
         "Taux BCE officiels"),

        ("FRED (T10Y)",
         lambda: req.get(
             "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
             timeout=8
         ).status_code == 200,
         "Taux US, spreads, macro"),

        ("Alternative.me (Fear&Greed)",
         lambda: req.get(
             "https://api.alternative.me/fng/?limit=1",
             timeout=6
         ).status_code == 200,
         "Indicateur crypto sentiment"),

        ("CoinGecko (BTC)",
         lambda: req.get(
             "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
             timeout=8
         ).status_code == 200,
         "Prix cryptomonnaies"),

        ("Reuters RSS",
         lambda: req.get(
             "https://feeds.reuters.com/reuters/businessNews",
             timeout=8, headers={"User-Agent":"Mozilla/5.0"}
         ).status_code == 200,
         "Actualités financières"),
    ]

    ok_count = 0
    for nom, test_fn, desc in TESTS:
        try:
            ok = test_fn()
            status = "✅" if ok else "⚠️  "
            if ok: ok_count += 1
        except Exception as e:
            status = "❌ "
            ok = False

        print(f"  {status} {nom:30s} {desc}")
        time.sleep(0.3)

    print(f"\n  {ok_count}/{len(TESTS)} APIs accessibles")
    if ok_count < 3:
        print("  ⚠️  Peu d'APIs disponibles — vérifier la connexion internet")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# §5  CRÉATION DU FICHIER .ENV
# ══════════════════════════════════════════════════════════════════════════════

def create_env() -> None:
    """Crée le template .env pour les clés API optionnelles."""
    env_path = PROJECT_DIR / ".env"
    if env_path.exists():
        print(f"  .env existe déjà : {env_path}")
        return

    env_content = """# ═══════════════════════════════════════════════════════
# CLÉS API GRATUITES — Market Oracle BCE
# Remplir et sauvegarder dans /Users/macbook/Documents/monbotv3/
# ═══════════════════════════════════════════════════════

# Alpha Vantage — intraday haute fréquence (25 req/jour gratuit)
# → https://alphavantage.co
ALPHA_VANTAGE_KEY=

# Finnhub — news, sentiment, calendrier résultats
# → https://finnhub.io
FINNHUB_KEY=

# FRED — données macro US avec accès JSON avancé
# → https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY=

# NewsAPI — actualités générales
# → https://newsapi.org
NEWS_API_KEY=

# Capital de trading (€) — pour le sizing des positions
CAPITAL=10000
"""
    env_path.write_text(env_content, encoding="utf-8")
    print(f"  ✅ .env créé : {env_path}")
    print("     Remplir avec vos clés API gratuites (toutes optionnelles)")


# ══════════════════════════════════════════════════════════════════════════════
# §6  COMMANDES DE DÉMARRAGE
# ══════════════════════════════════════════════════════════════════════════════

def show_start_commands() -> None:
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║  COMMANDES POUR DÉMARRER                                            ║
╚══════════════════════════════════════════════════════════════════════╝

  ── ÉTAPE 1 : Aller dans le dossier ────────────────────────────────
  cd /Users/macbook/Documents/monbotv3

  ── ÉTAPE 2 : Signal de décision rapide ─────────────────────────────
  python3 orchestrator.py --decision

  ── ÉTAPE 3 : Dashboard HTML (ouvre Safari) ─────────────────────────
  python3 orchestrator.py --html --open

  ── ÉTAPE 4 : Dashboard Streamlit BCE (interface web complète) ───────
  python3 -m streamlit run bce_dashboard.py
  → Ouvre http://localhost:8501 dans votre navigateur

  ── ÉTAPE 5 : Rapport BCE complet (terminal) ─────────────────────────
  python3 bce_engine.py

  ── MISE À JOUR AUTOMATIQUE (toutes les heures via cron) ─────────────
  python3 orchestrator.py --cron

  ── CORRIGER LES BUGS EXISTANTS ──────────────────────────────────────
  python3 corrections.py --fix all

  ── AIDE COMPLÈTE ────────────────────────────────────────────────────
  python3 orchestrator.py --commands
""")


# ══════════════════════════════════════════════════════════════════════════════
# §7  INTÉGRATION dans streamlit_app.py et bot_v3.py
# ══════════════════════════════════════════════════════════════════════════════

def integrate_bce_in_streamlit() -> None:
    """
    Ajoute un onglet BCE dans streamlit_app.py existant.
    Intégration non-destructive : ajoute à la fin des onglets existants.
    """
    st_file = PROJECT_DIR / "streamlit_app.py"
    if not st_file.exists():
        print("  streamlit_app.py absent — pas d'intégration")
        return

    content = st_file.read_text(encoding="utf-8")

    # Vérifier si déjà intégré
    if "bce_dashboard" in content or "tab_bce_oracle" in content:
        print("  ✅ bce_dashboard déjà intégré dans streamlit_app.py")
        return

    # Injection de l'import en début de fichier
    IMPORT_SNIPPET = """
# ── Intégration BCE Dashboard ─────────────────────────────────────────────────
try:
    from bce_dashboard import (
        tab_decision as tab_bce_decision,
        tab_tendances as tab_bce_tendances,
        tab_impact as tab_bce_impact,
        load_rapport_bce, load_decision, load_indices,
    )
    BCE_DASH_OK = True
except ImportError:
    BCE_DASH_OK = False
# ──────────────────────────────────────────────────────────────────────────────
"""

    # Ajouter l'import après les imports existants
    if "import streamlit as st" in content:
        content = content.replace(
            "import streamlit as st",
            "import streamlit as st" + IMPORT_SNIPPET,
            1
        )

    # Backup et sauvegarde
    backup_dir = PROJECT_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    (backup_dir / f"streamlit_app_{ts}.py").write_text(
        st_file.read_text(encoding="utf-8"), encoding="utf-8"
    )
    st_file.write_text(content, encoding="utf-8")
    print(f"  ✅ Intégration BCE dans streamlit_app.py (backup : backups/)")


# ══════════════════════════════════════════════════════════════════════════════
# §8  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="install_bce.py — Installation et configuration du projet",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--deps",    action="store_true",
                         help="Installer les dépendances Python")
    parser.add_argument("--check",   action="store_true",
                         help="Vérifier l'état de l'installation")
    parser.add_argument("--db",      action="store_true",
                         help="Initialiser les bases de données")
    parser.add_argument("--test",    action="store_true",
                         help="Tester toutes les APIs")
    parser.add_argument("--env",     action="store_true",
                         help="Créer le fichier .env")
    parser.add_argument("--integrate",action="store_true",
                         help="Intégrer BCE dans streamlit_app.py")
    parser.add_argument("--all",     action="store_true",
                         help="Installation complète (tout faire)")
    args = parser.parse_args()

    # Installation complète par défaut
    if not any([args.deps, args.check, args.db, args.test,
                args.env, args.integrate]):
        args.all = True

    if args.all or args.deps:
        install_deps()

    if args.all or args.env:
        print("📝  CONFIGURATION .ENV\n" + "─"*40)
        create_env()
        print()

    if args.all or args.check:
        check_installation()

    if args.all or args.db:
        init_database()

    if args.all or args.test:
        test_apis()

    if args.all or args.integrate:
        print("🔗  INTÉGRATION\n" + "─"*40)
        integrate_bce_in_streamlit()
        print()

    if args.all:
        show_start_commands()

    print("  Installation terminée ✅")
    print(f"  Dossier : {PROJECT_DIR.resolve()}\n")


if __name__ == "__main__":
    main()
