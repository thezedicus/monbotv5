#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MODULE INTÉGRATION REPO — ZEDICUS v3
Interopérabilité totale entre tous les fichiers

Permet:
✓ Charger tous les modules du repo
✓ Partager les données entre modules
✓ Orchestration des analyses
✓ Synchronisation des caches
"""

import sys, os, json, pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
import importlib.util
import hashlib

class ModuleRegistry:
    """Registre central des modules"""
    
    def __init__(self, repo_path="."):
        self.repo_path = Path(repo_path)
        self.modules = {}
        self.module_metadata = {}
        self.dependencies = {}
        self.shared_data = {}
    
    def register_module(self, name: str, module_obj: Any, dependencies: List[str] = None):
        """Enregistre un module"""
        self.modules[name] = module_obj
        self.module_metadata[name] = {
            'loaded_at': datetime.now().isoformat(),
            'version': getattr(module_obj, '__version__', '1.0'),
            'doc': getattr(module_obj, '__doc__', '')
        }
        if dependencies:
            self.dependencies[name] = dependencies
    
    def get_module(self, name: str) -> Optional[Any]:
        """Récupère un module enregistré"""
        return self.modules.get(name)
    
    def get_all_modules(self) -> Dict[str, Any]:
        """Retourne tous les modules"""
        return self.modules.copy()
    
    def share_data(self, key: str, data: Any):
        """Partage des données entre modules"""
        self.shared_data[key] = {
            'data': data,
            'timestamp': datetime.now().isoformat(),
            'hash': self._hash_data(data)
        }
    
    def get_shared_data(self, key: str) -> Optional[Any]:
        """Récupère des données partagées"""
        entry = self.shared_data.get(key)
        return entry['data'] if entry else None
    
    def _hash_data(self, data) -> str:
        """Hash les données"""
        try:
            s = json.dumps(data, sort_keys=True, default=str)
            return hashlib.md5(s.encode()).hexdigest()
        except:
            return hashlib.md5(str(data).encode()).hexdigest()

class DataPipeline:
    """Pipeline de données multi-source"""
    
    def __init__(self, registry: ModuleRegistry):
        self.registry = registry
        self.pipeline_steps = []
        self.processed_data = {}
    
    def add_step(self, name: str, function: Callable, input_key: str, output_key: str):
        """Ajoute une étape du pipeline"""
        self.pipeline_steps.append({
            'name': name,
            'function': function,
            'input_key': input_key,
            'output_key': output_key
        })
    
    def execute(self) -> Dict[str, Any]:
        """Exécute le pipeline complet"""
        results = {}
        
        for step in self.pipeline_steps:
            try:
                # Récupérer l'input
                input_data = self.registry.get_shared_data(step['input_key'])
                
                if input_data is None:
                    print(f"⚠️ Pipeline: Input '{step['input_key']}' not found for step '{step['name']}'")
                    continue
                
                # Exécuter la fonction
                output = step['function'](input_data)
                
                # Partager le résultat
                self.registry.share_data(step['output_key'], output)
                results[step['output_key']] = output
                
                print(f"✓ Pipeline step '{step['name']}' completed")
            
            except Exception as e:
                print(f"✗ Pipeline error in '{step['name']}': {e}")
        
        return results

class ModuleLoader:
    """Charge les modules Python du repo"""
    
    @staticmethod
    def load_module_file(file_path: Path) -> Optional[Any]:
        """Charge un fichier Python en module"""
        try:
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            print(f"✗ Erreur chargement {file_path}: {e}")
            return None
    
    @staticmethod
    def discover_modules(repo_path: Path) -> Dict[str, Path]:
        """Découvre tous les modules du repo"""
        modules = {}
        
        for py_file in repo_path.glob("*.py"):
            if not py_file.name.startswith("__"):
                modules[py_file.stem] = py_file
        
        return modules
    
    @staticmethod
    def load_all_modules(repo_path: Path) -> Dict[str, Any]:
        """Charge tous les modules du repo"""
        modules = ModuleLoader.discover_modules(repo_path)
        loaded = {}
        
        for name, path in modules.items():
            print(f"📦 Loading {name}...", end=" ")
            module = ModuleLoader.load_module_file(path)
            if module:
                loaded[name] = module
                print("✓")
            else:
                print("✗")
        
        return loaded

class RepositoryOrchestrator:
    """Orchestre l'ensemble du repository"""
    
    def __init__(self, repo_path="."):
        self.repo_path = Path(repo_path)
        self.registry = ModuleRegistry(repo_path)
        self.pipeline = DataPipeline(self.registry)
        self.execution_log = []
    
    def initialize(self):
        """Initialise l'orchestrateur"""
        print("🚀 Initialisation du Repository Orchestrator...")
        
        # Découvrir et charger les modules
        print("\n📦 Chargement des modules...")
        modules = ModuleLoader.load_all_modules(self.repo_path)
        
        for name, module in modules.items():
            self.registry.register_module(name, module)
        
        print(f"\n✓ {len(modules)} modules chargés")
        return modules
    
    def setup_pipelines(self):
        """Configure les pipelines de données"""
        print("\n🔗 Configuration des pipelines...")
        
        # Pipeline: Prix → Analyse Technique → Signaux
        # (À personnaliser selon vos modules)
        
        print("✓ Pipelines configurés")
    
    def execute_full_analysis(self) -> Dict[str, Any]:
        """Exécute l'analyse complète"""
        print("\n▶️ Exécution de l'analyse complète...")
        
        results = {
            'timestamp': datetime.now().isoformat(),
            'modules_used': list(self.registry.modules.keys()),
            'shared_data': self.registry.shared_data,
            'execution_log': self.execution_log
        }
        
        return results
    
    def log_execution(self, message: str, level: str = "INFO"):
        """Enregistre l'exécution"""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {level}: {message}"
        self.execution_log.append(log_entry)
        print(log_entry)

