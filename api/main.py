from datetime import timedelta, timezone
from functools import lru_cache
import json
import os
from pathlib import Path

from api.auth import auth_router

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from api.deliveries import delivery_router

from services.predictor_logic import (
    InvalidPredictionError, ModelLoadError, PredictionError, PredictorService,
)
from services.routing_api import (
    AmbiguousPlaceError, InvalidLocationError, InvalidResponseError, NoRouteError,
    PlaceNotFoundError, RoutingError, ServiceUnavailableError,
)
from services.weather_api import (
    ForecastUnavailableError, InvalidWeatherInputError, InvalidWeatherResponseError,
    UnsupportedWeatherError, WeatherError, WeatherServiceUnavailableError,
)

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def get_service():
    return PredictorService(model_dir=os.getenv('MODEL_DIR') or None)


class SelectedPlace(BaseModel):
    model_config = ConfigDict(extra='ignore')
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False, strict=True)
    lon: float = Field(ge=-180, le=180, allow_inf_nan=False, strict=True)
    label: str = Field(min_length=1, max_length=1500)
    source: str = 'selected'
    precision: str = 'search_result'


class GeocodeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=300)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    departure: SelectedPlace | str
    arrival: SelectedPlace | str
    departure_time: str = Field(min_length=16, max_length=60)
    urban: StrictBool


def error_response(status, code, message, **extra):
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message, **extra}})


def create_app():
    app = FastAPI(title='Wasel — Predicteur Maroc', version='0.1.0')
    auth, signed_in = auth_router()
    app.include_router(auth)
    app.include_router(delivery_router(signed_in, get_service))

    @app.middleware('http')
    async def private_delivery_headers(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(('/livreur/', '/suivi/', '/api/deliveries')):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith('/api/deliveries'):
            return JSONResponse(status_code=422, content={'detail': 'Vérifiez le trajet, les contacts et les données de position.'})
        if request.url.path.startswith('/api/auth/'):
            return JSONResponse(status_code=422, content={'detail': 'Vérifiez les champs du formulaire.'})
        return error_response(422, 'invalid_input', 'Vérifiez les lieux, la date et le type de trajet.')

    @app.exception_handler(RoutingError)
    async def routing_error(request, exc):
        if isinstance(exc, AmbiguousPlaceError):
            return error_response(409, 'ambiguous_place', str(exc), candidates=exc.candidates)
        if isinstance(exc, PlaceNotFoundError):
            return error_response(404, 'place_not_found', str(exc))
        if isinstance(exc, NoRouteError):
            return error_response(422, 'no_route', str(exc))
        if isinstance(exc, InvalidLocationError):
            return error_response(422, 'invalid_place', str(exc))
        return error_response(503 if isinstance(exc, ServiceUnavailableError) else 502, 'routing_unavailable', str(exc))

    @app.exception_handler(WeatherError)
    async def weather_error(request, exc):
        if isinstance(exc, UnsupportedWeatherError):
            return error_response(422, 'unsupported_weather', str(exc), weather_code=exc.weather_code)
        status = 503 if isinstance(exc, WeatherServiceUnavailableError) else 502 if isinstance(exc, InvalidWeatherResponseError) else 422
        return error_response(status, 'weather_unavailable', str(exc))

    @app.exception_handler(PredictionError)
    async def prediction_error(request, exc):
        status = 503 if isinstance(exc, ModelLoadError) else 500 if isinstance(exc, InvalidPredictionError) else 422
        return error_response(status, 'prediction_unavailable', str(exc))

    @app.get('/api/health')
    def health():
        return {'status': 'ok', 'tracking_mode': 'simulation'}

    @app.get('/api/config')
    def config(service=Depends(get_service)):
        weather = service.weather
        now = weather.clock().astimezone(timezone.utc)
        local = lambda value: value.astimezone(weather.zone).strftime('%Y-%m-%dT%H:%M')
        end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7)
        return {'cities': list(json.loads((ROOT / 'data/villes_maroc.json').read_text(encoding='utf-8'))),
                'timezone': 'Africa/Casablanca', 'default_departure': local((now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)),
                'min_departure': local(now + timedelta(minutes=1)), 'max_departure': local(end - timedelta(minutes=1))}

    @app.post('/api/geocode')
    def geocode(body: GeocodeRequest, service=Depends(get_service)):
        # Soumission explicite uniquement: aucune recherche a chaque frappe.
        return service.routing.geocode(body.query)

    @app.post('/api/predict')
    def predict(body: PredictionRequest, service=Depends(get_service)):
        departure = body.departure.model_dump() if isinstance(body.departure, SelectedPlace) else body.departure
        arrival = body.arrival.model_dump() if isinstance(body.arrival, SelectedPlace) else body.arrival
        return service.predict_trip(departure, arrival, body.departure_time, urban=body.urban)

    dist = ROOT / 'frontend/dist'
    if (dist / 'assets').is_dir():
        app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')

    @app.get('/favicon.svg', include_in_schema=False)
    def favicon():
        return FileResponse(ROOT / 'frontend/public/favicon.svg')

    @app.get('/images/gps-login.webp', include_in_schema=False)
    def gps_login_image():
        return FileResponse(ROOT / 'frontend/public/images/gps-login.webp', media_type='image/webp')

    @app.get('/livreur/{token}', include_in_schema=False)
    @app.get('/suivi/{token}', include_in_schema=False)
    @app.get('/', include_in_schema=False)
    def index():
        if (dist / 'index.html').is_file():
            return FileResponse(dist / 'index.html')
        return error_response(503, 'frontend_not_built', 'Construisez le frontend avec npm run build, ou lancez son serveur Vite.')

    return app


app = create_app()
