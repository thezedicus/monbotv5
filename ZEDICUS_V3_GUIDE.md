# 🚀 ZEDICUS v3 — GUIDE COMPLET

## 📋 TABLE DES MATIÈRES

1. [Architecture Globale](#architecture)
2. [Modules Principaux](#modules)
3. [Fonctionnalités Clés](#fonctionnalites)
4. [Guide d'Installation](#installation)
5. [Intégration du Repo](#integration)
6. [Utilisation](#utilisation)

---

## <a id="architecture"></a>🏗️ Architecture Globale

### Vue d'Ensemble

```
┌─────────────────────────────────────────────────────────────┐
│                    ZEDICUS v3 — Tier Application              │
├─────────────────────────────────────────────────────────────┤
│  Frontend Streamlit (UI interactive)                         │
│  - Dashboard                                                 │
│  - Trading Signals                                           │
│  - Technical Analysis                                        │
│  - News & Market                                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│           Repository Orchestrator (Intégration)              │
├─────────────────────────────────────────────────────────────┤
│  - Module Registry                                           │
│  - Data Pipeline                                             │
│  - Inter-Module Communication                                │
│  - Configuration Manager                                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
┌───────▼──────┐ ┌────▼──────┐ ┌────▼────────┐
│ Technical    │ │   News    │ │   Trading   │
│ Analyzer     │ │ Analyzer  │ │   Signals   │
├──────────────┤ ├───────────┤ ├─────────────┤
│- Bougies     │ │- Feeds    │ │- Entry/Exit │
│- Patterns    │ │- Sentiment│ │- Risk/Reward│
│- S&R Levels  │ │- Impact   │ │- Confidence │
│- Indicators  │ │           │ │             │
└───────┬──────┘ └────┬──────┘ └────┬────────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
┌───────▼──────┐           ┌────────▼─────┐
│ Cache Manager│           │ File I/O     │
├──────────────┤           ├──────────────┤
│- Memory      │           │- JSON        │
│- Disk        │           │- Pickle      │
│- TTL         │           │- CSV         │
└──────────────┘           └──────────────┘
```

---

## <a id="modules"></a>📦 Modules Principaux

### 1. **TechnicalAnalyzer** — Analyse Technique Complète

**Classe:** `TechnicalAnalyzer`  
**Responsabilités:**
- ✓ Téléchargement données OHLC
- ✓ Identification patterns de chandelles
- ✓ Calcul support/résistance
- ✓ Indicateurs (RSI, MACD, Bandes Bollinger)

**Méthodes principales:**
```python
analyzer = TechnicalAnalyzer("EURUSD=X")
analyzer.fetch_data(days=90)

# Patterns
patterns = analyzer.identify_candle_patterns(lookback=20)
# → [CandlePattern(...), ...]

# Support & Résistance
sr = analyzer.calculate_support_resistance(lookback=50)
# → SupportResistance(support_1=..., resistance_1=...)

# Indicateurs
indicators = analyzer.calculate_indicators()
# → {'rsi': 45.3, 'macd': 0.0005, ...}
```

**Patterns détectés:**
- 🕯️ Doji (indécision)
- 🔨 Marteau Haussier (achat)
- ⭐ Étoile du Soir (vente)
- 📦 Engulfing Haussier/Baissier (fort signal)

---

### 2. **NewsAnalyzer** — Analyse des News & Sentiment

**Classe:** `NewsAnalyzer`  
**Responsabilités:**
- ✓ Récupération news BCE
- ✓ Analyse sentiment
- ✓ Classification d'impact
- ✓ Pertinence pour trading

**Méthodes principales:**
```python
# Récupérer les news
news = NewsAnalyzer.fetch_bce_news()
# → [{'title': '...', 'published': '...', ...}, ...]

# Analyser sentiment
sentiment = NewsAnalyzer.analyze_sentiment("L'euro baisse")
# → -0.5 (négatif)

# Classifier l'impact
impact = NewsAnalyzer.classify_news_impact("BCE hausse taux")
# → NewsImpact(impact_score=+75, category="BCE", ...)
```

**Catégories d'impact:**
- 🏦 BCE (poids: 0.8)
- 📊 Économie (poids: 0.5)
- 🌍 Politique (poids: 0.3)
- 📈 Données (poids: 0.7)

---

### 3. **TradingSignalGenerator** — Génération de Signaux

**Classe:** `TradingSignalGenerator`  
**Responsabilités:**
- ✓ Génération points d'entrée
- ✓ Génération points de sortie
- ✓ Calcul Risk/Reward
- ✓ Signal final robuste

**Méthodes principales:**
```python
generator = TradingSignalGenerator(analyzer)

# Points d'entrée
entries = generator.generate_entry_points()
# → [{'type': 'Support Principal', 'price': ..., ...}, ...]

# Points de sortie
exits = generator.generate_exit_points()
# → [{'type': 'Résistance 1', 'type_exit': 'TP', ...}, ...]

# Signal final
signal = generator.generate_trade_signal()
# → TradeSignal(action='ACHETER', entry_price=..., confidence=85.3, ...)
```

**Signal à retourner:**
```
TradeSignal(
    action: "ACHETER" | "VENDRE" | "ATTENDRE"
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward_ratio: float (ex: 1:2.5)
    confidence: float (0-100)
    sources: List[str]  # Sources du signal
)
```

---

### 4. **CacheManager** — Gestion Cache Multi-Niveaux

**Classe:** `CacheManager`  
**Responsabilités:**
- ✓ Cache mémoire (rapide)
- ✓ Cache disque (persistent)
- ✓ TTL (Time To Live)
- ✓ Synchronisation

**Utilisation:**
```python
cache = CacheManager()

# Écrire
cache.set('price_data', data, ttl_seconds=3600)

# Lire
data = cache.get('price_data')

# Vider
cache.clear()
cache.clear('price*')  # Pattern
```

---

### 5. **RepoIntegrator** — Intégration du Repository

**Classe:** `RepoIntegrator`  
**Responsabilités:**
- ✓ Découverte des modules
- ✓ Chargement dynamique
- ✓ Analyse structure
- ✓ Mapping de dépendances

---

## <a id="fonctionnalites"></a>✨ Fonctionnalités Clés

### 🎯 1. Analyse Technique Avancée

**Points d'entrée intelligents:**
```
✓ Support Principal (confiance: 80%)
✓ Pivot (confiance: 70%)
✓ Zone Survendue (RSI < 30) (confiance: 85%)
```

**Points de sortie optimaux:**
```
✓ Take Profit 1 (Résistance 1)
✓ Take Profit 2 (Résistance 2)
✓ Stop Loss (Support 2 + ATR)
```

### 📊 2. Indicateurs Techniques

**RSI (Relative Strength Index)**
```
- < 30: Survendu → Signal d'ACHAT potentiel
- > 70: Suracheté → Signal de VENTE potentiel
- 30-70: Zone neutre
```

**MACD (Moving Average Convergence Divergence)**
```
- Histogram positif: Momentum haussier
- Histogram négatif: Momentum baissier
- Croisement signal: Retournement possible
```

**Bandes Bollinger**
```
- Prix > BB Upper: Suracheté
- Prix < BB Lower: Survendu
- Largeur: Mesure la volatilité
```

### 🎲 3. Gestion du Risque

**Risk/Reward Ratio:**
```
RRR = (TP - Entry) / (Entry - SL)
Optimal: RRR >= 2:1
```

**Position Sizing:**
```
Position = (Capital * Risk%) / (Entry - SL)
Risk% = 2% par position (recommandé)
```

### 📈 4. Signaux Fluides

Le système vote pour chaque module:
```
Patterns de chandelles + RSI + MACD + S&R
→ Score de confiance global (0-100%)
→ Action finale: ACHETER / VENDRE / ATTENDRE
```

---

## <a id="installation"></a>🔧 Installation

### Prérequis

```bash
Python 3.8+
pip install streamlit streamlit-extras
pip install pandas numpy
pip install yfinance
pip install plotly
pip install feedparser
```

### Installation Complète

```bash
# Cloner le repo
git clone https://github.com/thezedicus/monbotv5.git
cd monbotv5

# Installer les dépendances
pip install -r requirements.txt

# Ajouter les nouveaux fichiers
# - zedicus_v3.py (Dashboard principal)
# - integration_module.py (Orchestration)
```

### Lancer l'Application

```bash
# Mode Streamlit
streamlit run zedicus_v3.py

# Mode CLI (intégration)
python integration_module.py
```

---

## <a id="integration"></a>🔗 Intégration du Repository

### Chargement Automatique des Modules

```python
from integration_module import (
    RepositoryOrchestrator,
    ModuleRegistry,
    DataPipeline
)

# Initialiser
orchestrator = RepositoryOrchestrator()
modules = orchestrator.initialize()

# Tous les modules du repo sont chargés et enregistrés
# Accès via: orchestrator.registry.get_module('nom_module')
```

### Communication Inter-Modules

```python
# Module A publie une donnée
comm = InterModuleCommunication(registry)
comm.publish_event('price_updated', {'price': 1.0950})

# Module B s'abonne
def on_price_update(data):
    print(f"Prix mis à jour: {data['price']}")

comm.subscribe_event('price_updated', on_price_update)
```

### Pipeline de Données

```python
pipeline = DataPipeline(registry)

# Ajouter les étapes
pipeline.add_step(
    name="Fetch Price",
    function=lambda x: fetch_latest_price(),
    input_key="",
    output_key="current_price"
)

pipeline.add_step(
    name="Analyze Technical",
    function=lambda x: analyze_candlestick(x),
    input_key="current_price",
    output_key="technical_analysis"
)

# Exécuter
results = pipeline.execute()
```

---

## <a id="utilisation"></a>🚀 Utilisation

### Dashboard Principal

```
1. Prix et indicateurs clés (RSI, MACD, Bandes Bollinger)
2. Graphique candlestick avec supports/résistances
3. Recommandations intelligentes en temps réel
```

### Page Trading Signals

```
Points d'entrée:
- Support Principal (S1)
- Pivot
- Zone Survendue (RSI)

Points de sortie:
- Take Profit 1 (R1)
- Take Profit 2 (R2)
- Stop Loss (S2 + ATR)
```

### Page Technical Analysis

```
Patterns détectés:
- 🕯️ Doji
- 🔨 Marteau Haussier
- ⭐ Étoile du Soir
- 📦 Engulfing

Support & Résistance:
- Niveaux clés calculés via Pivot classique
- ATR pour ajustement volatilité
```

### Page News

```
Dernières news BCE avec:
- Titre
- Impact score (-100 à +100)
- Catégorie
- Sentiment
```

---

## 📊 Cas d'Usage Complets

### Scénario 1: Breakout Haussier

```
Conditions:
✓ Pattern: Engulfing Haussier
✓ RSI: 45 (zone neutre, pas survendu)
✓ MACD: Croisement positif
✓ News: Impact positive (+30)

Signal: ACHETER
Entrée: R1 du pivot
TP: R2
SL: Support principal
RRR: 1:2.5
Confiance: 88%
```

### Scénario 2: Retournement Baissier

```
Conditions:
✓ Pattern: Étoile du Soir
✓ RSI: 72 (suracheté)
✓ MACD: Croisement négatif
✓ News: Impact négative (-45)

Signal: VENDRE
Entrée: Résistance 1
TP: Support 1
SL: Résistance 2
RRR: 1:1.8
Confiance: 91%
```

---

## 🔍 Dépannage

### Les données ne se chargent pas
```
→ Vérifier la connexion internet
→ Vérifier l'API yfinance
→ Vérifier le ticker (ex: EURUSD=X)
```

### Le cache ne fonctionne pas
```
→ Vérifier les permissions du dossier .cache_zedicus
→ Vider le cache: cache.clear()
→ Redémarrer l'app
```

### Les modules ne se chargent pas
```
→ Vérifier integration_module.py dans le repo
→ Vérifier les imports
→ Consulter les logs: orchestrator.execution_log
```

---

## 📈 Performance

**Temps de chargement:**
- Chargement modules: ~2s
- Fetch données: ~3s
- Analyse complète: ~1.5s
- **Total: ~6.5s**

**Utilisation mémoire:**
- Cache mémoire: ~50MB
- Données OHLC (90j): ~2MB
- Interface Streamlit: ~30MB
- **Total: ~82MB**

---

## 🔐 Sécurité

- ✓ Pas de clés API stockées en dur
- ✓ Cache local chiffré
- ✓ Gestion d'erreur robuste
- ✓ Validation des entrées
- ✓ Logs détaillés

---

## 📝 Roadmap v3.1+

- [ ] Base de données Supabase
- [ ] Backtesting automatique
- [ ] Notifications Telegram
- [ ] Exécution trades via API broker
- [ ] Machine Learning pour patterns
- [ ] Multi-timeframe analysis
- [ ] Portfolio management

---

**Version:** 3.0  
**Date:** 2026-05-09  
**Statut:** ✅ Production Ready  

Pour toute question: Consultez la documentation ou ouvrez une issue GitHub!
