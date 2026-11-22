"""Routage automobile pour le prototype; aucune information de trafic en direct.

Les appels Nominatim doivent etre declenches par une soumission utilisateur,
jamais par une autocompletion. Limitation et cache partages via SQLite pour
les clients/processus qui utilisent le meme fichier sur une seule machine.
"""
import argparse
from contextlib import closing
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ATTRIBUTION = '© OpenStreetMap contributors — https://www.openstreetmap.org/copyright; routing: OSRM'


class RoutingError(Exception):
    """Erreur a presenter a l'utilisateur sans inventer de resultat."""


class PlaceNotFoundError(RoutingError):
    pass


class AmbiguousPlaceError(RoutingError):
    def __init__(self, candidates):
        super().__init__('Plusieurs lieux correspondent. Precisez l\'adresse ou choisissez un candidat.')
        self.candidates = candidates


class NoRouteError(RoutingError):
    pass


class InvalidLocationError(RoutingError):
    pass


class ServiceUnavailableError(RoutingError):
    pass


class InvalidResponseError(RoutingError):
    pass


def _normalise(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                            if not unicodedata.combining(c)).split())


def _coordinates(place):
    try:
        if isinstance(place['lat'], bool) or isinstance(place['lon'], bool):
            raise ValueError
        lat, lon = float(place['lat']), float(place['lon'])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidLocationError('Coordonnees GPS invalides: lat et lon sont obligatoires.') from exc
    return lat, lon


