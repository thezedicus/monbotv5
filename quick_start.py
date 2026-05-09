#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZEDICUS v3 — Quick Start Script
Démarre l'application avec toutes les vérifications nécessaires
"""

import sys, os
from pathlib import Path
import subprocess
import json

def print_header():
    """Affiche le header"""
    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║  THE ZEDICUS v3 — Advanced Trader Bot                        ║
    ║  Quick Start Configuration                                   ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

def check_python_version():
    """Vérifie la version Python"""
    print("✓ Checking Python version...", end=" ")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✓ Python {version.major}.{version.minor}")
        return True
    else:
        print(f"✗ Python 3.8+ required (found {version.major}.{version.minor})")
        return False

def check_dependencies():
    """Vérifie les dépendances"""
    print("\n✓ Checking dependencies...")
    
    required = {
        'streamlit': 'Streamlit',
        'pandas': 'Pandas',
        'numpy': 'NumPy',
        'plotly': 'Plotly',
        'yfinance': 'yfinance',
        'feedparser': 'Feedparser'
    }
    
    missing = []
    for module, name in required.items():
        try:
            __import__(module)
            print(f"  ✓ {name}")
        except ImportError:
            print(f"  ✗ {name} (MISSING)")
            missing.append(module)
    
    if missing:
        print(f"\n⚠️  Missing dependencies: {', '.join(missing)}")
        response = input("\nInstall now? (y/n): ").lower()
        if response == 'y':
            print("📦 Installing dependencies...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements_v3.txt'])
            return True
        else:
            return False
    
    return True

def check_files():
    """Vérifie les fichiers essentiels"""
    print("\n✓ Checking essential files...")
    
    required_files = [
        'zedicus_v3.py',
        'integration_module.py',
        'zedicus_config.json'
    ]
    
    missing = []
    for file in required_files:
        if Path(file).exists():
            print(f"  ✓ {file}")
        else:
            print(f"  ✗ {file} (MISSING)")
            missing.append(file)
    
    return len(missing) == 0

def setup_cache():
    """Configure le cache"""
    print("\n✓ Setting up cache...")
    cache_dir = Path('.cache_zedicus')
    cache_dir.mkdir(exist_ok=True)
    print(f"  ✓ Cache directory: {cache_dir}")

def setup_logs():
    """Configure les logs"""
    print("\n✓ Setting up logging...")
    log_file = Path('zedicus.log')
    print(f"  ✓ Log file: {log_file}")

def load_config():
    """Charge la configuration"""
    print("\n✓ Loading configuration...")
    
    config_file = Path('zedicus_config.json')
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
        print(f"  ✓ Loaded from {config_file}")
        print(f"  ✓ Ticker: {config.get('trading', {}).get('ticker', 'EURUSD=X')}")
        print(f"  ✓ Cache: {config.get('cache', {}).get('enabled', True)}")
        return config
    else:
        print(f"  ✗ Config file not found")
        return None

def show_menu():
    """Affiche le menu principal"""
    print("\n" + "="*60)
    print("ZEDICUS v3 — MENU PRINCIPAL")
    print("="*60)
    print("""
    1. 🚀 Lancer le Dashboard Streamlit
    2. 🔧 Tester l'intégration Repository
    3. 📊 Lancer une analyse complète
    4. 🔄 Configurer les paramètres
    5. 📚 Voir la documentation
    6. ❌ Quitter
    """)

def run_streamlit():
    """Lance Streamlit"""
    print("\n▶️  Launching Streamlit Dashboard...")
    subprocess.run(['streamlit', 'run', 'zedicus_v3.py'])

def test_integration():
    """Teste l'intégration"""
    print("\n▶️  Testing Repository Integration...")
    subprocess.run([sys.executable, 'integration_module.py'])

