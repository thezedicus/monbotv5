#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZEDICUS Repository Manager
Gestion automatisée du repository avec rafraîchissement, mises à jour et nettoyage
"""

import os
import sys
import shutil
import hashlib
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import time
from collections import defaultdict

# ============================================================================
# CONFIGURATION LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('repo_manager.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# CLASSE PRINCIPALE
# ============================================================================

class RepositoryManager:
    """Gestionnaire complet du repository"""
    
    def __init__(self, repo_path: str = '.'):
        """
        Initialise le gestionnaire du repository
        
        Args:
            repo_path: Chemin du repository (par défaut: répertoire courant)
        """
        self.repo_path = Path(repo_path).resolve()
        self.cache_dir = self.repo_path / '.cache'
        self.backup_dir = self.repo_path / '.backups'
        self.ignore_dirs = {
            '.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
            '.cache', '.backups', 'node_modules', '.streamlit'
        }
        self.ignore_files = {
            '.DS_Store', 'Thumbs.db', '*.pyc', '*.pyo', '*.egg-info'
        }
        
        logger.info(f"Repository Manager initialisé: {self.repo_path}")
    
    # ======================================================================
    # OPÉRATIONS DE RAFRAÎCHISSEMENT
    # ======================================================================
    
    def refresh_cache(self) -> bool:
        """
        Vide le cache du repository
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("🔄 Rafraîchissement du cache en cours...")
            
            # Supprimer __pycache__
            for pycache in self.repo_path.rglob('__pycache__'):
                shutil.rmtree(pycache, ignore_errors=True)
                logger.info(f"  ✓ Supprimé: {pycache}")
            
            # Supprimer .pytest_cache
            for pytest_cache in self.repo_path.rglob('.pytest_cache'):
                shutil.rmtree(pytest_cache, ignore_errors=True)
                logger.info(f"  ✓ Supprimé: {pytest_cache}")
            
            # Vider .cache si existe
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                logger.info(f"  ✓ Cache vidé: {self.cache_dir}")
            
            logger.info("✓ Rafraîchissement du cache réussi!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du rafraîchissement du cache: {e}")
            return False
    
    def full_refresh(self) -> bool:
        """
        Rafraîchissement complet: cache + dépendances
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("⚡ RAFRAÎCHISSEMENT COMPLET")
            
            # Vider le cache
            if not self.refresh_cache():
                return False
            
            # Réinstaller les dépendances
            if not self.reinstall_dependencies():
                return False
            
            logger.info("✓ Rafraîchissement complet terminé!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du rafraîchissement complet: {e}")
            return False
    
    def reinstall_dependencies(self) -> bool:
        """
        Réinstalle les dépendances Python
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("📦 Réinstallation des dépendances...")
            
            requirements_files = [
                self.repo_path / 'requirements.txt',
                self.repo_path / 'requirements_v2.txt'
            ]
            
            for req_file in requirements_files:
                if req_file.exists():
                    logger.info(f"  → Installation depuis: {req_file.name}")
                    result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'install', '-r', str(req_file)],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"  ✓ {req_file.name} installé avec succès")
                    else:
                        logger.warning(f"  ⚠ Erreur lors de l'installation: {result.stderr}")
            
            logger.info("✓ Dépendances réinstal­lées!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la réinstallation: {e}")
            return False
    
    def web_refresh(self) -> bool:
        """
        Actualisation des ressources web (assets, static)
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("🌐 Actualisation des ressources web...")
            
            # Supprimer les fichiers temporaires
            for pattern in ['*.cache', '*.tmp', '.DS_Store']:
                for file in self.repo_path.rglob(pattern):
                    file.unlink(missing_ok=True)
                    logger.info(f"  ✓ Supprimé: {file}")
            
            logger.info("✓ Ressources web actualisées!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de l'actualisation web: {e}")
            return False
    
    # ======================================================================
    # OPÉRATIONS DE MISE À JOUR
    # ======================================================================
    
    def update_dependencies(self) -> bool:
        """
        Met à jour tous les packages Python
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("📦 Mise à jour des dépendances...")
            
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("  ✓ pip mis à jour")
            
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip-tools'],
                capture_output=True,
                text=True
            )
            
            logger.info("✓ Dépendances mises à jour!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la mise à jour: {e}")
            return False
    
    def regenerate_requirements(self) -> bool:
        """
        Régénère les fichiers requirements.txt
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("📋 Régénération des requirements.txt...")
            
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'freeze'],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                # Écrire requirements.txt
                req_file = self.repo_path / 'requirements.txt'
                req_file.write_text(result.stdout)
                logger.info(f"  ✓ {req_file.name} régénéré ({len(result.stdout.splitlines())} packages)")
                
                # Créer une copie
                req_v2_file = self.repo_path / 'requirements_v2.txt'
                req_v2_file.write_text(result.stdout)
                logger.info(f"  ✓ {req_v2_file.name} créé")
            
            logger.info("✓ Requirements régénérés!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la régénération: {e}")
            return False
    
    def sync_branch(self) -> bool:
        """
        Synchronise la branche locale avec la branche distante
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("🔀 Synchronisation de la branche...")
            
            # Fetch depuis origin
            result = subprocess.run(
                ['git', 'fetch', 'origin'],
                cwd=self.repo_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("  ✓ Fetch depuis origin")
                
                # Pull depuis origin
                result = subprocess.run(
                    ['git', 'pull', 'origin', 'main'],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    logger.info("  ✓ Pull depuis main")
            
            logger.info("✓ Branche synchronisée!")
            return True
            
        except Exception as e:
            logger.warning(f"⚠ Git non disponible ou erreur: {e}")
            return False
    
    # ======================================================================
    # OPÉRATIONS DE DÉTECTION DE DOUBLONS
    # ======================================================================
    
    def find_file_hash(self, filepath: Path) -> str:
        """
        Calcule le hash SHA256 d'un fichier
        
        Args:
            filepath: Chemin du fichier
            
        Returns:
            str: Hash SHA256 du fichier
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except:
            return ""
    
    def find_duplicates(self) -> Dict[str, List[Path]]:
        """
        Trouve tous les fichiers en double
        
        Returns:
            Dict: {hash: [paths]} des fichiers dupliqués
        """
        logger.info("🔍 Recherche de doublons...")
        
        file_hashes = defaultdict(list)
        duplicates = {}
        
        try:
            for file_path in self.repo_path.rglob('*'):
                # Ignorer les répertoires et fichiers ignorés
                if file_path.is_dir():
                    continue
                
                if any(ignored in file_path.parts for ignored in self.ignore_dirs):
                    continue
                
                # Ignorer les petits fichiers (< 1KB)
                if file_path.stat().st_size < 1024:
                    continue
                
                # Calculer le hash
                file_hash = self.find_file_hash(file_path)
                if file_hash:
                    file_hashes[file_hash].append(file_path)
            
            # Extraire les doublons
            for file_hash, paths in file_hashes.items():
                if len(paths) > 1:
                    duplicates[file_hash] = paths
                    logger.info(f"  ⚠ Doublon trouvé ({len(paths)} fichiers):")
                    for path in paths:
                        rel_path = path.relative_to(self.repo_path)
                        logger.info(f"    - {rel_path}")
            
            if duplicates:
                logger.info(f"✓ {len(duplicates)} doublons détectés")
            else:
                logger.info("✓ Aucun doublon détecté")
            
            return duplicates
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la recherche de doublons: {e}")
            return {}
    
    def remove_duplicates(self, keep_first: bool = True) -> int:
        """
        Supprime les fichiers en double
        
        Args:
            keep_first: Si True, garde le premier et supprime les autres
            
        Returns:
            int: Nombre de fichiers supprimés
        """
        logger.info("🧹 Suppression des doublons...")
        
        duplicates = self.find_duplicates()
        removed_count = 0
        
        try:
            for file_hash, paths in duplicates.items():
                if keep_first:
                    # Garder le premier, supprimer les autres
                    for file_path in paths[1:]:
                        # Créer une sauvegarde
                        self.backup_dir.mkdir(exist_ok=True)
                        backup_path = self.backup_dir / file_path.name
                        shutil.copy2(file_path, backup_path)
                        
                        # Supprimer le fichier
                        file_path.unlink()
                        removed_count += 1
                        logger.info(f"  ✓ Supprimé: {file_path.relative_to(self.repo_path)}")
            
            logger.info(f"✓ {removed_count} fichiers supprimés!")
            return removed_count
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la suppression: {e}")
            return removed_count
    
    # ======================================================================
    # OPÉRATIONS DE NETTOYAGE
    # ======================================================================
    
    def clean_cache(self) -> bool:
        """
        Nettoie tous les fichiers de cache
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("🗑️ Nettoyage du cache...")
            
            patterns = ['*.pyc', '*.pyo', '*.pyd', '__pycache__', '.pytest_cache']
            removed_count = 0
            
            for pattern in patterns:
                for file_path in self.repo_path.rglob(pattern):
                    if file_path.is_file():
                        file_path.unlink()
                        removed_count += 1
                    elif file_path.is_dir():
                        shutil.rmtree(file_path, ignore_errors=True)
                        removed_count += 1
            
            logger.info(f"✓ {removed_count} fichiers/répertoires supprimés!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du nettoyage du cache: {e}")
            return False
    
    def clean_temp_files(self) -> bool:
        """
        Nettoie les fichiers temporaires
        
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info("📂 Suppression des fichiers temporaires...")
            
            patterns = ['*.tmp', '*.log', '*.backup', '*.swp', '*.swo', '.DS_Store']
            removed_count = 0
            
            for pattern in patterns:
                for file_path in self.repo_path.rglob(pattern):
                    try:
                        file_path.unlink()
                        removed_count += 1
                        logger.info(f"  ✓ Supprimé: {file_path.relative_to(self.repo_path)}")
                    except:
                        pass
            
            logger.info(f"✓ {removed_count} fichiers temporaires supprimés!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du nettoyage: {e}")
            return False
    
    def advanced_clean(self, patterns: List[str]) -> bool:
        """
        Nettoyage avancé avec patterns personnalisés
        
        Args:
            patterns: Liste de patterns (ex: ['*.tmp', '*.bak'])
            
        Returns:
            bool: True si succès, False sinon
        """
        try:
            logger.info(f"🎯 Nettoyage avancé avec patterns: {patterns}")
            
            removed_count = 0
            
            for pattern in patterns:
                pattern = pattern.strip()
                for file_path in self.repo_path.rglob(pattern):
                    try:
                        if file_path.is_file():
                            file_path.unlink()
                        else:
                            shutil.rmtree(file_path)
                        removed_count += 1
                        logger.info(f"  ✓ Supprimé: {file_path.relative_to(self.repo_path)}")
                    except Exception as e:
                        logger.warning(f"  ⚠ Impossible de supprimer {file_path}: {e}")
            
            logger.info(f"✓ {removed_count} éléments supprimés!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du nettoyage avancé: {e}")
            return False
    
    # ======================================================================
    # GESTION DES FICHIERS
    # ======================================================================
    
    def get_files_info(self) -> List[Dict]:
        """
        Récupère les informations de tous les fichiers
        
        Returns:
            List[Dict]: Liste des infos fichiers
        """
        files_info = []
        
        try:
            for file_path in self.repo_path.rglob('*'):
                if file_path.is_file():
                    # Ignorer certains fichiers
                    if any(ignored in file_path.parts for ignored in self.ignore_dirs):
                        continue
                    
                    rel_path = file_path.relative_to(self.repo_path)
                    size = file_path.stat().st_size
                    
                    files_info.append({
                        'path': str(rel_path),
                        'size': size,
                        'size_mb': round(size / (1024*1024), 2),
                        'modified': datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()
                    })
            
            return sorted(files_info, key=lambda x: x['size'], reverse=True)
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la récupération des infos: {e}")
            return []
    
    def delete_file(self, filename: str) -> bool:
        """
        Supprime un fichier du repository
        
        Args:
            filename: Nom ou chemin du fichier
            
        Returns:
            bool: True si succès, False sinon
        """
        try:
            file_path = self.repo_path / filename
            
            if not file_path.exists():
                logger.warning(f"⚠ Fichier non trouvé: {filename}")
                return False
            
            # Créer une sauvegarde
            self.backup_dir.mkdir(exist_ok=True)
            backup_path = self.backup_dir / file_path.name
            shutil.copy2(file_path, backup_path)
            
            # Supprimer le fichier
            file_path.unlink()
            logger.info(f"✓ Fichier supprimé: {filename}")
            logger.info(f"  Sauvegarde: {backup_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Erreur lors de la suppression: {e}")
            return False
    
    # ======================================================================
    # STATISTIQUES ET RAPPORT
    # ======================================================================
    
    def get_stats(self) -> Dict:
        """
        Récupère les statistiques du repository
        
        Returns:
            Dict: Statistiques
        """
        try:
            files = self.get_files_info()
            total_size = sum(f['size'] for f in files)
            
            stats = {
                'total_files': len(files),
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024*1024), 2),
                'largest_files': files[:5],
                'duplicates_count': len(self.find_duplicates()),
                'repo_path': str(self.repo_path),
                'timestamp': datetime.now().isoformat()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"✗ Erreur lors du calcul des stats: {e}")
            return {}
    
    def generate_report(self) -> str:
        """
        Génère un rapport complet
        
        Returns:
            str: Rapport en JSON
        """
        logger.info("📊 Génération du rapport...")
        
        stats = self.get_stats()
        duplicates = self.find_duplicates()
        
        report = {
            'statistics': stats,
            'duplicates': {
                hash_key: [str(p.relative_to(self.repo_path)) for p in paths]
                for hash_key, paths in duplicates.items()
            },
            'generated_at': datetime.now().isoformat()
        }
        
        # Sauvegarder le rapport
        report_file = self.repo_path / 'repo_report.json'
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✓ Rapport sauvegardé: {report_file}")
        
        return json.dumps(report, indent=2, ensure_ascii=False)


# ============================================================================
# INTERFACE CLI
# ============================================================================

def main():
    """Fonction principale"""
    
    print("\n" + "="*60)
    print("⚡ ZEDICUS Repository Manager".center(60))
    print("="*60 + "\n")
    
    manager = RepositoryManager()
    
    commands = {
        '1': ('Rafraîchissement complet', manager.full_refresh),
        '2': ('Rafraîchir le cache', manager.refresh_cache),
        '3': ('Actualiser le web', manager.web_refresh),
        '4': ('Mettre à jour dépendances', manager.update_dependencies),
        '5': ('Régénérer requirements', manager.regenerate_requirements),
        '6': ('Synchroniser branche', manager.sync_branch),
        '7': ('Trouver doublons', manager.find_duplicates),
        '8': ('Supprimer doublons', manager.remove_duplicates),
        '9': ('Nettoyer cache', manager.clean_cache),
        '10': ('Nettoyer fichiers temp', manager.clean_temp_files),
        '11': ('Afficher statistiques', manager.get_stats),
        '12': ('Générer rapport', manager.generate_report),
        '0': ('Quitter', None)
    }
    
    while True:
        print("\nOptions disponibles:")
        for key, (desc, _) in commands.items():
            print(f"  [{key}] {desc}")
        
        choice = input("\nSélectionnez une option (0-12): ").strip()
        
        if choice == '0':
            print("✓ Au revoir!")
            break
        
        if choice not in commands:
            print("✗ Option invalide!")
            continue
        
        desc, func = commands[choice]
        
        if func:
            print(f"\n▶ {desc}...")
            try:
                result = func()
                
                if isinstance(result, dict):
                    print("\n📊 Résultats:")
                    print(json.dumps(result, indent=2, ensure_ascii=False))
                elif isinstance(result, str):
                    print(result)
                elif result is True or result is False:
                    status = "✓ Succès" if result else "✗ Échec"
                    print(status)
                
            except Exception as e:
                print(f"✗ Erreur: {e}")
        
        time.sleep(1)


if __name__ == '__main__':
    main()