class RoutingClient:
    def __init__(self, *, cache_path=None, timeout=15, nominatim_url=None, osrm_url=None, user_agent=None):
        self.cache_path = Path(cache_path or os.getenv('ROUTING_CACHE_PATH', str(PROJECT_ROOT / 'cache/routing.sqlite3')))
        self.timeout = float(timeout)
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError('Le timeout doit etre positif et fini.')
        self.nominatim_url = (nominatim_url or os.getenv('NOMINATIM_URL', 'https://nominatim.openstreetmap.org')).rstrip('/')
        self.osrm_url = (osrm_url or os.getenv('OSRM_URL', 'https://router.project-osrm.org')).rstrip('/')
        for url in (self.nominatim_url, self.osrm_url):
            if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).netloc:
                raise ValueError('URL de service invalide.')
        self.user_agent = user_agent or os.getenv('ROUTING_USER_AGENT', 'predicteur-retard-maroc/0.2 (educational route-delay prototype)')
        cities = json.loads((PROJECT_ROOT / 'data/villes_maroc.json').read_text(encoding='utf-8'))
        self.cities = {_normalise(name): dict(lat=value['lat'], lon=value['lon'],
                                           label=name, source='local', precision='city')
                       for name, value in cities.items()}

    def _download(self, url, params):
        request = Request(url + '?' + urlencode(params), headers={
            'User-Agent': self.user_agent, 'Accept': 'application/json',
            'Accept-Language': 'fr,ar;q=0.9,en;q=0.8',
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except HTTPError as exc:
            try:
                error_body = exc.read(65536)
            except OSError:
                error_body = b''
            finally:
                exc.close()
            # OSRM peut renvoyer NoRoute/NoSegment avec un statut HTTP 400.
            if exc.code == 400:
                try:
                    payload = json.loads(error_body.decode('utf-8'))
                    if isinstance(payload, dict) and payload.get('code') in ('NoRoute', 'NoSegment'):
                        raise NoRouteError('Aucun trajet routier trouve pres de ces points.') from exc
                except (ValueError, UnicodeError):
                    pass
            if exc.code == 429:
                message = 'Limite de requetes atteinte. Reessayez plus tard.'
            elif exc.code == 403:
                message = 'Acces refuse par le service. Verifiez sa configuration et sa politique d\'utilisation.'
            else:
                message = f'Service de routage indisponible (HTTP {exc.code}).'
            raise ServiceUnavailableError(message) from exc
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException) as exc:
            raise ServiceUnavailableError('Service injoignable ou delai depasse. Reessayez plus tard.') from exc
        except (ValueError, UnicodeError) as exc:
            raise InvalidResponseError('Le service a renvoye une reponse JSON invalide.') from exc

    def _cached_request(self, url, params, ttl, validate):
        key = url + '?' + urlencode(sorted(params.items()))
        # Le verrou SQLite serialize aussi les requetes entre processus locaux.
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.cache_path, timeout=self.timeout + 5, isolation_level=None)) as connection:
                connection.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL, payload TEXT)')
                connection.execute('CREATE TABLE IF NOT EXISTS throttle (host TEXT PRIMARY KEY, last_request REAL)')
                connection.execute('BEGIN IMMEDIATE')
                try:
                    cached = connection.execute('SELECT payload FROM cache WHERE key=? AND expires>?', (key, time.time())).fetchone()
                    if cached:
                        try:
                            return validate(json.loads(cached[0]))
                        except (RoutingError, ValueError, TypeError):
                            connection.execute('DELETE FROM cache WHERE key=?', (key,))
                    # Une requete / seconde / hote, y compris apres une erreur.
                    host = urlsplit(url).netloc.lower()
                    last = connection.execute('SELECT last_request FROM throttle WHERE host=?', (host,)).fetchone()
                    if last:
                        time.sleep(max(0.0, 1.05 - (time.time() - last[0])))
                    connection.execute('INSERT OR REPLACE INTO throttle VALUES (?,?)', (host, time.time()))
                    payload = self._download(url, params)
                    result = validate(payload)
                    connection.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',
                                       (key, time.time() + ttl, json.dumps(payload, allow_nan=False)))
                    return result
                finally:
                    # Conserve la limitation meme si le fournisseur echoue.
                    connection.commit()
        except (sqlite3.Error, OSError) as exc:
            raise ServiceUnavailableError('Cache de routage indisponible; verifiez son chemin ou reessayez.') from exc

    @staticmethod
    def _places(payload):
        if not isinstance(payload, list):
            raise InvalidResponseError('Format de geocodage invalide.')
        candidates = []
        for item in payload:
            try:
                lat, lon = _coordinates(item)
                label = item['display_name']
                if not isinstance(label, str) or not label.strip():
                    raise ValueError
            except (RoutingError, KeyError, TypeError, ValueError) as exc:
                raise InvalidResponseError('Lieu renvoye par le service invalide.') from exc
            candidate = dict(lat=lat, lon=lon, label=label, source='nominatim', precision='search_result')
            if not any(abs(c['lat'] - lat) < 0.00001 and abs(c['lon'] - lon) < 0.00001 for c in candidates):
                candidates.append(candidate)
        return candidates

    def geocode(self, query):
        if not isinstance(query, str) or not query.strip():
            raise InvalidLocationError('Veuillez saisir un lieu.')
        query = ' '.join(query.split())
        if len(query) > 300:
            raise InvalidLocationError('Adresse trop longue (300 caracteres maximum).')
        local = self.cities.get(_normalise(query))
        if local:
            return dict(local)
        candidates = self._cached_request(self.nominatim_url + '/search', {
            'q': query, 'format': 'jsonv2', 'countrycodes': 'ma,eh',
            'limit': 3, 'addressdetails': 1,
        }, 30 * 86400, self._places)
        if not candidates:
            raise PlaceNotFoundError('Lieu introuvable. Precisez le quartier et la ville.')
        if len(candidates) > 1:
            raise AmbiguousPlaceError(candidates)
        return candidates[0]

    @staticmethod
    def _route(payload):
        if not isinstance(payload, dict):
            raise InvalidResponseError('Format de routage invalide.')
        if payload.get('code') in ('NoRoute', 'NoSegment'):
            raise NoRouteError('Aucun trajet routier trouve pres de ces points.')
        if payload.get('code') != 'Ok':
            raise InvalidResponseError('Le service n\'a pas pu calculer le trajet.')
        try:
            route = payload['routes'][0]
            distance, duration = route['distance'], route['duration']
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (distance, duration)):
                raise ValueError
            geometry = route['geometry']
            if geometry['type'] != 'LineString' or len(geometry['coordinates']) < 2:
                raise ValueError
            for point in geometry['coordinates']:
                if len(point) != 2:
                    raise ValueError
                _coordinates({'lat': point[1], 'lon': point[0]})
        except (KeyError, IndexError, TypeError, ValueError, RoutingError) as exc:
            raise InvalidResponseError('Distance, duree ou geometrie du trajet invalide.') from exc
        return dict(distance_km=distance / 1000, duree_theorique_min=duration / 60,
                    geometry=geometry, attribution=ATTRIBUTION)

    def route(self, departure, arrival):
        lat1, lon1 = _coordinates(departure)
        lat2, lon2 = _coordinates(arrival)
        if abs(lat1 - lat2) < 1e-7 and abs(lon1 - lon2) < 1e-7:
            raise InvalidLocationError('Depart et arrivee identiques. Pour un trajet urbain, utilisez deux adresses distinctes.')
        # Ordre OSRM obligatoire: longitude,latitude. Six decimales ~ 0,1 m.
        coordinates = f'{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}'
        result = self._cached_request(self.osrm_url + '/route/v1/driving/' + coordinates, {
            'overview': 'simplified', 'geometries': 'geojson', 'steps': 'false',
            'alternatives': 'false', 'radiuses': '1000;1000', 'generate_hints': 'false',
        }, 3600, self._route)
        return dict(result, departure=dict(departure), arrival=dict(arrival))

    def calculate_route(self, departure, arrival):
        return self.route(self.geocode(departure), self.geocode(arrival))


def main():
    parser = argparse.ArgumentParser(description='Calculer un trajet automobile de reference au Maroc.')
    parser.add_argument('departure')
    parser.add_argument('arrival')
    args = parser.parse_args()
    try:
        result = RoutingClient().calculate_route(args.departure, args.arrival)
    except RoutingError as exc:
        parser.exit(1, f'Erreur: {exc}\n')
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
