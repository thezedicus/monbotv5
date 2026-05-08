#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  clean_project.py — Nettoyeur & correcteur du projet Market Oracle BCE      ║
║  Supprime les fichiers inutiles · Corrige les bugs · Répare le code         ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  COMMANDES MAC :                                                             ║
║                                                                              ║
║  python3 clean_project.py               # Rapport complet (sans modifier)  ║
║  python3 clean_project.py --fix         # Corriger tous les bugs           ║
║  python3 clean_project.py --clean       # Supprimer les fichiers inutiles  ║
║  python3 clean_project.py --all         # Tout faire (fix + clean)         ║
║  python3 clean_project.py --backup      # Créer une sauvegarde du projet   ║
║  python3 clean_project.py --reset-cache # Vider les caches Python/Streamlit║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import re
import shutil
import subprocess
import hashlib
import tarfile
import argparse
from pathlib  import Path
from datetime import datetime
from typing   import Dict, List, Tuple, Optional

# ── Dossier du projet ─────────────────────────────────────────────────────────
PROJECT = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════════════
# §1  CATALOGUE DES FICHIERS
# ═══════════════════════════════════════════════════════════════════════════════

# Fichiers indispensables — NE PAS TOUCHER
FICHIERS_ESSENTIELS = {
    "bce_dashboard.py":            "Dashboard principal (remplace tous les anciens)",
    "bce_engine.py":               "Moteur BCE — APIs + SQLite + tendances + impact",
    "orchestrator.py":             "Orchestrateur — décision + dashboard HTML",
    "install_bce.py":              "Installation et configuration du projet",
    "clean_project.py":            "Ce fichier — nettoyeur du projet",
    "bot_v3.py":                   "Bot trading v3 (backtest, screener, rapport)",
    "api_manager.py":              "Gestionnaire APIs marché (YF, FRED, CoinGecko)",
    "market_db.py":                "Base de données SQLite marché",
    "market_oracle_extension.py":  "Analyse quantitative avancée (Monte-Carlo, etc.)",
    "features_engine.py":          "Moteur features ML (81 indicateurs)",
    "generate_dashboard.py":       "Générateur dashboard HTML iOS",
    "bce_data.py":                 "Moteur données BCE (indices EU, veille RSS)",
    "streamlit_app.py":            "Dashboard Streamlit général (multi-actifs)",
}

# Fichiers obsolètes — À SUPPRIMER
FICHIERS_OBSOLETES = {
    "api_sources.py":       "Remplacé par api_manager.py",
    "bot.py":               "Version v1 — remplacée par bot_v3.py",
    "bot_v2.py":            "Version v2 — remplacée par bot_v3.py",
    "dashboard.py":         "Ancien dashboard — remplacé par bce_dashboard.py",
    "dashboard_v3.py":      "Ancien dashboard v3 — remplacé par bce_dashboard.py (importe bot_v3_final inexistant)",
    "market_oracle_bce.py": "Ancienne version — remplacée par bce_dashboard.py",
    "market_snapshot.py":   "Fonctionnalité intégrée dans api_manager.py",
    "corrections.py":       "Remplacé par clean_project.py",
}

