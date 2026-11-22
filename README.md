# Predicteur de retard de trajet au Maroc

Prototype de prediction de **duree de conduite** sur donnees synthetiques.
La preparation d'une commande, l'attente du livreur et la remise au client ne
sont pas modelisees.

## Installation et execution

Depuis la racine du projet, avec Python 3.13 :

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe src/data_generator.py
.\.venv\Scripts\python.exe src/train_model.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Les scripts localisent les donnees relativement a leur propre fichier.
Le generateur utilise la graine 42 pour Python et NumPy.
Relancer les scripts remplace le dataset et les artefacts actifs.

## Entrees et sortie

Les variables sont : `distance_km`, `duree_theorique_min`, `heure_depart` (0-23),
`jour_semaine` (lundi=0), `est_weekend`, `est_heure_pointe`,
`est_intra_urbain` et `meteo`.
Les creneaux de pointe sont actuellement 8, 9, 12, 13, 18, 19 et 20 heures
en semaine. La regle de determination urbain/interurbain reste a definir pour
les futures entrees API.

`duree_theorique_min` est calculee a partir d'une vitesse tiree aleatoirement,
**avant** les ralentissements et le bruit. Elle ne provient pas de la cible.
Lors de l'integration, OSRM fournira une estimation de reference : cette
nouvelle distribution devra etre validee contre des trajets observes.

Le modele retourne `duree_reelle_min`. Le retard estime est cette prediction
moins la reference. Les seuils sont `<5`, `5 a 15 inclus`, `>15` minutes.
Un retard negatif reste classe fluide.

Pour encoder une seule requete ou un lot, utiliser la meme fonction :

```python
import joblib
import pandas as pd
from src.model_features import prepare_features

model = joblib.load('models/modele_retard_maroc.pkl')
columns = joblib.load('models/colonnes_modele.pkl')
# request_data doit contenir toutes les variables ci-dessus.
features = prepare_features(pd.DataFrame([request_data]))
duration = float(model.predict(features.reindex(columns=columns))[0])
```

Le nouvel artefact exige `duree_theorique_min`; l'ancien contrat a change.
L'encodage meteo est explicite, avec `Forte pluie` comme reference. Les valeurs
inconnues sont rejetees au lieu d'etre silencieusement ignorees.

## Evaluation

Partitions fixes : 60 % entrainement, 20 % validation, 20 % test.
Le choix entre regression lineaire et Random Forest utilise uniquement la MAE
de validation. Les modeles sauvegardes restent ceux ajustes sur l'entrainement.
Le rapport `models/evaluation_modele.json` contient les versions, l'empreinte du
dataset, la MAE, le R2, les erreurs urbaines/interurbaines et les matrices de
confusion des alertes sur le test final.

Une Random Forest sans reference et une prediction egale a la reference servent
de comparaisons. L'ablation utilise exactement les memes trajets et partitions.
Les anciens scores sur l'ancien dataset ne constituent pas une comparaison
controlee avec les nouveaux scores.

Ces mesures evaluent des regles de simulation, pas la precision du trafic reel.
Les API de routage/meteo et l'interface Streamlit restent a implementer.