class InterModuleCommunication:
    """Système de communication entre modules"""
    
    def __init__(self, registry: ModuleRegistry):
        self.registry = registry
        self.message_queue = []
        self.event_handlers = {}
    
    def publish_event(self, event_type: str, data: Any):
        """Publie un événement"""
        event = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        self.message_queue.append(event)
        
        # Déclencher les handlers
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    handler(data)
                except Exception as e:
                    print(f"⚠️ Event handler error: {e}")
    
    def subscribe_event(self, event_type: str, handler: Callable):
        """S'abonne à un événement"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
    
    def get_message_history(self, event_type: str = None) -> List[Dict]:
        """Récupère l'historique des messages"""
        if event_type:
            return [m for m in self.message_queue if m['type'] == event_type]
        return self.message_queue

class IntegrationHealthCheck:
    """Vérification de santé de l'intégration"""
    
    @staticmethod
    def check_module_compatibility(registry: ModuleRegistry) -> Dict[str, bool]:
        """Vérifie la compatibilité des modules"""
        compatibility = {}
        
        modules = registry.modules
        
        # Vérifier les dépendances
        for name, deps in registry.dependencies.items():
            compatible = True
            for dep in (deps or []):
                if dep not in modules:
                    compatible = False
                    break
            compatibility[name] = compatible
        
        return compatibility
    
    @staticmethod
    def check_data_integrity(registry: ModuleRegistry) -> Dict[str, bool]:
        """Vérifie l'intégrité des données partagées"""
        integrity = {}
        
        for key, entry in registry.shared_data.items():
            # Vérifier que les données existent
            integrity[key] = entry['data'] is not None
        
        return integrity
    
    @staticmethod
    def generate_health_report(registry: ModuleRegistry) -> Dict[str, Any]:
        """Génère un rapport de santé complet"""
        return {
            'timestamp': datetime.now().isoformat(),
            'total_modules': len(registry.modules),
            'shared_data_keys': len(registry.shared_data),
            'module_compatibility': IntegrationHealthCheck.check_module_compatibility(registry),
            'data_integrity': IntegrationHealthCheck.check_data_integrity(registry)
        }

class ConfigurationManager:
    """Gère la configuration globale"""
    
    def __init__(self, config_file: str = "zedicus_config.json"):
        self.config_file = Path(config_file)
        self.config = self.load_config()
    
    def load_config(self) -> Dict[str, Any]:
        """Charge la configuration"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return self.get_default_config()
    
    def get_default_config(self) -> Dict[str, Any]:
        """Configuration par défaut"""
        return {
            'ticker': 'EURUSD=X',
            'lookback_days': 90,
            'cache_ttl': 3600,
            'update_interval': 300,
            'modules': {
                'technical_analysis': True,
                'news_analysis': True,
                'trading_signals': True,
                'cache_management': True
            }
        }
    
    def save_config(self):
        """Sauvegarde la configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def get(self, key: str, default=None):
        """Récupère une clé de config"""
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        
        return value if value is not None else default

# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Exemple d'utilisation
    print("=" * 80)
    print("ZEDICUS v3 — MODULE INTÉGRATION REPOSITORY")
    print("=" * 80)
    
    # Initialiser l'orchestrateur
    orchestrator = RepositoryOrchestrator()
    modules = orchestrator.initialize()
    
    # Configurer
    config = ConfigurationManager()
    print(f"\n⚙️ Configuration: {config.config}")
    
    # Health check
    health = IntegrationHealthCheck.generate_health_report(orchestrator.registry)
    print(f"\n🏥 Health Report: {json.dumps(health, indent=2, default=str)}")
    
    # Exécuter l'analyse
    results = orchestrator.execute_full_analysis()
    print(f"\n✓ Analyse complétée: {len(results)} résultats")
