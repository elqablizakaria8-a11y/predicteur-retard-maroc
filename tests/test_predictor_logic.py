from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import joblib
import numpy as np

from services.predictor_logic import (
    InvalidPredictionError, InvalidPredictionInputError, ModelLoadError, PredictorService,
)
from services.routing_api import AmbiguousPlaceError, NoRouteError, RoutingClient
from services.weather_api import ForecastUnavailableError, UnsupportedWeatherError, WeatherClient
from src.model_features import FEATURE_COLUMNS


class ExampleModel:
    def __init__(self, columns=None):
        self.feature_names_in_ = np.array(columns if columns is not None else FEATURE_COLUMNS)
        self.n_features_in_ = len(self.feature_names_in_)
        self.output = [30.0]
        self.calls = 0
        self.last_features = None

    def predict(self, features):
        self.calls += 1
        self.last_features = features.copy()
        return self.output


class PredictorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.save_model()
        self.origin = dict(label='Depart test', lat=33.57, lon=-7.59)
        self.destination = dict(label='Arrivee test', lat=34.02, lon=-6.84)
        self.route = dict(departure=self.origin, arrival=self.destination,
                          distance_km=10.0, duree_theorique_min=20.0, attribution='OSM',
                          geometry={'type': 'LineString', 'coordinates': [[-7.59, 33.57], [-6.84, 34.02]]})
        self.routing = Mock(spec=RoutingClient)
        self.routing.geocode.side_effect = lambda name: dict(self.origin if name == 'Depart' else self.destination)
        self.routing.route.return_value = self.route
        self.weather = WeatherClient(cache_path=self.root / 'weather.sqlite',
                                     clock=lambda: datetime(2026, 11, 23, tzinfo=timezone.utc))
        self.weather.get_forecast = Mock(return_value=dict(meteo='Pluie', temperature_c=20, attribution='Open-Meteo'))
        self.departure = datetime(2026, 11, 23, 8, 30, tzinfo=self.weather.zone)
        self.service = self.new_service()

    def save_model(self, model=None, columns=None):
        joblib.dump(model if model is not None else ExampleModel(), self.root / 'modele_retard_maroc.pkl')
        joblib.dump(columns if columns is not None else list(FEATURE_COLUMNS), self.root / 'colonnes_modele.pkl')

    def new_service(self):
        return PredictorService(model_dir=self.root, routing_client=self.routing, weather_client=self.weather)

    def predict(self, **kwargs):
        return self.service.predict_trip('Depart', 'Arrivee', self.departure, urban=kwargs.pop('urban', False), **kwargs)

    def test_connects_route_weather_and_model(self):
        result = self.predict()
        self.assertEqual(result['duree_estimee_min'], 30)
        self.assertEqual(result['retard_min'], 10)
        self.assertEqual(result['alert']['color'], 'orange')
        self.assertEqual(result['model_inputs']['jour_semaine'], 0)
        self.assertEqual(result['model_inputs']['heure_depart'], 8)
        self.assertEqual(result['model_inputs']['est_weekend'], 0)
        self.assertEqual(result['model_inputs']['est_heure_pointe'], 1)
        self.weather.get_forecast.assert_called_once_with(self.origin['lat'], self.origin['lon'], self.departure)
        self.routing.route.assert_called_once_with(self.origin, self.destination)
        self.assertEqual(result['route']['attribution'], 'OSM')
        self.assertEqual(result['weather']['attribution'], 'Open-Meteo')

    def test_alert_boundaries_use_unrounded_delay(self):
        for delay, code in [(-2, 'fluide'), (4.999, 'fluide'), (5, 'ralentissements'),
                            (15, 'ralentissements'), (15.001, 'retard')]:
            with self.subTest(delay=delay):
                self.service.model.output = [20 + delay]
                self.assertEqual(self.predict()['alert']['code'], code)

    def test_negative_delay_is_preserved(self):
        self.service.model.output = [10]
        result = self.predict()
        self.assertEqual(result['retard_min'], -10)
        self.assertEqual(result['alert']['code'], 'fluide')

    def test_weekend_has_no_rush_hour(self):
        self.departure = datetime(2026, 11, 28, 8, tzinfo=self.weather.zone)
        inputs = self.predict()['model_inputs']
        self.assertEqual(inputs['jour_semaine'], 5)
        self.assertEqual(inputs['est_weekend'], 1)
        self.assertEqual(inputs['est_heure_pointe'], 0)

    def test_utc_input_uses_local_model_features(self):
        # Avant le changement de septembre 2026, cet instant est a UTC+1.
        self.weather.clock = lambda: datetime(2026, 6, 1, tzinfo=timezone.utc)
        utc = datetime(2026, 6, 1, 7, 30, tzinfo=timezone.utc)
        result = self.service.predict_trip('Depart', 'Arrivee', utc, urban=True)
        self.assertEqual(result['model_inputs']['heure_depart'], utc.astimezone(self.weather.zone).hour)
        self.assertEqual(result['model_inputs']['est_intra_urbain'], 1)

    def test_arrival_uses_elapsed_time_across_clock_change(self):
        # Test d'un passage d'heure historique connu dans la base IANA.
        cursor = datetime(2026, 1, 1, tzinfo=timezone.utc)
        previous = cursor.astimezone(self.weather.zone).utcoffset()
        for _ in range(24 * 366):
            cursor += timedelta(hours=1)
            current = cursor.astimezone(self.weather.zone).utcoffset()
            if current != previous:
                break
            previous = current
        else:
            self.fail('No clock transition found in the test year')
        departure = cursor - timedelta(minutes=15)
        self.weather.clock = lambda: departure - timedelta(hours=1)
        self.service.model.output = [45]
        result = self.service.predict_trip('Depart', 'Arrivee', departure, urban=True)
        arrival = datetime.fromisoformat(result['estimated_arrival_time'])
        self.assertEqual((arrival.astimezone(timezone.utc) - departure).total_seconds(), 45 * 60)

    def test_selected_coordinates_skip_geocoding(self):
        self.service.predict_trip(self.origin, self.destination, self.departure, urban=False)
        self.routing.geocode.assert_not_called()

    def test_urban_must_be_explicit_boolean(self):
        for value in (None, 0, 1, 'urban', 'False'):
            with self.subTest(value=value), self.assertRaises(InvalidPredictionInputError):
                self.predict(urban=value)
        self.routing.route.assert_not_called()

    def test_invalid_places_fail_before_network(self):
        for value in ('', '  ', None, 123):
            with self.subTest(value=value), self.assertRaises(InvalidPredictionInputError):
                self.service.predict_trip(value, 'Arrivee', self.departure, urban=True)
        self.routing.geocode.assert_not_called()

    def test_invalid_date_fails_before_geocoding(self):
        with self.assertRaises(ForecastUnavailableError):
            self.service.predict_trip('Depart', 'Arrivee', self.departure - timedelta(days=2), urban=False)
        self.routing.geocode.assert_not_called()

    def test_ambiguous_place_preserves_candidates(self):
        error = AmbiguousPlaceError([self.origin, self.destination])
        self.routing.geocode.side_effect = error
        with self.assertRaises(AmbiguousPlaceError) as caught:
            self.predict()
        self.assertIs(caught.exception, error)
        self.weather.get_forecast.assert_not_called()
        self.assertEqual(self.service.model.calls, 0)

    def test_no_route_stops_weather_and_prediction(self):
        self.routing.route.side_effect = NoRouteError('No route')
        with self.assertRaises(NoRouteError):
            self.predict()
        self.weather.get_forecast.assert_not_called()
        self.assertEqual(self.service.model.calls, 0)

    def test_unsupported_weather_stops_prediction(self):
        self.weather.get_forecast.side_effect = UnsupportedWeatherError(71)
        with self.assertRaises(UnsupportedWeatherError):
            self.predict()
        self.assertEqual(self.service.model.calls, 0)

    def test_single_row_weather_encoding_and_column_order(self):
        columns = list(reversed(FEATURE_COLUMNS))
        self.save_model(ExampleModel(columns), columns)
        self.service = self.new_service()
        self.predict()
        features = self.service.model.last_features
        self.assertEqual(list(features.columns), columns)
        self.assertEqual(features.iloc[0]['intensite_meteo'], 2)
        self.assertEqual(features.iloc[0]['duree_theorique_min'], 20)

    def test_bad_service_data_is_rejected(self):
        for value in ('Brouillard', None):
            self.weather.get_forecast.return_value['meteo'] = value
            with self.subTest(value=value), self.assertRaises(InvalidPredictionInputError):
                self.predict()
        self.assertEqual(self.service.model.calls, 0)

    def test_invalid_model_outputs_are_rejected(self):
        for output in ([], [0], [-1], [float('nan')], [float('inf')], [True], ['30'], [[30]], [1, 2], [1e100]):
            self.service.model.output = output
            with self.subTest(output=output), self.assertRaises(InvalidPredictionError):
                self.predict()

    def test_model_runtime_failure_is_readable(self):
        with patch.object(self.service.model, 'predict', side_effect=ValueError('bad input')):
            with self.assertRaises(InvalidPredictionError):
                self.predict()

    def test_missing_or_corrupt_artifacts_are_readable(self):
        with self.assertRaises(ModelLoadError):
            PredictorService(model_dir=self.root / 'missing')
        (self.root / 'modele_retard_maroc.pkl').write_bytes(b'not a model')
        with self.assertRaises(ModelLoadError):
            self.new_service()

    def test_incompatible_artifact_columns_are_rejected(self):
        for columns in (FEATURE_COLUMNS[:-1], FEATURE_COLUMNS[:-1] + [FEATURE_COLUMNS[0]],
                        FEATURE_COLUMNS[:-1] + ['unknown_feature']):
            self.save_model(columns=columns)
            with self.subTest(columns=columns), self.assertRaises(ModelLoadError):
                self.new_service()

    def test_artifacts_are_loaded_once_per_service(self):
        with patch('services.predictor_logic.joblib.load', wraps=joblib.load) as load:
            service = self.new_service()
            for _ in range(2):
                service.predict_trip('Depart', 'Arrivee', self.departure, urban=False)
            self.assertEqual(load.call_count, 2)  # modele + colonnes, pas par requete


if __name__ == '__main__':
    unittest.main()
