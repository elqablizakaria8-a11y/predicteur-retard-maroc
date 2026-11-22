"""Previsions horaires Open-Meteo pour le depart, sans cle pour le prototype.

Les timestamps du fournisseur sont UTC; leur conversion utilise les regles
IANA Africa/Casablanca (y compris les changements d'heure pendant Ramadan).
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TIMEZONE = 'Africa/Casablanca'
FORECAST_DAYS = 7
CACHE_SECONDS = 900
ATTRIBUTION = 'Weather data by Open-Meteo — https://open-meteo.com/ (CC BY 4.0)'
# Ces regroupements sont ceux de notre application, pas des classes WMO.
WEATHER_CATEGORIES = {
    0: 'Soleil', 1: 'Soleil', 2: 'Nuageux', 3: 'Nuageux',
    51: 'Pluie', 53: 'Pluie', 55: 'Pluie',
    61: 'Pluie', 63: 'Pluie', 65: 'Forte pluie',
    80: 'Pluie', 81: 'Pluie', 82: 'Forte pluie',
}


class WeatherError(Exception):
    """Erreur exploitable par la future interface."""


class InvalidWeatherInputError(WeatherError):
    pass


class ForecastUnavailableError(WeatherError):
    pass


class WeatherServiceUnavailableError(WeatherError):
    pass


class InvalidWeatherResponseError(WeatherError):
    pass


class UnsupportedWeatherError(WeatherError):
    def __init__(self, code):
        super().__init__(f'Condition meteo WMO {code} non couverte par le modele (ex. brouillard, neige, verglas ou orage).')
        self.weather_code = code


def weather_category(code):
    if isinstance(code, bool) or not isinstance(code, (int, float)) or not math.isfinite(code) or code != int(code):
        raise InvalidWeatherResponseError('Code meteo WMO invalide.')
    if int(code) not in WEATHER_CATEGORIES:
        raise UnsupportedWeatherError(int(code))
    return WEATHER_CATEGORIES[int(code)]


class WeatherClient:
    def __init__(self, *, cache_path=None, timeout=15, api_url=None, clock=None):
        self.cache_path = Path(cache_path or os.getenv('WEATHER_CACHE_PATH', str(PROJECT_ROOT / 'cache/weather.sqlite3')))
        self.api_url = (api_url or os.getenv('OPEN_METEO_URL', 'https://api.open-meteo.com/v1/forecast')).rstrip('/')
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('Le timeout doit etre positif et fini.')
        if urlsplit(self.api_url).scheme not in ('http', 'https') or not urlsplit(self.api_url).netloc or urlsplit(self.api_url).query:
            raise ValueError('URL Open-Meteo invalide.')
        try:
            self.zone = ZoneInfo(TIMEZONE)
        except ZoneInfoNotFoundError as exc:
            raise WeatherServiceUnavailableError('Fuseau Africa/Casablanca absent. Installez les dependances, notamment tzdata.') from exc
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _departure(self, value):
        if isinstance(value, str):
            if not re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', value):
                raise InvalidWeatherInputError('Depart attendu: date et heure ISO, par exemple 2026-11-22T15:30.')
            try:
                value = datetime.fromisoformat(value)
            except ValueError as exc:
                raise InvalidWeatherInputError('Date ou heure de depart invalide.') from exc
        if not isinstance(value, datetime):
            raise InvalidWeatherInputError('Le depart doit contenir une date et une heure.')
        if value.tzinfo is None or value.utcoffset() is None:
            # Refuse les heures locales inexistantes ou doubles, au lieu de
            # choisir silencieusement un cote du changement d'heure.
            candidates = {}
            for fold in (0, 1):
                candidate = value.replace(tzinfo=self.zone, fold=fold)
                restored = candidate.astimezone(timezone.utc).astimezone(self.zone)
                if restored.replace(tzinfo=None) == value:
                    candidates[candidate.timestamp()] = candidate
            if len(candidates) != 1:
                raise InvalidWeatherInputError('Heure locale inexistante ou ambigue. Choisissez une autre heure ou indiquez un decalage UTC explicite.')
            value = next(iter(candidates.values()))
        return value.astimezone(timezone.utc).astimezone(self.zone)

    def _download(self, params):
        request = Request(self.api_url + '?' + urlencode(params), headers={
            'User-Agent': 'predicteur-retard-maroc/0.2 (educational weather prototype)',
            'Accept': 'application/json',
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            exc.close()
            message = ('Limite Open-Meteo atteinte. Reessayez plus tard.' if exc.code == 429
                       else f'Open-Meteo indisponible ou requete refusee (HTTP {exc.code}).')
            raise WeatherServiceUnavailableError(message) from exc
        except (URLError, OSError, TimeoutError, HTTPException) as exc:
            raise WeatherServiceUnavailableError('Open-Meteo injoignable ou delai depasse.') from exc
        except (ValueError, UnicodeError) as exc:
            raise InvalidWeatherResponseError('Open-Meteo a renvoye un JSON invalide.') from exc

    @staticmethod
    def _validate(payload):
        try:
            if not isinstance(payload, dict) or payload.get('error'):
                raise ValueError
            hourly, units = payload['hourly'], payload['hourly_units']
            if units['time'] != 'unixtime' or units['temperature_2m'] != '°C' or units['weather_code'] != 'wmo code':
                raise ValueError
            times = hourly['time']
            if not isinstance(times, list) or not times:
                raise ValueError
            for name in ('temperature_2m', 'weather_code'):
                if not isinstance(hourly[name], list) or len(hourly[name]) != len(times):
                    raise ValueError
            if any(isinstance(t, bool) or not isinstance(t, int) for t in times):
                raise ValueError
            if any(right - left != 3600 for left, right in zip(times, times[1:])):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidWeatherResponseError('Previsions horaires Open-Meteo incompletes ou unites invalides.') from exc
        return payload

    def _forecast(self, params):
        key = (self.api_url + '?' + urlencode(sorted(params.items()))
               + '|utc-day=' + self.clock().astimezone(timezone.utc).date().isoformat())
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.cache_path, timeout=self.timeout + 5, isolation_level=None)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS forecast (key TEXT PRIMARY KEY, expires REAL, payload TEXT)')
                connection.execute('CREATE TABLE IF NOT EXISTS throttle (host TEXT PRIMARY KEY, last_request REAL)')
                connection.execute('BEGIN IMMEDIATE')
                try:
                    now = self.clock().timestamp()
                    cached = connection.execute('SELECT payload FROM forecast WHERE key=? AND expires>?', (key, now)).fetchone()
                    if cached:
                        try:
                            return self._validate(json.loads(cached[0]))
                        except (WeatherError, ValueError, TypeError):
                            connection.execute('DELETE FROM forecast WHERE key=?', (key,))
                    host = urlsplit(self.api_url).netloc.lower()
                    last = connection.execute('SELECT last_request FROM throttle WHERE host=?', (host,)).fetchone()
                    if last:
                        time.sleep(max(0.0, 1.05 - (time.time() - last[0])))
                    connection.execute('INSERT OR REPLACE INTO throttle VALUES (?,?)', (host, time.time()))
                    payload = self._validate(self._download(params))
                    try:
                        encoded = json.dumps(payload, allow_nan=False)
                    except (TypeError, ValueError) as exc:
                        raise InvalidWeatherResponseError('Valeurs non finies dans les previsions.') from exc
                    connection.execute('INSERT OR REPLACE INTO forecast VALUES (?,?,?)',
                                       (key, self.clock().timestamp() + CACHE_SECONDS, encoded))
                    return payload
                finally:
                    connection.commit()
        except (sqlite3.Error, OSError) as exc:
            raise WeatherServiceUnavailableError('Cache meteo indisponible. Verifiez son chemin ou reessayez.') from exc

    def validate_departure(self, departure):
        """Valide l'heure locale et la fenetre avant tout appel reseau."""
        local_departure = self._departure(departure)
        utc_departure = local_departure.astimezone(timezone.utc)
        now = self.clock().astimezone(timezone.utc)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=FORECAST_DAYS)
        if utc_departure < now or utc_departure >= end:
            raise ForecastUnavailableError('Choisissez un depart futur dans la fenetre de prevision de 7 jours.')
        return local_departure

    def get_forecast(self, latitude, longitude, departure):
        try:
            if isinstance(latitude, bool) or isinstance(longitude, bool):
                raise ValueError
            lat, lon = float(latitude), float(longitude)
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError
        except (TypeError, ValueError, OverflowError) as exc:
            raise InvalidWeatherInputError('Latitude ou longitude invalide.') from exc
        local_departure = self.validate_departure(departure)
        utc_departure = local_departure.astimezone(timezone.utc)
        # Les dates UTC font aussi partie de la cle du cache: aucun vieux jour
        # ne peut etre reutilise quand la fenetre glisse apres minuit UTC.
        payload = self._forecast(dict(latitude=lat, longitude=lon,
            hourly='temperature_2m,weather_code', timezone='UTC', timeformat='unixtime',
            temperature_unit='celsius', forecast_days=FORECAST_DAYS))
        slot = int(utc_departure.replace(minute=0, second=0, microsecond=0).timestamp())
        hourly = payload['hourly']
        try:
            index = hourly['time'].index(slot)
        except ValueError as exc:
            raise ForecastUnavailableError('Aucune prevision disponible pour cette heure de depart.') from exc
        temperature, code = hourly['temperature_2m'][index], hourly['weather_code'][index]
        if temperature is None or code is None:
            raise ForecastUnavailableError('Temperature ou condition meteo indisponible a cette heure.')
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not math.isfinite(temperature):
            raise InvalidWeatherResponseError('Temperature invalide dans les previsions.')
        return dict(temperature_c=temperature, meteo=weather_category(code), weather_code=int(code),
                    departure_time=local_departure.isoformat(),
                    forecast_time=datetime.fromtimestamp(slot, self.zone).isoformat(),
                    timezone=TIMEZONE, source='open-meteo', attribution=ATTRIBUTION)


def main():
    parser = argparse.ArgumentParser(description='Prevision meteo pour une heure de depart au Maroc.')
    parser.add_argument('latitude', type=float)
    parser.add_argument('longitude', type=float)
    parser.add_argument('departure', nargs='?', help='Date/heure ISO; sans decalage = heure Maroc. Defaut: prochaine heure entiere.')
    args = parser.parse_args()
    try:
        client = WeatherClient()
        departure = args.departure or (client.clock().astimezone(timezone.utc) + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        result = client.get_forecast(args.latitude, args.longitude, departure)
    except WeatherError as exc:
        parser.exit(1, f'Erreur: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