def full_analysis():
    """Lance une analyse complète"""
    print("\n▶️  Running Full Analysis...")
    
    try:
        from zedicus_v3 import (
            TechnicalAnalyzer,
            NewsAnalyzer,
            TradingSignalGenerator
        )
        
        print("\n📊 ANALYSE COMPLÈTE ZEDICUS v3\n")
        
        # Créer l'analyseur
        analyzer = TechnicalAnalyzer("EURUSD=X")
        
        # Fetch data
        print("📥 Fetching data...", end=" ")
        if analyzer.fetch_data(days=90):
            print("✓")
        else:
            print("✗")
            return
        
        # Technical Analysis
        print("📈 Technical Analysis...", end=" ")
        patterns = analyzer.identify_candle_patterns()
        sr = analyzer.calculate_support_resistance()
        indicators = analyzer.calculate_indicators()
        print(f"✓ ({len(patterns)} patterns)")
        
        # Afficher les patterns
        if patterns:
            print("\n🕯️  Patterns Detected:")
            for pattern in patterns:
                print(f"  - {pattern.name}: {pattern.signal} (Force: {pattern.strength*100:.0f}%)")
        
        # Afficher S&R
        if sr:
            print("\n🎯 Support & Resistance:")
            print(f"  R2: {sr.resistance_2:.4f}")
            print(f"  R1: {sr.resistance_1:.4f}")
            print(f"  Pivot: {sr.pivot:.4f}")
            print(f"  S1: {sr.support_1:.4f}")
            print(f"  S2: {sr.support_2:.4f}")
        
        # Afficher indicateurs
        if indicators:
            print("\n📊 Indicators:")
            print(f"  RSI: {indicators.get('rsi', 50):.1f}")
            print(f"  MACD: {indicators.get('macd', 0):.5f}")
            print(f"  Price: {indicators.get('price', 0):.4f}")
        
        # News Analysis
        print("\n📰 News Analysis...", end=" ")
        news = NewsAnalyzer.fetch_bce_news()
        print(f"✓ ({len(news)} articles)")
        
        # Trading Signal
        print("\n🎯 Trading Signal...", end=" ")
        generator = TradingSignalGenerator(analyzer)
        signal = generator.generate_trade_signal()
        print("✓")
        
        if signal:
            print(f"\n{'='*50}")
            print(f"SIGNAL: {signal.action}")
            print(f"{'='*50}")
            print(f"Entry: {signal.entry_price:.4f}")
            print(f"TP: {signal.take_profit:.4f}")
            print(f"SL: {signal.stop_loss:.4f}")
            print(f"RRR: 1:{signal.risk_reward_ratio:.2f}")
            print(f"Confiance: {signal.confidence:.1f}%")
            print(f"Sources: {', '.join(signal.sources[:3])}")
            print(f"{'='*50}\n")
        
        print("✅ Analyse complète terminée!")
        
    except Exception as e:
        print(f"✗ Erreur: {e}")
        import traceback
        traceback.print_exc()

def show_config():
    """Affiche la configuration"""
    print("\n⚙️  CONFIGURATION ZEDICUS v3\n")
    
    config_file = Path('zedicus_config.json')
    if config_file.exists():
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        print("Trading Settings:")
        trading = config.get('trading', {})
        print(f"  Ticker: {trading.get('ticker')}")
        print(f"  Lookback: {trading.get('lookback_days')} days")
        print(f"  Risk/Trade: {trading.get('risk_per_trade')}%")
        print(f"  Target RRR: {trading.get('target_rrr')}")
        
        print("\nTechnical Settings:")
        tech = config.get('technical_analysis', {})
        print(f"  RSI Period: {tech.get('rsi_period')}")
        print(f"  MACD: ({tech.get('macd_fast')}, {tech.get('macd_slow')}, {tech.get('macd_signal')})")
        
        print("\nCache Settings:")
        cache = config.get('cache', {})
        print(f"  Enabled: {cache.get('enabled')}")
        print(f"  TTL: {cache.get('ttl_seconds')}s")
        
        print("\nModules:")
        modules = config.get('modules', {})
        for name, enabled in modules.items():
            status = "✓" if enabled else "✗"
            print(f"  {status} {name}")

def show_docs():
    """Affiche la documentation"""
    print("\n📚 DOCUMENTATION ZEDICUS v3\n")
    print("Consultez: ZEDICUS_V3_GUIDE.md")
    print("\nSections disponibles:")
    print("  1. Architecture Globale")
    print("  2. Modules Principaux")
    print("  3. Fonctionnalités Clés")
    print("  4. Guide d'Installation")
    print("  5. Intégration du Repo")
    print("  6. Utilisation")

def main():
    """Fonction principale"""
    print_header()
    
    # Vérifications
    if not check_python_version():
        return
    
    if not check_dependencies():
        print("\n⚠️  Please install dependencies to continue")
        return
    
    if not check_files():
        print("\n⚠️  Some essential files are missing")
        return
    
    setup_cache()
    setup_logs()
    config = load_config()
    
    print("\n✅ All checks passed!")
    
    # Menu principal
    while True:
        show_menu()
        choice = input("Sélectionnez une option (1-6): ").strip()
        
        if choice == '1':
            run_streamlit()
        elif choice == '2':
            test_integration()
        elif choice == '3':
            full_analysis()
        elif choice == '4':
            show_config()
        elif choice == '5':
            show_docs()
        elif choice == '6':
            print("\n✅ Goodbye!")
            break
        else:
            print("❌ Invalid option")

if __name__ == "__main__":
    main()