# Bugs connus et leurs correctifs
BUGS = [
    {
        "id":      "cummax_ndarray",
        "fichier": "market_oracle_extension.py",
        "desc":    "cummax() appelé sur ndarray numpy → crash Monte-Carlo",
        "detect":  lambda c: ".cummax()" in c and "pd.Series(paths" not in c,
        "fix":     lambda c: c.replace(
            "np.max(1 - paths[s]/paths[s].cummax())",
            "np.max(1 - paths[s]/pd.Series(paths[s]).cummax())"
        ).replace(
            "paths[s].cummax()",
            "pd.Series(paths[s]).cummax()"
        ),
    },
    {
        "id":      "bot_v3_final_import",
        "fichier": "dashboard_v3.py",
        "desc":    "Importe bot_v3_final qui n'existe pas → ImportError au lancement",
        "detect":  lambda c: "bot_v3_final" in c,
        "fix":     lambda c: c.replace("from bot_v3_final import", "from bot_v3 import")
                               .replace("import bot_v3_final", "import bot_v3"),
    },
    {
        "id":      "synthetic_default",
        "fichier": "bot_v3.py",
        "desc":    "use_synthetic=True par défaut → données inventées au lieu de données réelles",
        "detect":  lambda c: "use_synthetic: bool = True" in c,
        "fix":     lambda c: c.replace(
            "use_synthetic: bool = True",
            "use_synthetic: bool = False  # CORRIGÉ — données réelles par défaut"
        ).replace(
            'TradingBot(mode="demo", use_synthetic=True)',
            'TradingBot(mode="demo", use_synthetic=False)'
        ).replace(
            'TradingBot(mode="paper", use_synthetic=True)',
            'TradingBot(mode="paper", use_synthetic=False)'
        ),
    },
    {
        "id":      "pandas_ta",
        "fichier": "codesupplementaire.py",
        "desc":    "import pandas_ta non installé → crash immédiat",
        "detect":  lambda c: "import pandas_ta" in c,
        "fix":     lambda c: re.sub(r"import pandas_ta as ta\n", "", c)
                               .replace("from pandas_ta import", "# from pandas_ta import"),
    },
    {
        "id":      "plotly_go_undefined",
        "fichier": "streamlit_app.py",
        "desc":    "go non défini si plotly absent → NameError ligne 370+",
        "detect":  lambda c: "import plotly" in c and "class _GoStub" not in c,
        "fix":     lambda c: c.replace(
            "except ImportError:\n    PLOTLY_OK = False\n    st.error",
            """except ImportError:
    PLOTLY_OK = False
    class _GoStub:
        Figure = object; Candlestick = object; Scatter = object
        Bar = object; Box = object; Heatmap = object
    go = _GoStub()
    def make_subplots(*a, **kw): return None
    # st.error""",
        ) if "except ImportError:\n    PLOTLY_OK = False\n    st.error" in c else c,
    },
    {
        "id":      "market_oracle_syntax",
        "fichier": "market_oracle.py",
        "desc":    "Fichier ne commence pas par # → erreur de parsing potentielle",
        "detect":  lambda c: len(c) > 0 and not c.startswith("#") and not c.startswith("'") and not c.startswith('"'),
        "fix":     lambda c: "# -*- coding: utf-8 -*-\n" + c,
    },
    {
        "id":      "main_ls_typo",
        "fichier": "market_ultimate.py",
        "desc":    "main()ls à la place de main() → SyntaxError",
        "detect":  lambda c: "main()ls" in c,
        "fix":     lambda c: c.replace("main()ls", "main()"),
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# §2  UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════════════

def divider(char: str = "─", n: int = 60) -> None:
    print(f"  {char * n}")

def header(titre: str, char: str = "═") -> None:
    print(f"\n{char * 62}")
    print(f"  {titre}")
    print(f"{char * 62}")

def ok(msg: str)   -> None: print(f"  ✅  {msg}")
def warn(msg: str) -> None: print(f"  ⚠️   {msg}")
def err(msg: str)  -> None: print(f"  ❌  {msg}")
def info(msg: str) -> None: print(f"  ℹ️   {msg}")

def check_syntax(fp: Path) -> Tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(fp)],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        return True, ""
    # Extraire ligne et message d'erreur
    msg = r.stderr.strip().split("\n")[-1] if r.stderr else "Erreur inconnue"
    return False, msg

def make_backup(fp: Path) -> Path:
    backup_dir = PROJECT / "backups"
    backup_dir.mkdir(exist_ok=True)
    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = backup_dir / f"{fp.stem}_{ts}{fp.suffix}"
    shutil.copy2(fp, dst)
    return dst

def file_hash(fp: Path) -> str:
    return hashlib.md5(fp.read_bytes()).hexdigest()[:8]


# ═══════════════════════════════════════════════════════════════════════════════
# §3  RAPPORT DE SANTÉ
# ═══════════════════════════════════════════════════════════════════════════════

def rapport_sante(verbose: bool = True) -> Dict:
    """Analyse complète du projet sans rien modifier."""
    result = {
        "essentiels":  {},
        "obsoletes":   {},
        "bugs":        [],
        "syntax_errors":[],
        "unknown":     [],
        "db":          {},
        "deps":        {},
    }

    if verbose:
        header("RAPPORT DE SANTÉ — Market Oracle BCE")

    # ── Fichiers essentiels ───────────────────────────────────────────────────
    if verbose:
        print(f"\n  FICHIERS ESSENTIELS\n  {'─'*58}")
        print(f"  {'Fichier':38s} {'État':14s} {'Lignes':8s} {'Syntaxe'}")
        print(f"  {'─'*78}")

    for nom, role in FICHIERS_ESSENTIELS.items():
        fp = PROJECT / nom
        if fp.exists():
            lines   = fp.read_text(encoding="utf-8",errors="ignore").count("\n")
            ok_, er = check_syntax(fp)
            status  = "✅ présent" if ok_ else "❌ erreur synta."
            result["essentiels"][nom] = {"ok": ok_, "lines": lines, "error": er}
            if verbose:
                print(f"  {nom:38s} {status:14s} {lines:8d}"
                      f"  {'OK' if ok_ else er[:28]}")
        else:
            result["essentiels"][nom] = {"ok": False, "lines": 0, "error": "absent"}
            if verbose:
                print(f"  {nom:38s} {'⚠️  ABSENT':14s}")

    # ── Fichiers obsolètes ────────────────────────────────────────────────────
    if verbose:
        print(f"\n  FICHIERS OBSOLÈTES (peuvent être supprimés)\n  {'─'*58}")

    for nom, raison in FICHIERS_OBSOLETES.items():
        fp = PROJECT / nom
        if fp.exists():
            sz = fp.stat().st_size // 1024
            result["obsoletes"][nom] = {"existe": True, "taille_kb": sz, "raison": raison}
            if verbose:
                print(f"  🗑️   {nom:35s} {sz:4d} KB  →  {raison[:35]}")
        else:
            result["obsoletes"][nom] = {"existe": False}

    # ── Bugs détectés ─────────────────────────────────────────────────────────
    if verbose:
        print(f"\n  BUGS DÉTECTÉS\n  {'─'*58}")

    for bug in BUGS:
        fp = PROJECT / bug["fichier"]
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            if bug["detect"](content):
                result["bugs"].append(bug)
                if verbose:
                    print(f"  🐛  [{bug['fichier']}] {bug['desc']}")
        except Exception as e:
            if verbose:
                warn(f"Impossible de lire {bug['fichier']} : {e}")

    if not result["bugs"] and verbose:
        ok("Aucun bug connu détecté")

    # ── Erreurs de syntaxe sur tous les .py ───────────────────────────────────
    if verbose:
        print(f"\n  VÉRIFICATION SYNTAXE (tous les .py)\n  {'─'*58}")

    for fp in sorted(PROJECT.glob("*.py")):
        ok_, er = check_syntax(fp)
        if not ok_:
            result["syntax_errors"].append({"fichier": fp.name, "error": er})
            if verbose:
                err(f"{fp.name:35s} → {er[:45]}")

    if not result["syntax_errors"] and verbose:
        ok("Tous les fichiers .py ont une syntaxe valide")

    # ── Fichiers inconnus ─────────────────────────────────────────────────────
    known = set(FICHIERS_ESSENTIELS.keys()) | set(FICHIERS_OBSOLETES.keys()) | {"clean_project.py"}
    for fp in sorted(PROJECT.glob("*.py")):
        if fp.name not in known:
            result["unknown"].append(fp.name)

    if result["unknown"] and verbose:
        print(f"\n  FICHIERS NON CATALOGUÉS\n  {'─'*40}")
        for f in result["unknown"]:
            info(f"{f}")

    # ── Bases de données ──────────────────────────────────────────────────────
    if verbose:
        print(f"\n  BASES DE DONNÉES\n  {'─'*40}")

    for db_name in ["bce_intelligence.db", "market.db"]:
        db_path = PROJECT / "data" / db_name
        if db_path.exists():
            sz = db_path.stat().st_size / 1024
            result["db"][db_name] = {"existe": True, "taille_kb": round(sz,1)}
            if verbose:
                ok(f"{db_name:30s} {sz:.1f} KB")
        else:
            result["db"][db_name] = {"existe": False}
            if verbose:
                warn(f"{db_name:30s} absent")

    # ── Dépendances ───────────────────────────────────────────────────────────
    DEPS = ["yfinance","requests","pandas","numpy","scipy",
             "streamlit","plotly","feedparser"]
    if verbose:
        print(f"\n  DÉPENDANCES PYTHON\n  {'─'*40}")

    for dep in DEPS:
        try:
            m   = __import__(dep.replace("-","_"))
            ver = getattr(m,"__version__","?")
            result["deps"][dep] = True
            if verbose:
                ok(f"{dep:15s} v{ver}")
        except ImportError:
            result["deps"][dep] = False
            if verbose:
                err(f"{dep:15s} MANQUANT → pip3 install {dep}")

    # ── Résumé ────────────────────────────────────────────────────────────────
    if verbose:
        n_bugs     = len(result["bugs"])
        n_obsoletes= sum(1 for v in result["obsoletes"].values() if v.get("existe"))
        n_missing  = sum(1 for v in result["essentiels"].values() if not v.get("ok"))
        n_syntax   = len(result["syntax_errors"])
        n_deps_miss= sum(1 for v in result["deps"].values() if not v)

        print(f"\n  {'═'*60}")
        print(f"  RÉSUMÉ")
        print(f"  {'─'*60}")
        print(f"  Bugs connus détectés      : {n_bugs}")
        print(f"  Fichiers obsolètes        : {n_obsoletes}")
        print(f"  Fichiers essentiels KO    : {n_missing}")
        print(f"  Erreurs de syntaxe        : {n_syntax}")
        print(f"  Dépendances manquantes    : {n_deps_miss}")
        print()

        if n_bugs + n_obsoletes + n_missing + n_syntax + n_deps_miss == 0:
            print("  🎉  Projet en parfait état !")
        else:
            print("  Recommandations :")
            if n_deps_miss   > 0: info("pip3 install yfinance requests pandas numpy scipy streamlit plotly feedparser")
            if n_bugs        > 0: info("python3 clean_project.py --fix")
            if n_obsoletes   > 0: info("python3 clean_project.py --clean")
            if n_syntax      > 0: info("python3 clean_project.py --fix   (corrige les erreurs connues)")
        print()

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# §4  CORRECTEUR DE BUGS
# ═══════════════════════════════════════════════════════════════════════════════

def corriger_bugs(dry_run: bool = False) -> int:
    """Applique tous les correctifs de bugs connus. Retourne le nombre de fichiers modifiés."""
    header("CORRECTION DES BUGS")
    fixed = 0

    for bug in BUGS:
        fp = PROJECT / bug["fichier"]
        if not fp.exists():
            info(f"[{bug['fichier']}] absent — ignoré")
            continue

        try:
            content  = fp.read_text(encoding="utf-8", errors="ignore")
            if not bug["detect"](content):
                ok(f"[{bug['fichier']}] {bug['id']} — déjà corrigé")
                continue

            new_content = bug["fix"](content)
            if new_content == content:
                warn(f"[{bug['fichier']}] correctif {bug['id']} n'a pas modifié le fichier")
                continue

            if dry_run:
                print(f"  🔧 [DRY-RUN] {bug['fichier']} → {bug['desc']}")
                fixed += 1
                continue

            # Backup avant modification
            bkp = make_backup(fp)
            fp.write_text(new_content, encoding="utf-8")

            # Vérifier la syntaxe après correction
            ok_, er = check_syntax(fp)
            if ok_:
                ok(f"[{bug['fichier']}] {bug['id']} → corrigé ✓  (backup: backups/{bkp.name})")
                fixed += 1
            else:
                # Rollback si la correction a cassé la syntaxe
                shutil.copy2(bkp, fp)
                err(f"[{bug['fichier']}] correctif annulé (syntaxe invalide après) : {er}")

        except Exception as e:
            err(f"[{bug['fichier']}] Erreur : {e}")

    # Correctifs supplémentaires non listés dans BUGS
    _corriger_bot_v3_live()

    print(f"\n  {fixed} fichier(s) corrigé(s)")
    return fixed


def _corriger_bot_v3_live() -> None:
    """Corrections supplémentaires spécifiques à bot_v3.py."""
    fp = PROJECT / "bot_v3.py"
    if not fp.exists():
        return

    content  = fp.read_text(encoding="utf-8", errors="ignore")
    original = content

    # Brancher api_manager.py si présent
    if "from api_manager import MarketAPI" not in content:
        snippet = """
# ── Intégration api_manager.py (données réelles) ────────────────────────────
try:
    import sys as _sys
    _sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    from api_manager import MarketAPI as _MarketAPI
    _API = _MarketAPI()
    API_MANAGER_AVAILABLE = True
except Exception:
    _API = None
    API_MANAGER_AVAILABLE = False
# ─────────────────────────────────────────────────────────────────────────────
"""
        # Insérer après les imports yfinance
        if "import yfinance as yf" in content:
            content = content.replace(
                "import yfinance as yf",
                "import yfinance as yf" + snippet,
                1,
            )

    if content != original:
        make_backup(fp)
        fp.write_text(content, encoding="utf-8")
        ok(f"[bot_v3.py] api_manager.py branché pour les prix live")


# ═══════════════════════════════════════════════════════════════════════════════
# §5  NETTOYEUR DE FICHIERS OBSOLÈTES
# ═══════════════════════════════════════════════════════════════════════════════

def nettoyer_fichiers(dry_run: bool = False, force: bool = False) -> int:
    """Supprime les fichiers obsolètes après confirmation. Retourne le nombre supprimé."""
    header("NETTOYAGE DES FICHIERS OBSOLÈTES")

    a_supprimer = []
    for nom, raison in FICHIERS_OBSOLETES.items():
        fp = PROJECT / nom
        if fp.exists():
            sz = fp.stat().st_size // 1024
            a_supprimer.append((fp, nom, raison, sz))

    if not a_supprimer:
        ok("Aucun fichier obsolète trouvé — projet déjà propre")
        return 0

    print(f"\n  Fichiers à supprimer :\n  {'─'*58}")
    total_kb = 0
    for fp, nom, raison, sz in a_supprimer:
        print(f"  🗑️   {nom:35s} {sz:4d} KB")
        print(f"       Raison : {raison}")
        total_kb += sz

    print(f"\n  Total : {len(a_supprimer)} fichiers · {total_kb} KB libérés")

    if dry_run:
        print("\n  [DRY-RUN] Aucun fichier supprimé")
        return len(a_supprimer)

    if not force:
        print()
        reponse = input("  Confirmer la suppression ? [o/N] : ").strip().lower()
        if reponse not in ("o","oui","y","yes"):
            print("  Annulé.")
            return 0

    # Backup puis suppression
    print(f"\n  Suppression en cours...\n  {'─'*40}")
    deleted = 0
    for fp, nom, raison, sz in a_supprimer:
        try:
            bkp = make_backup(fp)
            fp.unlink()
            ok(f"Supprimé : {nom}  (backup : backups/{bkp.name})")
            deleted += 1
        except Exception as e:
            err(f"Impossible de supprimer {nom} : {e}")

    print(f"\n  {deleted} fichier(s) supprimé(s) · Backups dans : {PROJECT / 'backups'}")
    return deleted


# ═══════════════════════════════════════════════════════════════════════════════
# §6  SAUVEGARDE DU PROJET
# ═══════════════════════════════════════════════════════════════════════════════

def backup_projet() -> Path:
    """Crée une archive tar.gz complète du projet."""
    header("SAUVEGARDE DU PROJET")
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    arc_name = PROJECT / f"backup_{ts}.tar.gz"

    EXCLUDE = {".git","__pycache__",".streamlit","backups","node_modules",
                "venv",".env"}

    try:
        with tarfile.open(arc_name, "w:gz") as tar:
            for item in sorted(PROJECT.iterdir()):
                if item.name in EXCLUDE or item.name.startswith("."):
                    continue
                if item.is_file():
                    tar.add(item, arcname=item.name)
                elif item.is_dir() and item.name not in EXCLUDE:
                    tar.add(item, arcname=item.name,
                             recursive=True,
                             filter=lambda ti: (
                                 None if any(ex in ti.name for ex in EXCLUDE) else ti
                             ))

        sz = arc_name.stat().st_size // 1024
        ok(f"Archive créée : {arc_name.name} ({sz} KB)")
        print(f"\n  Chemin complet : {arc_name.resolve()}")
        return arc_name

    except Exception as e:
        err(f"Erreur lors de la sauvegarde : {e}")
        return PROJECT


# ═══════════════════════════════════════════════════════════════════════════════
# §7  RESET CACHE
# ═══════════════════════════════════════════════════════════════════════════════

def reset_cache() -> None:
    """Vide les caches Python et Streamlit."""
    header("NETTOYAGE DU CACHE")
    CACHES = [
        PROJECT / "__pycache__",
        Path.home() / ".streamlit" / "cache",
        PROJECT / ".streamlit" / "cache",
        PROJECT / "cache",
    ]
    for cache_dir in CACHES:
        if cache_dir.exists():
            try:
                shutil.rmtree(cache_dir)
                ok(f"Cache supprimé : {cache_dir}")
            except Exception as e:
                warn(f"{cache_dir} : {e}")
        else:
            info(f"Cache absent : {cache_dir.name}/")

    # Nettoyer aussi les .pyc
    n_pyc = 0
    for pyc in PROJECT.rglob("*.pyc"):
        try:
            pyc.unlink(); n_pyc += 1
        except Exception:
            pass
    if n_pyc > 0:
        ok(f"{n_pyc} fichier(s) .pyc supprimé(s)")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# §8  INSTALLATION RAPIDE DES DÉPENDANCES
# ═══════════════════════════════════════════════════════════════════════════════

def installer_deps() -> None:
    """Installe toutes les dépendances manquantes."""
    header("INSTALLATION DES DÉPENDANCES")
    DEPS = [
        ("yfinance",      "Données Yahoo Finance"),
        ("requests",      "Appels APIs REST"),
        ("pandas",        "Manipulation de données"),
        ("numpy",         "Calculs numériques"),
        ("scipy",         "Statistiques avancées"),
        ("streamlit",     "Dashboard web"),
        ("plotly",        "Graphiques interactifs"),
        ("feedparser",    "Flux RSS actualités"),
        ("python-dotenv", "Fichier .env"),
    ]
    for pkg, desc in DEPS:
        mod = pkg.replace("-","_")
        try:
            __import__(mod)
            ok(f"{pkg:20s} déjà installé")
        except ImportError:
            print(f"  📥 Installation de {pkg}...", end=" ", flush=True)
            r = subprocess.run(
                [sys.executable,"-m","pip","install",pkg,
                 "--break-system-packages","-q"],
                capture_output=True, text=True,
            )
            print("✅" if r.returncode == 0 else f"❌ {r.stderr[:50]}")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# §9  RAPPORT FINAL STRUCTURÉ
# ═══════════════════════════════════════════════════════════════════════════════

def afficher_resume_final() -> None:
    """Affiche un résumé de l'état du projet après les opérations."""
    print(f"\n{'═'*62}")
    print(f"  ÉTAT FINAL DU PROJET")
    print(f"{'═'*62}")

    essentiels_ok = sum(
        1 for nom in FICHIERS_ESSENTIELS
        if (PROJECT / nom).exists()
    )
    obsoletes_reste = sum(
        1 for nom in FICHIERS_OBSOLETES
        if (PROJECT / nom).exists()
    )

    print(f"\n  Fichiers essentiels présents : {essentiels_ok}/{len(FICHIERS_ESSENTIELS)}")
    print(f"  Fichiers obsolètes restants  : {obsoletes_reste}")

    print(f"\n  COMMANDES DE LANCEMENT :")
    print(f"  {'─'*50}")
    print(f"  python3 -m streamlit run bce_dashboard.py")
    print(f"  python3 orchestrator.py --decision")
    print(f"  python3 orchestrator.py --html --open")
    print(f"  python3 bce_engine.py --tendances")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# §10  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("""
╔══════════════════════════════════════════════════════════╗
║  clean_project.py — Market Oracle BCE                   ║
║  Nettoyeur · Correcteur · Gestionnaire de fichiers      ║
╚══════════════════════════════════════════════════════════╝
""")

    parser = argparse.ArgumentParser(
        description="Nettoyeur et correcteur du projet Market Oracle BCE",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--fix",         action="store_true",
                         help="Corriger tous les bugs connus")
    parser.add_argument("--clean",       action="store_true",
                         help="Supprimer les fichiers obsolètes")
    parser.add_argument("--all",         action="store_true",
                         help="Tout faire : rapport + fix + clean")
    parser.add_argument("--backup",      action="store_true",
                         help="Créer une sauvegarde tar.gz du projet")
    parser.add_argument("--reset-cache", action="store_true",
                         help="Vider les caches Python et Streamlit")
    parser.add_argument("--install",     action="store_true",
                         help="Installer les dépendances manquantes")
    parser.add_argument("--dry-run",     action="store_true",
                         help="Simuler sans rien modifier")
    parser.add_argument("--force",       action="store_true",
                         help="Ne pas demander de confirmation pour --clean")
    args = parser.parse_args()

    # Par défaut : rapport seulement
    if not any([args.fix, args.clean, args.all, args.backup,
                args.reset_cache, args.install]):
        rapport_sante(verbose=True)
        return

    # Backup en premier si demandé
    if args.backup or args.all:
        backup_projet()

    # Installation des dépendances
    if args.install or args.all:
        installer_deps()

    # Reset cache
    if args.reset_cache:
        reset_cache()

    # Rapport de santé (toujours en mode --all)
    if args.all:
        rapport_sante(verbose=True)

    # Correctifs bugs
    if args.fix or args.all:
        corriger_bugs(dry_run=args.dry_run)

    # Nettoyage fichiers
    if args.clean or args.all:
        nettoyer_fichiers(dry_run=args.dry_run, force=args.force or args.all)

    # Rapport final
    afficher_resume_final()


if __name__ == "__main__":
    main()
