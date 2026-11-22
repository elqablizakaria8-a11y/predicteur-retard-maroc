from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from services.routing_api import (
    AmbiguousPlaceError, InvalidLocationError, InvalidResponseError,
    NoRouteError, PlaceNotFoundError, RoutingClient, ServiceUnavailableError,
)


def place(lat=33.5731, lon=-7.5898):
    return dict(lat=lat, lon=lon, display_name='Adresse test, Casablanca')


def route_response():
    return dict(code='Ok', routes=[dict(distance=90000, duration=3600,
        geometry=dict(type='LineString', coordinates=[[-7.5898, 33.5731], [-6.8416, 34.0209]]))])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'routing.sqlite3'
        self.client = RoutingClient(cache_path=self.cache)
        self.departure = self.client.geocode('Casablanca')
        self.arrival = self.client.geocode('Rabat')

    def test_known_cities_work_offline_with_accents_and_spacing(self):
        with patch.object(self.client, '_download', side_effect=AssertionError('Unexpected network')):
            self.assertEqual(self.client.geocode('  fes ')['label'], 'Fès')
            self.assertEqual(self.client.geocode('BÉNI   MELLAL')['source'], 'local')
        self.assertFalse(self.cache.exists())

    def test_route_coordinate_order_and_units(self):
        with patch.object(self.client, '_download', return_value=route_response()) as download:
            result = self.client.route(self.departure, self.arrival)
        url, params = download.call_args.args
        self.assertIn('/driving/-7.589800,33.573100;-6.841600,34.020900', url)
        self.assertEqual(params['geometries'], 'geojson')
        self.assertEqual(result['distance_km'], 90)
        self.assertEqual(result['duree_theorique_min'], 60)
        self.assertEqual(result['departure']['label'], 'Casablanca')
        self.assertIn('OpenStreetMap', result['attribution'])

    def test_cache_survives_new_clients(self):
        with patch.object(self.client, '_download', return_value=route_response()):
            first = self.client.route(self.departure, self.arrival)
        other = RoutingClient(cache_path=self.cache)
        with patch.object(other, '_download', side_effect=AssertionError('Cache missed')):
            self.assertEqual(first, other.route(self.departure, self.arrival))

    def test_geocoding_cache_and_country_filter(self):
        with patch.object(self.client, '_download', return_value=[place()]) as download:
            first = self.client.geocode('Adresse test, Casablanca')
            self.assertEqual(first, self.client.geocode('Adresse test, Casablanca'))
            self.assertEqual(download.call_count, 1)
            self.assertEqual(download.call_args.args[1]['countrycodes'], 'ma,eh')

    def test_ambiguous_search_requires_selection(self):
        with patch.object(self.client, '_download', return_value=[place(), place(34, -7)]):
            with self.assertRaises(AmbiguousPlaceError) as caught:
                self.client.geocode('Adresse ambigue')
        self.assertEqual(len(caught.exception.candidates), 2)

    def test_unknown_place_is_cached_without_invented_coordinates(self):
        with patch.object(self.client, '_download', return_value=[]) as download:
            for _ in range(2):
                with self.assertRaises(PlaceNotFoundError):
                    self.client.geocode('Lieu inexistant')
            self.assertEqual(download.call_count, 1)

    def test_invalid_queries_and_coordinates_fail_before_network(self):
        with patch.object(self.client, '_download', side_effect=AssertionError('Unexpected network')):
            for query in ['', '  ', None, 'a' * 301]:
                with self.assertRaises(InvalidLocationError):
                    self.client.geocode(query)
            for invalid in [{}, {'lat': 91, 'lon': 0}, {'lat': float('nan'), 'lon': 0},
                            {'lat': True, 'lon': 0}, {'lat': 0, 'lon': float('inf')}]:
                with self.assertRaises(InvalidLocationError):
                    self.client.route(invalid, self.arrival)
            with self.assertRaises(InvalidLocationError):
                self.client.route(self.departure, self.departure)

    def test_no_route_response(self):
        with patch.object(self.client, '_download', return_value={'code': 'NoRoute'}):
            with self.assertRaises(NoRouteError):
                self.client.route(self.departure, self.arrival)

    def test_invalid_route_payloads(self):
        payloads = [[], {'code': 'Ok', 'routes': []}, {'code': 'Error'}]
        for field, value in [('distance', -1), ('duration', 0), ('duration', float('nan')),
                             ('distance', True), ('geometry', {'type': 'Point', 'coordinates': [1, 2]})]:
            payload = route_response()
            payload['routes'][0][field] = value
            payloads.append(payload)
        with patch('services.routing_api.time.sleep'):
            for payload in payloads:
                with self.subTest(payload=payload), patch.object(self.client, '_download', return_value=payload):
                    with self.assertRaises(InvalidResponseError):
                        self.client.route(self.departure, self.arrival)

    def test_invalid_geocoding_payloads(self):
        with patch('services.routing_api.time.sleep'):
            for payload in [{}, [dict(lat='bad', lon=0, display_name='x')], [dict(lat=0, lon=0)]]:
                with patch.object(self.client, '_download', return_value=payload):
                    with self.assertRaises(InvalidResponseError):
                        self.client.geocode('Adresse test')

    def test_rate_limit_shared_across_clients_and_after_failure(self):
        other = RoutingClient(cache_path=self.cache)
        with patch('services.routing_api.time.time', return_value=100), patch('services.routing_api.time.sleep') as sleep:
            with patch.object(self.client, '_download', side_effect=ServiceUnavailableError('offline')):
                with self.assertRaises(ServiceUnavailableError):
                    self.client.geocode('Adresse A')
            with patch.object(other, '_download', return_value=[place()]):
                other.geocode('Adresse B')
            sleep.assert_called_once_with(1.05)

    def test_expired_cache_is_refreshed(self):
        with patch('services.routing_api.time.time', return_value=100), patch.object(self.client, '_download', return_value=route_response()):
            self.client.route(self.departure, self.arrival)
        with patch('services.routing_api.time.time', return_value=4000), patch.object(self.client, '_download', return_value=route_response()) as download:
            self.client.route(self.departure, self.arrival)
            self.assertEqual(download.call_count, 1)

    def test_http_headers_encoding_and_timeout(self):
        with patch('services.routing_api.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b'[]'
            self.assertEqual(self.client._download('https://example.test/search', {'q': 'Fès, Maroc'}), [])
        request = open_url.call_args.args[0]
        self.assertIn('F%C3%A8s%2C+Maroc', request.full_url)
        self.assertIn('predicteur-retard-maroc', request.get_header('User-agent'))
        self.assertEqual(open_url.call_args.kwargs['timeout'], 15)

    def test_http_and_network_failures_are_readable(self):
        failures = [HTTPError('https://example.test', code, 'failure', {}, BytesIO(b'{}')) for code in (403, 429, 500)]
        failures += [URLError('offline'), TimeoutError('timeout')]
        for error in failures:
            with self.subTest(error=error), patch('services.routing_api.urlopen', side_effect=error):
                with self.assertRaises(ServiceUnavailableError):
                    self.client._download('https://example.test', {})

    def test_http_400_no_route_is_specific(self):
        error = HTTPError('https://example.test', 400, 'NoRoute', {}, BytesIO(json.dumps({'code': 'NoRoute'}).encode()))
        with patch('services.routing_api.urlopen', side_effect=error):
            with self.assertRaises(NoRouteError):
                self.client._download('https://example.test', {})

    def test_invalid_json_is_readable(self):
        with patch('services.routing_api.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b'<html>offline</html>'
            with self.assertRaises(InvalidResponseError):
                self.client._download('https://example.test', {})


if __name__ == '__main__':
    unittest.main()
