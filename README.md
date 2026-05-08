# ⚡ THE ZEDICUS — Dashboard BCE Zone Euro

## Lancement local
```bash
pip install -r requirements.txt
python3 -m streamlit run zedicus.py
```

## Déploiement Streamlit Cloud
1. Fork ce repo sur GitHub
2. https://share.streamlit.io → sélectionner ce repo → `zedicus.py`

## Fichiers optionnels (fonctionnalités avancées)
- `bce_engine.py` — Moteur BCE complet
- `orchestrator.py` — Scores composite

Sans eux, le dashboard fonctionne en mode autonome.
