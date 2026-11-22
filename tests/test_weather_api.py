from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from services.weather_api import (
    ForecastUnavailableError, InvalidWeatherInputError, InvalidWeatherResponseError,
    UnsupportedWeatherError, WeatherClient, WeatherServiceUnavailableError, weather_category,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 22, 12, tzinfo=UTC)
DEFAULT = object()


def forecast():
    return dict(hourly_units={'time': 'unixtime', 'temperature_2m': '°C', 'weather_code': 'wmo code'},
                hourly={'time': [int((NOW + timedelta(hours=h)).timestamp()) for h in (0, 1, 2)],
                        'temperature_2m': [20, 21, 22], 'weather_code': [0, 63, 65]})


class WeatherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name) / 'weather.sqlite3'
        self.client = WeatherClient(cache_path=self.cache, clock=lambda: NOW)
        self.departure = (NOW + timedelta(hours=1, minutes=45)).astimezone(self.client.zone)
        self.local_text = self.departure.replace(tzinfo=None).isoformat()

    def get(self, departure=DEFAULT):
        if departure is DEFAULT:
            departure = self.local_text
        return self.client.get_forecast(33.5731, -7.5898, departure)

    def test_all_supported_wmo_mappings(self):
        expected = {'Soleil': [0, 1], 'Nuageux': [2, 3],
                    'Pluie': [51, 53, 55, 61, 63, 80, 81], 'Forte pluie': [65, 82]}
        for category, codes in expected.items():
            for code in codes:
                with self.subTest(code=code):
                    self.assertEqual(weather_category(code), category)

    def test_hazards_and_unknown_codes_are_not_silently_relabelled(self):
        for code in (45, 48, 56, 57, 66, 67, 71, 73, 75, 77, 85, 86, 95, 96, 97, 99, 999):
            with self.subTest(code=code), self.assertRaises(UnsupportedWeatherError) as error:
                weather_category(code)
            self.assertEqual(error.exception.weather_code, code)

    def test_invalid_weather_codes(self):
        for code in (None, True, '65', 63.5, float('nan'), float('inf')):
            with self.subTest(code=code), self.assertRaises(InvalidWeatherResponseError):
                weather_category(code)

    def test_selected_local_hour_and_minutes_use_correct_forecast(self):
        with patch.object(self.client, '_download', return_value=forecast()) as download:
            result = self.get()
        self.assertEqual(result['temperature_c'], 21)
        self.assertEqual(result['meteo'], 'Pluie')
        expected_slot = (NOW + timedelta(hours=1)).astimezone(self.client.zone)
        self.assertEqual(result['forecast_time'], expected_slot.isoformat())
        self.assertEqual(result['departure_time'], self.departure.isoformat())
        self.assertIn('Open-Meteo', result['attribution'])
        params = download.call_args.args[0]
        self.assertEqual(params['timezone'], 'UTC')
        self.assertEqual(params['timeformat'], 'unixtime')
        self.assertEqual(params['forecast_days'], 7)

    def test_explicit_utc_and_local_departure_are_equivalent(self):
        with patch.object(self.client, '_download', return_value=forecast()) as download:
            local = self.get()
            utc = self.get(self.departure.astimezone(UTC).isoformat())
        self.assertEqual(local, utc)
        self.assertEqual(download.call_count, 1)

    def test_different_departure_hours_share_forecast_but_select_different_rows(self):
        with patch.object(self.client, '_download', return_value=forecast()) as download:
            self.assertEqual(self.get()['meteo'], 'Pluie')
            self.assertEqual(self.get(NOW + timedelta(hours=2, minutes=10))['meteo'], 'Forte pluie')
        self.assertEqual(download.call_count, 1)

    def test_invalid_inputs_fail_before_network(self):
        with patch.object(self.client, '_download', side_effect=AssertionError('Unexpected network')):
            for departure in ('2026-11-22', 'not-a-date', '2026-13-01T14:00', None, NOW.date()):
                with self.subTest(departure=departure), self.assertRaises(InvalidWeatherInputError):
                    self.get(departure)
            for lat, lon in ((91, 0), (0, 181), (True, 0), (float('nan'), 0), (0, float('inf')), (None, 0)):
                with self.subTest(lat=lat, lon=lon), self.assertRaises(InvalidWeatherInputError):
                    self.client.get_forecast(lat, lon, '2026-11-22T14:00')

    def test_past_and_outside_forecast_window_fail_before_network(self):
        with patch.object(self.client, '_download', side_effect=AssertionError('Unexpected network')):
            for departure in (NOW - timedelta(minutes=1), NOW.replace(hour=0) + timedelta(days=7)):
                with self.subTest(departure=departure), self.assertRaises(ForecastUnavailableError):
                    self.get(departure)

    def test_missing_selected_hour_is_not_replaced_by_current_weather(self):
        with patch.object(self.client, '_download', return_value=forecast()):
            with self.assertRaises(ForecastUnavailableError):
                self.get(NOW + timedelta(days=1))

    def test_missing_selected_values_are_unavailable(self):
        with patch('services.weather_api.time.sleep'):
            for name in ('temperature_2m', 'weather_code'):
                payload = forecast()
                payload['hourly'][name][1] = None
                with patch.object(self.client, '_download', return_value=payload):
                    # Each iteration needs a fresh cache, not the previous null payload.
                    client = WeatherClient(cache_path=Path(self.directory.name) / (name + '.sqlite'), clock=lambda: NOW)
                    with patch.object(client, '_download', return_value=payload), self.assertRaises(ForecastUnavailableError):
                        client.get_forecast(33, -7, self.departure)

    def test_malformed_payloads_are_rejected(self):
        payloads = [None, [], {}, {'error': True, 'reason': 'Bad request'}]
        for mutation in ('short', 'units', 'duplicate_time', 'string_time'):
            payload = forecast()
            if mutation == 'short':
                payload['hourly']['weather_code'].pop()
            elif mutation == 'units':
                payload['hourly_units']['temperature_2m'] = '°F'
            elif mutation == 'duplicate_time':
                payload['hourly']['time'][1] = payload['hourly']['time'][0]
            else:
                payload['hourly']['time'][0] = '2026-11-22T12:00'
            payloads.append(payload)
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(InvalidWeatherResponseError):
                self.client._validate(payload)

    def test_cache_is_shared_between_clients_and_expires(self):
        with patch.object(self.client, '_download', return_value=forecast()):
            expected = self.get()
        other = WeatherClient(cache_path=self.cache, clock=lambda: NOW + timedelta(minutes=10))
        with patch.object(other, '_download', side_effect=AssertionError('Cache missed')):
            self.assertEqual(other.get_forecast(33.5731, -7.5898, self.departure), expected)
        expired = WeatherClient(cache_path=self.cache, clock=lambda: NOW + timedelta(minutes=16))
        with patch('services.weather_api.time.sleep'), patch.object(expired, '_download', return_value=forecast()) as download:
            expired.get_forecast(33.5731, -7.5898, self.departure)
            self.assertEqual(download.call_count, 1)

    def test_failure_does_not_return_stale_forecast(self):
        with patch.object(self.client, '_download', return_value=forecast()):
            self.get()
        self.client.clock = lambda: NOW + timedelta(minutes=16)
        with patch('services.weather_api.time.sleep'), patch.object(self.client, '_download', side_effect=WeatherServiceUnavailableError('offline')):
            with self.assertRaises(WeatherServiceUnavailableError):
                self.get()

    def test_new_utc_day_does_not_reuse_previous_forecast_window(self):
        before = NOW.replace(hour=23, minute=59)
        self.client.clock = lambda: before
        with patch('services.weather_api.time.sleep'), patch.object(self.client, '_download', return_value=forecast()) as download:
            self.client._forecast({'latitude': 33, 'longitude': -7})
            self.client.clock = lambda: before + timedelta(minutes=2)
            self.client._forecast({'latitude': 33, 'longitude': -7})
            self.assertEqual(download.call_count, 2)

    def test_selected_invalid_temperature_is_rejected(self):
        payload = forecast()
        payload['hourly']['temperature_2m'][1] = '21'
        with patch.object(self.client, '_download', return_value=payload):
            with self.assertRaises(InvalidWeatherResponseError):
                self.get()

    def test_clock_changes_reject_missing_and_ambiguous_local_times(self):
        cursor = datetime(2026, 1, 1, tzinfo=UTC)
        previous = cursor.astimezone(self.client.zone).utcoffset()
        transitions = []
        for _ in range(24 * 366):
            cursor += timedelta(hours=1)
            local = cursor.astimezone(self.client.zone)
            current = local.utcoffset()
            if current != previous:
                wall = local.replace(tzinfo=None) + (timedelta(minutes=30) if current < previous else -timedelta(minutes=30))
                transitions.append((wall, current < previous))
                previous = current
        self.assertGreaterEqual(len(transitions), 2)
        for wall, repeated in transitions:
            with self.assertRaises(InvalidWeatherInputError):
                self.client._departure(wall)
            if repeated:
                first = self.client._departure(wall.replace(tzinfo=self.client.zone, fold=0).isoformat())
                second = self.client._departure(wall.replace(tzinfo=self.client.zone, fold=1).isoformat())
                self.assertEqual(abs(first.timestamp() - second.timestamp()), 3600)

    def test_network_http_and_invalid_json_errors(self):
        errors = [URLError('offline'), TimeoutError(), IncompleteRead(b'')]
        errors += [HTTPError('https://example.test', code, 'error', {}, BytesIO(b'{}')) for code in (400, 429, 500)]
        for error in errors:
            with self.subTest(error=error), patch('services.weather_api.urlopen', side_effect=error):
                with self.assertRaises(WeatherServiceUnavailableError):
                    self.client._download({})
        with patch('services.weather_api.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = b'<html>offline</html>'
            with self.assertRaises(InvalidWeatherResponseError):
                self.client._download({})

    def test_request_uses_https_timeout_and_identifying_header(self):
        with patch('services.weather_api.urlopen') as open_url:
            open_url.return_value.__enter__.return_value.read.return_value = json.dumps(forecast()).encode()
            self.client._download({'latitude': 33.5731, 'longitude': -7.5898})
        request = open_url.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://api.open-meteo.com/v1/forecast?'))
        self.assertIn('predicteur-retard-maroc', request.get_header('User-agent'))
        self.assertEqual(open_url.call_args.kwargs['timeout'], 15)


if __name__ == '__main__':
    unittest.main()
