"""Relie le routage, la prevision meteo et le modele de duree de conduite."""
import argparse
from datetime import timedelta, timezone
import json
import math
from pathlib import Path
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.exceptions import InconsistentVersionWarning

from services.routing_api import AmbiguousPlaceError, RoutingClient, RoutingError
from services.weather_api import WeatherClient, WeatherError
from src.model_features import FEATURE_COLUMNS, alert_categories, prepare_features

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALERTS = [
    {'code': 'fluide', 'label': 'Trafic fluide', 'color': 'green'},
    {'code': 'ralentissements', 'label': 'Ralentissements', 'color': 'orange'},
    {'code': 'retard', 'label': 'Alerte retard', 'color': 'red'},
]


class PredictionError(Exception):
    """Erreur de configuration, de contrat ou de prediction."""


class ModelLoadError(PredictionError):
    pass


class InvalidPredictionInputError(PredictionError):
    pass


class InvalidPredictionError(PredictionError):
    pass


class PredictorService:
    def __init__(self, *, model_dir=None, routing_client=None, weather_client=None):
        root = Path(model_dir) if model_dir is not None else PROJECT_ROOT / 'models'
        try:
            # On refuse explicitement un artefact sklearn d'une autre version.
            with warnings.catch_warnings():
                warnings.simplefilter('error', InconsistentVersionWarning)
                self.model = joblib.load(root / 'modele_retard_maroc.pkl')
                self.columns = joblib.load(root / 'colonnes_modele.pkl')
            if (not isinstance(self.columns, list)
                    or not all(isinstance(c, str) for c in self.columns)
                    or len(self.columns) != len(FEATURE_COLUMNS)
                    or set(self.columns) != set(FEATURE_COLUMNS)
                    or list(self.model.feature_names_in_) != self.columns
                    or self.model.n_features_in_ != len(self.columns)
                    or not callable(self.model.predict)):
                raise ValueError('Contrat du modele incompatible')
        except Exception as exc:
            raise ModelLoadError('Impossible de charger le modele et ses colonnes. Verifiez les fichiers et les versions, ou relancez src/train_model.py.') from exc
        # Une seule lecture des artefacts par instance, reutilisable par l'UI.
        self.routing = routing_client if routing_client is not None else RoutingClient()
        self.weather = weather_client if weather_client is not None else WeatherClient()

    def predict_trip(self, departure, arrival, departure_time, *, urban):
        """urban doit etre un bool explicite, jamais devine par la distance.

        departure/arrival: noms ou dictionnaires de lieux deja selectionnes.
        Les exceptions de routage/meteo restent intactes (candidats, code WMO).
        """
        if type(urban) is not bool:
            raise InvalidPredictionInputError('Indiquez explicitement si le trajet est urbain (True) ou interurbain (False).')
        for place in (departure, arrival):
            if not isinstance(place, (str, dict)) or (isinstance(place, str) and not place.strip()):
                raise InvalidPredictionInputError('Le depart et l\'arrivee doivent etre des lieux ou des coordonnees selectionnees.')
        # Refuse les dates invalides avant geocodage ou recherche de route.
        local_departure = self.weather.validate_departure(departure_time)
        origin = self.routing.geocode(departure) if isinstance(departure, str) else dict(departure)
        destination = self.routing.geocode(arrival) if isinstance(arrival, str) else dict(arrival)
        route = self.routing.route(origin, destination)
        weather = self.weather.get_forecast(origin['lat'], origin['lon'], local_departure)
        weekday = local_departure.weekday()
        weekend = int(weekday in (5, 6))
        try:
            row = dict(distance_km=route['distance_km'], duree_theorique_min=route['duree_theorique_min'],
                       heure_depart=local_departure.hour, jour_semaine=weekday, est_weekend=weekend,
                       est_heure_pointe=int(not weekend and local_departure.hour in (8, 9, 12, 13, 18, 19, 20)),
                       est_intra_urbain=int(urban), meteo=weather['meteo'])
            # Contrat identique a l'entrainement, y compris pour une seule ligne.
            features = prepare_features(pd.DataFrame([row])).reindex(columns=self.columns)
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidPredictionInputError('Les donnees de routage ou meteo ne correspondent pas aux entrees du modele.') from exc
        try:
            predictions = np.asarray(self.model.predict(features))
            if predictions.shape != (1,) or predictions.dtype.kind not in 'fiu':
                raise ValueError('Sortie du modele invalide')
            duration = float(predictions[0])
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError('Duree predite invalide')
            reference = float(row['duree_theorique_min'])
            delay = duration - reference
            # Addition en UTC: conserve la duree ecoulee lors d'un changement d'heure.
            estimated_arrival = (local_departure.astimezone(timezone.utc)
                                 + timedelta(minutes=duration)).astimezone(self.weather.zone)
        except (ValueError, TypeError, AttributeError, RuntimeError, OverflowError) as exc:
            raise InvalidPredictionError('Le modele ne peut pas produire une duree de trajet valide.') from exc
        # Les seuils utilisent la valeur brute; l'interface formatera l'affichage.
        alert = dict(ALERTS[int(alert_categories([delay])[0])])
        return dict(distance_km=float(row['distance_km']), duree_theorique_min=reference,
                    duree_estimee_min=duration, retard_min=delay,
                    departure_time=local_departure.isoformat(), estimated_arrival_time=estimated_arrival.isoformat(),
                    alert=alert, urban=urban, route=route, weather=weather,
                    model_inputs=row, estimate_kind='experimental_synthetic_model')


def main():
    parser = argparse.ArgumentParser(description='Estimer la duree de conduite et le retard d\'un trajet au Maroc.')
    parser.add_argument('departure')
    parser.add_argument('arrival')
    parser.add_argument('--departure-time', help='Date/heure ISO; sans decalage = heure Maroc. Defaut: prochaine heure entiere.')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--urban', action='store_true', help='Trajet dans une meme agglomeration.')
    group.add_argument('--intercity', action='store_true', help='Trajet entre agglomerations.')
    args = parser.parse_args()
    try:
        service = PredictorService()
        departure_time = args.departure_time or (service.weather.clock().astimezone(timezone.utc)
            + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        result = service.predict_trip(args.departure, args.arrival, departure_time, urban=args.urban)
    except AmbiguousPlaceError as exc:
        labels = '\n'.join(f"- {place['label']}" for place in exc.candidates)
        parser.exit(1, f'Erreur: {exc}\n{labels}\n')
    except (PredictionError, RoutingError, WeatherError) as exc:
        parser.exit(1, f'Erreur: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
