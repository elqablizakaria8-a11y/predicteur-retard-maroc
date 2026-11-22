# Predicteur de retard de trajet au Maroc

Prototype de prediction de **duree de conduite** sur donnees synthetiques.
La preparation d'une commande, l'attente du livreur et la remise au client ne
sont pas modelisees.

## Interface React et simulation

L'interface **Wasel** utilise React, Tailwind CSS et Leaflet; FastAPI appelle
les services Python existants. Il s'agit d'une application locale, pas d'un
service de suivi GPS reel. Le modele sauvegarde est reutilise sans entrainement.

Prerequis : Python 3.13 et Node.js compatible Vite (22.12 ou plus recent).
Depuis la racine du depot :

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Ouvrir ensuite **http://127.0.0.1:8000**. Garder le terminal ouvert pendant
l'utilisation. Les donnees et les fichiers `.pkl` doivent etre presents.
Ne pas regenerer le dataset ni reentrainer pour simplement lancer l'interface.
Apres cette installation, `./start.ps1` lance le serveur avec le meme environnement.

Pour developper avec rechargement a chaud, conserver le backend sur le port
8000 et lancer `npm run dev` depuis `frontend` dans un second terminal.
Ouvrir http://127.0.0.1:5173. Vite transmet `/api` au backend sur la meme machine.
Le serveur Python sert aussi le build React : aucun CORS generique n'est ajoute.

### Utilisation

1. Choisir deux lieux, la date/heure Maroc et le type urbain/interurbain.
2. Cliquer sur **Estimer mon trajet**. Les suggestions de villes sont locales;
   le geocodage externe est declenche uniquement par cette soumission.
3. Si plusieurs adresses correspondent, choisir explicitement un candidat.
4. Lire la reference OSRM, la duree predite, l'ecart et l'heure d'arrivee.
5. Demarrer la simulation, changer sa vitesse, mettre en pause ou reinitialiser.

Le marqueur est interpole selon les distances entre les sommets GeoJSON, pas
simplement selon leur nombre. Le navigateur utilise le temps ecoule et le
facteur choisi (x1, x30, x120 ou x600). Le parcours est borne a son arrivee.
La progression et les temps/distances restants sont **simules**, sans nouveaux
appels d'API a chaque image. Cette animation ne valide pas la precision du modele.
Modifier le formulaire ne remplace pas l'ancien resultat avant un nouveau calcul.

