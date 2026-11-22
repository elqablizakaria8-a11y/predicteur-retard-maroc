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
Les services de routage et meteo sont disponibles. L'orchestration des
predictions et l'interface Streamlit restent a implementer.

## Routage (Nominatim + OSRM)

Depuis la racine du projet :

```powershell
python -m services.routing_api Casablanca Rabat
```

Ou dans le futur backend :

```python
from services.routing_api import RoutingClient

client = RoutingClient()
route = client.calculate_route('Casablanca', 'Rabat')
distance = route['distance_km']
reference_minutes = route['duree_theorique_min']
```

Les noms exacts des 16 villes (casse et accents ignores) utilisent le fichier
local, sans appel Nominatim. Ces points sont des centres de ville approximatifs,
pas des adresses de livraison. Pour un trajet dans une meme ville, fournir deux
adresses distinctes. Les autres recherches passent par Nominatim; le filtre
`ma,eh` couvre la zone des lieux du fichier local selon les codes du fournisseur.
Une recherche ambigue leve `AmbiguousPlaceError` avec une liste `candidates` :
la future interface devra demander un choix explicite, puis appeler
`client.route(departure, arrival)` avec les lieux choisis.

OSRM recoit **lon,lat** et fournit des metres et secondes, convertis en km et
minutes. Le resultat contient aussi les lieux, une geometrie GeoJSON et
`attribution`, a afficher dans l'interface. Le trajet est automobile. La duree
de reference ne contient pas d'information de trafic en direct.
La recherche de route est limitee aux routes situees a moins de 1 km des points.
Une erreur, une absence de route ou un lieu inconnu ne produit aucun resultat
de remplacement invente. Les exceptions heritent de `RoutingError`.

### Conditions des services publics

Lire la [politique Nominatim](https://operations.osmfoundation.org/policies/nominatim/).
Appels uniquement sur soumission explicite, **aucune autocompletion**, pas de
collecte massive ni de donnees personnelles/confidentielles. Le client emet un
User-Agent identifiant le projet, conserve les recherches 30 jours et limite
les requetes a une par seconde par fournisseur. Il conserve les routes une heure.
Les resultats et les horodatages sont partages entre processus dans
`cache/routing.sqlite3`, ignore par Git. Tous les clients doivent utiliser le
meme cache sur une seule machine; un deploiement distribue exige un limiteur
central avant utilisation du service public. Aucun renouvellement automatique
ni retry n'est effectue. Un cache expire est renouvele uniquement a la demande.

Le [serveur de demonstration OSRM](https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server)
convient a une utilisation raisonnable et non commerciale, sans garantie de
disponibilite. La [documentation HTTP](https://github.com/Project-OSRM/osrm-backend/blob/master/docs/http.md)
decrit les unites, erreurs et coordonnees.

Configuration facultative par variables d'environnement :

- `NOMINATIM_URL` : URL de base du geocodeur compatible Nominatim.
- `OSRM_URL` : URL de base du routeur compatible OSRM.
- `ROUTING_USER_AGENT` : identifiant de l'application (ajouter un contact reel).
- `ROUTING_CACHE_PATH` : chemin du cache partage.

Les tests de routage simulent les reponses HTTP; ils ne consomment pas les API.
Pour verifier les services publics, executer manuellement la commande ci-dessus.

## Meteo a l'heure de depart (Open-Meteo)

Test manuel pour Casablanca a la prochaine heure entiere :

```powershell
python -m services.weather_api 33.5731 -7.5898
```

Avec une date et heure futures choisies dans la fenetre de prevision :

```python
from datetime import datetime, timedelta, timezone
from services.weather_api import WeatherClient

departure = datetime.now(timezone.utc) + timedelta(hours=2)
weather = WeatherClient().get_forecast(33.5731, -7.5898, departure)
print(weather['meteo'], weather['temperature_c'])
```

La methode accepte un `datetime` ou une chaine ISO avec date **et** heure.
Sans decalage UTC, la saisie est interpretee en `Africa/Casablanca`.
Avec un decalage (ex. `+01:00` ou `Z`), l'instant est converti au fuseau Maroc.
Les changements d'heure sont geres par IANA via `zoneinfo` et `tzdata`, sans
supposer que le Maroc reste toute l'annee a UTC+1. Les heures locales doubles
ou inexistantes sont refusees sans indication explicite du decalage.

Les previsions horaires sont demandees en timestamps UTC pour les 7 jours du
fournisseur a partir de minuit UTC du jour courant. Les departs passes ou hors
de cette fenetre sont refuses. A 14h45, la ligne horaire de 14h00 est utilisee :
aucune interpolation ni substitution par la meteo actuelle n'est effectuee.
La disponibilite de la ligne et de ses valeurs est verifiee apres reception.
Le resultat contient `meteo`, `temperature_c`, `weather_code`, `departure_time`,
`forecast_time`, `timezone`, `source` et `attribution`.

### Correspondance WMO vers les categories du modele

| Codes WMO | Categorie utilisee |
| --- | --- |
| 0, 1 | Soleil |
| 2, 3 | Nuageux |
| 51, 53, 55, 61, 63, 80, 81 | Pluie |
| 65, 82 | Forte pluie |

Cette reduction est une convention de l'application. `Soleil` signifie aussi
ciel degage la nuit; ce n'est pas une mesure d'ensoleillement.
Le brouillard, les precipitations verglaçantes, la neige, les orages et les
codes inconnus levent `UnsupportedWeatherError` car le modele n'a pas ete
entraine sur ces conditions. Ils ne sont pas remplaces par une categorie
arbitraire. Toutes les erreurs meteo heritent de `WeatherError`, notamment
`ForecastUnavailableError`, `InvalidWeatherInputError`,
`WeatherServiceUnavailableError` et `InvalidWeatherResponseError`.

### Cache et conditions d'utilisation

Cache partage SQLite de 15 minutes dans `cache/weather.sqlite3` (ignore par
Git). Les heures de depart d'un meme lieu reutilisent la meme prevision.
La cle inclut le jour UTC pour eviter de reutiliser une ancienne fenetre apres
minuit. Une erreur ne sert jamais de prevision perimee. Les requetes locales
sont espacees d'au moins une seconde, sans retry automatique.

Le service gratuit sans cle convient au prototype educatif non commercial;
il impose des quotas. Une utilisation commerciale, par exemple un service de
livraison exploite commercialement, necessite de revoir l'offre fournisseur.
Afficher l'attribution Open-Meteo avec les resultats.
Voir la [documentation et les codes WMO](https://open-meteo.com/en/docs) et les
[conditions d'utilisation](https://open-meteo.com/en/terms).

Configuration facultative : `OPEN_METEO_URL` (URL complete compatible avec
`/v1/forecast`) et `WEATHER_CACHE_PATH` (cache partage sur une seule machine).
Les tests meteo simulent les reponses HTTP et ne consomment pas les API.
La temperature est informative : elle n'est pas une entree du modele actuel.
La prevision concerne uniquement le point de depart, pas tout le trajet.
