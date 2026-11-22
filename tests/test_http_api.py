from datetime import datetime, timezone
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from api.main import create_app, get_service
from services.predictor_logic import ModelLoadError
from services.routing_api import AmbiguousPlaceError, NoRouteError, PlaceNotFoundError, ServiceUnavailableError
from services.weather_api import UnsupportedWeatherError, WeatherClient, WeatherServiceUnavailableError


class HttpApiTests(unittest.TestCase):
    def setUp(self):
        self.service = Mock()
        self.service.weather = WeatherClient(clock=lambda: datetime(2026, 11, 22, 12, tzinfo=timezone.utc))
        self.place = dict(lat=33.5731, lon=-7.5898, label='Casablanca', source='local', precision='city')
        self.service.routing.geocode.return_value = self.place
        self.service.predict_trip.return_value = {'duree_estimee_min': 70, 'retard_min': 2}
        self.app = create_app()
        self.app.dependency_overrides[get_service] = lambda: self.service
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.body = dict(departure='Casablanca', arrival='Rabat', departure_time='2026-11-22T15:00', urban=False)

    def test_health_does_not_load_model(self):
        self.app.dependency_overrides[get_service] = lambda: (_ for _ in ()).throw(AssertionError('Loaded model'))
        self.assertEqual(self.client.get('/api/health').json()['tracking_mode'], 'simulation')

    def test_configuration_supplies_local_time_and_cities(self):
        response = self.client.get('/api/config')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['timezone'], 'Africa/Casablanca')
        self.assertIn('Casablanca', data['cities'])
        self.assertLess(data['min_departure'], data['default_departure'])
        self.assertLess(data['default_departure'], data['max_departure'])

    def test_geocoding_is_explicit_post(self):
        self.assertEqual(self.client.post('/api/geocode', json={'query': 'Casablanca'}).json(), self.place)
        self.service.routing.geocode.assert_called_once_with('Casablanca')
        self.assertEqual(self.client.get('/api/geocode?query=Casablanca').status_code, 405)

    def test_ambiguous_geocoding_preserves_choices(self):
        self.service.routing.geocode.side_effect = AmbiguousPlaceError([self.place])
        response = self.client.post('/api/geocode', json={'query': 'Place'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['candidates'], [self.place])

    def test_predict_forwards_explicit_trip_type_and_selected_place(self):
        self.body['departure'] = self.place
        response = self.client.post('/api/predict', json=self.body)
        self.assertEqual(response.status_code, 200)
        self.service.predict_trip.assert_called_once_with(self.place, 'Rabat', self.body['departure_time'], urban=False)

    def test_strict_input_validation(self):
        invalid = [dict(self.body, urban='false'), dict(self.body, urban=1), dict(self.body, unexpected='value'),
                   dict(self.body, departure=dict(self.place, lat=100)), dict(self.body, departure=dict(self.place, lat=True))]
        for body in invalid:
            with self.subTest(body=body):
                response = self.client.post('/api/predict', json=body)
                self.assertEqual(response.status_code, 422)
                self.assertIn('message', response.json()['error'])
        self.service.predict_trip.assert_not_called()

    def test_known_failures_have_structured_safe_errors(self):
        failures = [(NoRouteError('No route'), 422), (PlaceNotFoundError('Unknown place'), 404),
                    (ServiceUnavailableError('Unavailable'), 503), (UnsupportedWeatherError(71), 422),
                    (WeatherServiceUnavailableError('Offline'), 503), (ModelLoadError('Missing model'), 503)]
        for error, status in failures:
            self.service.predict_trip.side_effect = error
            with self.subTest(error=error):
                response = self.client.post('/api/predict', json=self.body)
                self.assertEqual(response.status_code, status)
                self.assertIsInstance(response.json()['error']['message'], str)


if __name__ == '__main__':
    unittest.main()