Les libelles SIMULATION, l'absence de GPS reel et la nature experimentale du
modele sont visibles. Une fenetre explique aussi les limites et seuils.
Les cartes utilisent les tuiles OpenStreetMap avec attribution et cache normal
du navigateur, sans telechargement hors-ligne ni prechargement massif :
[politique des tuiles](https://operations.osmfoundation.org/policies/tiles/).
Un acces Internet reste necessaire pour la carte et les fournisseurs externes.

### API et tests

- `GET /api/health` : etat du serveur et mode simulation.
- `GET /api/config` : villes locales et fenetre de dates au fuseau Maroc.
- `POST /api/geocode` : recherche explicite d'un lieu; HTTP 409 avec candidats
  en cas d'ambiguite.
- `POST /api/predict` : prediction avec `departure`, `arrival`, `departure_time`
  et un booleen strict `urban`. Les lieux peuvent etre des coordonnees choisies.
- `/docs` : documentation interactive FastAPI.

Les erreurs JSON ont la forme `{"error":{"code":"...","message":"..."}}`.
Une condition non supportee ou un fournisseur indisponible ne produit pas de
prediction de remplacement. Le modele est charge une fois par processus.
`MODEL_DIR` permet de choisir un repertoire d'artefacts different pour les tests.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
cd frontend
npm test
npm run build
```

Les tests HTTP utilisent des services simules, sans appels externes.
Ce prototype est prevu pour une execution locale sur une seule machine avec
les caches partages. Le suivi reel, les comptes et l'hebergement public sont
des etapes ulterieures.

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
en semaine. Le type urbain/interurbain doit etre choisi explicitement par
l'appelant; il n'est pas deduit de la distance ni des noms des lieux.

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
La meteo est encodee en `intensite_meteo` : Soleil=0, Nuageux=1, Pluie=2,
Forte pluie=3. Ce classement suit les perturbations du generateur. Les valeurs
inconnues sont rejetees au lieu d'etre silencieusement ignorees.
Les arbres sont contraints pour qu'une aggravation de la meteo, a autres
entrees identiques, ne puisse pas reduire la duree predite. Cette regle garantit
la coherence de l'estimation; elle ne prouve pas sa precision dans le monde reel.

## Evaluation

Partitions fixes : 60 % entrainement, 20 % validation, 20 % test.
La regression lineaire sert de baseline. Le choix entre Random Forest et
HistGradientBoosting, tous deux contraints sur l'intensite meteo, utilise
uniquement la MAE de validation. Les modeles sauvegardes restent ceux ajustes
sur l'entrainement. L'ordre des quatre conditions est aussi verifie sur les
2000 exemples de validation avant toute sauvegarde.
Le rapport `models/evaluation_modele.json` contient les versions, l'empreinte du
dataset, la MAE, le R2, les erreurs urbaines/interurbaines et les matrices de
confusion des alertes sur le test final.

Une Random Forest sans reference et une prediction egale a la reference servent
de comparaisons. L'ablation utilise exactement les memes trajets et partitions.
Les anciens scores sur l'ancien dataset ne constituent pas une comparaison
controlee avec les nouveaux scores.

Ces mesures evaluent des regles de simulation, pas la precision du trafic reel.
Les services de routage, meteo et prediction sont disponibles.
L'interface React et la simulation sont disponibles; le suivi GPS reel reste
a implementer.

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

## Prediction complete d'un trajet

Depuis la racine du projet, a la prochaine heure entiere :

```powershell
python -m services.predictor_logic Casablanca Rabat --intercity
```

On peut ajouter `--departure-time "AAAA-MM-JJTHH:MM"` avec une date future.
`--urban` ou `--intercity` est obligatoire : le modele exige cette information.
Pour une livraison en ville, fournir deux adresses distinctes et `--urban`.

```python
from datetime import datetime, timedelta, timezone
from services.predictor_logic import PredictorService

predictor = PredictorService()  # reutiliser cette instance entre requetes
departure_time = datetime.now(timezone.utc) + timedelta(hours=2)
result = predictor.predict_trip('Casablanca', 'Rabat', departure_time, urban=False)
print(result['duree_estimee_min'], result['retard_min'], result['alert'])
```

La methode accepte aussi des dictionnaires `lat`, `lon`, `label` pour les lieux
deja selectionnes apres une recherche ambigue. Dans ce cas, elle ne relance pas
le geocodage. Une date invalide est refusee avant les appels de routage.

`PredictorService` charge une fois les deux artefacts `.pkl`, verifie leurs
colonnes et refuse une incompatibilite de version sklearn. Il utilise le meme
encodage que l'entrainement et derive le jour, l'heure locale, le weekend et
l'heure de pointe a partir de la date validee en `Africa/Casablanca`.

Les champs principaux du resultat sont :

- `distance_km`, `duree_theorique_min` : reference OSRM.
- `duree_estimee_min` : duree de conduite predite par le modele.
- `retard_min` : prediction moins reference, valeur signee conservee.
- `departure_time`, `estimated_arrival_time` : instants ISO avec decalage UTC.
- `alert` : code, libelle et couleur (`green`, `orange`, `red`).
- `route`, `weather` : details et attributions des fournisseurs.
- `urban`, `model_inputs` : choix explicite et entrees utilisees.
- `estimate_kind` : `experimental_synthetic_model`.

Les seuils d'alerte sont appliques avant tout arrondi; l'affichage peut ensuite
formater les valeurs. Un ecart negatif reste visible et classe fluide.
L'heure d'arrivee est calculee par addition de la duree en UTC, puis reconvertie
au fuseau Maroc pour respecter la duree ecoulee lors des changements d'heure.

Les erreurs de routage et meteo sont propagees avec leurs details : aucune
prediction n'est produite si une etape necessaire echoue. Les erreurs du modele
heritent de `PredictionError` (`ModelLoadError`, `InvalidPredictionInputError`,
`InvalidPredictionError`). Les mesures restent experimentales, sans trafic en
direct ni temps de preparation/attente d'une commande.
